"""Shared verified transaction for SSH and Moonraker config-only deployment."""

from __future__ import annotations

import hashlib
import os
import posixpath
import tempfile
import threading
import time
import uuid
from contextlib import nullcontext
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, Mapping, Optional
from urllib.parse import urlsplit
from weakref import WeakValueDictionary

from core.configuration_review import ConfigurationReview, build_configuration_review

from core.managed_config import (
    HARDWARE_REMOTE,
    LEGACY_MACROS_REMOTE,
    MACROS_REMOTE,
    MOONRAKER_REMOTE,
    ROOT_REMOTE,
    ManagedConfigPlan,
    build_managed_config_plan,
    config_includes,
)
from core.snapshot import (
    DeploymentSnapshot, create_snapshot, rollback_file_owned, verify_snapshot_restored,
)


_destination_locks = WeakValueDictionary()
_destination_locks_guard = threading.Lock()
_UNCONDITIONAL = object()


def config_destination_lock(transport):
    """Serialize one destination in this process, including activation/rollback.

    Separate transport instances must supply the same destination_key for the
    same printer. This is not a lock against Mainsail or independent processes.
    """
    key = transport.destination_key
    if not isinstance(key, tuple) or not key:
        raise ValueError("configuration destination identity is unavailable")
    with _destination_locks_guard:
        lock = _destination_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _destination_locks[key] = lock
        return lock


class ConfigConflictError(RuntimeError):
    """The reviewed remote state changed or could not be revalidated."""


class FirmwareVerificationError(RuntimeError):
    """The activated MCU does not prove the expected firmware identity."""


def read_config_state(transport, generated_hardware: bytes = b"", generated_macros: Optional[bytes] = None) -> dict[str, Optional[bytes]]:
    """Copy a complete byte-level baseline, distinguishing absence from failure."""
    names = ConfigDeploymentTransaction.CANDIDATES
    remote = transport.read_files(names)
    state = {}
    for name in names:
        content = remote[name]  # An omitted entry is not confirmed absence.
        if content is not None and not isinstance(content, bytes):
            raise TypeError(f"configuration read did not return bytes for {name}")
        state[name] = content
    pending = [(ROOT_REMOTE, generated_hardware), (MACROS_REMOTE, generated_macros), (ROOT_REMOTE, state[ROOT_REMOTE])]
    visited = set()
    total = 0
    while pending:
        source, content = pending.pop()
        if content is None:
            continue
        key = (source, content)
        if key in visited:
            continue
        visited.add(key)
        total += len(content)
        if len(state) > 256 or total > 8 * 1024 * 1024:
            raise ValueError("configuration include graph exceeds review limits")
        for _, name in config_includes(content, source):
            if name not in state:
                value = transport.read_files((name,))[name]
                if value is not None and not isinstance(value, bytes):
                    raise TypeError(f"configuration read did not return bytes for {name}")
                state[name] = value
            pending.append((name, state[name]))
    return state


def require_conditional_writes(transport, plan, *, persist_root=None):
    """Reject a whole unsafe plan before any live write or firmware action."""
    unsupported = [item for item in plan.changed_artifacts
                   if not transport.supports_conditional_write(item.previous)]
    if unsupported:
        proposal = create_snapshot(
            {item.remote_name: item.content for item in plan.artifacts},
            deployment_id=f"{uuid.uuid4()}-proposed", persist_root=persist_root,
        )
        raise ConfigConflictError(
            "transport cannot atomically condition these writes on reviewed content: "
            + ", ".join(item.remote_name for item in unsupported)
            + f"; live files preserved; manually apply reviewed proposal from {proposal.storage_path}"
        )


def revalidate_config_state(transport, reviewed) -> dict[str, Optional[bytes]]:
    """Fail closed on content changes, creations, removals or unreadable files."""
    try:
        transport.validate_activation_target()
        remote = transport.read_files(tuple(reviewed))
        current = {name: remote[name] for name in reviewed}
        if any(value is not None and not isinstance(value, bytes) for value in current.values()):
            raise TypeError("configuration read did not return bytes")
    except Exception as exc:
        raise ConfigConflictError(f"configuration revalidation failed: {exc}") from exc
    changed = [name for name in current if current[name] != reviewed[name]]
    if changed:
        raise ConfigConflictError(
            "concurrent configuration modification detected: " + ", ".join(changed)
        )
    return current


class ConfigTransactionState(Enum):
    PRECONDITION_FAILED = auto()
    CANCELLED = auto()
    SNAPSHOT_FAILED = auto()
    UPLOAD_FAILED = auto()
    VERIFY_FAILED = auto()
    ACTIVATION_FAILED = auto()
    FIRMWARE_FAILED = auto()
    ROLLBACK_FAILED = auto()
    DEPLOYED_PENDING_ACTIVATION = auto()
    COMMITTED = auto()


