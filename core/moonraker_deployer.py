"""Transactional KACE deployment state machine.

The physical MCU monitor is deliberately separate from Moonraker.  Losing the
HTTP API is not evidence that a board was unplugged, and a Klipper shutdown is
not a USB remove event.  The state machine consumes both sources in order and
does not publish configuration until the expected firmware is running.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional

from core.mcu_monitor import McuIdentityMismatch, McuMonitorCancelled, McuMonitorError
from core.terminal_progress import TerminalProgressRenderer, WorkflowEventEmitter

_NETWORK_ERRORS: tuple = (OSError, ConnectionError, TimeoutError)
try:
    from requests.exceptions import RequestException as _RequestException
    _NETWORK_ERRORS += (_RequestException,)
except ImportError:
    pass


class DeployState(Enum):
    INIT = auto()
    BACKUP = auto()
    COPYING_FIRMWARE = auto()
    FIRMWARE_COPIED = auto()
    MONITOR_ARMED = auto()
    AWAITING_DISCONNECT = auto()
    MCU_ABSENT = auto()
    AWAITING_RECONNECT = auto()
    MCU_PRESENT = auto()
    WAITING_MOONRAKER = auto()
    MOONRAKER_ONLINE = auto()
    WAITING_KLIPPER_READY = auto()
    KLIPPER_READY = auto()
    WAITING_MCU_REGISTRATION = auto()
    MCU_REGISTERED = auto()
    VERIFYING_FIRMWARE = auto()
    FIRMWARE_VERIFIED = auto()
    APPLYING_CONFIG = auto()
    VERIFYING_UPLOAD = auto()
    FIRMWARE_RESTART = auto()
    VERIFYING_CONFIG = auto()
    ROLLING_BACK = auto()
    VERIFYING_ROLLBACK = auto()
    DONE = auto()
    FAILED_FLASH = auto()
    TIMEOUT = auto()  # retained for explicitly bounded callers/tests
    CONFIG_ERROR = auto()
    ABORTED = auto()
    FAILED_UPLOAD = auto()
    FAILED_MONITOR = auto()
    FAILED_PRECONDITION = auto()


@dataclass(frozen=True)
class McuTarget:
    name: str
    expected_version: str


@dataclass(frozen=True)
class ConfigArtifact:
    local_path: str
    remote_name: str

    @property
    def sha256(self) -> str:
        digest = hashlib.sha256()
        with open(self.local_path, "rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()


@dataclass
class DeploymentManifest:
    targets: list
    printer_cfg_path: str
    macros_cfg_path: object = None
    auxiliary_files: list = field(default_factory=list)
    config_artifacts: Optional[list] = None

    def artifacts(self) -> list[ConfigArtifact]:
        if self.config_artifacts is not None:
            return [
                item if isinstance(item, ConfigArtifact) else ConfigArtifact(*item)
                for item in self.config_artifacts
            ]
        result = [ConfigArtifact(self.printer_cfg_path, "printer.cfg")]
        if self.macros_cfg_path and os.path.isfile(self.macros_cfg_path):
            result.append(ConfigArtifact(str(self.macros_cfg_path), "macros.cfg"))
        for item in self.auxiliary_files:
            result.append(item if isinstance(item, ConfigArtifact) else ConfigArtifact(*item))
        return result


@dataclass
class DeployResult:
    state: DeployState
    detail: str = ""
    mcu_versions: dict = field(default_factory=dict)
    snapshot: Optional[object] = None
    workflow_id: str = ""
    rollback_succeeded: Optional[bool] = None

    @property
    def ok(self) -> bool:
        return self.state is DeployState.DONE


class JsonEventSink:
    """Stable line protocol consumed by terminals and KACE Studio."""

    PREFIX = "=== KACE_WORKFLOW_EVENT: "

    def __init__(self, stream=None):
        self.stream = stream if stream is not None else sys.stdout

    def __call__(self, event: dict) -> None:
        print(
            f"{self.PREFIX}{json.dumps(event, sort_keys=True)} ===",
            file=self.stream,
            flush=True,
        )


class Deployer:
    """Execute one firmware/config transaction from physical reboot to DONE."""

    WAIT_TIMEOUT_S = None  # user waits are indefinite by default
    POLL_INTERVAL_S = 1.0
    POLL_BACKOFF_MAX_S = 5.0

    def __init__(
        self,
        client,
        manifest: DeploymentManifest,
        verify_firmware: bool = True,
        snapshot: Optional[object] = None,
        *,
        mcu_monitor=None,
        power_cycle_prompt: Optional[Callable[[], None]] = None,
        power_off: Optional[Callable[[], object]] = None,
        power_on: Optional[Callable[[], object]] = None,
        cancel_event: Optional[threading.Event] = None,
        event_sink: Optional[Callable[[dict], None]] = None,
        snapshot_loader: Optional[Callable[[], object]] = None,
        firmware_copy: Optional[Callable[[], bool]] = None,
        firmware_deploy: Optional[Callable[[], object]] = None,
        monitor_before_firmware: bool = False,
        firmware_already_copied: bool = False,
    ):
        self.client = client
        self.manifest = manifest
        self.verify_firmware = verify_firmware
        self.snapshot = snapshot
        self.mcu_monitor = mcu_monitor
        self.power_cycle_prompt = power_cycle_prompt
        self.power_off = power_off
        self.power_on = power_on
        self.cancel_event = cancel_event or threading.Event()
        self.snapshot_loader = snapshot_loader
        self.firmware_copy = firmware_copy
        self.firmware_deploy = firmware_deploy
        self.monitor_before_firmware = monitor_before_firmware
        self.firmware_already_copied = firmware_already_copied
        self.state = DeployState.INIT
        self.workflow_id = str(uuid.uuid4())
        self._sequence = 0
        self._manifest_names = {target.name for target in manifest.targets}
        self._owns_event_sink = event_sink is None
        if event_sink is None:
            renderer = TerminalProgressRenderer(sys.stdout)
            try:
                renderer.start()
            except Exception:
                # A terminal capability or output failure must not block KACE.
                pass
            self.event_sink = WorkflowEventEmitter(JsonEventSink(sys.stdout), renderer)
        else:
            self.event_sink = event_sink

    def _transition(self, state: DeployState, detail: str = "", **data) -> None:
        self.state = state
        self._sequence += 1
        event = {
            "schema": 1,
            "workflow_id": self.workflow_id,
            "sequence": self._sequence,
            "state": state.name,
            "detail": detail,
        }
        if data:
            event["data"] = data
        self.event_sink(event)

    def _result(self, state: DeployState, detail: str, versions=None, rollback=None) -> DeployResult:
        self._transition(state, detail)
        return DeployResult(
            state, detail, versions or {}, self.snapshot, self.workflow_id, rollback
        )

    def _cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def _deadline(self):
        return None if self.WAIT_TIMEOUT_S is None else time.monotonic() + self.WAIT_TIMEOUT_S

    @staticmethod
    def _expired(deadline) -> bool:
        return deadline is not None and time.monotonic() >= deadline

    def _pause(self, interval: float) -> None:
        if self.cancel_event.wait(interval):
            raise McuMonitorCancelled("cancelled")

    def _safe_klippy_state(self) -> str:
        try:
            return self.client.get_klippy_state()
        except _NETWORK_ERRORS:
            return "disconnected"

    def _safe_mcu_versions(self) -> dict:
        try:
            return self.client.get_mcu_versions()
        except _NETWORK_ERRORS:
            return {}

    def _wait_moonraker(self) -> bool:
        deadline = self._deadline()
        interval = self.POLL_INTERVAL_S
        online_samples = 0
        while not self._expired(deadline):
            if self._cancelled():
                raise McuMonitorCancelled("cancelled")
            try:
                if self.client.is_moonraker_online():
                    online_samples += 1
                    if online_samples >= 2:
                        return True
                else:
                    online_samples = 0
            except _NETWORK_ERRORS:
                online_samples = 0
            self._pause(interval)
            interval = min(interval * 1.5, self.POLL_BACKOFF_MAX_S)
        return False

    def _wait_klipper_ready(self, *, fail_on_config_error: bool) -> tuple[bool, str]:
        deadline = self._deadline()
        interval = self.POLL_INTERVAL_S
        last = "disconnected"
        ready_samples = 0
        while not self._expired(deadline):
            if self._cancelled():
                raise McuMonitorCancelled("cancelled")
            last = self._safe_klippy_state()
            if last == "ready":
                ready_samples += 1
                if ready_samples >= 2:
                    return True, last
            else:
                ready_samples = 0
            if fail_on_config_error and last in ("shutdown", "error"):
                return False, last
            self._pause(interval)
            interval = min(interval * 1.5, self.POLL_BACKOFF_MAX_S)
        return False, last

    def _wait_mcu_registered(self) -> Optional[dict]:
        deadline = self._deadline()
        interval = self.POLL_INTERVAL_S
        while not self._expired(deadline):
            if self._cancelled():
                raise McuMonitorCancelled("cancelled")
            versions = self._safe_mcu_versions()
            if self._manifest_names.issubset(versions):
                return versions
            self._pause(interval)
            interval = min(interval * 1.5, self.POLL_BACKOFF_MAX_S)
        return None

    def _check_versions(self, actual: dict) -> tuple:
        wrong, missing = [], []
        for target in self.manifest.targets:
            reported = actual.get(target.name)
            if reported is None:
                missing.append(target.name)
            elif reported != target.expected_version:
                wrong.append(target.name)
        return wrong, missing

    def _verify_uploads(self) -> tuple[bool, str]:
        for artifact in self.manifest.artifacts():
            ok, remote = self.client.download_config(artifact.remote_name)
            if not ok or not isinstance(remote, bytes):
                return False, f"could not download {artifact.remote_name} after upload"
            remote_hash = hashlib.sha256(remote).hexdigest()
            if remote_hash != artifact.sha256:
                return False, f"checksum mismatch for {artifact.remote_name}"
        return True, ""

    def _rollback(self) -> tuple[bool, str]:
        if self.snapshot is None:
            return False, "no pre-deployment snapshot is available"
        self._transition(DeployState.ROLLING_BACK, "restoring previous configuration")
        try:
            failed = self.client.restore_snapshot(self.snapshot)
        except Exception as exc:
            return False, f"rollback failed: {exc}"
        if failed:
            return False, "rollback upload failed: " + ", ".join(failed)
        self._transition(DeployState.VERIFYING_ROLLBACK, "waiting for Klipper Ready after rollback")
        snapshot_names = set(self.snapshot.config_files) | set(
            getattr(self.snapshot, "missing_files", ())
        )
        if "moonraker.conf" in snapshot_names:
            try:
                self.client.restart_moonraker()
            except Exception as exc:
                return False, f"Moonraker rollback restart failed: {exc}"
        if not self._wait_moonraker():
            return False, "Moonraker did not recover after rollback"
        try:
            self.client.firmware_restart()
        except Exception as exc:
            return False, f"Klipper rollback restart failed: {exc}"
        ready, state = self._wait_klipper_ready(fail_on_config_error=True)
        if not ready:
            return False, f"Klipper did not become Ready after rollback (state={state})"
        return True, "rollback restored Klipper Ready"

    def run(self) -> DeployResult:
        versions = {}
        monitor_armed = False
        try:
            if self.snapshot_loader is not None:
                self._transition(DeployState.BACKUP, "capturing pre-deployment configuration")
                self.snapshot = self.snapshot_loader()
                if self.manifest.artifacts() and self.snapshot is None:
                    return self._result(
                        DeployState.FAILED_PRECONDITION,
                        "configuration backup failed; firmware deployment was not started",
                    )

            if self.monitor_before_firmware and self.mcu_monitor is not None:
                self.mcu_monitor.arm()
                monitor_armed = True
                self._transition(DeployState.MONITOR_ARMED, "physical MCU monitor armed")

            firmware_action = self.firmware_deploy or self.firmware_copy
            if firmware_action is not None:
                self._transition(DeployState.COPYING_FIRMWARE, "executing firmware deployment method")
                outcome = firmware_action()
                outcome_ok = outcome if isinstance(outcome, bool) else bool(getattr(outcome, "ok", False))
                outcome_detail = getattr(outcome, "detail", "")
                if not outcome_ok:
                    return self._result(
                        DeployState.FAILED_UPLOAD,
                        outcome_detail or "firmware deployment method did not complete",
                    )
                self._transition(
                    DeployState.FIRMWARE_COPIED,
                    outcome_detail or "firmware deployment method completed",
                )
            elif self.firmware_already_copied:
                self._transition(DeployState.FIRMWARE_COPIED, "firmware.bin copied to SD")

            if self.mcu_monitor is not None:
                if not monitor_armed:
                    self.mcu_monitor.arm()
                    monitor_armed = True
                    self._transition(DeployState.MONITOR_ARMED, "physical MCU monitor armed")
                if self.power_cycle_prompt:
                    self.power_cycle_prompt()
                if self.power_off:
                    self.power_off()
                self._transition(DeployState.AWAITING_DISCONNECT, "waiting for physical MCU removal")
                self.mcu_monitor.wait_for_absent(cancel_event=self.cancel_event, timeout=self.WAIT_TIMEOUT_S)
                self._transition(DeployState.MCU_ABSENT, "physical MCU absent")
                if self.power_on:
                    self.power_on()
                self._transition(DeployState.AWAITING_RECONNECT, "waiting for the same physical MCU")
                identity = self.mcu_monitor.wait_for_present(cancel_event=self.cancel_event, timeout=self.WAIT_TIMEOUT_S)
                self._transition(DeployState.MCU_PRESENT, "same physical MCU present", device=identity.device_node)

            self._transition(DeployState.WAITING_MOONRAKER, "waiting for Moonraker")
            if not self._wait_moonraker():
                return self._result(DeployState.TIMEOUT, "Moonraker wait expired")
            self._transition(DeployState.MOONRAKER_ONLINE, "Moonraker reachable")

            self._transition(DeployState.WAITING_KLIPPER_READY, "waiting for Klipper Ready")
            ready, state = self._wait_klipper_ready(fail_on_config_error=False)
            if not ready:
                return self._result(DeployState.TIMEOUT, f"Klipper Ready wait expired (state={state})")
            self._transition(DeployState.KLIPPER_READY, "Klipper Ready")

            self._transition(DeployState.WAITING_MCU_REGISTRATION, "waiting for MCU registration")
            versions = self._wait_mcu_registered()
            if versions is None:
                return self._result(DeployState.TIMEOUT, "MCU registration wait expired")
            self._transition(DeployState.MCU_REGISTERED, "all expected MCUs registered", versions=versions)

            self._transition(DeployState.VERIFYING_FIRMWARE, "verifying firmware fingerprint")
            if self.verify_firmware:
                wrong, missing = self._check_versions(versions)
                if wrong or missing:
                    detail = []
                    if wrong:
                        detail.append("wrong firmware: " + ", ".join(wrong))
                    if missing:
                        detail.append("missing MCU: " + ", ".join(missing))
                    return self._result(DeployState.FAILED_FLASH, "; ".join(detail), versions)
            self._transition(DeployState.FIRMWARE_VERIFIED, "firmware fingerprint verified")

            self._transition(DeployState.APPLYING_CONFIG, "uploading configuration")
            for artifact in self.manifest.artifacts():
                self.client.upload_config(artifact.local_path, artifact.remote_name)

            self._transition(DeployState.VERIFYING_UPLOAD, "verifying uploaded checksums")
            upload_ok, detail = self._verify_uploads()
            if not upload_ok:
                rollback_ok, rollback_detail = self._rollback()
                return self._result(DeployState.FAILED_UPLOAD, f"{detail}; {rollback_detail}", versions, rollback_ok)

            if any(
                artifact.remote_name == "moonraker.conf"
                for artifact in self.manifest.artifacts()
            ):
                self.client.restart_moonraker()
                self._transition(DeployState.WAITING_MOONRAKER, "waiting for Moonraker after config reconciliation")
                if not self._wait_moonraker():
                    rollback_ok, rollback_detail = self._rollback()
                    return self._result(
                        DeployState.CONFIG_ERROR,
                        f"Moonraker did not recover after config reconciliation; {rollback_detail}",
                        versions,
                        rollback_ok,
                    )

            self._transition(DeployState.FIRMWARE_RESTART, "restarting Klipper")
            self.client.firmware_restart()
            self._transition(DeployState.VERIFYING_CONFIG, "waiting for second Klipper Ready")
            if not self._wait_moonraker():
                rollback_ok, rollback_detail = self._rollback()
                return self._result(DeployState.CONFIG_ERROR, f"Moonraker did not recover; {rollback_detail}", versions, rollback_ok)
            ready, state = self._wait_klipper_ready(fail_on_config_error=True)
            if not ready:
                rollback_ok, rollback_detail = self._rollback()
                return self._result(DeployState.CONFIG_ERROR, f"new configuration state={state}; {rollback_detail}", versions, rollback_ok)

            return self._result(DeployState.DONE, "deployment validated", versions)
        except (KeyboardInterrupt, McuMonitorCancelled):
            return self._result(DeployState.ABORTED, "cancelled by user", versions)
        except McuIdentityMismatch as exc:
            return self._result(DeployState.FAILED_MONITOR, str(exc), versions)
        except McuMonitorError as exc:
            return self._result(DeployState.FAILED_MONITOR, str(exc), versions)
        except TimeoutError as exc:
            return self._result(DeployState.TIMEOUT, str(exc), versions)
        except Exception as exc:
            if self.state.value >= DeployState.APPLYING_CONFIG.value and self.state not in (
                DeployState.ROLLING_BACK, DeployState.VERIFYING_ROLLBACK
            ):
                try:
                    rollback_ok, rollback_detail = self._rollback()
                except Exception as rollback_exc:
                    rollback_ok, rollback_detail = False, f"rollback failed: {rollback_exc}"
                return self._result(DeployState.CONFIG_ERROR, f"{exc}; {rollback_detail}", versions, rollback_ok)
            return self._result(DeployState.FAILED_PRECONDITION, str(exc), versions)
        finally:
            try:
                if self.mcu_monitor is not None:
                    self.mcu_monitor.close()
            finally:
                if self._owns_event_sink:
                    self.event_sink.close()
