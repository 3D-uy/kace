# core/moonraker_deployer.py
#
# State-machine-driven firmware deployment engine for KACE.
#
# Client interface expected by Deployer (implemented by _MoonrakerClient
# in core/deployer.py):
#
#   client.get_klippy_state() -> str
#       Returns one of: "ready", "startup", "shutdown", "error", "disconnected"
#   client.get_mcu_versions() -> dict[str, str]
#       e.g. {"mcu": "kace-a1b2c3d", "mcu toolboard": "kace-e4f5a6b"}
#   client.upload_and_apply_config(printer_cfg_path, macros_cfg_path=None) -> None
#   client.firmware_restart() -> None

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

# Network error types treated as "still down" in polling safe wrappers.
#
# Why not bare `except:` or `except Exception:`?
#   - `except Exception:` would also swallow AttributeError, NameError, etc.,
#     hiding programming bugs in the client adapter as spurious "disconnected"
#     states that just loop until timeout. A typo in the adapter should crash
#     loudly, not look like a reboot window.
#   - `KeyboardInterrupt` and `SystemExit` inherit from BaseException, NOT
#     Exception. So `except Exception:` already lets them propagate correctly
#     to the `except KeyboardInterrupt:` handler in `_wait_for_reconnect`.
#     _NETWORK_ERRORS is a strict subset of Exception, so that invariant holds.
#
# The tuple is built at import time so the cost is paid once, not per-call.
_NETWORK_ERRORS: tuple = (OSError, ConnectionError, TimeoutError)
try:
    # requests.exceptions are IOError / OSError subclasses in recent versions,
    # but importing explicitly makes the intent clear and covers edge cases.
    from requests.exceptions import RequestException as _RequestException
    _NETWORK_ERRORS = _NETWORK_ERRORS + (_RequestException,)
except ImportError:
    pass  # requests not installed; OSError family already covers most cases


class DeployState(Enum):
    INIT                = auto()
    BACKUP              = auto()  # capturing pre-deployment snapshot
    AWAITING_DISCONNECT = auto()
    AWAITING_RECONNECT  = auto()
    VERIFYING_FIRMWARE  = auto()
    APPLYING_CONFIG     = auto()
    VERIFYING_UPLOAD    = auto()  # verifying byte-for-byte upload integrity
    FIRMWARE_RESTART    = auto()
    VERIFYING_CONFIG    = auto()  # verifying post-restart config/Klipper health
    DONE                = auto()
    # Terminal failure states
    FAILED_FLASH        = auto()  # reconnected but version mismatch on >=1 MCU
    TIMEOUT             = auto()  # never reached "ready" within budget
    CONFIG_ERROR        = auto()  # Klipper shutdown/error after reboot
    ABORTED             = auto()  # user cancelled
    FAILED_UPLOAD       = auto()  # upload integrity validation failed


@dataclass
class McuTarget:
    """One MCU KACE compiled firmware for in this run."""
    name: str             # Moonraker object name, e.g. "mcu", "mcu toolboard"
    expected_version: str # e.g. "kace-a1b2c3d" (sha256[:8] of .config)


@dataclass
class DeploymentManifest:
    """Build manifest produced by builder.py for one firmware compile run."""
    targets: list           # list[McuTarget]
    printer_cfg_path: str
    macros_cfg_path: object = None  # str | None


@dataclass
class DeployResult:
    state: DeployState
    detail: str = ""
    mcu_versions: dict = field(default_factory=dict)
    snapshot: Optional[object] = None  # DeploymentSnapshot | None (typed as object to avoid circular import)