@dataclass(frozen=True)
class ConfigTransactionResult:
    state: ConfigTransactionState
    detail: str
    transaction_id: str = ""
    snapshot: Optional[DeploymentSnapshot] = None
    rollback_succeeded: Optional[bool] = None

    @property
    def ok(self) -> bool:
        return self.state is ConfigTransactionState.COMMITTED

    @property
    def pending(self) -> bool:
        return self.state is ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION


class ConfigDeploymentTransaction:
    """Execute the same preflight/snapshot/upload/verify flow for any transport.

    The transport must expose a stable ``destination_key`` tuple, ``read_files``,
    ``validate_activation_target``, ``supports_conditional_write``,
    ``upload_if_unchanged``,
    ``restart``, ``restart_moonraker``, ``moonraker_online`` and
    ``klipper_state``. Read failures must raise; ``None`` is reserved for a
    positively confirmed absent file.
    """

    CANDIDATES = (
        ROOT_REMOTE,
        MOONRAKER_REMOTE,
        HARDWARE_REMOTE,
        MACROS_REMOTE,
        LEGACY_MACROS_REMOTE,
    )

    def __init__(
        self,
        transport,
        generated_hardware: bytes,
        generated_macros: Optional[bytes],
        *,
        activation: str,
        confirm: Optional[Callable[[str], bool]] = None,
        output: Optional[Callable[[str], None]] = None,
        review: Optional[Callable[[ConfigurationReview], bool]] = None,
        activation_selector: Optional[Callable[[], str]] = None,
        snapshot_root: Optional[str] = None,
        board: str = "",
        kace_version: str = "unknown",
        timeout: float = 90.0,
        poll_interval: float = 1.0,
        state_sink: Optional[Callable[[str, str], None]] = None,
        verify_existing_ready: bool = False,
        verify_firmware: Optional[Callable[[], None]] = None,
    ):
        if activation not in {"firmware", "service", "none"}:
            raise ValueError(f"Unsupported activation mode: {activation}")
        self.transport = transport
        self.generated_hardware = generated_hardware
        self.generated_macros = generated_macros
        self.activation = activation
        self.confirm = confirm or (lambda _diff: True)
        self.output = output or (lambda _line: None)
        self.review = review
        self.activation_selector = activation_selector
        self.snapshot_root = snapshot_root
        self.board = board
        self.kace_version = kace_version
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.transaction_id = str(uuid.uuid4())
        self.snapshot: Optional[DeploymentSnapshot] = None
        self.plan: Optional[ManagedConfigPlan] = None
        self._expected_config_state: dict[str, Optional[bytes]] = {}
        self._written_names: set[str] = set()
        self.state_sink = state_sink
        self.verify_existing_ready = bool(verify_existing_ready)
        self.verify_firmware = verify_firmware

    def _emit(self, state: str, detail: str) -> None:
        if self.state_sink is None:
            return
        try:
            self.state_sink(state, detail)
        except Exception:
            # Studio progress is observational and cannot change transaction
            # authority or rollback behavior.
            pass

    def _verify_firmware(self) -> None:
        if self.verify_firmware is not None:
            try:
                self.verify_firmware()
            except Exception as exc:
                raise FirmwareVerificationError(str(exc)) from exc

    @staticmethod
    def _sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _wait_ready(self) -> tuple[bool, str]:
        deadline = time.monotonic() + self.timeout
        last = "disconnected"
        ready_samples = 0
        while time.monotonic() < deadline:
            if not self.transport.moonraker_online():
                ready_samples = 0
                time.sleep(self.poll_interval)
                continue
            last = self.transport.klipper_state()
            if last == "ready":
                ready_samples += 1
                if ready_samples >= 2:
                    return True, last
                time.sleep(self.poll_interval)
                continue
            ready_samples = 0
            if last in {"shutdown", "error"}:
                return False, last
            time.sleep(self.poll_interval)
        return False, last

    def _wait_moonraker(self) -> bool:
        deadline = time.monotonic() + self.timeout
        online_samples = 0
        while time.monotonic() < deadline:
            if self.transport.moonraker_online():
                online_samples += 1
                if online_samples >= 2:
                    return True
            else:
                online_samples = 0
            time.sleep(self.poll_interval)
        return False

    def _ordered_artifacts(self):
        assert self.plan is not None
        # Includes must exist before root printer.cfg starts referencing them.
        return sorted(
            self.plan.changed_artifacts,
            key=lambda item: (item.remote_name == ROOT_REMOTE, item.remote_name),
        )

    def _verify_plan(self) -> None:
        assert self.plan is not None
        self.transport.validate_activation_target()
        current = self.transport.read_files(tuple(self._expected_config_state))
        planned = {item.remote_name: item.content for item in self.plan.artifacts}
        for name, expected in planned.items():
            if current[name] is None:
                raise RuntimeError(f"uploaded file disappeared: {name}")
            if current[name] != expected:
                raise RuntimeError(f"checksum mismatch for {name}")
        changed = [name for name, expected in self._expected_config_state.items()
                   if name not in planned and current[name] != expected]
        if changed:
            raise ConfigConflictError("concurrent configuration modification detected: " + ", ".join(changed))

    def _rollback(self) -> tuple[Optional[bool], str]:
        if not self._written_names:
            return None, "rollback not required: the failed upload created no remote file"
        if self.snapshot is None:
            return False, "no snapshot is available"
        expected = {item.remote_name: item.content for item in self.plan.changed_artifacts}

        def owned(name):
            current = self.transport.read_files((name,))[name]
            return rollback_file_owned(
                name, current, self.snapshot.config_files.get(name), expected[name],
            )

        # Diagnose conflicts without performing a read-then-write rollback.
        try:
            for name in self._written_names:
                owned(name)
        except Exception as exc:
            return False, f"rollback conflict; current files preserved: {exc}; manual recovery from {self.snapshot.storage_path}"
        restored_names = tuple(self._written_names)
        try:
            verify_snapshot_restored(self.snapshot,
                self.transport.read_files(restored_names), restored_names)
        except Exception:
            # None of the supported transports offers atomic compare-and-swap.
            # Keep current bytes and the durable snapshot for operator recovery.
            return False, ("automatic rollback unavailable: transport has no atomic conditional restore; "
                           f"current files preserved; manual recovery from snapshot {self.snapshot.storage_path}")

        def verify_restoration():
            verify_snapshot_restored(
                self.snapshot, self.transport.read_files(restored_names), restored_names,
            )

        try:
            verify_restoration()
            if self.activation == "none":
                return True, "rollback restored byte-identical inactive files"
            if MOONRAKER_REMOTE in self.snapshot.config_files or MOONRAKER_REMOTE in self.snapshot.missing_files:
                self.transport.restart_moonraker()
                if not self._wait_moonraker():
                    return False, "Moonraker did not recover after rollback"
            self.transport.restart(self.activation)
            ready, state = self._wait_ready()
            if not ready:
                return False, f"Klipper did not become Ready after rollback (state={state})"
            verify_restoration()
        except Exception as exc:
            return False, f"rollback verification or activation failed: {exc}"
        return True, "rollback restored byte-identical state and Klipper Ready"

    def _record_possible_write(self, name: str) -> None:
        """Record a failed upload only when the remote bytes may have changed."""
        assert self.snapshot is not None
        try:
            current = self.transport.read_files((name,)).get(name)
        except (Exception, KeyboardInterrupt):
            # If the post-failure state cannot be inspected, rollback must be
            # conservative: the server may have written before returning an
            # error or dropping the connection.
            self._written_names.add(name)
            return
        if name in self.snapshot.missing_files and current is None:
            return
        if (
            name in self.snapshot.config_files
            and current == self.snapshot.config_files[name]
        ):
            return
        self._written_names.add(name)

    def run(self) -> ConfigTransactionResult:
        try:
            lock = config_destination_lock(self.transport)
        except Exception as exc:
            return ConfigTransactionResult(
                ConfigTransactionState.PRECONDITION_FAILED,
                f"configuration destination could not be identified: {exc}",
                self.transaction_id,
            )
        # Hold through review, snapshot, activation and rollback. A second KACE
        # transaction must not read an intermediate state or race a rollback.
        with lock:
            try:
                with (self.transport.destination_lock() if hasattr(self.transport, "destination_lock") else nullcontext()):
                    return self._run_locked()
            except KeyboardInterrupt:
                rollback_ok, rollback_detail = None, "no configuration files were written"
                if self._written_names:
                    try:
                        rollback_ok, rollback_detail = self._rollback()
                    except KeyboardInterrupt:
                        rollback_ok, rollback_detail = False, "rollback interrupted by user"
                    except Exception as exc:
                        rollback_ok, rollback_detail = False, f"rollback failed: {exc}"
                state = ConfigTransactionState.CANCELLED
                if rollback_ok is False:
                    state = ConfigTransactionState.ROLLBACK_FAILED
                    detail = f"cancelled by user; rollback error: {rollback_detail}"
                elif rollback_ok is True:
                    detail = f"cancelled by user; rollback succeeded: {rollback_detail}"
                else:
                    detail = f"cancelled by user; {rollback_detail}"
                return ConfigTransactionResult(
                    state, detail, self.transaction_id, self.snapshot, rollback_ok,
                )
            except (OSError, TimeoutError, ConfigConflictError) as exc:
                return ConfigTransactionResult(
                    ConfigTransactionState.PRECONDITION_FAILED,
                    f"local publication could not be secured: {exc}", self.transaction_id, self.snapshot,
                )

    def _preserve_proposal(self):
        if self.plan is not None:
            create_snapshot(
                {item.remote_name: item.content for item in self.plan.artifacts},
                deployment_id=self.transaction_id + "-proposed", persist_root=self.snapshot_root,
            )

    def _run_locked(self) -> ConfigTransactionResult:
        self._emit("BACKUP", "validating configuration and preparing snapshot")
        try:
            self.transport.validate_activation_target()
            remote = read_config_state(self.transport, self.generated_hardware, self.generated_macros)
            self.plan = build_managed_config_plan(
                self.generated_hardware, self.generated_macros, remote
            )
            self._expected_config_state = {
                **remote, **{item.remote_name: item.content for item in self.plan.artifacts},
            }
            diff = self.plan.dry_run_diff()
            configuration_review = build_configuration_review(self.plan)
            require_conditional_writes(self.transport, self.plan, persist_root=self.snapshot_root)
            if self.review is None:
                self.output(diff or "No configuration changes are required.")
                for warning in configuration_review.validation.warnings:
                    self.output(f"WARNING: {warning.message}")
                for error in configuration_review.validation.errors:
                    self.output(f"ERROR: {error.message}")
            else:
                accepted = self.review(configuration_review)
        except Exception as exc:
            return ConfigTransactionResult(
                ConfigTransactionState.PRECONDITION_FAILED,
                f"configuration preflight failed: {exc}",
                self.transaction_id,
            )

        if not configuration_review.validation.valid:
            return ConfigTransactionResult(
                ConfigTransactionState.PRECONDITION_FAILED,
                "semantic configuration validation failed: "
                + "; ".join(item.message for item in configuration_review.validation.errors),
                self.transaction_id,
            )

        try:
            if not (accepted if self.review is not None else self.confirm(diff)):
                return ConfigTransactionResult(
                    ConfigTransactionState.CANCELLED,
                    "deployment cancelled after dry-run diff",
                    self.transaction_id,
                )
            # Only a verified no-op retry can skip the restart decision. Files
            # may already match while their activation is still pending.
            if self.activation_selector is not None and (
                self.plan.changed_artifacts or not self.verify_existing_ready
            ):
                selected = self.activation_selector()
                if selected not in {"firmware", "service", "none"}:
                    raise ValueError(f"Unsupported activation mode: {selected}")
                self.activation = selected
            current = revalidate_config_state(self.transport, remote)
            require_conditional_writes(self.transport, self.plan, persist_root=self.snapshot_root)
            originals = {
                item.remote_name: current[item.remote_name] for item in self.plan.changed_artifacts
            }
            self.snapshot = create_snapshot(
                originals,
                deployment_id=self.transaction_id,
                board=self.board,
                kace_version=self.kace_version,
                persist_root=self.snapshot_root,
            ) if originals else None
        except ConfigConflictError as exc:
            self._preserve_proposal()
            return ConfigTransactionResult(
                ConfigTransactionState.PRECONDITION_FAILED,
                f"{exc}; no configuration files were written",
                self.transaction_id,
            )
        except OSError as exc:
            return ConfigTransactionResult(
                ConfigTransactionState.SNAPSHOT_FAILED,
                f"snapshot could not be completed: {exc}",
                self.transaction_id,
            )
        except Exception as exc:
            return ConfigTransactionResult(
                ConfigTransactionState.SNAPSHOT_FAILED,
                f"snapshot could not be completed: {exc}",
                self.transaction_id,
            )

        self._emit("APPLYING_CONFIG", "uploading reconciled configuration")
        try:
            # Snapshot persistence can take time. Check again immediately before
            # the first write; external editors do not participate in our lock.
            revalidate_config_state(self.transport, current)
        except ConfigConflictError as exc:
            self._preserve_proposal()
            return ConfigTransactionResult(
                ConfigTransactionState.PRECONDITION_FAILED,
                f"{exc}; no configuration files were written",
                self.transaction_id,
                self.snapshot,
            )

        try:
            for artifact in self._ordered_artifacts():
                revalidate_config_state(self.transport, {artifact.remote_name: current[artifact.remote_name]})
                try:
                    self.transport.upload_if_unchanged(artifact.remote_name, artifact.content, current[artifact.remote_name])
                    self._written_names.add(artifact.remote_name)
                except (Exception, KeyboardInterrupt):
                    self._record_possible_write(artifact.remote_name)
                    raise
            self._emit("VERIFYING_UPLOAD", "verifying uploaded configuration checksums")
            self._verify_plan()
            if not self.plan.changed_artifacts and self.verify_existing_ready:
                ready, state = self._wait_ready()
                if not ready:
                    raise RuntimeError(f"Klipper did not become Ready (state={state})")
                self._verify_firmware()
                if hasattr(self.transport, "verify_active_configuration"):
                    self.transport.verify_active_configuration(self.plan)
                self._verify_plan()
                self._emit("DONE", "configuration already installed; Klipper Ready")
                return ConfigTransactionResult(
                    ConfigTransactionState.COMMITTED,
                    "configuration already installed; Klipper Ready and firmware verified",
                    self.transaction_id,
                )
            if self.activation == "none":
                return ConfigTransactionResult(
                    ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION,
                    "checksums verified; configuration requires an explicit restart",
                    self.transaction_id,
                    self.snapshot,
                )

            self.transport.validate_activation_target()
            if any(item.remote_name == MOONRAKER_REMOTE for item in self.plan.changed_artifacts):
                self._emit("WAITING_MOONRAKER", "restarting Moonraker before Klipper activation")
                self.transport.restart_moonraker()
                if not self._wait_moonraker():
                    raise RuntimeError("Moonraker did not recover after restart")
            self._emit("FIRMWARE_RESTART", "restarting Klipper to activate configuration")
            self.transport.restart(self.activation)
            self._emit("VERIFYING_CONFIG", "waiting for Klipper Ready after restart")
            ready, state = self._wait_ready()
            if not ready:
                raise RuntimeError(f"Klipper did not become Ready (state={state})")
            self._verify_firmware()
            self._verify_plan()
            self._emit("DONE", "configuration activated and Klipper Ready")
            return ConfigTransactionResult(
                ConfigTransactionState.COMMITTED,
                "configuration checksums verified and Klipper Ready",
                self.transaction_id,
                self.snapshot,
            )
        except Exception as exc:
            self._preserve_proposal()
            self._emit("CONFIG_ERROR", str(exc))
            rollback_ok, rollback_detail = self._rollback()
            state = (
                ConfigTransactionState.FIRMWARE_FAILED
                if isinstance(exc, FirmwareVerificationError)
                else ConfigTransactionState.ACTIVATION_FAILED
                if "Ready" in str(exc) or "restart" in str(exc).lower()
                else ConfigTransactionState.VERIFY_FAILED
                if "checksum" in str(exc)
                else ConfigTransactionState.UPLOAD_FAILED
            )
            failure_label = {
                ConfigTransactionState.FIRMWARE_FAILED: "firmware verification error",
                ConfigTransactionState.ACTIVATION_FAILED: "activation error",
                ConfigTransactionState.VERIFY_FAILED: "verification error",
                ConfigTransactionState.UPLOAD_FAILED: "upload error",
            }[state]
            if rollback_ok is False:
                state = ConfigTransactionState.ROLLBACK_FAILED
                detail = f"{failure_label}: {exc}; rollback error: {rollback_detail}"
            elif rollback_ok is True:
                detail = f"{failure_label}: {exc}; rollback succeeded: {rollback_detail}"
            else:
                detail = f"{failure_label}: {exc}; {rollback_detail}"
            return ConfigTransactionResult(
                state,
                detail,
                self.transaction_id,
                self.snapshot,
                rollback_ok,
            )


