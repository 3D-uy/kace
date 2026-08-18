"""Fail-closed physical executor for typed BoardContract SD-card plans.

The executor accepts one object: a typed ``DeploymentPlan``.  Board metadata
is reloaded from the versioned catalog and every identity/hash is checked
again before a removable medium is touched.  Power control is intentionally
absent from this module; manual relay actions live in ``core.power_controller``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from typing import Any, Callable, Mapping, Optional, Sequence

from core.mcu_monitor import (
    McuIdentityAmbiguous,
    McuIdentityMismatch,
    McuMonitorCancelled,
    McuMonitorError,
)
from core.moonraker import get_klipper_state, get_mcu_versions

from .catalog import BoardCatalog, load_default_catalog
from .deployment import (
    ContractDeploymentError,
    DeploymentPlan,
    validate_deployment_plan,
)
from .models import FlashStrategy, SupportStatus
from .models import TransportKind


class ContractDeploymentState(str, Enum):
    PREPARED = "PREPARED"
    MEDIA_SELECTED = "MEDIA_SELECTED"
    MEDIA_VERIFIED = "MEDIA_VERIFIED"
    COPIED = "COPIED"
    COPY_VERIFIED = "COPY_VERIFIED"
    EJECTED = "EJECTED"
    WAITING_FOR_MANUAL_POWER_CYCLE = "WAITING_FOR_MANUAL_POWER_CYCLE"
    WAITING_FOR_MCU_REENUMERATION = "WAITING_FOR_MCU_REENUMERATION"
    MCU_REENUMERATED = "MCU_REENUMERATED"
    WAITING_FOR_KLIPPER = "WAITING_FOR_KLIPPER"
    VERIFYING_FIRMWARE = "VERIFYING_FIRMWARE"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class SafeEjectStatus(str, Enum):
    EJECTED = "EJECTED"
    UNSUPPORTED = "UNSUPPORTED"
    FAILED = "FAILED"


class ContractDeploymentExecutionError(RuntimeError):
    def __init__(self, message: str, *, code: str, proof=None):
        super().__init__(message)
        self.code = code
        self.proof = proof


class UnsupportedContractStrategy(ContractDeploymentExecutionError):
    pass


class MediaSelectionError(ContractDeploymentExecutionError):
    pass


class MediaVerificationError(ContractDeploymentExecutionError):
    pass


class ArtifactExecutionError(ContractDeploymentExecutionError):
    pass


class PostFlashVerificationError(ContractDeploymentExecutionError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ArtifactExecutionError(
            f"cannot read firmware artifact {path}: {exc}", code="ARTIFACT_UNREADABLE"
        ) from exc
    return digest.hexdigest()


@dataclass(frozen=True)
class MediaCandidate:
    stable_id: str
    device_path: str
    parent_device: str
    mount_path: str
    filesystem: str
    size_bytes: int
    free_bytes: int
    removable: bool
    system_disk: bool
    read_only: bool
    label: str = ""
    model: str = ""
    serial: str = ""

    def __post_init__(self) -> None:
        if not self.stable_id or not self.device_path or not self.mount_path:
            raise ValueError("media candidate requires stable identity, device and mount path")
        if self.size_bytes < 0 or self.free_bytes < 0:
            raise ValueError("media capacity values must not be negative")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def same_physical_medium(self, other: "MediaCandidate") -> bool:
        return isinstance(other, MediaCandidate) and (
            self.stable_id,
            self.device_path,
            self.parent_device,
            str(Path(self.mount_path).resolve()),
            self.filesystem.casefold(),
            self.size_bytes,
            self.serial,
        ) == (
            other.stable_id,
            other.device_path,
            other.parent_device,
            str(Path(other.mount_path).resolve()),
            other.filesystem.casefold(),
            other.size_bytes,
            other.serial,
        )


@dataclass(frozen=True)
class SafeEjectResult:
    status: SafeEjectStatus
    device_path: str
    detail: str
    timestamp: str

    def to_dict(self) -> dict[str, str]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass(frozen=True)
class DeploymentStepRecord:
    state: ContractDeploymentState
    timestamp: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "state": self.state.value,
            "timestamp": self.timestamp,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class PowerObservation:
    state: str
    timestamp: str
    detail: str = ""
    requested_action: str = ""
    confirmed: bool = False


@dataclass(frozen=True)
class FirmwareVerificationResult:
    klipper_connected: bool
    observed_fingerprint: str
    observed_versions: Mapping[str, str]
    detail: str


@dataclass(frozen=True)
class McuIdentityEvidence:
    configured_path: str = ""
    device_node: str = ""
    devpath: str = ""
    serial: str = ""
    physical_path: str = ""
    vendor_id: str = ""
    model_id: str = ""
    physical_port: str = ""
    by_path: tuple[str, ...] = ()
    vid_pid: str = ""

    @classmethod
    def capture(cls, identity: object) -> "McuIdentityEvidence":
        if hasattr(identity, "to_dict"):
            data = identity.to_dict()
        else:
            data = {"device_node": str(identity)}
        return cls(
            configured_path=str(data.get("configured_path") or ""),
            device_node=str(data.get("device_node") or data.get("value") or ""),
            devpath=str(data.get("devpath") or ""),
            serial=str(data.get("serial") or ""),
            physical_path=str(data.get("physical_path") or ""),
            vendor_id=str(data.get("vendor_id") or ""),
            model_id=str(data.get("model_id") or ""),
            physical_port=str(data.get("physical_port") or ""),
            by_path=tuple(str(item) for item in data.get("by_path") or ()),
            vid_pid=str(data.get("vid_pid") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["by_path"] = list(self.by_path)
        return data


@dataclass(frozen=True)
class DeploymentProof:
    schema: str
    deployment_id: str
    plan_digest: str
    board_id: str
    hardware_variant_id: str
    build_target_id: str
    board_contract_digest: str
    klipper_commit: str
    build_proof_digest: str
    artifact_native_hash: str
    artifact_staged_hash: str
    artifact_filename: str
    artifact_size: int
    selected_media: Optional[MediaCandidate]
    filesystem: str
    destination: str
    media_readback_hash: str
    media_readback_size: int
    safe_eject: Optional[SafeEjectResult]
    executed_steps: tuple[DeploymentStepRecord, ...]
    started_at: str
    finished_at: str
    manual_confirmation: bool
    manual_confirmation_at: str
    power_observations: tuple[PowerObservation, ...]
    reenumeration_result: str
    observed_mcu_identity: Optional[McuIdentityEvidence]
    klipper_connection_result: str
    expected_fingerprint: str
    observed_fingerprint: str
    final_state: ContractDeploymentState
    errors: tuple[str, ...]

    def to_mapping(self, *, include_digest: bool = False) -> dict[str, Any]:
        data = asdict(self)
        data["selected_media"] = (
            self.selected_media.to_dict() if self.selected_media else None
        )
        data["safe_eject"] = self.safe_eject.to_dict() if self.safe_eject else None
        data["observed_mcu_identity"] = (
            self.observed_mcu_identity.to_dict() if self.observed_mcu_identity else None
        )
        data["executed_steps"] = [item.to_dict() for item in self.executed_steps]
        data["final_state"] = self.final_state.value
        if include_digest:
            data["proof_digest"] = self.digest
        return data

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.to_mapping(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass
class ContractDeploymentSession:
    plan: DeploymentPlan
    state: ContractDeploymentState
    started_at: str
    steps: list[DeploymentStepRecord] = field(default_factory=list)
    selected_media: Optional[MediaCandidate] = None
    media_readback_hash: str = ""
    media_readback_size: int = 0
    safe_eject: Optional[SafeEjectResult] = None
    manual_confirmation: bool = False
    manual_confirmation_at: str = ""
    power_observations: list[PowerObservation] = field(default_factory=list)
    reenumeration_result: str = ""
    observed_mcu_identity: Optional[McuIdentityEvidence] = None
    klipper_connection_result: str = ""
    observed_fingerprint: str = ""
    errors: list[str] = field(default_factory=list)
    finished_at: str = ""

    def proof(self) -> DeploymentProof:
        identity = self.plan.artifact.firmware_identity
        return DeploymentProof(
            schema="kace-board-deployment-proof/v1",
            deployment_id=self.plan.deployment_id,
            plan_digest=self.plan.plan_digest,
            board_id=self.plan.board_id,
            hardware_variant_id=self.plan.hardware_variant_id,
            build_target_id=self.plan.build_target_id,
            board_contract_digest=self.plan.board_contract_digest,
            klipper_commit=self.plan.klipper_commit,
            build_proof_digest=self.plan.build_proof_digest,
            artifact_native_hash=self.plan.artifact.sha256,
            artifact_staged_hash=self.plan.transformation.final_sha256,
            artifact_filename=self.plan.transformation.final_filename,
            artifact_size=self.plan.artifact.size_bytes,
            selected_media=self.selected_media,
            filesystem=(self.selected_media.filesystem if self.selected_media else ""),
            destination=(self.selected_media.mount_path if self.selected_media else ""),
            media_readback_hash=self.media_readback_hash,
            media_readback_size=self.media_readback_size,
            safe_eject=self.safe_eject,
            executed_steps=tuple(self.steps),
            started_at=self.started_at,
            finished_at=self.finished_at,
            manual_confirmation=self.manual_confirmation,
            manual_confirmation_at=self.manual_confirmation_at,
            power_observations=tuple(self.power_observations),
            reenumeration_result=self.reenumeration_result,
            observed_mcu_identity=self.observed_mcu_identity,
            klipper_connection_result=self.klipper_connection_result,
            expected_fingerprint=(identity.reported_version if identity else ""),
            observed_fingerprint=self.observed_fingerprint,
            final_state=self.state,
            errors=tuple(self.errors),
        )


class LinuxRemovableMediaProvider:
    """Read-only discovery of mounted Linux block devices via allow-listed lsblk."""

    _LSBLK = (
        "lsblk", "--json", "--bytes", "--output",
        "NAME,PATH,TYPE,RM,RO,SIZE,FSTYPE,MOUNTPOINTS,UUID,PARTUUID,PKNAME,MODEL,SERIAL,TRAN,LABEL",
    )

    def __init__(self, command_runner: Optional[Callable[[Sequence[str]], object]] = None):
        self.command_runner = command_runner or self._run

    @staticmethod
    def _run(argv: Sequence[str]):
        return subprocess.run(
            tuple(argv), check=False, capture_output=True, text=True
        )

    @staticmethod
    def _truth(value: object) -> bool:
        return str(value or "0").strip().lower() in {"1", "true", "yes"}

    @staticmethod
    def _mountpoints(node: Mapping[str, Any]) -> tuple[str, ...]:
        raw = node.get("mountpoints", ())
        if isinstance(raw, str):
            raw = (raw,)
        if not isinstance(raw, list) and not isinstance(raw, tuple):
            return ()
        return tuple(str(item) for item in raw if item)

    def list_candidates(self) -> tuple[MediaCandidate, ...]:
        if os.name != "posix":
            raise MediaSelectionError(
                "real removable-media discovery is supported only on the KACE Linux host",
                code="MEDIA_DISCOVERY_UNSUPPORTED",
            )
        completed = self.command_runner(self._LSBLK)
        if int(getattr(completed, "returncode", 1)) != 0:
            raise MediaSelectionError(
                f"lsblk failed: {getattr(completed, 'stderr', '')}",
                code="MEDIA_DISCOVERY_FAILED",
            )
        try:
            payload = json.loads(str(getattr(completed, "stdout", "")))
            roots = payload["blockdevices"]
        except (ValueError, KeyError, TypeError) as exc:
            raise MediaSelectionError(
                "lsblk returned invalid JSON", code="MEDIA_DISCOVERY_FAILED"
            ) from exc

        flattened: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
        system_roots: set[str] = set()

        def visit(node, root):
            if not isinstance(node, dict):
                return
            flattened.append((node, root))
            if "/" in self._mountpoints(node):
                system_roots.add(str(root.get("path") or ""))
            for child in node.get("children") or ():
                visit(child, root)

        for root in roots if isinstance(roots, list) else ():
            if isinstance(root, dict):
                visit(root, root)

        candidates = []
        for node, root in flattened:
            node_type = str(node.get("type") or "")
            if node_type not in {"part", "disk"}:
                continue
            mounts = self._mountpoints(node)
            if len(mounts) != 1 or mounts[0] == "/":
                continue
            device_path = str(node.get("path") or "")
            parent_path = str(root.get("path") or device_path)
            filesystem = str(node.get("fstype") or "").casefold()
            removable = self._truth(node.get("rm")) or self._truth(root.get("rm"))
            read_only = self._truth(node.get("ro")) or self._truth(root.get("ro"))
            system_disk = parent_path in system_roots
            serial = str(root.get("serial") or node.get("serial") or "")
            partuuid = str(node.get("partuuid") or "")
            uuid = str(node.get("uuid") or "")
            if partuuid:
                stable_id = f"partuuid:{partuuid.casefold()}"
            elif uuid:
                stable_id = f"uuid:{uuid.casefold()}"
            elif serial and device_path:
                stable_id = f"serial-path:{serial.casefold()}:{device_path}"
            else:
                continue
            mount_path = str(Path(mounts[0]).resolve())
            if not os.path.isdir(mount_path):
                continue
            try:
                free = shutil.disk_usage(mount_path).free
            except OSError:
                continue
            candidates.append(MediaCandidate(
                stable_id=stable_id,
                device_path=device_path,
                parent_device=parent_path,
                mount_path=mount_path,
                filesystem=filesystem,
                size_bytes=int(node.get("size") or 0),
                free_bytes=int(free),
                removable=removable,
                system_disk=system_disk,
                read_only=read_only,
                label=str(node.get("label") or ""),
                model=str(root.get("model") or node.get("model") or "").strip(),
                serial=serial,
            ))
        return tuple(sorted(candidates, key=lambda item: item.stable_id))

    def refresh(self, selected: MediaCandidate) -> Optional[MediaCandidate]:
        for candidate in self.list_candidates():
            if candidate.stable_id == selected.stable_id:
                return candidate
        return None


class LinuxSafeEjector:
    """Unmount exactly one selected partition using udisksctl."""

    def __init__(self, command_runner: Optional[Callable[[Sequence[str]], object]] = None):
        self.command_runner = command_runner or self._run

    @staticmethod
    def _run(argv: Sequence[str]):
        return subprocess.run(
            tuple(argv), check=False, capture_output=True, text=True
        )

    def eject(self, selected: MediaCandidate) -> SafeEjectResult:
        timestamp = _utc_now()
        executable = shutil.which("udisksctl")
        if os.name != "posix" or not executable:
            return SafeEjectResult(
                SafeEjectStatus.UNSUPPORTED,
                selected.device_path,
                "udisksctl is unavailable on this platform",
                timestamp,
            )
        argv = (
            executable,
            "unmount",
            "--block-device",
            selected.device_path,
            "--no-user-interaction",
        )
        completed = self.command_runner(argv)
        if int(getattr(completed, "returncode", 1)) != 0:
            return SafeEjectResult(
                SafeEjectStatus.FAILED,
                selected.device_path,
                str(getattr(completed, "stderr", "") or "udisksctl failed").strip(),
                timestamp,
            )
        if os.path.ismount(selected.mount_path):
            return SafeEjectResult(
                SafeEjectStatus.FAILED,
                selected.device_path,
                "selected filesystem still appears mounted after udisksctl",
                timestamp,
            )
        return SafeEjectResult(
            SafeEjectStatus.EJECTED,
            selected.device_path,
            str(getattr(completed, "stdout", "") or "unmounted").strip(),
            timestamp,
        )


class VerifiedMediaWriter:
    """Copy one file atomically at the selected filesystem root and fsync it."""

    def copy(self, source: Path, destination: Path, deployment_id: str) -> None:
        if destination.exists() and destination.is_symlink():
            raise OSError("destination firmware path is a symbolic link")
        temporary = destination.parent / f".kace-{deployment_id}.part"
        if temporary.exists():
            raise OSError(f"stale KACE temporary file exists: {temporary.name}")
        try:
            with source.open("rb") as input_file, temporary.open("xb") as output_file:
                shutil.copyfileobj(input_file, output_file, length=1024 * 1024)
                output_file.flush()
                os.fsync(output_file.fileno())
            os.replace(temporary, destination)
            if hasattr(os, "O_DIRECTORY"):
                directory_fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            if temporary.exists():
                temporary.unlink()


class MoonrakerFirmwareVerifier:
    """Wait for Klipper and return the exact registered MCU fingerprint."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 7125,
        api_key: Optional[str] = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self.host = host
        self.port = int(port)
        self.api_key = api_key
        self.sleep = sleep
        self.monotonic = monotonic

    def wait_for_firmware(
        self,
        *,
        mcu_name: str,
        expected_fingerprint: str,
        timeout: float,
    ) -> FirmwareVerificationResult:
        if not mcu_name:
            return FirmwareVerificationResult(False, "", {}, "MCU object name is empty")
        deadline = self.monotonic() + float(timeout)
        last_state = "disconnected"
        last_versions: dict[str, str] = {}
        while self.monotonic() < deadline:
            last_state = get_klipper_state(self.host, self.port, api_key=self.api_key)
            if last_state == "ready":
                last_versions = get_mcu_versions(
                    self.host, self.port, api_key=self.api_key
                )
                observed = last_versions.get(mcu_name)
                if observed:
                    return FirmwareVerificationResult(
                        True,
                        observed,
                        dict(last_versions),
                        "Klipper Ready and expected MCU object registered",
                    )
            self.sleep(0.5)
        return FirmwareVerificationResult(
            False,
            last_versions.get(mcu_name, ""),
            dict(last_versions),
            f"Klipper/MCU verification timed out (state={last_state})",
        )