class Deployer:
    """
    Drives one firmware deployment through to completion.

    Usage:
        deployer = Deployer(client, manifest)
        result   = deployer.run()

    NOTE: run() is synchronous and blocks for up to DISCONNECT_TIMEOUT_S +
    RECONNECT_TIMEOUT_S (~105s worst case). KACE is a CLI tool, so blocking
    the calling thread is the expected behaviour. If this is ever integrated
    into an async context, wrap the call in a thread or task.
    """

    DISCONNECT_COOLDOWN_S = 2.0    # ignore reads right after prompting reboot
    DISCONNECT_TIMEOUT_S  = 15.0   # how long to wait for Klipper to actually drop
    RECONNECT_TIMEOUT_S   = 90.0   # generous -- CAN toolboards can lag mainboard
    POLL_INTERVAL_S       = 1.0
    POLL_BACKOFF_MAX_S    = 5.0

    class _ReconnectOutcome(Enum):
        """Internal outcome of _wait_for_reconnect. Kept nested so it doesn't
        pollute the module namespace -- callers see it only via run()'s branching."""
        READY        = auto()  # Klipper ready AND all manifest MCUs visible
        CONFIG_ERROR = auto()  # Klipper entered shutdown/error state
        TIMEOUT      = auto()  # Deadline elapsed before all conditions met
        ABORTED      = auto()  # KeyboardInterrupt during polling wait

    def __init__(self, client, manifest: DeploymentManifest, verify_firmware: bool = True,
                 snapshot: Optional[object] = None):
        self.client          = client
        self.manifest        = manifest
        self.verify_firmware = verify_firmware
        self.snapshot        = snapshot  # pre-captured DeploymentSnapshot | None
        self.state           = DeployState.INIT
        self._manifest_names = {t.name for t in manifest.targets}

    # ── Safe client wrappers ───────────────────────────────────────────────
    # The reboot window is exactly when the Pi's network stack is flapping
    # and Moonraker's HTTP endpoint is intermittently unreachable. Any
    # ConnectionError, TimeoutError, or similar should be treated as
    # "still down, keep polling" rather than propagating up as a crash.

    def _safe_klippy_state(self) -> str:
        """Return Klippy state string; treat network errors as 'disconnected'.

        Catches only _NETWORK_ERRORS (OSError / ConnectionError / TimeoutError
        and optionally requests.RequestException). KeyboardInterrupt and
        SystemExit are BaseException subclasses and are NOT caught here, so
        they propagate correctly to _wait_for_reconnect's cancellation handler.
        """
        try:
            return self.client.get_klippy_state()
        except _NETWORK_ERRORS:
            return "disconnected"

    def _safe_mcu_versions(self) -> dict:
        """Return MCU versions dict; treat network errors as empty dict.

        Same exception-narrowing rationale as _safe_klippy_state: only network
        errors are swallowed; programming errors in the adapter still propagate.
        """
        try:
            return self.client.get_mcu_versions()
        except _NETWORK_ERRORS:
            return {}

    def run(self) -> DeployResult:
        # ── Phase 1: Wait for disconnect (best-effort) ──────────────────
        self.state = DeployState.AWAITING_DISCONNECT
        disconnect_confirmed = self._wait_for_disconnect()
        if not disconnect_confirmed:
            # Printer never went offline. This could mean no power-cycle
            # occurred, a very fast reboot, or a network blip masked the drop.
            # Proceed anyway — the version check in Phase 3 will catch stale
            # firmware, but surface a note so the eventual error is less
            # confusing than "running old firmware" with no context.
            print("\033[93m[!] Printer did not go offline — " 
                  "power-cycle may not have triggered. Proceeding with version check.\033[0m")

        # ── Phase 2: Wait for reconnect + all manifest MCUs present ─────
        # _wait_for_reconnect returns (outcome, versions_dict) so run() can
        # reuse the last-fetched versions without a second round-trip or race.
        self.state = DeployState.AWAITING_RECONNECT
        outcome, versions = self._wait_for_reconnect()
        if outcome is self._ReconnectOutcome.ABORTED:
            return DeployResult(DeployState.ABORTED, "Cancelled by user during reconnect wait")
        if outcome is self._ReconnectOutcome.TIMEOUT:
            return DeployResult(DeployState.TIMEOUT, "Printer did not come back online in time")
        if outcome is self._ReconnectOutcome.CONFIG_ERROR:
            return DeployResult(DeployState.CONFIG_ERROR, "Klipper reported shutdown/error on reboot")

        # ── Phase 3: Verify firmware versions ────────────────────────────
        # versions was fetched by _wait_for_reconnect at the moment all MCUs
        # became visible — no second call needed.
        self.state = DeployState.VERIFYING_FIRMWARE
        if self.verify_firmware:
            wrong_version, not_visible = self._check_versions(versions)
            if wrong_version or not_visible:
                parts = []
                if wrong_version:
                    parts.append("running old firmware: " + ", ".join(wrong_version))
                if not_visible:
                    parts.append("missing from Moonraker: " + ", ".join(not_visible))
                return DeployResult(DeployState.FAILED_FLASH, "; ".join(parts), mcu_versions=versions)
        else:
            # --dev-deploy: skip fingerprint check but still surface what versions
            # are actually running so the user can see the mismatch in the log.
            print(
                "\033[93m[DEV] --dev-deploy active — firmware fingerprint check skipped.\033[0m\n"
                "\033[93m      Do NOT use this flag in production.\033[0m"
            )
            if versions:
                for name, ver in versions.items():
                    print(f"\033[93m      {name}: {ver} (running)\033[0m")

        # ── Phase 4: Apply config ─────────────────────────────────────────
        self.state = DeployState.APPLYING_CONFIG
        self.client.upload_and_apply_config(
            self.manifest.printer_cfg_path,
            self.manifest.macros_cfg_path,
        )

        # ── Phase 4.5: Verify configuration upload ─────────────────────────
        self.state = DeployState.VERIFYING_UPLOAD

        # Verify printer.cfg exists on the target after upload.
        # Klipper performs authoritative configuration validation on restart,
        # so we only need to confirm the file was accepted and stored.
        try:
            if not self.client.verify_file_exists("printer.cfg"):
                return DeployResult(DeployState.FAILED_UPLOAD, "Verification failed: printer.cfg not found on target after upload")
        except Exception as e:
            return DeployResult(DeployState.FAILED_UPLOAD, f"Could not verify printer.cfg on target: {e}")

        # Verify macros.cfg if it was uploaded
        if self.manifest.macros_cfg_path:
            try:
                if not self.client.verify_file_exists("macros.cfg"):
                    return DeployResult(DeployState.FAILED_UPLOAD, "Verification failed: macros.cfg not found on target after upload")
            except Exception as e:
                return DeployResult(DeployState.FAILED_UPLOAD, f"Could not verify macros.cfg on target: {e}")

        # ── Phase 5: Trigger firmware restart ─────────────────────────────
        self.state = DeployState.FIRMWARE_RESTART
        self.client.firmware_restart()

        # ── Phase 6: Post-restart Verification ─────────────────────────────
        # Wait for Klipper to reload and confirm it enters the "ready" state
        # using the new configuration.
        self.state = DeployState.VERIFYING_CONFIG
        
        # Wait for the restart-triggered disconnect to happen
        self._wait_for_disconnect()
        
        # Wait for Klipper to come back up and reach ready
        outcome, versions = self._wait_for_reconnect()
        
        if outcome is self._ReconnectOutcome.ABORTED:
            return DeployResult(DeployState.ABORTED, "Cancelled by user during post-restart verification")
        if outcome is self._ReconnectOutcome.TIMEOUT:
            return DeployResult(DeployState.TIMEOUT, "Printer did not come back online after configuration update")
        if outcome is self._ReconnectOutcome.CONFIG_ERROR:
            return DeployResult(DeployState.CONFIG_ERROR, "Klipper reported shutdown/error with the new configuration")

        self.state = DeployState.DONE
        return DeployResult(
            DeployState.DONE,
            "Deployment verified and applied",
            mcu_versions=versions,
            snapshot=self.snapshot,
        )

    # ── Internals ─────────────────────────────────────────────────────────

    def _wait_for_disconnect(self) -> bool:
        """Poll until Klippy leaves 'ready'. Returns True if disconnect was
        confirmed, False if the timeout elapsed without observing a drop.

        Network exceptions during the reboot window are handled by
        _safe_klippy_state() and treated as 'still disconnecting'.
        """
        time.sleep(self.DISCONNECT_COOLDOWN_S)
        deadline = time.monotonic() + self.DISCONNECT_TIMEOUT_S
        interval = self.POLL_INTERVAL_S
        while time.monotonic() < deadline:
            if self._safe_klippy_state() != "ready":
                return True  # confirmed disconnect
            time.sleep(interval)
            interval = min(interval * 1.5, self.POLL_BACKOFF_MAX_S)
        return False  # timed out without observing disconnect

    def _wait_for_reconnect(self) -> tuple:
        """Poll until Klippy is 'ready' AND every manifest MCU is visible.

        Returns (outcome, versions_dict). versions_dict is the last-fetched
        get_mcu_versions() snapshot at the moment all MCUs became visible,
        so run() can reuse it in _check_versions() without a second round-trip
        or a race between two sequential Moonraker queries.

        Network exceptions during the reboot window are handled by the safe
        wrappers — they are treated as 'not yet ready' and polling continues.

        KeyboardInterrupt is caught and returned as ABORTED so the caller can
        surface a clean cancellation message rather than a stack trace.
        """
        deadline = time.monotonic() + self.RECONNECT_TIMEOUT_S
        interval = self.POLL_INTERVAL_S
        try:
            while time.monotonic() < deadline:
                s = self._safe_klippy_state()
                if s in ("shutdown", "error"):
                    return self._ReconnectOutcome.CONFIG_ERROR, {}
                if s == "ready":
                    live = self._safe_mcu_versions()
                    if self._manifest_names.issubset(live.keys()):
                        return self._ReconnectOutcome.READY, live
                    # Ready but not all MCUs visible yet (e.g. CAN toolboard
                    # still handshaking) -- keep polling rather than bail out.
                time.sleep(interval)
                interval = min(interval * 1.5, self.POLL_BACKOFF_MAX_S)
        except KeyboardInterrupt:
            return self._ReconnectOutcome.ABORTED, {}
        return self._ReconnectOutcome.TIMEOUT, {}

    def _check_versions(self, actual: dict) -> tuple:
        """Returns (wrong_version, not_visible) lists of MCU names.

        wrong_version: MCU visible but version doesn't match compiled binary.
        not_visible:   MCU key absent.
                       
                       NOTE: This is a defensive branch. Since `_wait_for_reconnect`
                       guarantees that all manifest MCU names are keys in `actual`
                       before returning READY, and `run()` reuses that identical
                       versions snapshot, `not_visible` is normally unreachable
                       under the current state machine flow. It is retained to
                       prevent regressions if the flow/manifest verification
                       logic changes in the future.
        """
        wrong_version, not_visible = [], []
        for target in self.manifest.targets:
            reported = actual.get(target.name)
            if reported is None:
                not_visible.append(target.name)
            elif reported != target.expected_version:
                wrong_version.append(target.name)
        return wrong_version, not_visible