class MoonrakerConfigTransport:
    """Config transaction transport backed by Moonraker's file/API endpoints."""

    def __init__(self, host: str, port: int, api_key: Optional[str] = None):
        self.host = host
        self.port = port
        self.api_key = api_key

    def _active_config(self):
        from core.moonraker import _get, _base_url
        ok, detail, body = _get(_base_url(self.host, self.port) + "/printer/info", api_key=self.api_key)
        path = body.get("result", {}).get("config_file") if ok else None
        if not isinstance(path, str) or not path.startswith("/"):
            raise ConfigConflictError(f"active Klipper config_file is unavailable: {detail}")
        return posixpath.normpath(path)

    def validate_activation_target(self):
        from core.moonraker import _get, _base_url
        active = self._active_config()
        ok, detail, body = _get(_base_url(self.host, self.port) + "/server/files/roots", api_key=self.api_key)
        roots = [entry.get("path") for entry in body.get("result", []) if entry.get("name") == "config"] if ok else []
        if len(roots) != 1 or not isinstance(roots[0], str) or active != posixpath.join(roots[0], ROOT_REMOTE):
            raise ConfigConflictError("Moonraker config root does not match active Klipper printer.cfg")

    def verify_active_configuration(self, plan):
        from core.moonraker import _get, _base_url
        from core.managed_config import effective_hardware_text, _section_options
        ok, detail, body = _get(_base_url(self.host, self.port) + "/printer/objects/query?configfile", api_key=self.api_key)
        active = body.get("result", {}).get("status", {}).get("configfile", {}).get("config") if ok else None
        if not isinstance(active, dict):
            raise ConfigConflictError("active configuration could not be verified; explicit activation is required")
        active = {
            str(section).casefold(): {str(key).casefold(): value for key, value in options.items()}
            for section, options in active.items() if isinstance(options, dict)
        }
        expected = _section_options(effective_hardware_text(plan))
        for section, options in expected.items():
            if section.startswith("include "):
                continue
            for name, value in options.items():
                actual = active.get(section, {}).get(name)
                if actual is None or " ".join(str(actual).split()) != " ".join(value.split()):
                    raise ConfigConflictError(f"active configuration differs at [{section}] {name}; explicit activation is required")

    def supports_conditional_write(self, previous):
        return False  # Moonraker's upload API offers no content precondition.

    def upload_if_unchanged(self, name, content, previous):
        raise ConfigConflictError("Moonraker has no atomic conditional upload")

    @property
    def destination_key(self) -> tuple:
        from core.moonraker import _base_url

        endpoint = urlsplit(_base_url(self.host, self.port))
        if not endpoint.hostname or endpoint.port is None:
            raise ValueError("Moonraker configuration destination is invalid")
        # SFTP shares this activation endpoint and therefore the same lock.
        # Credentials and transport objects must not split one printer's lock.
        return (
            "moonraker", endpoint.hostname.casefold().rstrip("."), endpoint.port,
            endpoint.path.rstrip("/"),
        )

    def read_files(self, names) -> Mapping[str, Optional[bytes]]:
        from core.moonraker import download_printer_cfg, list_config_files_checked
        ok, detail, listed = list_config_files_checked(
            self.host, self.port, api_key=self.api_key
        )
        if not ok:
            raise ConnectionError(detail)
        existing = set(listed)
        result: dict[str, Optional[bytes]] = {}
        for name in names:
            if name not in existing:
                result[name] = None
                continue
            downloaded, data = download_printer_cfg(
                self.host, self.port, name, api_key=self.api_key
            )
            if not downloaded:
                raise ConnectionError(f"could not back up {name}: {data!r}")
            result[name] = data
        return result

    def upload_bytes(self, name: str, content: bytes) -> None:
        from core.moonraker import upload_printer_cfg
        fd, path = tempfile.mkstemp(prefix="kace-upload-", suffix=".cfg")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            ok, detail = upload_printer_cfg(
                self.host, self.port, path, filename=name, api_key=self.api_key
            )
            if not ok:
                raise RuntimeError(f"upload failed for {name}: {detail}")
        finally:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass

    def delete_file(self, name: str) -> None:
        from core.moonraker import delete_config_file
        ok, detail = delete_config_file(self.host, self.port, name, api_key=self.api_key)
        if not ok:
            raise RuntimeError(f"delete failed for {name}: {detail}")

    def restart(self, mode: str) -> None:
        from core.moonraker import restart_firmware, restart_klipper_service
        fn = restart_firmware if mode == "firmware" else restart_klipper_service
        ok, detail = fn(self.host, self.port, api_key=self.api_key)
        if not ok:
            raise RuntimeError(f"restart failed: {detail}")

    def restart_moonraker(self) -> None:
        from core.moonraker import restart_moonraker_service
        ok, detail = restart_moonraker_service(
            self.host, self.port, api_key=self.api_key
        )
        if not ok:
            raise RuntimeError(f"Moonraker restart failed: {detail}")

    def moonraker_online(self) -> bool:
        from core.moonraker import check_moonraker
        return check_moonraker(self.host, self.port, api_key=self.api_key)[0]

    def klipper_state(self) -> str:
        from core.moonraker import get_klipper_state
        return get_klipper_state(self.host, self.port, api_key=self.api_key)


