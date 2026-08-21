"""Shared verified transaction for SSH and Moonraker config-only deployment."""

from __future__ import annotations

import hashlib
import os
import posixpath
import tempfile
import time
import uuid
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, Mapping, Optional

from core.configuration_review import ConfigurationReview, build_configuration_review

from core.managed_config import (
    HARDWARE_REMOTE,
    LEGACY_MACROS_REMOTE,
    MACROS_REMOTE,
    MOONRAKER_REMOTE,
    ROOT_REMOTE,
    ManagedConfigPlan,
    build_managed_config_plan,
)
from core.snapshot import DeploymentSnapshot, create_snapshot


class ConfigTransactionState(Enum):
    PRECONDITION_FAILED = auto()
    CANCELLED = auto()
    SNAPSHOT_FAILED = auto()
    UPLOAD_FAILED = auto()
    VERIFY_FAILED = auto()
    ACTIVATION_FAILED = auto()
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

    The transport must expose ``read_files``, ``upload_bytes``, ``delete_file``,
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
        self._written_names: set[str] = set()

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
        for artifact in self.plan.changed_artifacts:
            remote = self.transport.read_files((artifact.remote_name,))[artifact.remote_name]
            if remote is None:
                raise RuntimeError(f"uploaded file disappeared: {artifact.remote_name}")
            if self._sha256(remote) != self._sha256(artifact.content):
                raise RuntimeError(f"checksum mismatch for {artifact.remote_name}")

    def _rollback(self) -> tuple[Optional[bool], str]:
        if self.snapshot is None:
            return False, "no snapshot is available"
        if not self._written_names:
            return None, "rollback not required: the failed upload created no remote file"
        failures: list[str] = []
        names = [
            name for name in self.snapshot.config_files
            if name in self._written_names
        ]
        names.sort(key=lambda name: name == ROOT_REMOTE)
        for name in names:
            try:
                self.transport.upload_bytes(name, self.snapshot.config_files[name])
            except Exception as exc:
                failures.append(f"restore {name}: {exc}")
        missing = [
            name for name in self.snapshot.missing_files
            if name in self._written_names
        ]
        for name in missing:
            try:
                self.transport.delete_file(name)
            except Exception as exc:
                failures.append(f"delete {name}: {exc}")
        if failures:
            return False, "; ".join(failures)

        try:
            restored = self.transport.read_files(tuple(
                names + missing
            ))
            for name in names:
                original = self.snapshot.config_files[name]
                if restored.get(name) != original:
                    return False, f"rollback checksum mismatch for {name}"
            for name in missing:
                if restored.get(name) is not None:
                    return False, f"rollback did not remove newly created {name}"
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
        except Exception as exc:
            return False, f"rollback activation failed: {exc}"
        return True, "rollback restored byte-identical state and Klipper Ready"

    def _record_possible_write(self, name: str) -> None:
        """Record a failed upload only when the remote bytes may have changed."""
        assert self.snapshot is not None
        try:
            current = self.transport.read_files((name,)).get(name)
        except Exception:
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
            remote = self.transport.read_files(self.CANDIDATES)
            self.plan = build_managed_config_plan(
                self.generated_hardware, self.generated_macros, remote
            )
            diff = self.plan.dry_run_diff()
            configuration_review = build_configuration_review(self.plan)
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

        if not self.plan.changed_artifacts:
            return ConfigTransactionResult(
                ConfigTransactionState.COMMITTED,
                "configuration is already reconciled; no files were written",
                self.transaction_id,
            )

        try:
            if not (accepted if self.review is not None else self.confirm(diff)):
                return ConfigTransactionResult(
                    ConfigTransactionState.CANCELLED,
                    "deployment cancelled after dry-run diff",
                    self.transaction_id,
                )
            if self.activation_selector is not None:
                selected = self.activation_selector()
                if selected not in {"firmware", "service", "none"}:
                    raise ValueError(f"Unsupported activation mode: {selected}")
                self.activation = selected
            originals = {
                item.remote_name: item.previous for item in self.plan.changed_artifacts
            }
            self.snapshot = create_snapshot(
                originals,
                deployment_id=self.transaction_id,
                board=self.board,
                kace_version=self.kace_version,
                persist_root=self.snapshot_root,
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

        try:
            for artifact in self._ordered_artifacts():
                try:
                    self.transport.upload_bytes(artifact.remote_name, artifact.content)
                except Exception:
                    self._record_possible_write(artifact.remote_name)
                    raise
                self._written_names.add(artifact.remote_name)
            self._verify_plan()
            if self.activation == "none":
                return ConfigTransactionResult(
                    ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION,
                    "checksums verified; configuration requires an explicit restart",
                    self.transaction_id,
                    self.snapshot,
                )

            if any(item.remote_name == MOONRAKER_REMOTE for item in self.plan.changed_artifacts):
                self.transport.restart_moonraker()
                if not self._wait_moonraker():
                    raise RuntimeError("Moonraker did not recover after restart")
            self.transport.restart(self.activation)
            ready, state = self._wait_ready()
            if not ready:
                raise RuntimeError(f"Klipper did not become Ready (state={state})")
            return ConfigTransactionResult(
                ConfigTransactionState.COMMITTED,
                "configuration checksums verified and Klipper Ready",
                self.transaction_id,
                self.snapshot,
            )
        except Exception as exc:
            rollback_ok, rollback_detail = self._rollback()
            state = (
                ConfigTransactionState.ACTIVATION_FAILED
                if "Ready" in str(exc) or "restart" in str(exc).lower()
                else ConfigTransactionState.VERIFY_FAILED
                if "checksum" in str(exc)
                else ConfigTransactionState.UPLOAD_FAILED
            )
            failure_label = {
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

    def upload_bytes(self, name: str, content: bytes) -> None:
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
            # Standard SFTP rename may refuse to replace an existing target.
            # OpenSSH's POSIX extension is both overwrite-capable and atomic;
            # refusing servers without it is safer than creating a delete gap.
            posix_rename = getattr(self.sftp, "posix_rename", None)
            if not callable(posix_rename):
                raise RuntimeError("SFTP server/client does not support atomic POSIX rename")
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

    def _path(self, name: str) -> str:
        if not name or name.startswith(("/", "\\")):
            raise ValueError(f"invalid relative config path: {name!r}")
        candidate = os.path.abspath(os.path.join(self.config_dir, *name.split("/")))
        if os.path.commonpath((self.config_dir, candidate)) != self.config_dir:
            raise ValueError(f"config path escapes destination: {name!r}")
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

    def upload_bytes(self, name: str, content: bytes) -> None:
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