_ALLOWED_TRANSITIONS = {
    ContractDeploymentState.PREPARED: {ContractDeploymentState.MEDIA_SELECTED},
    ContractDeploymentState.MEDIA_SELECTED: {ContractDeploymentState.MEDIA_VERIFIED},
    ContractDeploymentState.MEDIA_VERIFIED: {ContractDeploymentState.COPIED},
    ContractDeploymentState.COPIED: {ContractDeploymentState.COPY_VERIFIED},
    ContractDeploymentState.COPY_VERIFIED: {ContractDeploymentState.EJECTED},
    ContractDeploymentState.EJECTED: {
        ContractDeploymentState.WAITING_FOR_MANUAL_POWER_CYCLE
    },
    ContractDeploymentState.WAITING_FOR_MANUAL_POWER_CYCLE: {
        ContractDeploymentState.WAITING_FOR_MCU_REENUMERATION
    },
    ContractDeploymentState.WAITING_FOR_MCU_REENUMERATION: {
        ContractDeploymentState.MCU_REENUMERATED
    },
    ContractDeploymentState.MCU_REENUMERATED: {
        ContractDeploymentState.WAITING_FOR_KLIPPER
    },
    ContractDeploymentState.WAITING_FOR_KLIPPER: {
        ContractDeploymentState.VERIFYING_FIRMWARE
    },
    ContractDeploymentState.VERIFYING_FIRMWARE: {ContractDeploymentState.VERIFIED},
    ContractDeploymentState.VERIFIED: set(),
    ContractDeploymentState.FAILED: set(),
}