class SftpConfigTransport(MoonrakerConfigTransport):
    """Atomic SFTP file transport with Moonraker-based activation checks."""

    def __init__(self, sftp, config_dir: str, host: str, port: int, api_key: Optional[str] = None):
        super().__init__(host, port, api_key)
        self.sftp = sftp
        self.config_dir = config_dir.rstrip("/")

    def validate_activation_target(self):
        active = self._active_config()
        if self.sftp.normalize(active) != self.sftp.normalize(self._path(ROOT_REMOTE)):
            raise ConfigConflictError("SFTP destination does not match active Klipper printer.cfg")

    def supports_conditional_write(self, previous):
        return previous is None

    def upload_if_unchanged(self, name, content, previous):
        if previous is not None:
            raise ConfigConflictError("SFTP has no atomic conditional replacement")
        self.upload_bytes(name, content, exclusive=True)

    def _path(self, name: str) -> str:
        return posixpath.join(self.config_dir, *name.split("/"))

    def read_files(self, names) -> Mapping[str, Optional[bytes]]:
        result: dict[str, Optional[bytes]] = {}
        for name in names:
            path = self._path(name)
            try:
                self.sftp.stat(path)
            except FileNotFoundError:
                result[name] = None
                continue
            except OSError as exc:
                # Paramiko uses errno=2 for a confirmed missing file.
                if getattr(exc, "errno", None) == 2:
                    result[name] = None
                    continue
                raise
            with self.sftp.open(path, "rb") as handle:
                result[name] = handle.read()
        return result

    def _ensure_parent(self, path: str) -> None:
        parent = posixpath.dirname(path)
        current = "" if parent.startswith("/") else "."
        for part in parent.split("/"):
            if not part:
                current = "/"
                continue
            current = posixpath.join(current, part)
            try:
                self.sftp.stat(current)
            except FileNotFoundError:
                self.sftp.mkdir(current, mode=0o755)
            except OSError as exc:
                if getattr(exc, "errno", None) != 2:
                    raise
                self.sftp.mkdir(current, mode=0o755)

    def upload_bytes(self, name: str, content: bytes, *, exclusive=False) -> None:
        remote = self._path(name)
        temporary_remote = f"{remote}.kace-part-{uuid.uuid4().hex}"
        self._ensure_parent(remote)
        fd, local = tempfile.mkstemp(prefix="kace-sftp-", suffix=".cfg")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            self.sftp.put(local, temporary_remote)
            # Standard SFTP rename must not replace an existing target. The
            # POSIX extension is reserved for explicit unconditional callers.
            posix_rename = getattr(self.sftp, "rename" if exclusive else "posix_rename", None)
            if not callable(posix_rename):
                mode = "no-replace" if exclusive else "POSIX"
                raise RuntimeError(f"SFTP server/client does not support atomic {mode} rename")
            posix_rename(temporary_remote, remote)
        except BaseException:
            try:
                self.sftp.remove(temporary_remote)
            except Exception:
                pass
            raise
        finally:
            try:
                os.remove(local)
            except FileNotFoundError:
                pass

    def delete_file(self, name: str) -> None:
        path = self._path(name)
        try:
            self.sftp.remove(path)
        except FileNotFoundError:
            return
        except OSError as exc:
            if getattr(exc, "errno", None) != 2:
                raise


