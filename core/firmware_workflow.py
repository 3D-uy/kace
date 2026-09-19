"""Durable authority for the firmware -> configuration -> deploy workflow.

The interactive CLI is only an adapter over this contract.  A prompt cannot
advance the workflow by itself: every deployable state is backed by persisted,
revalidated evidence.
"""

from __future__ import annotations

from dataclasses import asdict, fields, is_dataclass, replace
from enum import Enum
import hashlib
import glob
import json
import os
import re
import tempfile
import time
import uuid
from typing import Any, Callable, Mapping, Optional

from core.mcu_monitor import (
    McuIdentity, McuIdentityReader, McuIdentityVerdict, McuMonitorError,
    assess_mcu_identity,
)
from core.workspace import exclusive_file_lock


CHECKPOINT_SCHEMA = "kace-firmware-workflow/v1"
DEFAULT_CHECKPOINT_PATH = "~/kace/firmware-workflow.json"
_STORAGE_REVISION = "_storage_revision"


class FirmwareWorkflowError(RuntimeError):
    """Base error for rejected workflow state or evidence."""


class CheckpointCorrupt(FirmwareWorkflowError):
    """The persisted checkpoint is malformed or failed its integrity check."""


class CheckpointIncompatible(FirmwareWorkflowError):
    """The checkpoint does not describe the currently observed hardware."""


class CheckpointConflict(FirmwareWorkflowError):
    """A concurrent writer changed the checkpoint since this workflow read it."""


class DeploymentInvariantError(FirmwareWorkflowError):
    """A configuration deployment attempted to bypass a workflow invariant."""


class RunningFirmwareMismatch(FirmwareWorkflowError):
    """Klipper did not report the exact firmware build owned by the workflow."""


class FirmwareWorkflowState(str, Enum):
    HARDWARE_SELECTED = "HARDWARE_SELECTED"
    COMPILE_REQUIRED = "COMPILE_REQUIRED"
    ARTIFACT_READY = "ARTIFACT_READY"
    AWAITING_FLASH = "AWAITING_FLASH"
    VERIFYING_MCU = "VERIFYING_MCU"
    MCU_VERIFIED = "MCU_VERIFIED"
    CONFIG_GENERATED = "CONFIG_GENERATED"
    READY_TO_DEPLOY = "READY_TO_DEPLOY"
    DEPLOYING = "DEPLOYING"
    COMPLETE = "COMPLETE"


_TRANSITIONS = {
    FirmwareWorkflowState.HARDWARE_SELECTED: {
        FirmwareWorkflowState.COMPILE_REQUIRED,
        FirmwareWorkflowState.ARTIFACT_READY,
    },
    FirmwareWorkflowState.COMPILE_REQUIRED: {
        FirmwareWorkflowState.ARTIFACT_READY,
    },
    FirmwareWorkflowState.ARTIFACT_READY: {
        FirmwareWorkflowState.COMPILE_REQUIRED,
        FirmwareWorkflowState.AWAITING_FLASH,
        FirmwareWorkflowState.VERIFYING_MCU,
    },
    FirmwareWorkflowState.AWAITING_FLASH: {
        FirmwareWorkflowState.COMPILE_REQUIRED,
        FirmwareWorkflowState.VERIFYING_MCU,
    },
    FirmwareWorkflowState.VERIFYING_MCU: {
        FirmwareWorkflowState.COMPILE_REQUIRED,
        FirmwareWorkflowState.AWAITING_FLASH,
        FirmwareWorkflowState.MCU_VERIFIED,
    },
    FirmwareWorkflowState.MCU_VERIFIED: {
        FirmwareWorkflowState.COMPILE_REQUIRED,
        FirmwareWorkflowState.CONFIG_GENERATED,
    },
    FirmwareWorkflowState.CONFIG_GENERATED: {
        FirmwareWorkflowState.COMPILE_REQUIRED,
        FirmwareWorkflowState.READY_TO_DEPLOY,
    },
    FirmwareWorkflowState.READY_TO_DEPLOY: {
        FirmwareWorkflowState.COMPILE_REQUIRED,
        FirmwareWorkflowState.DEPLOYING,
    },
    FirmwareWorkflowState.DEPLOYING: {
        FirmwareWorkflowState.READY_TO_DEPLOY,
        FirmwareWorkflowState.COMPLETE,
    },
    FirmwareWorkflowState.COMPLETE: {
        FirmwareWorkflowState.COMPILE_REQUIRED,
    },
}