class SdCardDeploymentExecutor:
    """The only Phase-4B physical executor; all other strategies are rejected."""

    def __init__(
        self,
        *,
        media_provider,
        ejector,
        mcu_monitor,
        firmware_verifier,
        mcu_name: str = "mcu",
        media_writer=None,
        catalog: Optional[BoardCatalog] = None,
        cancel_event: Optional[threading.Event] = None,
        mcu_timeout: float = 180.0,
        klipper_timeout: float = 120.0,
        event_sink: Optional[Callable[[dict[str, Any]], None]] = None,
        clock: Callable[[], str] = _utc_now,
    ):
        self.media_provider = media_provider
        self.ejector = ejector
        self.mcu_monitor = mcu_monitor
        self.firmware_verifier = firmware_verifier
        self.mcu_name = mcu_name
        self.media_writer = media_writer or VerifiedMediaWriter()
        self.catalog = catalog or load_default_catalog()
        self.cancel_event = cancel_event or threading.Event()
        self.mcu_timeout = float(mcu_timeout)
        self.klipper_timeout = float(klipper_timeout)
        self.event_sink = event_sink or (lambda _event: None)
        self.clock = clock
        self._sequences: dict[str, int] = {}

    def _emit(self, session: ContractDeploymentSession, detail: str) -> None:
        sequence = self._sequences.get(session.plan.deployment_id, 0) + 1
        self._sequences[session.plan.deployment_id] = sequence
        self.event_sink({
            "schema": 2,
            "workflow_kind": "firmware_deployment",
            "workflow_id": session.plan.deployment_id,
            "sequence": sequence,
            "state": session.state.value,
            "detail": detail,
            "data": {
                "firmware_authority": "board_contract",
                "plan_digest": session.plan.plan_digest,
            },
        })

    def _transition(
        self,
        session: ContractDeploymentSession,
        state: ContractDeploymentState,
        detail: str,
    ) -> None:
        if state is not ContractDeploymentState.FAILED:
            allowed = _ALLOWED_TRANSITIONS.get(session.state, set())
            if state not in allowed:
                raise RuntimeError(
                    f"invalid contractual deployment transition {session.state.value} -> {state.value}"
                )
        session.state = state
        session.steps.append(DeploymentStepRecord(state, self.clock(), detail))
        if state in {ContractDeploymentState.VERIFIED, ContractDeploymentState.FAILED}:
            session.finished_at = self.clock()
        self._emit(session, detail)

    def _fail(
        self,
        session: ContractDeploymentSession,
        exc: Exception,
        *,
        code: str,
        error_type=ContractDeploymentExecutionError,
    ):
        message = str(exc)
        session.errors.append(message)
        if session.state not in {
            ContractDeploymentState.FAILED,
            ContractDeploymentState.VERIFIED,
        }:
            self._transition(session, ContractDeploymentState.FAILED, message)
        try:
            self.mcu_monitor.close()
        except Exception:
            pass
        raise error_type(message, code=code, proof=session.proof()) from exc

    def _validate_plan(self, plan: DeploymentPlan):
        if not isinstance(plan, DeploymentPlan):
            raise ContractDeploymentExecutionError(
                "executor accepts only a typed BoardContract DeploymentPlan",
                code="INVALID_PLAN_TYPE",
            )
        contract = self.catalog.by_id(plan.board_id)
        if contract is None:
            raise ContractDeploymentExecutionError(
                "DeploymentPlan board is absent from the BoardContract catalog",
                code="CONTRACT_NOT_FOUND",
            )
        try:
            target = validate_deployment_plan(contract, plan)
        except ContractDeploymentError as exc:
            raise ContractDeploymentExecutionError(
                str(exc), code="PLAN_IDENTITY_MISMATCH"
            ) from exc
        if target.flash.strategy is not FlashStrategy.SD_CARD:
            raise UnsupportedContractStrategy(
                f"physical strategy {target.flash.strategy.value} is unsupported in Phase 4B",
                code="UNSUPPORTED_STRATEGY",
            )
        if target.support_status not in {
            SupportStatus.RUNTIME_SUPPORTED,
            SupportStatus.DEPLOYMENT_VERIFIED,
        }:
            raise ContractDeploymentExecutionError(
                f"target support status {target.support_status.value} cannot execute physically",
                code="TARGET_NOT_RUNTIME_SUPPORTED",
            )
        if target.transport.kind is TransportKind.USB:
            application_id = target.transport.endpoint.get("application_vid_pid", "")
            if not re.fullmatch(r"[0-9a-fA-F]{4}:[0-9a-fA-F]{4}", application_id):
                raise ContractDeploymentExecutionError(
                    "USB target has no exact application VID:PID identity",
                    code="MCU_IDENTITY_CONTRACT_INCOMPLETE",
                )
        return contract, target

    @staticmethod
    def _verify_artifacts(plan: DeploymentPlan) -> tuple[Path, Path]:
        native = Path(plan.artifact.path)
        staged = Path(plan.transformation.final_path)
        checks = (
            (native, plan.artifact.sha256, plan.artifact.size_bytes, plan.artifact.native_filename),
            (staged, plan.transformation.final_sha256, plan.transformation.size_bytes,
             plan.transformation.final_filename),
        )
        for path, expected_hash, expected_size, expected_name in checks:
            if not path.is_file():
                raise ArtifactExecutionError(
                    f"firmware artifact is absent: {path}", code="ARTIFACT_ABSENT"
                )
            if path.name != expected_name:
                raise ArtifactExecutionError(
                    "firmware artifact filename changed", code="ARTIFACT_FILENAME_MISMATCH"
                )
            if path.stat().st_size != expected_size:
                raise ArtifactExecutionError(
                    "firmware artifact size changed", code="ARTIFACT_SIZE_MISMATCH"
                )
            if _sha256_file(path) != expected_hash:
                raise ArtifactExecutionError(
                    "firmware artifact hash changed", code="ARTIFACT_HASH_MISMATCH"
                )
        if _sha256_file(native) != _sha256_file(staged):
            raise ArtifactExecutionError(
                "staged artifact content differs from native artifact",
                code="ARTIFACT_CONTENT_MISMATCH",
            )
        return native, staged

    @staticmethod
    def _select_media(
        candidates: Sequence[MediaCandidate], selected_id: Optional[str]
    ) -> MediaCandidate:
        valid = tuple(candidates)
        if not valid:
            raise MediaSelectionError(
                "no removable media candidates are available", code="NO_MEDIA"
            )
        if selected_id:
            matches = tuple(item for item in valid if item.stable_id == selected_id)
            if len(matches) != 1:
                raise MediaSelectionError(
                    "explicit media selection does not identify exactly one candidate",
                    code="MEDIA_SELECTION_INVALID",
                )
            return matches[0]
        if len(valid) != 1:
            raise MediaSelectionError(
                "multiple removable media candidates require explicit selection",
                code="MEDIA_AMBIGUOUS",
            )
        return valid[0]

    @staticmethod
    def _verify_media(
        candidate: MediaCandidate,
        target,
        artifact_size: int,
        *,
        require_space: bool = True,
    ) -> None:
        if candidate.system_disk:
            raise MediaVerificationError(
                "selected medium belongs to the system disk", code="SYSTEM_DISK_REJECTED"
            )
        if target.flash.options.get("require_removable") and not candidate.removable:
            raise MediaVerificationError(
                "selected medium is not reported removable", code="MEDIA_NOT_REMOVABLE"
            )
        if candidate.read_only:
            raise MediaVerificationError(
                "selected medium is read-only", code="MEDIA_READ_ONLY"
            )
        required = {
            str(item).casefold()
            for item in target.flash.options.get("required_filesystems", ())
        }
        if candidate.filesystem.casefold() not in required:
            raise MediaVerificationError(
                f"filesystem {candidate.filesystem!r} is not allowed; required={sorted(required)}",
                code="FILESYSTEM_MISMATCH",
            )
        if target.flash.options.get("destination") != "sd-card-root":
            raise MediaVerificationError(
                "FlashRecipe destination is not the SD-card root",
                code="DESTINATION_POLICY_MISMATCH",
            )
        mount = Path(candidate.mount_path)
        if not mount.is_dir() or str(mount.resolve()) != candidate.mount_path:
            raise MediaVerificationError(
                "selected mount root is absent or not canonical", code="MOUNT_INVALID"
            )
        if require_space and candidate.free_bytes < artifact_size:
            raise MediaVerificationError(
                "selected medium has insufficient free space", code="INSUFFICIENT_SPACE"
            )

    def prepare_media(
        self,
        plan: DeploymentPlan,
        *,
        selected_media_id: Optional[str] = None,
    ) -> ContractDeploymentSession:
        _contract, target = self._validate_plan(plan)
        try:
            self._verify_artifacts(plan)
        except ArtifactExecutionError:
            raise
        session = ContractDeploymentSession(
            plan=plan,
            state=ContractDeploymentState.PREPARED,
            started_at=self.clock(),
            steps=[DeploymentStepRecord(
                ContractDeploymentState.PREPARED,
                self.clock(),
                "DeploymentPlan and staged artifact validated",
            )],
        )
        self._emit(session, "DeploymentPlan and staged artifact validated")
        try:
            if self.mcu_monitor is None or self.firmware_verifier is None:
                raise ContractDeploymentExecutionError(
                    "MCU monitor and Klipper verifier are required before media writes",
                    code="POST_FLASH_VERIFIER_UNAVAILABLE",
                )
            self.mcu_monitor.arm()
            candidates = self.media_provider.list_candidates()
            selected = self._select_media(candidates, selected_media_id)
            session.selected_media = selected
            self._transition(
                session, ContractDeploymentState.MEDIA_SELECTED,
                f"selected removable medium {selected.stable_id}",
            )
            self._verify_media(selected, target, plan.artifact.size_bytes)
            refreshed = self.media_provider.refresh(selected)
            if refreshed is None:
                raise MediaVerificationError(
                    "selected medium disappeared before copy", code="MEDIA_DISAPPEARED"
                )
            if not selected.same_physical_medium(refreshed):
                raise MediaVerificationError(
                    "selected medium identity changed before copy", code="MEDIA_IDENTITY_CHANGED"
                )
            session.selected_media = refreshed
            self._verify_media(refreshed, target, plan.artifact.size_bytes)
            self._transition(
                session, ContractDeploymentState.MEDIA_VERIFIED,
                "filesystem, removability, identity and free space verified",
            )

            # The staged bytes and plan are checked a second time immediately
            # before the first write to removable media.
            self._validate_plan(plan)
            _native, staged = self._verify_artifacts(plan)
            refreshed_again = self.media_provider.refresh(refreshed)
            if refreshed_again is None:
                raise MediaVerificationError(
                    "selected medium disappeared immediately before copy",
                    code="MEDIA_DISAPPEARED",
                )
            if not refreshed.same_physical_medium(refreshed_again):
                raise MediaVerificationError(
                    "selected medium identity changed immediately before copy",
                    code="MEDIA_IDENTITY_CHANGED",
                )
            self._verify_media(refreshed_again, target, plan.artifact.size_bytes)
            session.selected_media = refreshed_again
            destination = Path(refreshed_again.mount_path) / plan.transformation.final_filename
            if destination.parent.resolve() != Path(refreshed_again.mount_path):
                raise MediaVerificationError(
                    "firmware destination escapes the selected media root",
                    code="DESTINATION_ESCAPE",
                )
            self.media_writer.copy(staged, destination, plan.deployment_id)
            after_copy = self.media_provider.refresh(refreshed_again)
            if after_copy is None:
                raise MediaVerificationError(
                    "selected medium disappeared during copy", code="MEDIA_DISAPPEARED"
                )
            if not refreshed_again.same_physical_medium(after_copy):
                raise MediaVerificationError(
                    "selected medium identity changed during copy",
                    code="MEDIA_IDENTITY_CHANGED",
                )
            self._verify_media(
                after_copy, target, plan.artifact.size_bytes, require_space=False
            )
            session.selected_media = after_copy
            self._transition(
                session, ContractDeploymentState.COPIED,
                f"copied {destination.name} to selected media root",
            )
            if not destination.is_file():
                raise ArtifactExecutionError(
                    "copied firmware is absent from the selected medium",
                    code="MEDIA_FILE_ABSENT",
                )
            session.media_readback_size = destination.stat().st_size
            session.media_readback_hash = _sha256_file(destination)
            if session.media_readback_size != plan.artifact.size_bytes:
                raise ArtifactExecutionError(
                    "media readback size differs from staged artifact",
                    code="MEDIA_SIZE_MISMATCH",
                )
            if session.media_readback_hash != plan.transformation.final_sha256:
                raise ArtifactExecutionError(
                    "media readback hash differs from staged artifact",
                    code="MEDIA_HASH_MISMATCH",
                )
            self._transition(
                session, ContractDeploymentState.COPY_VERIFIED,
                "media file reread; size and SHA-256 match staged artifact",
            )
            session.safe_eject = self.ejector.eject(after_copy)
            if session.safe_eject.status is not SafeEjectStatus.EJECTED:
                raise MediaVerificationError(
                    f"safe eject did not complete: {session.safe_eject.detail}",
                    code=(
                        "EJECT_UNSUPPORTED"
                        if session.safe_eject.status is SafeEjectStatus.UNSUPPORTED
                        else "EJECT_FAILED"
                    ),
                )
            self._transition(
                session, ContractDeploymentState.EJECTED,
                "selected medium safely ejected",
            )
            self._transition(
                session,
                ContractDeploymentState.WAITING_FOR_MANUAL_POWER_CYCLE,
                "waiting for explicit confirmation of manual power off, SD insertion and power on",
            )
            return session
        except ContractDeploymentExecutionError as exc:
            self._fail(
                session, exc, code=exc.code, error_type=type(exc)
            )
        except Exception as exc:
            self._fail(session, exc, code="MEDIA_PREPARATION_FAILED")

    def record_power_observation(
        self,
        session: ContractDeploymentSession,
        observation: PowerObservation,
    ) -> ContractDeploymentSession:
        if session.state is not ContractDeploymentState.WAITING_FOR_MANUAL_POWER_CYCLE:
            raise ContractDeploymentExecutionError(
                "power observations are only recorded at the manual gate",
                code="INVALID_POWER_OBSERVATION_STATE",
                proof=session.proof(),
            )
        session.power_observations.append(observation)
        # Observation is evidence only. ON/OFF never advances the gate.
        return session

    def cancel_at_manual_gate(
        self, session: ContractDeploymentSession, *, reason: str
    ) -> DeploymentProof:
        if session.state is not ContractDeploymentState.WAITING_FOR_MANUAL_POWER_CYCLE:
            raise ContractDeploymentExecutionError(
                "deployment is not waiting at the manual gate",
                code="MANUAL_GATE_NOT_ACTIVE",
                proof=session.proof(),
            )
        session.errors.append(str(reason or "cancelled by user"))
        self._transition(
            session, ContractDeploymentState.FAILED,
            str(reason or "cancelled by user"),
        )
        try:
            self.mcu_monitor.close()
        except Exception:
            pass
        return session.proof()

    def confirm_manual_power_cycle(
        self,
        session: ContractDeploymentSession,
        *,
        confirmed: bool,
    ) -> DeploymentProof:
        if session.state is not ContractDeploymentState.WAITING_FOR_MANUAL_POWER_CYCLE:
            raise ContractDeploymentExecutionError(
                "deployment is not waiting for manual power-cycle confirmation",
                code="MANUAL_GATE_NOT_ACTIVE",
                proof=session.proof(),
            )
        if confirmed is not True:
            return session.proof()
        session.manual_confirmation = True
        session.manual_confirmation_at = self.clock()
        try:
            self._transition(
                session,
                ContractDeploymentState.WAITING_FOR_MCU_REENUMERATION,
                "user explicitly confirmed the manual power-cycle procedure",
            )
            identity = self.mcu_monitor.wait_for_present(
                cancel_event=self.cancel_event,
                timeout=self.mcu_timeout,
            )
            session.observed_mcu_identity = McuIdentityEvidence.capture(identity)
            session.reenumeration_result = "expected physical MCU identity accepted"
            self._transition(
                session,
                ContractDeploymentState.MCU_REENUMERATED,
                session.reenumeration_result,
            )
            self._transition(
                session,
                ContractDeploymentState.WAITING_FOR_KLIPPER,
                "waiting for Klipper and expected MCU registration",
            )
            expected = session.plan.artifact.firmware_identity.reported_version
            result = self.firmware_verifier.wait_for_firmware(
                mcu_name=self.mcu_name,
                expected_fingerprint=expected,
                timeout=self.klipper_timeout,
            )
            session.klipper_connection_result = result.detail
            session.observed_fingerprint = result.observed_fingerprint
            if not result.klipper_connected:
                raise PostFlashVerificationError(
                    result.detail, code="KLIPPER_NOT_READY"
                )
            self._transition(
                session,
                ContractDeploymentState.VERIFYING_FIRMWARE,
                "verifying exact firmware build-id/fingerprint",
            )
            if result.observed_fingerprint != expected:
                raise PostFlashVerificationError(
                    f"firmware fingerprint mismatch: expected {expected!r}, "
                    f"observed {result.observed_fingerprint!r}",
                    code="FIRMWARE_FINGERPRINT_MISMATCH",
                )
            self._transition(
                session,
                ContractDeploymentState.VERIFIED,
                "physical SD deployment and firmware identity verified",
            )
            return session.proof()
        except (
            McuIdentityAmbiguous,
            McuIdentityMismatch,
            McuMonitorCancelled,
            McuMonitorError,
            TimeoutError,
            ContractDeploymentExecutionError,
        ) as exc:
            if isinstance(exc, ContractDeploymentExecutionError):
                code = exc.code
                error_type = type(exc)
            elif isinstance(exc, TimeoutError):
                code, error_type = "MCU_REENUMERATION_TIMEOUT", PostFlashVerificationError
            else:
                code, error_type = "MCU_IDENTITY_REJECTED", PostFlashVerificationError
            self._fail(session, exc, code=code, error_type=error_type)
        except Exception as exc:
            self._fail(
                session, exc, code="POST_FLASH_VERIFICATION_FAILED",
                error_type=PostFlashVerificationError,
            )
        finally:
            if session.state in {
                ContractDeploymentState.VERIFIED,
                ContractDeploymentState.FAILED,
            }:
                try:
                    self.mcu_monitor.close()
                except Exception:
                    pass


def write_deployment_proof(proof: DeploymentProof, output_directory: str) -> str:
    if not isinstance(proof, DeploymentProof):
        raise TypeError("only a typed DeploymentProof can be persisted")
    root = Path(output_directory).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{proof.deployment_id}.json"
    temporary = root / f".{proof.deployment_id}.json.part"
    content = json.dumps(
        proof.to_mapping(include_digest=True),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ).encode("utf-8") + b"\n"
    try:
        with temporary.open("xb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return str(path)