class LocalConfigTransport:
    """Atomic transport for an offline local/removable-media config root."""

    def __init__(self, config_dir: str):
        self.config_dir = os.path.realpath(os.path.abspath(config_dir))
        if not os.path.isdir(self.config_dir):
            raise NotADirectoryError(self.config_dir)

    @property
    def destination_key(self) -> tuple:
        return ("local", os.path.normcase(self.config_dir))

    def validate_activation_target(self):
        pass  # Offline export has no activation endpoint.

    def supports_conditional_write(self, previous):
        return previous is None

    def upload_if_unchanged(self, name, content, previous):
        if previous is not None:
            raise ConfigConflictError("local filesystem has no atomic conditional replacement")
        self.upload_bytes(name, content, exclusive=True)

    def _path(self, name: str) -> str:
        if not name or name.startswith(("/", "\\")):
            raise ValueError(f"invalid relative config path: {name!r}")
        candidate = os.path.abspath(os.path.join(self.config_dir, *name.split("/")))
        if os.path.commonpath((self.config_dir, candidate)) != self.config_dir:
            raise ValueError(f"config path escapes destination: {name!r}")
        if os.path.commonpath((self.config_dir, os.path.realpath(candidate))) != self.config_dir:
            raise ConfigConflictError("config path resolves outside destination")
        return candidate

    def read_files(self, names) -> Mapping[str, Optional[bytes]]:
        result: dict[str, Optional[bytes]] = {}
        for name in names:
            path = self._path(name)
            if not os.path.lexists(path):
                result[name] = None
                continue
            if os.path.islink(path) or not os.path.isfile(path):
                raise OSError(f"refusing non-regular config target: {path}")
            with open(path, "rb") as source:
                result[name] = source.read()
        return result

    def upload_bytes(self, name: str, content: bytes, *, exclusive=False, expected=_UNCONDITIONAL) -> None:
        path = self._path(name)
        parent = os.path.dirname(path)
        existing_ancestor = parent
        while not os.path.lexists(existing_ancestor):
            next_ancestor = os.path.dirname(existing_ancestor)
            if next_ancestor == existing_ancestor:
                raise OSError(f"could not resolve config parent: {parent}")
            existing_ancestor = next_ancestor
        if os.path.islink(existing_ancestor):
            raise OSError(f"refusing symlinked config parent: {existing_ancestor}")
        if os.path.commonpath((self.config_dir, os.path.realpath(existing_ancestor))) != self.config_dir:
            raise OSError(f"config parent resolves outside destination: {parent}")
        os.makedirs(parent, mode=0o755, exist_ok=True)
        if os.path.commonpath((self.config_dir, os.path.realpath(parent))) != self.config_dir:
            raise OSError(f"config parent resolves outside destination: {parent}")
        if os.path.lexists(path) and (os.path.islink(path) or not os.path.isfile(path)):
            raise OSError(f"refusing non-regular config target: {path}")
        mode = 0o644
        if os.path.isfile(path):
            mode = os.stat(path, follow_symlinks=False).st_mode & 0o777
        fd, temporary = tempfile.mkstemp(prefix=".kace-part-", dir=parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, mode)
            if expected is not _UNCONDITIONAL:
                current = self.read_files((name,))[name]
                if current != expected:
                    raise ConfigConflictError(f"concurrent configuration modification detected: {name}")
            if exclusive:
                os.link(temporary, path)  # Atomic create-if-absent, never replace.
                os.unlink(temporary)
            else:
                os.replace(temporary, path)
            if os.name == "posix":
                directory_fd = os.open(
                    parent,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
                )
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        except BaseException:
            try:
                os.remove(temporary)
            except FileNotFoundError:
                pass
            raise

    def delete_file(self, name: str) -> None:
        path = self._path(name)
        try:
            if os.path.islink(path) or not os.path.isfile(path):
                raise OSError(f"refusing non-regular config target: {path}")
            os.remove(path)
        except FileNotFoundError:
            return

    def restart(self, mode: str) -> None:
        raise RuntimeError("offline configuration cannot restart Klipper")

    def restart_moonraker(self) -> None:
        raise RuntimeError("offline configuration cannot restart Moonraker")

    def moonraker_online(self) -> bool:
        return False

    def klipper_state(self) -> str:
        return "disconnected"