_SECRET_KEYS = {
    "password",
    "ssh_password",
    "wifi_password",
    "moonraker_api_key",
    "api_key",
}
_RUNTIME_KEYS = {
    "firmware_artifact",
    "firmware_deployment_service",
    "firmware_deployment_plan",
    "prepared_firmware_deployment",
    "board_contract_build_proof",
    "board_contract_deployment_plan",
    "board_contract_deployment_proof",
    "workflow_checkpoint",
}
_DEPLOYABLE_STATES = {
    FirmwareWorkflowState.READY_TO_DEPLOY,
    FirmwareWorkflowState.DEPLOYING,
    FirmwareWorkflowState.COMPLETE,
}
_STABLE_SERIAL_PREFIX = "/dev/serial/by-id/"


def _same_mcu_model(board: str, expected: str, observed: str) -> bool:
    """Allow only exact model/resolved-name aliases from the selected contract."""
    if expected == observed:
        return True
    # Legacy Octopus variants predate BoardContract, but have verified Kconfig
    # spellings. Do not generalize this to arbitrary suffixes or other boards.
    if board == "generic-bigtreetech-octopus-v1.1.cfg":
        if any({expected, observed} <= pair for pair in (
            {"stm32f446", "stm32f446xx"}, {"stm32f429", "stm32f429xx"},
        )):
            return True
    from firmware.boards.catalog import load_default_catalog
    contract = load_default_catalog().resolve_exact(board)
    return bool(contract and any(
        {expected, observed} <= {variant.processor.model.lower(), variant.processor.resolved_mcu.lower()}
        for variant in contract.hardware_variants
    ))


def checkpoint_path(path: Optional[str] = None) -> str:
    configured = path or os.environ.get("KACE_FIRMWARE_WORKFLOW_PATH") or DEFAULT_CHECKPOINT_PATH
    return os.path.abspath(os.path.expanduser(configured))


def checkpoint_revision(path: Optional[str] = None) -> tuple[str, Optional[str]]:
    """Capture a replacement precondition, including corrupt/legacy checkpoints."""
    destination = checkpoint_path(path)
    try:
        with open(destination, "rb") as source:
            digest = hashlib.sha256(source.read()).hexdigest()
    except FileNotFoundError:
        digest = None
    return destination, digest


