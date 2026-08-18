"""Non-executing BoardContract artifact preparation and deployment plans.

This module is deliberately separate from ``firmware.deployment``.  It can
prepare and prove the final filename, but it has no flashing or execution API.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any, Optional

from firmware.artifacts import BuildArtifact, BuildProvenance, FirmwareFormat
from firmware.identity import FirmwareBuildInputs

from .kconfig import BuildProof, artifact_contains_firmware_fingerprint
from .models import ArtifactFormat, BoardContract, BuildTarget, FlashStrategy


class ContractDeploymentError(RuntimeError):
    """Base error for a rejected BoardContract deployment plan."""


class ContractIdentityMismatch(ContractDeploymentError):
    pass


class ContractArtifactError(ContractDeploymentError):
    pass


class FilenamePolicyError(ContractDeploymentError):
    pass


class DeploymentStepId(str, Enum):
    VALIDATE_ARTIFACT = "VALIDATE_ARTIFACT"
    ASSIGN_FINAL_FILENAME = "ASSIGN_FINAL_FILENAME"
    VERIFY_FILENAME_POLICY = "VERIFY_FILENAME_POLICY"
    PREPARE_MEDIA = "PREPARE_MEDIA"
    ENTER_BOOTSEL = "ENTER_BOOTSEL"
    COPY_TO_MEDIA = "COPY_TO_MEDIA"
    VERIFY_MEDIA_CHECKSUM = "VERIFY_MEDIA_CHECKSUM"
    SAFE_EJECT = "SAFE_EJECT"
    REQUIRE_POWER_OFF = "REQUIRE_POWER_OFF"
    REQUIRE_MEDIA_INSERTED = "REQUIRE_MEDIA_INSERTED"
    REQUIRE_POWER_ON = "REQUIRE_POWER_ON"
    WAIT_FOR_MCU_REENUMERATION = "WAIT_FOR_MCU_REENUMERATION"
    VERIFY_KLIPPER_BUILD_ID = "VERIFY_KLIPPER_BUILD_ID"


class ArtifactTransformationKind(str, Enum):
    RENAME_ONLY = "RENAME_ONLY"


@dataclass(frozen=True)
class ArtifactTransformation:
    kind: ArtifactTransformationKind
    native_path: str
    native_filename: str
    native_sha256: str
    final_path: str
    final_filename: str
    final_sha256: str
    size_bytes: int
    content_changed: bool


@dataclass(frozen=True)
class DeploymentStep:
    id: DeploymentStepId
    ordinal: int


@dataclass(frozen=True)
class DeploymentPlan:
    """Immutable, non-executable plan derived from one exact contract build."""

    schema: str
    deployment_id: str
    board_id: str
    hardware_variant_id: str
    build_target_id: str
    board_contract_digest: str
    klipper_commit: str
    build_proof_digest: str
    strategy: FlashStrategy
    artifact: BuildArtifact
    transformation: ArtifactTransformation
    steps: tuple[DeploymentStep, ...]
    warnings: tuple[str, ...]
    plan_digest: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["strategy"] = self.strategy.value
        data["artifact"] = self.artifact.to_dict()
        data["transformation"]["kind"] = self.transformation.kind.value
        data["steps"] = [
            {"id": step.id.value, "ordinal": step.ordinal} for step in self.steps
        ]
        return data


_FORMAT_MAP = {
    ArtifactFormat.BIN: FirmwareFormat.BIN,
    ArtifactFormat.UF2: FirmwareFormat.UF2,
    ArtifactFormat.IHEX: FirmwareFormat.IHEX,
}
_FORMAT_SUFFIX = {
    ArtifactFormat.BIN: ".bin",
    ArtifactFormat.UF2: ".uf2",
    ArtifactFormat.IHEX: ".hex",
}
_SD_STEPS = (
    DeploymentStepId.VALIDATE_ARTIFACT,
    DeploymentStepId.ASSIGN_FINAL_FILENAME,
    DeploymentStepId.VERIFY_FILENAME_POLICY,
    DeploymentStepId.PREPARE_MEDIA,
    DeploymentStepId.COPY_TO_MEDIA,
    DeploymentStepId.VERIFY_MEDIA_CHECKSUM,
    DeploymentStepId.SAFE_EJECT,
    DeploymentStepId.REQUIRE_POWER_OFF,
    DeploymentStepId.REQUIRE_MEDIA_INSERTED,
    DeploymentStepId.REQUIRE_POWER_ON,
    DeploymentStepId.WAIT_FOR_MCU_REENUMERATION,
    DeploymentStepId.VERIFY_KLIPPER_BUILD_ID,
)
_BOOTSEL_STEPS = (
    DeploymentStepId.VALIDATE_ARTIFACT,
    DeploymentStepId.ASSIGN_FINAL_FILENAME,
    DeploymentStepId.VERIFY_FILENAME_POLICY,
    DeploymentStepId.PREPARE_MEDIA,
    DeploymentStepId.ENTER_BOOTSEL,
    DeploymentStepId.COPY_TO_MEDIA,
    DeploymentStepId.VERIFY_MEDIA_CHECKSUM,
    DeploymentStepId.SAFE_EJECT,
    DeploymentStepId.WAIT_FOR_MCU_REENUMERATION,
    DeploymentStepId.VERIFY_KLIPPER_BUILD_ID,
)


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ContractArtifactError(f"cannot read artifact {path}: {exc}") from exc
    return digest.hexdigest()


def _require_contract_identity(contract: BoardContract, artifact: BuildArtifact):
    if not isinstance(contract, BoardContract):
        raise ContractIdentityMismatch(
            "DeploymentPlan requires a typed BoardContract, not legacy deployment data"
        )
    if not isinstance(artifact, BuildArtifact):
        raise ContractIdentityMismatch("DeploymentPlan requires a typed BuildArtifact")
    expected = {
        "board_id": contract.board_id,
        "board_contract_digest": contract.contract_digest,
        "klipper_commit": contract.upstream.validated_commit,
    }
    for field, value in expected.items():
        if getattr(artifact, field, "") != value:
            raise ContractIdentityMismatch(
                f"artifact {field}={getattr(artifact, field, '')!r} does not match {value!r}"
            )
    variant = contract.variant(artifact.hardware_variant_id)
    if variant is None:
        raise ContractIdentityMismatch(
            f"artifact variant {artifact.hardware_variant_id!r} is not in the contract"
        )
    target = variant.target(artifact.build_target_id)
    if target is None:
        raise ContractIdentityMismatch(
            f"artifact target {artifact.build_target_id!r} is not in the selected variant"
        )
    if not re.fullmatch(r"[0-9a-f]{64}", artifact.build_proof_digest or ""):
        raise ContractIdentityMismatch("artifact has no valid BuildProof digest")
    return variant, target


def build_artifact_from_proof(
    proof: BuildProof,
    contract: BoardContract,
) -> BuildArtifact:
    """Verify BuildProof evidence and bridge it into the additive artifact model."""
    if not isinstance(proof, BuildProof):
        raise ContractIdentityMismatch("artifact creation requires a typed BuildProof")
    if not isinstance(contract, BoardContract):
        raise ContractIdentityMismatch("artifact creation requires a typed BoardContract")
    expected = (
        ("board_id", contract.board_id),
        ("contract_digest", contract.contract_digest),
        ("klipper_commit", contract.upstream.validated_commit),
    )
    for field, value in expected:
        if getattr(proof, field) != value:
            raise ContractIdentityMismatch(
                f"BuildProof {field}={getattr(proof, field)!r} does not match {value!r}"
            )
    variant = contract.variant(proof.hardware_variant_id)
    if variant is None:
        raise ContractIdentityMismatch("BuildProof hardware variant is not in the contract")
    target = variant.target(proof.build_target_id)
    if target is None:
        raise ContractIdentityMismatch("BuildProof build target is not in the variant")
    if not (
        proof.olddefconfig.ok
        and proof.requested_selections.ok
        and proof.resolved_assertions.ok
        and proof.build.ok
    ):
        raise ContractArtifactError("BuildProof does not record a successful verified build")

    evidence = (
        (Path(proof.requested_config_path), proof.requested_config_sha256, None),
        (Path(proof.resolved_config_path), proof.resolved_config_sha256, None),
        (Path(proof.artifact_path), proof.artifact_sha256, proof.artifact_size),
    )
    for path, expected_hash, expected_size in evidence:
        if not path.is_file():
            raise ContractArtifactError(f"BuildProof evidence is absent: {path}")
        observed_hash = _sha256_file(path)
        if observed_hash != expected_hash:
            raise ContractArtifactError(f"BuildProof evidence hash changed: {path}")
        if expected_size is not None and path.stat().st_size != expected_size:
            raise ContractArtifactError("BuildProof artifact size changed")

    artifact_path = Path(proof.artifact_path)
    if artifact_path.name != target.artifact.native_filename:
        raise ContractArtifactError("BuildProof native filename violates ArtifactPolicy")
    resolved_config = Path(proof.resolved_config_path).read_text(encoding="utf-8")
    proof_digest = proof.digest
    if not re.fullmatch(r"[0-9a-f]{32}", proof.build_id or ""):
        raise ContractArtifactError("BuildProof has no valid embedded firmware build ID")
    expected_fingerprint = f"kace-b1-{proof.build_id}"
    if proof.firmware_fingerprint != expected_fingerprint:
        raise ContractArtifactError(
            "BuildProof firmware fingerprint does not match its embedded build ID"
        )
    if proof.embedded_fingerprint_verified is not True:
        raise ContractArtifactError(
            "BuildProof did not verify the fingerprint inside the native artifact"
        )
    if not artifact_contains_firmware_fingerprint(
        artifact_path.read_bytes(), proof.firmware_fingerprint
    ):
        raise ContractArtifactError(
            "BuildProof artifact no longer contains its firmware fingerprint"
        )
    if not any(
        item == f"KLIPPER_VERSION={proof.firmware_fingerprint}"
        for attempt in proof.build_attempts
        for item in attempt.argv
    ):
        raise ContractArtifactError(
            "BuildProof does not prove that its firmware fingerprint was compiled"
        )
    identity = FirmwareBuildInputs.create(
        klipper_commit=proof.klipper_commit,
        canonical_config=resolved_config,
        toolchain=proof.toolchain,
        build_options={
            "requested_flags": list(proof.requested_flags),
            "effective_flags": list(proof.effective_flags),
            "lto_requested": proof.lto_requested,
            "lto_effective": proof.lto_effective,
            "fallback_used": proof.fallback_used,
            "fallback_reason": proof.fallback_reason,
        },
        build_id=proof.build_id,
    ).complete(
        artifact_sha256=proof.artifact_sha256,
        artifact_size=proof.artifact_size,
        artifact_format=_FORMAT_MAP[target.artifact.format].value,
    )
    return BuildArtifact(
        build_id=proof_digest[:32],
        path=str(artifact_path.resolve()),
        native_filename=target.artifact.native_filename,
        format=_FORMAT_MAP[target.artifact.format],
        sha256=proof.artifact_sha256,
        size_bytes=proof.artifact_size,
        mcu=variant.processor.resolved_mcu,
        firmware_fingerprint=identity.reported_version,
        provenance=BuildProvenance.REAL,
        # Keep every BoardContract artifact out of legacy physical execution
        # until runtime authority is migrated explicitly.
        flashable=False,
        firmware_identity=identity,
        board_id=contract.board_id,
        hardware_variant_id=variant.id,
        build_target_id=target.id,
        board_contract_digest=contract.contract_digest,
        klipper_commit=contract.upstream.validated_commit,
        build_proof_digest=proof_digest,
    )


def _final_filename(target: BuildTarget, artifact: BuildArtifact) -> str:
    policy = target.artifact.final_filename
    strategy = policy["strategy"]
    if strategy == "fixed":
        filename = str(policy["value"])
    elif strategy == "native":
        filename = artifact.native_filename
    elif strategy == "build-id":
        filename = str(policy["template"]).replace(
            "{build_id_short}", artifact.build_id[:12]
        )
    else:  # guarded by the BoardContract loader
        raise FilenamePolicyError(f"unsupported filename strategy {strategy!r}")
    if not filename or Path(filename).name != filename or filename in {".", ".."}:
        raise FilenamePolicyError("final firmware filename must be a safe basename")
    if "{" in filename or "}" in filename:
        raise FilenamePolicyError("final firmware filename contains an unresolved template")
    required_suffix = str(policy.get("required_suffix") or "")
    if required_suffix and not filename.lower().endswith(required_suffix.lower()):
        raise FilenamePolicyError(
            f"final filename {filename!r} must end in {required_suffix!r}"
        )
    return filename


def _copy_artifact_bytes(source: Path, destination: Path) -> None:
    shutil.copyfile(source, destination)


def apply_artifact_policy(
    contract: BoardContract,
    artifact: BuildArtifact,
    *,
    output_directory: str,
    last_successful_filename: Optional[str] = None,
) -> tuple[BuildTarget, ArtifactTransformation]:
    _variant, target = _require_contract_identity(contract, artifact)
    source = Path(artifact.path)
    if not source.is_file():
        raise ContractArtifactError(f"native artifact is absent: {source}")
    if source.name != artifact.native_filename:
        raise ContractArtifactError("artifact path and native filename disagree")
    if artifact.native_filename != target.artifact.native_filename:
        raise ContractArtifactError("native filename does not match ArtifactPolicy")
    if artifact.format is not _FORMAT_MAP[target.artifact.format]:
        raise ContractArtifactError("artifact format does not match ArtifactPolicy")
    suffix = _FORMAT_SUFFIX[target.artifact.format]
    if not artifact.native_filename.lower().endswith(suffix):
        raise ContractArtifactError("native artifact extension is incompatible")
    native_hash = _sha256_file(source)
    if native_hash != artifact.sha256:
        raise ContractArtifactError("native artifact hash no longer matches BuildArtifact")
    if source.stat().st_size != artifact.size_bytes:
        raise ContractArtifactError("native artifact size no longer matches BuildArtifact")

    filename = _final_filename(target, artifact)
    policy = target.artifact.final_filename
    if policy.get("must_differ_from_last_successful_flash"):
        previous = str(last_successful_filename or "")
        if previous and previous.casefold() == filename.casefold():
            raise FilenamePolicyError(
                "final filename must differ from the last successful flash"
            )

    output_root = Path(output_directory).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    prepared_directory = (
        output_root / f"{contract.board_id}-{artifact.build_proof_digest[:12]}"
    )
    prepared_directory.mkdir(parents=False, exist_ok=True)
    final_path = prepared_directory / filename
    temporary = prepared_directory / f".{filename}.part"
    try:
        _copy_artifact_bytes(source, temporary)
        final_hash = _sha256_file(temporary)
        if final_hash != native_hash:
            raise ContractArtifactError(
                "ArtifactPolicy transformation changed content during rename-only preparation"
            )
        os.replace(temporary, final_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    final_hash = _sha256_file(final_path)
    if final_hash != native_hash:
        raise ContractArtifactError("prepared artifact hash differs from native artifact")
    return target, ArtifactTransformation(
        kind=ArtifactTransformationKind.RENAME_ONLY,
        native_path=str(source.resolve()),
        native_filename=artifact.native_filename,
        native_sha256=native_hash,
        final_path=str(final_path),
        final_filename=filename,
        final_sha256=final_hash,
        size_bytes=artifact.size_bytes,
        content_changed=False,
    )


def _typed_steps(target: BuildTarget) -> tuple[DeploymentStep, ...]:
    try:
        ids = tuple(DeploymentStepId(item) for item in target.flash.steps)
    except ValueError as exc:
        raise ContractDeploymentError(
            "contract flash recipe contains a non-Phase-3 deployment step"
        ) from exc
    expected = {
        FlashStrategy.SD_CARD: _SD_STEPS,
        FlashStrategy.RP2040_BOOTSEL: _BOOTSEL_STEPS,
    }.get(target.flash.strategy)
    if expected is None or ids != expected:
        raise ContractDeploymentError(
            f"contract has no exact non-executing plan for {target.flash.strategy.value}"
        )
    return tuple(DeploymentStep(item, index) for index, item in enumerate(ids, 1))


def _plan_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def deployment_plan_payload(plan: DeploymentPlan) -> dict[str, Any]:
    """Reconstruct the exact canonical payload signed by ``plan_digest``."""
    if not isinstance(plan, DeploymentPlan):
        raise ContractIdentityMismatch(
            "contract deployment requires a typed BoardContract DeploymentPlan"
        )
    return {
        "schema": plan.schema,
        "board_id": plan.board_id,
        "hardware_variant_id": plan.hardware_variant_id,
        "build_target_id": plan.build_target_id,
        "board_contract_digest": plan.board_contract_digest,
        "klipper_commit": plan.klipper_commit,
        "build_proof_digest": plan.build_proof_digest,
        "strategy": plan.strategy.value,
        "artifact_sha256": plan.artifact.sha256,
        "transformation": asdict(plan.transformation),
        "steps": [step.id.value for step in plan.steps],
        "warnings": list(plan.warnings),
    }


def compute_deployment_plan_digest(plan: DeploymentPlan) -> str:
    return _plan_digest(deployment_plan_payload(plan))


def validate_deployment_plan(
    contract: BoardContract,
    plan: DeploymentPlan,
) -> BuildTarget:
    """Pure, strict validation used immediately before physical execution."""
    if not isinstance(contract, BoardContract):
        raise ContractIdentityMismatch("executor contract must be a typed BoardContract")
    if not isinstance(plan, DeploymentPlan):
        raise ContractIdentityMismatch(
            "executor accepts only a typed BoardContract DeploymentPlan"
        )
    expected_identity = {
        "board_id": contract.board_id,
        "board_contract_digest": contract.contract_digest,
        "klipper_commit": contract.upstream.validated_commit,
    }
    for field, expected in expected_identity.items():
        observed = getattr(plan, field, "")
        if observed != expected:
            raise ContractIdentityMismatch(
                f"plan {field}={observed!r} does not match {expected!r}"
            )
    variant = contract.variant(plan.hardware_variant_id)
    if variant is None:
        raise ContractIdentityMismatch("plan hardware variant is not in the contract")
    target = variant.target(plan.build_target_id)
    if target is None:
        raise ContractIdentityMismatch("plan build target is not in the variant")
    if plan.strategy is not target.flash.strategy:
        raise ContractIdentityMismatch("plan strategy differs from FlashRecipe")
    if plan.steps != _typed_steps(target):
        raise ContractIdentityMismatch("plan steps differ from FlashRecipe")
    if plan.warnings != tuple(warning.text for warning in contract.warnings):
        raise ContractIdentityMismatch("plan warnings differ from the contract")

    artifact = plan.artifact
    artifact_variant, artifact_target = _require_contract_identity(contract, artifact)
    if artifact_variant.id != variant.id or artifact_target.id != target.id:
        raise ContractIdentityMismatch("plan and artifact target identities differ")
    if artifact.build_proof_digest != plan.build_proof_digest:
        raise ContractIdentityMismatch("plan and artifact BuildProof digests differ")
    identity = artifact.firmware_identity
    if identity is None:
        raise ContractIdentityMismatch("contract artifact has no firmware identity")
    if identity.klipper_commit != plan.klipper_commit:
        raise ContractIdentityMismatch("firmware identity has a different Klipper commit")
    if identity.artifact_sha256 != artifact.sha256:
        raise ContractIdentityMismatch("firmware identity has a different artifact hash")
    if identity.artifact_size != artifact.size_bytes:
        raise ContractIdentityMismatch("firmware identity has a different artifact size")

    transformation = plan.transformation
    if transformation.kind is not ArtifactTransformationKind.RENAME_ONLY:
        raise ContractIdentityMismatch("physical SD execution permits rename-only artifacts")
    expected_filename = _final_filename(target, artifact)
    if transformation.final_filename != expected_filename:
        raise FilenamePolicyError("plan final filename differs from ArtifactPolicy")
    if Path(transformation.final_path).name != expected_filename:
        raise FilenamePolicyError("plan staged path filename differs from ArtifactPolicy")
    if transformation.native_filename != artifact.native_filename:
        raise ContractIdentityMismatch("plan native filename differs from BuildArtifact")
    if transformation.native_path != str(Path(artifact.path).resolve()):
        raise ContractIdentityMismatch("plan native path differs from BuildArtifact")
    if transformation.native_sha256 != artifact.sha256:
        raise ContractIdentityMismatch("plan native hash differs from BuildArtifact")
    if transformation.final_sha256 != artifact.sha256:
        raise ContractIdentityMismatch("plan staged hash differs from BuildArtifact")
    if transformation.size_bytes != artifact.size_bytes:
        raise ContractIdentityMismatch("plan staged size differs from BuildArtifact")
    if transformation.content_changed:
        raise ContractIdentityMismatch("rename-only plan records changed content")

    computed = compute_deployment_plan_digest(plan)
    if plan.plan_digest != computed:
        raise ContractIdentityMismatch("DeploymentPlan digest is invalid")
    if plan.deployment_id != f"board-contract-{computed[:24]}":
        raise ContractIdentityMismatch("DeploymentPlan ID is not derived from its digest")
    return target


def create_deployment_plan(
    contract: BoardContract,
    artifact: BuildArtifact,
    *,
    output_directory: str,
    last_successful_filename: Optional[str] = None,
) -> DeploymentPlan:
    """Apply policy and return evidence only; no deployment step is executed."""
    target, transformation = apply_artifact_policy(
        contract,
        artifact,
        output_directory=output_directory,
        last_successful_filename=last_successful_filename,
    )
    steps = _typed_steps(target)
    draft = DeploymentPlan(
        schema="kace-board-deployment-plan/v1",
        deployment_id="",
        board_id=contract.board_id,
        hardware_variant_id=artifact.hardware_variant_id,
        build_target_id=artifact.build_target_id,
        board_contract_digest=contract.contract_digest,
        klipper_commit=contract.upstream.validated_commit,
        build_proof_digest=artifact.build_proof_digest,
        strategy=target.flash.strategy,
        artifact=artifact,
        transformation=transformation,
        steps=steps,
        warnings=tuple(warning.text for warning in contract.warnings),
        plan_digest="",
    )
    digest = compute_deployment_plan_digest(draft)
    return DeploymentPlan(
        **{
            **draft.__dict__,
            "deployment_id": f"board-contract-{digest[:24]}",
            "plan_digest": digest,
        }
    )