class LocalMoonrakerConfigTransport(LocalConfigTransport, MoonrakerConfigTransport):
    """Local publication serialized with other KACE writers.

    External editors are rechecked after staging/fsync, just before replacement.
    Strict exclusion across the final replacement requires cooperating writers.
    """

    def __init__(self, config_dir, host="127.0.0.1", port=7125, api_key=None):
        LocalConfigTransport.__init__(self, config_dir)
        MoonrakerConfigTransport.__init__(self, host, port, api_key)

    def destination_lock(self):
        from core.workspace import exclusive_file_lock
        path = os.path.join(self.config_dir, ".kace-deploy.lock")
        if os.path.islink(path):
            raise ConfigConflictError("refusing a symlinked destination lock")
        return exclusive_file_lock(path, timeout_seconds=30)

    def validate_activation_target(self):
        MoonrakerConfigTransport.validate_activation_target(self)
        if self._active_config() != os.path.join(self.config_dir, ROOT_REMOTE):
            raise ConfigConflictError("local destination does not match active Klipper printer.cfg")

    def supports_conditional_write(self, previous):
        return True

    def upload_if_unchanged(self, name, content, previous):
        self.upload_bytes(name, content, exclusive=previous is None, expected=previous)

    restart = MoonrakerConfigTransport.restart
    restart_moonraker = MoonrakerConfigTransport.restart_moonraker
    moonraker_online = MoonrakerConfigTransport.moonraker_online
    klipper_state = MoonrakerConfigTransport.klipper_state


def local_moonraker_available():
    return os.name == "posix" and os.path.isfile(os.path.expanduser("~/printer_data/config/printer.cfg"))


def configuration_transport(host, port=7125, api_key=None):
    """Never infer filesystem authority from a remote host's reported path."""
    from core.moonraker import _base_url
    remote = MoonrakerConfigTransport(host, port, api_key)
    endpoint = urlsplit(_base_url(host, port))
    if os.name == "posix" and endpoint.hostname in {"localhost", "127.0.0.1", "::1"}:
        remote.validate_activation_target()
        active = remote._active_config()
        transport = LocalMoonrakerConfigTransport(os.path.dirname(active), host, port, api_key)
        transport.validate_activation_target()
        return transport
    return remote