def discard_checkpoint(checkpoint):
    """Archive only the revision explicitly discarded by the operator."""
    expected = checkpoint.get(_STORAGE_REVISION)
    if not expected:
        raise CheckpointConflict("checkpoint revision is unavailable")
    destination = expected[0]
    with exclusive_file_lock(destination + ".lock", timeout_seconds=30):
        if checkpoint_revision(destination) != tuple(expected):
            raise CheckpointConflict("checkpoint changed before discard; reload it")
        os.replace(destination, destination + ".discarded-" + uuid.uuid4().hex)


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            if not isinstance(key, str) or key in _SECRET_KEYS or key in _RUNTIME_KEYS:
                continue
            result[key] = _jsonable(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    raise TypeError(f"unsupported checkpoint value: {type(value).__name__}")


def persistable_wizard_data(user_data: Mapping[str, Any]) -> dict[str, Any]:
    """Return wizard decisions only, excluding credentials and runtime objects."""
    result: dict[str, Any] = {}
    for key, value in user_data.items():
        if key in _SECRET_KEYS or key in _RUNTIME_KEYS:
            continue
        try:
            result[key] = _jsonable(value)
        except (TypeError, ValueError):
            # Runtime helpers are reconstructed from validated persisted facts.
            continue
    return result


def _canonical_payload(checkpoint: Mapping[str, Any]) -> bytes:
    payload = dict(checkpoint)
    payload.pop("integrity_sha256", None)
    payload.pop(_STORAGE_REVISION, None)
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _with_integrity(checkpoint: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(checkpoint)
    payload["integrity_sha256"] = hashlib.sha256(_canonical_payload(payload)).hexdigest()
    return payload


def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_evidence(user_data: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    """Extract the smallest revalidatable artifact/deployment projection."""
    artifact = user_data.get("firmware_artifact")
    artifact_data = artifact.to_dict() if hasattr(artifact, "to_dict") else None
    plan = user_data.get("board_contract_deployment_plan")
    prepared = user_data.get("prepared_firmware_deployment")
    if artifact_data is None:
        return None
    digest = str(artifact_data.get("sha256") or "")
    size = int(artifact_data.get("size_bytes") or 0)
    identity = artifact_data.get("firmware_identity") or {}
    if not digest or identity.get("artifact_sha256") != digest or identity.get("artifact_size") != size:
        raise FirmwareWorkflowError("firmware build identity is missing or inconsistent")

    path = str(user_data.get("firmware_path") or "")
    final_filename = os.path.basename(path) if path else ""
    method = ""
    strategy = ""
    instructions: list[dict[str, str]] = []
    expected_vid_pids = ()
    bootloader_vid_pids = ()
    if plan is not None:
        from firmware.boards.catalog import load_default_catalog

        contract = load_default_catalog().by_id(plan.board_id)
        variant = contract.variant(plan.hardware_variant_id) if contract else None
        target = variant.target(plan.build_target_id) if variant else None
        if target is None:
            raise FirmwareWorkflowError("firmware plan target is absent from the catalog")
        application_id = target.transport.endpoint.get("application_vid_pid")
        bootloader_id = target.transport.endpoint.get("bootloader_vid_pid")
        expected_vid_pids = (application_id,) if application_id else ()
        bootloader_vid_pids = (bootloader_id,) if bootloader_id else ()
        transformation = getattr(plan, "transformation", None)
        if (getattr(transformation, "native_sha256", None) != digest
                or getattr(transformation, "final_sha256", None) != digest
                or getattr(transformation, "size_bytes", None) != size):
            raise FirmwareWorkflowError("firmware transformation does not match the immutable build")
        path = str(getattr(transformation, "final_path", "") or path)
        final_filename = str(getattr(transformation, "final_filename", "") or final_filename)
        strategy = str(getattr(getattr(plan, "strategy", None), "value", "") or "")
        instructions = [
            {"id": str(getattr(item, "id", "")), "text": str(getattr(item, "text", ""))}
            for item in getattr(plan, "instructions", ())
        ]
    if prepared is not None:
        if prepared.sha256 != digest or prepared.plan.artifact.sha256 != digest:
            raise FirmwareWorkflowError("prepared firmware does not match the immutable build")
        legacy_plan = getattr(prepared, "plan", None)
        path = str(getattr(prepared, "staged_path", "") or path)
        final_filename = str(getattr(legacy_plan, "final_filename", "") or final_filename)
        method = str(getattr(getattr(legacy_plan, "method", None), "value", "") or "")
        profile = getattr(legacy_plan, "profile", None)
        usb = getattr(profile, "usb", None)
        expected_vid_pids = tuple(getattr(usb, "application_vid_pids", ()))
        bootloader_vid_pids = tuple(getattr(usb, "bootloader_vid_pids", ()))
        strategy = str(getattr(getattr(profile, "strategy", None), "value", "") or strategy)
        instructions = [
            {"id": str(getattr(item, "id", "")), "text": str(getattr(item, "text", ""))}
            for item in getattr(legacy_plan, "instructions", ())
        ]

    expanded = os.path.abspath(os.path.expanduser(path)) if path else ""
    try:
        if not expanded or not os.path.isfile(expanded):
            raise FirmwareWorkflowError("verified firmware artifact is missing")
        if os.path.getsize(expanded) != size or _file_sha256(expanded) != digest:
            raise FirmwareWorkflowError("firmware bytes changed after the verified build; rebuild required")
    except OSError as exc:
        raise FirmwareWorkflowError(f"verified firmware artifact could not be read: {exc}") from exc

    if not expanded or not digest:
        return None
    return {
        "path": expanded,
        "final_filename": final_filename or os.path.basename(expanded),
        "sha256": digest,
        "size_bytes": size,
        "method": method,
        "strategy": strategy,
        "instructions": instructions,
        "build": artifact_data or {},
        "expected_vid_pids": list(expected_vid_pids),
        "bootloader_vid_pids": list(bootloader_vid_pids),
    }


def create_checkpoint(
    user_data: Mapping[str, Any],
    *,
    state: FirmwareWorkflowState = FirmwareWorkflowState.HARDWARE_SELECTED,
    identity_reader=None,
) -> dict[str, Any]:
    board = str(user_data.get("board") or "").strip()
    mcu = str(user_data.get("mcu_type") or user_data.get("derived_mcu") or "").strip().lower()
    if not board or not mcu:
        raise FirmwareWorkflowError("a selected board and detected MCU are required")
    now = int(time.time())
    baseline = None
    try:
        baseline = (identity_reader or McuIdentityReader()).read(str(user_data.get("mcu_path") or ""))
    except (McuMonitorError, OSError):
        # Missing evidence must require physical confirmation later, never be
        # reconstructed from a potentially different MCU after flashing.
        pass
    checkpoint = {
        "schema": CHECKPOINT_SCHEMA,
        "workflow_id": f"firmware-{uuid.uuid4().hex}",
        "sequence": 1,
        "state": FirmwareWorkflowState(state).value,
        "created_at": now,
        "updated_at": now,
        "hardware": {
            "board": board,
            "mcu": mcu,
            "baseline_serial_path": str(user_data.get("mcu_path") or ""),
            "baseline_identity": baseline.to_dict() if baseline is not None else None,
            "verified_serial_path": "",
            "flash_evidence_recorded_at": 0,
        },
        "wizard_data": persistable_wizard_data(user_data),
        "artifact": None,
        "last_error": "",
    }
    return _with_integrity(checkpoint)


def transition_checkpoint(
    checkpoint: Mapping[str, Any],
    state: FirmwareWorkflowState,
    *,
    user_data: Optional[Mapping[str, Any]] = None,
    artifact: Optional[Mapping[str, Any]] = None,
    verified_serial_path: Optional[str] = None,
    flash_evidence_recorded_at: Optional[int] = None,
    last_error: str = "",
) -> dict[str, Any]:
    validate_checkpoint(checkpoint, verify_artifact=False)
    current = FirmwareWorkflowState(checkpoint["state"])
    target = FirmwareWorkflowState(state)
    if target is not current and target not in _TRANSITIONS[current]:
        raise FirmwareWorkflowError(f"illegal firmware workflow transition {current.value} -> {target.value}")
    updated = dict(checkpoint)
    updated["state"] = target.value
    updated["sequence"] = int(checkpoint["sequence"]) + 1
    updated["updated_at"] = int(time.time())
    updated["last_error"] = str(last_error or "")
    if user_data is not None:
        updated["wizard_data"] = persistable_wizard_data(user_data)
    if artifact is not None:
        updated["artifact"] = _jsonable(artifact)
    if verified_serial_path is not None:
        hardware = dict(updated["hardware"])
        hardware["verified_serial_path"] = str(verified_serial_path)
        updated["hardware"] = hardware
    if flash_evidence_recorded_at is not None:
        hardware = dict(updated["hardware"])
        hardware["flash_evidence_recorded_at"] = int(flash_evidence_recorded_at)
        updated["hardware"] = hardware
    if target is FirmwareWorkflowState.MCU_VERIFIED:
        hardware = updated["hardware"]
        if not str(hardware.get("verified_serial_path") or ""):
            raise FirmwareWorkflowError(
                "MCU_VERIFIED requires a validated serial path"
            )
        if int(hardware.get("flash_evidence_recorded_at") or 0) <= 0:
            raise FirmwareWorkflowError(
                "MCU_VERIFIED requires completed flashing evidence"
            )
    return _with_integrity(updated)


def write_checkpoint(
    checkpoint: Mapping[str, Any], path: Optional[str] = None,
    *, expected_revision: Optional[tuple[str, Optional[str]]] = None,
) -> str:
    validated = validate_checkpoint(checkpoint, verify_artifact=False)
    destination = checkpoint_path(path)
    directory = os.path.dirname(destination)
    os.makedirs(directory, exist_ok=True)
    expected = expected_revision or validated.get(_STORAGE_REVISION) or (destination, None)
    # Runtime CAS evidence travels with transitions, but never enters the v1
    # checkpoint format or its integrity hash.
    validated.pop(_STORAGE_REVISION, None)
    encoded = (json.dumps(validated, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with exclusive_file_lock(destination + ".lock", timeout_seconds=30):
        current = checkpoint_revision(destination)
        if current != tuple(expected):
            raise CheckpointConflict("firmware checkpoint changed on disk; reload it before continuing")
        fd, temporary = tempfile.mkstemp(prefix="firmware-workflow-", suffix=".json", dir=directory)
        try:
            with os.fdopen(fd, "wb") as target:
                target.write(encoded)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)
        if isinstance(checkpoint, dict):
            checkpoint[_STORAGE_REVISION] = (destination, hashlib.sha256(encoded).hexdigest())
    # Normal CLI output stays human-readable; Studio also observes the file.
    if os.environ.get("KACE_MACHINE_OUTPUT") != "1":
        return destination
    # Emit only after durable publication. Studio observes; it owns no state.
    try:
        from core.moonraker_deployer import JsonEventSink
        artifact = validated.get("artifact") or {}
        state = validated["state"]
        JsonEventSink()({
            "schema": 2, "workflow_kind": "firmware_deployment",
            "workflow_id": validated["workflow_id"], "sequence": validated["sequence"],
            "state": state, "detail": validated.get("last_error", ""),
            "data": {
                "firmware_authority": "durable_checkpoint",
                "last_error": validated.get("last_error", ""),
                "language": validated.get("wizard_data", {}).get("language", "English"),
                "staged_path": artifact.get("path", ""),
                "final_filename": artifact.get("final_filename", ""),
                "download_available": state in {"ARTIFACT_READY", "AWAITING_FLASH", "VERIFYING_MCU"},
            },
        })
    except (OSError, ValueError):
        pass  # A closed terminal cannot invalidate a committed checkpoint.
    return destination


def load_checkpoint(
    path: Optional[str] = None,
    *,
    current_hardware: Optional[Mapping[str, Any]] = None,
    verify_artifact: bool = True,
) -> Optional[dict[str, Any]]:
    source_path = checkpoint_path(path)
    if not os.path.exists(source_path):
        return None
    try:
        with open(source_path, "rb") as source:
            encoded = source.read()
        value = json.loads(encoded.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CheckpointCorrupt(f"could not read firmware workflow checkpoint: {exc}") from exc
    value = validate_checkpoint(
        value, current_hardware=current_hardware, verify_artifact=verify_artifact
    )
    value[_STORAGE_REVISION] = (source_path, hashlib.sha256(encoded).hexdigest())
    return value


def validate_checkpoint(
    checkpoint: Mapping[str, Any],
    *,
    current_hardware: Optional[Mapping[str, Any]] = None,
    verify_artifact: bool = True,
) -> dict[str, Any]:
    if not isinstance(checkpoint, Mapping):
        raise CheckpointCorrupt("firmware workflow checkpoint is not an object")
    value = dict(checkpoint)
    if value.get("schema") != CHECKPOINT_SCHEMA:
        raise CheckpointCorrupt("unsupported firmware workflow checkpoint schema")
    expected = str(value.get("integrity_sha256") or "")
    actual = hashlib.sha256(_canonical_payload(value)).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{64}", expected) or expected != actual:
        raise CheckpointCorrupt("firmware workflow checkpoint integrity check failed")
    try:
        state = FirmwareWorkflowState(value.get("state"))
    except ValueError as exc:
        raise CheckpointCorrupt("firmware workflow checkpoint has an unknown state") from exc
    if not isinstance(value.get("sequence"), int) or isinstance(value.get("sequence"), bool) or value["sequence"] < 1:
        raise CheckpointCorrupt("firmware workflow checkpoint sequence is invalid")
    hardware = value.get("hardware")
    wizard_data = value.get("wizard_data")
    if not isinstance(hardware, dict) or not isinstance(wizard_data, dict):
        raise CheckpointCorrupt("firmware workflow checkpoint payload is incomplete")
    board = str(hardware.get("board") or "").strip()
    expected_mcu = str(hardware.get("mcu") or "").strip().lower()
    if not board or not expected_mcu or wizard_data.get("board") != board:
        raise CheckpointCorrupt("firmware workflow hardware identity is incomplete")

    if current_hardware:
        current_board = str(current_hardware.get("board") or "").strip()
        current_mcu = str(
            current_hardware.get("derived_mcu")
            or current_hardware.get("mcu_type")
            or ""
        ).strip().lower()
        if current_board and current_board != board:
            raise CheckpointIncompatible(
                f"checkpoint board {board} does not match current board {current_board}"
            )
        if current_mcu and not _same_mcu_model(board, expected_mcu, current_mcu):
            raise CheckpointIncompatible(
                f"checkpoint MCU {expected_mcu} does not match detected MCU {current_mcu}"
            )
        current_serial = str(current_hardware.get("mcu_path") or "").strip()
        verified_serial = str(hardware.get("verified_serial_path") or "").strip()
        if current_serial and verified_serial and current_serial != verified_serial:
            raise CheckpointIncompatible(
                "detected MCU serial path does not match the checkpoint's verified MCU"
            )

    artifact = value.get("artifact")
    if state not in {
        FirmwareWorkflowState.HARDWARE_SELECTED,
        FirmwareWorkflowState.COMPILE_REQUIRED,
    }:
        if not isinstance(artifact, dict):
            raise CheckpointCorrupt("firmware workflow checkpoint has no build artifact evidence")
        artifact_path = str(artifact.get("path") or "")
        digest = str(artifact.get("sha256") or "").lower()
        build = artifact.get("build") or {}
        built_mcu = str(build.get("mcu") or "").lower()
        if not built_mcu or not _same_mcu_model(board, expected_mcu, built_mcu):
            raise CheckpointIncompatible("compiled MCU does not match the originally selected hardware")
        identity = build.get("firmware_identity") or {}
        # Reject old checkpoints which blessed changed bytes with a fresh hash.
        for recorded in (build.get("sha256"), identity.get("artifact_sha256")):
            if recorded is not None and recorded != digest:
                raise CheckpointIncompatible("checkpoint artifact differs from its immutable build")
        for recorded in (build.get("size_bytes"), identity.get("artifact_size")):
            if recorded is not None and recorded != artifact.get("size_bytes"):
                raise CheckpointIncompatible("checkpoint artifact size differs from its immutable build")
        if not artifact_path or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise CheckpointCorrupt("firmware artifact evidence is incomplete")
        if verify_artifact:
            try:
                if not os.path.isfile(artifact_path):
                    raise CheckpointIncompatible("checkpoint firmware artifact is missing")
                if os.path.getsize(artifact_path) != int(artifact.get("size_bytes") or -1):
                    raise CheckpointIncompatible("checkpoint firmware artifact size changed")
                if _file_sha256(artifact_path) != digest:
                    raise CheckpointIncompatible("checkpoint firmware artifact hash changed")
            except OSError as exc:
                raise CheckpointIncompatible(f"could not revalidate firmware artifact: {exc}") from exc
    return value


def extract_mcu_serial(config_path: str) -> str:
    """Return the active ``[mcu].serial`` value, or an empty string."""
    section = ""
    try:
        resolved_path = (
            os.path.expanduser(config_path)
            if str(config_path).startswith("~")
            else str(config_path)
        )
        with open(resolved_path, "r", encoding="utf-8") as source:
            lines = source
            for raw_line in lines:
                line = raw_line.split("#", 1)[0].split(";", 1)[0].strip()
                if not line:
                    continue
                if line.startswith("[") and line.endswith("]"):
                    section = line[1:-1].strip().lower()
                    continue
                if section != "mcu":
                    continue
                match = re.match(r"^serial\s*[:=]\s*(.*?)\s*$", line, re.IGNORECASE)
                if match:
                    return match.group(1).strip()
    except (OSError, UnicodeError):
        return ""
    return ""


def verify_reappeared_mcu(
    checkpoint: Mapping[str, Any],
    *,
    detector: Optional[Callable[[], Mapping[str, Any]]] = None,
    flash_evidence: bool = False,
    identity_reader=None,
    ambiguity_resolver=None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Observe the current MCU and persist only stable, compatible serial evidence."""
    checked = validate_checkpoint(checkpoint, verify_artifact=True)
    if FirmwareWorkflowState(checked["state"]) not in {
        FirmwareWorkflowState.AWAITING_FLASH,
        FirmwareWorkflowState.VERIFYING_MCU,
    }:
        raise FirmwareWorkflowError("MCU verification is not valid in the current workflow state")
    if flash_evidence is not True:
        raise FirmwareWorkflowError(
            "explicit evidence that the board-specific flashing step completed is required"
        )
    expected_mcu = str(checked["hardware"]["mcu"]).lower()
    reader = identity_reader or McuIdentityReader()
    baseline_data = checked["hardware"].get("baseline_identity")
    if baseline_data:
        try:
            baseline = McuIdentity(**{f.name: baseline_data[f.name] for f in fields(McuIdentity)})
        except (KeyError, TypeError) as exc:
            raise CheckpointCorrupt("invalid original MCU identity evidence") from exc
    else:
        baseline = McuIdentity(str(checked["hardware"].get("baseline_serial_path") or ""), "")
    evidence = checked.get("artifact") or {}
    expected = evidence.get("expected_vid_pids") or ((baseline.vid_pid,) if baseline.vid_pid else ())
    bridge_ids = None
    if detector is None:
        from firmware.detector import mcu_context_from_path

        observations = [mcu_context_from_path(path) for path in sorted(glob.glob(_STABLE_SERIAL_PREFIX + "*"))]
    else:
        observations = [dict(detector() or {})]
    candidates = []
    for observed in observations:
        serial_path = str(observed.get("mcu_path") or "").strip()
        derived = str(observed.get("derived_mcu") or "").lower()
        if derived and not _same_mcu_model(checked["hardware"]["board"], expected_mcu, derived):
            continue
        if not derived and bridge_ids is None:
            from firmware.deployment.profiles import load_profiles
            from firmware.deployment.models import UsbTopology
            bridge_ids = {
                vid_pid for profile in load_profiles()
                if str(checked["hardware"]["board"]).lower() in profile.board_patterns
                and expected_mcu in profile.mcu_patterns
                and profile.usb.topology is UsbTopology.USB_SERIAL_BRIDGE
                for vid_pid in profile.usb.application_vid_pids
            }
            # A native UART target keeps the originally selected USB adapter's
            # identity. The adapter cannot expose the MCU model after flashing.
            from firmware.boards.runtime import resolve_firmware_authority, FirmwareAuthority
            from firmware.boards.catalog import load_default_catalog
            decision = resolve_firmware_authority(checked["hardware"]["board"], detected_mcu=expected_mcu)
            if decision.authority is FirmwareAuthority.BOARD_CONTRACT and baseline.vid_pid:
                variant = load_default_catalog().by_id(decision.board_id).variant(decision.hardware_variant_id)
                target = variant.target(decision.build_target_id)
                if target.transport.kind.value == "UART":
                    bridge_ids.add(baseline.vid_pid)
        if not derived and not bridge_ids:
            continue
        if not serial_path.startswith(_STABLE_SERIAL_PREFIX) or not os.path.exists(serial_path):
            continue
        try:
            candidate = reader.read(serial_path)
        except (McuMonitorError, OSError):
            candidate = None
        if candidate is None:
            # A present by-id path alone cannot prove USB topology or VID:PID.
            candidate = McuIdentity(serial_path, os.path.realpath(serial_path))
        if expected and candidate.vid_pid and candidate.vid_pid not in expected:
            continue
        assessment = assess_mcu_identity(
            baseline, candidate, expected_vid_pids=expected,
            bootloader_vid_pids=evidence.get("bootloader_vid_pids") or (),
        )
        if not baseline_data or not candidate.has_topology:
            if assessment.verdict not in {McuIdentityVerdict.MISMATCH, McuIdentityVerdict.TRANSIENT}:
                assessment = replace(
                    assessment, verdict=McuIdentityVerdict.AMBIGUOUS,
                    reasons=assessment.reasons + ("original or current physical identity evidence is unavailable",),
                )
        if not derived:
            # A bridge keeps its Arduino/CH340 by-id name across MCU flashes.
            # Accept only the contracted bridge with positive physical evidence.
            if candidate.vid_pid not in bridge_ids or assessment.verdict is not McuIdentityVerdict.MATCH:
                continue
            observed = {**observed, "derived_mcu": expected_mcu}
        if assessment.verdict in {McuIdentityVerdict.MATCH, McuIdentityVerdict.AMBIGUOUS}:
            candidates.append((observed, assessment))
    matches = [item for item in candidates if item[1].verdict is McuIdentityVerdict.MATCH]
    eligible = matches or candidates
    if len(eligible) != 1:
        raise CheckpointIncompatible(
            "MCU physical identity is absent, conflicting, or ambiguous across multiple devices; "
            "connect only the originally selected MCU and retry"
        )
    observed, assessment = eligible[0]
    manual = assessment.verdict is not McuIdentityVerdict.MATCH
    if manual and (ambiguity_resolver is None or ambiguity_resolver(assessment) is not True):
        raise CheckpointIncompatible("MCU physical identity requires explicit confirmation: " + assessment.describe())
    serial_path = observed["mcu_path"]
    verifying = checked
    if FirmwareWorkflowState(checked["state"]) is FirmwareWorkflowState.AWAITING_FLASH:
        verifying = transition_checkpoint(checked, FirmwareWorkflowState.VERIFYING_MCU)
    verified = transition_checkpoint(
        verifying,
        FirmwareWorkflowState.MCU_VERIFIED,
        verified_serial_path=serial_path,
        flash_evidence_recorded_at=int(time.time()),
    )
    verified["hardware"] = {
        **verified["hardware"],
        "identity_assessment": assessment.to_dict(),
        "identity_manually_confirmed": manual,
    }
    verified = _with_integrity(verified)
    return verified, observed


def deployment_blockers(
    config_path: str,
    user_data: Mapping[str, Any],
    *,
    checkpoint: Optional[Mapping[str, Any]] = None,
) -> tuple[str, ...]:
    blockers: list[str] = []
    serial = extract_mcu_serial(config_path)
    if not serial:
        blockers.append("[mcu].serial is missing or empty")

    workflow = checkpoint or user_data.get("workflow_checkpoint")
    if workflow is None:
        try:
            workflow = load_checkpoint(verify_artifact=True)
        except FirmwareWorkflowError as exc:
            blockers.append(str(exc))
            workflow = None
    if workflow is not None:
        try:
            checked = validate_checkpoint(workflow, verify_artifact=True)
            state = FirmwareWorkflowState(checked["state"])
            if state not in _DEPLOYABLE_STATES:
                blockers.append(
                    f"firmware workflow is {state.value}; MCU verification and configuration validation are required"
                )
            hardware = checked["hardware"]
            expected_board = str(hardware.get("board") or "")
            if expected_board != str(user_data.get("board") or ""):
                blockers.append("checkpoint board does not match the deployment board")
            verified_path = str(hardware.get("verified_serial_path") or "")
            if not verified_path:
                blockers.append("checkpoint has no validated MCU serial path")
            elif serial and serial != verified_path:
                blockers.append("[mcu].serial does not match the validated MCU serial path")
            if int(hardware.get("flash_evidence_recorded_at") or 0) <= 0:
                blockers.append("checkpoint has no completed flashing evidence")
        except FirmwareWorkflowError as exc:
            blockers.append(str(exc))
    return tuple(dict.fromkeys(blockers))


def enforce_deployment_invariants(
    config_path: str,
    user_data: Mapping[str, Any],
    *,
    checkpoint: Optional[Mapping[str, Any]] = None,
) -> None:
    blockers = deployment_blockers(config_path, user_data, checkpoint=checkpoint)
    if blockers:
        raise DeploymentInvariantError("; ".join(blockers))


def verify_running_firmware(
    checkpoint: Mapping[str, Any],
    versions: Mapping[str, Any],
    *,
    mcu_name: str = "mcu",
) -> str:
    """Require Klipper to report the exact compiled build after activation.

    Reappearance and a stable serial prove that the expected physical MCU is
    available.  This second proof closes the workflow only when Klipper itself
    reports the build identity embedded in the compiled artifact.
    """
    checked = validate_checkpoint(checkpoint, verify_artifact=True)
    state = FirmwareWorkflowState(checked["state"])
    if state not in {FirmwareWorkflowState.DEPLOYING, FirmwareWorkflowState.COMPLETE}:
        raise RunningFirmwareMismatch(
            f"running firmware verification is not valid in state {state.value}"
        )

    artifact = checked.get("artifact") or {}
    build = artifact.get("build") if isinstance(artifact, dict) else None
    identity = build.get("firmware_identity") if isinstance(build, dict) else None
    expected = str(identity.get("reported_version") or "") if isinstance(identity, dict) else ""
    if not re.fullmatch(r"kace-b1-[0-9a-f]{32}", expected):
        raise RunningFirmwareMismatch(
            "the checkpoint has no trustworthy compiled firmware identity"
        )

    actual = str(versions.get(mcu_name) or "") if isinstance(versions, Mapping) else ""
    if not actual:
        raise RunningFirmwareMismatch(
            f"Klipper did not report a firmware version for MCU object {mcu_name!r}"
        )
    from firmware.identity import firmware_version_matches
    if not firmware_version_matches(actual, expected):
        raise RunningFirmwareMismatch(
            f"MCU {mcu_name!r} reports {actual!r}, expected compiled build {expected!r}"
        )
    return actual
