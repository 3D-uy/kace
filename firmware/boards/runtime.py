"""Controlled BoardContract firmware authority for Phase 4A.

This module is the only bridge between the interactive runtime and the
contract build/deployment evidence pipeline.  It deliberately exposes no
flashing API and never reads legacy board firmware metadata.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import os
from pathlib import Path
from typing import Any, Optional, Sequence

from firmware.artifacts import BuildArtifact

from .catalog import BoardCatalog, load_default_catalog, normalize_exact_alias
from .deployment import (
    DeploymentPlan,
    build_artifact_from_proof,
    create_deployment_plan,
)
from .kconfig import BoardContractBuildContext, BoardContractKconfigBuilder, BuildProof
from .models import BoardContract, SupportStatus
from .resolver import BoardResolver, ResolutionStatus


def _runtime_build_progress(message: str) -> None:
    print(message, flush=True)


class FirmwareAuthority(str, Enum):
    BOARD_CONTRACT = "board_contract"
    LEGACY = "legacy"


class BoardContractRuntimeError(RuntimeError):
    """A terminal error for a target whose authority is BoardContract."""


@dataclass(frozen=True)
class FirmwareAuthorityDecision:
    authority: FirmwareAuthority
    board_alias: str
    board_id: str = ""
    hardware_variant_id: str = ""
    build_target_id: str = ""
    support_status: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        identity = (self.board_id, self.hardware_variant_id, self.build_target_id)
        if self.authority is FirmwareAuthority.BOARD_CONTRACT and not all(identity):
            raise ValueError("BoardContract authority requires an exact target identity")
        if self.authority is FirmwareAuthority.LEGACY and any(identity):
            raise ValueError("legacy authority may not carry BoardContract identity")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["authority"] = self.authority.value
        return data


@dataclass(frozen=True)
class BoardContractRuntimeBundle:
    """Verified evidence produced by one exact runtime-supported target."""

    decision: FirmwareAuthorityDecision
    proof: BuildProof
    artifact: BuildArtifact
    deployment_plan: DeploymentPlan

    def __post_init__(self) -> None:
        expected = (
            self.decision.board_id,
            self.decision.hardware_variant_id,
            self.decision.build_target_id,
        )
        for evidence in (self.proof, self.artifact, self.deployment_plan):
            observed = (
                evidence.board_id,
                evidence.hardware_variant_id,
                evidence.build_target_id,
            )
            if observed != expected:
                raise BoardContractRuntimeError(
                    "BuildProof, BuildArtifact and DeploymentPlan do not share "
                    "the selected BoardContract identity"
                )
        if not (
            self.proof.contract_digest
            == self.artifact.board_contract_digest
            == self.deployment_plan.board_contract_digest
        ):
            raise BoardContractRuntimeError("contract digests differ across build evidence")
        if not (
            self.proof.klipper_commit
            == self.artifact.klipper_commit
            == self.deployment_plan.klipper_commit
        ):
            raise BoardContractRuntimeError("Klipper commits differ across build evidence")
        if not (
            self.proof.digest
            == self.artifact.build_proof_digest
            == self.deployment_plan.build_proof_digest
        ):
            raise BoardContractRuntimeError("BuildProof digest differs across build evidence")


def _runtime_targets(contract: BoardContract):
    return tuple(
        (variant, target)
        for variant in contract.hardware_variants
        for target in variant.build_targets
        if target.support_status in {
            SupportStatus.RUNTIME_SUPPORTED,
            SupportStatus.DEPLOYMENT_VERIFIED,
        }
    )


def resolve_firmware_authority(
    board_alias: object,
    *,
    detected_mcu: object = None,
    catalog: Optional[BoardCatalog] = None,
) -> FirmwareAuthorityDecision:
    """Choose exactly one authority without fuzzy matching or inference.

    A target is runtime-supported only after its pinned build, artifact policy,
    non-executing deployment plan and no-fallback integration have been
    verified.  This status does not claim that physical flashing was tested.
    """
    alias = str(board_alias or "")
    active_catalog = catalog or load_default_catalog()
    contract = active_catalog.resolve_exact(alias)
    if contract is None:
        return FirmwareAuthorityDecision(
            FirmwareAuthority.LEGACY,
            alias,
            reason="no exact BoardContract alias",
        )

    candidates = _runtime_targets(contract)
    if not candidates:
        return FirmwareAuthorityDecision(
            FirmwareAuthority.LEGACY,
            alias,
            reason="contract has no runtime-authoritative build target",
        )
    if len(candidates) == 1:
        variant, target = candidates[0]
        reason = "exact alias resolved to the sole runtime-authoritative build target"
    else:
        # Reuse KACE's existing discover_mcu() result.  This is deliberately
        # an exact comparison against contract processor identities: no family
        # inference, substring match, regex, probing, or new evidence source.
        observed_mcu = normalize_exact_alias(detected_mcu)
        if not observed_mcu:
            raise BoardContractRuntimeError(
                f"{contract.board_id} has {len(candidates)} runtime targets and "
                "KACE MCU detection did not identify an exact variant"
            )
        matches = tuple(
            (candidate_variant, candidate_target)
            for candidate_variant, candidate_target in candidates
            if observed_mcu in {
                normalize_exact_alias(candidate_variant.processor.model),
                normalize_exact_alias(candidate_variant.processor.resolved_mcu),
            }
        )
        if len(matches) != 1:
            raise BoardContractRuntimeError(
                f"detected MCU {detected_mcu!r} does not identify exactly one "
                f"runtime variant of {contract.board_id}"
            )
        variant, target = matches[0]
        reason = (
            f"exact alias and existing KACE MCU detection {observed_mcu!r} "
            "resolved one runtime-authoritative build target"
        )
    resolution = BoardResolver(active_catalog).resolve(
        alias,
        hardware_variant_id=variant.id,
        build_target_id=target.id,
    )
    if resolution.status is not ResolutionStatus.RESOLVED:
        raise BoardContractRuntimeError(
            f"runtime target resolution failed: {resolution.status.value}"
        )
    return FirmwareAuthorityDecision(
        FirmwareAuthority.BOARD_CONTRACT,
        alias,
        contract.board_id,
        variant.id,
        target.id,
        target.support_status.value,
        reason,
    )


def record_firmware_authority(
    user_data: dict,
    decision: FirmwareAuthorityDecision,
) -> dict[str, Any]:
    """Record additive internal telemetry; do not alter Studio event schemas."""
    event = {
        "schema": "kace-firmware-authority-event/v1",
        "firmware_authority": decision.authority.value,
        "board_alias": decision.board_alias,
        "board_id": decision.board_id,
        "hardware_variant_id": decision.hardware_variant_id,
        "build_target_id": decision.build_target_id,
        "support_status": decision.support_status,
        "reason": decision.reason,
    }
    user_data["firmware_authority"] = decision.authority.value
    user_data["firmware_authority_decision"] = decision.to_dict()
    user_data["firmware_authority_event"] = event
    user_data.setdefault("firmware_authority_events", []).append(dict(event))
    return event


def record_board_contract_authority_failure(
    user_data: dict,
    board_alias: object,
    error: object,
) -> dict[str, Any]:
    """Make a catalog/authority failure explicit without inventing identity."""
    event = {
        "schema": "kace-firmware-authority-event/v1",
        "firmware_authority": FirmwareAuthority.BOARD_CONTRACT.value,
        "board_alias": str(board_alias or ""),
        "board_id": "",
        "hardware_variant_id": "",
        "build_target_id": "",
        "support_status": SupportStatus.BLOCKED.value,
        "reason": str(error),
    }
    user_data["firmware_authority"] = FirmwareAuthority.BOARD_CONTRACT.value
    user_data["firmware_authority_decision"] = dict(event)
    user_data["firmware_authority_event"] = event
    user_data.setdefault("firmware_authority_events", []).append(dict(event))
    return event


def _argv(value: object, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    if isinstance(value, str):
        # A string is one executable path/name.  It is never shell-split.
        return (value,)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return tuple(str(item) for item in value)
    raise BoardContractRuntimeError("build command must be an argv sequence")


def build_board_contract_runtime(
    decision: FirmwareAuthorityDecision,
    user_data: dict,
    *,
    catalog: Optional[BoardCatalog] = None,
) -> BoardContractRuntimeBundle:
    """Build and plan one target; never execute any deployment step."""
    if decision.authority is not FirmwareAuthority.BOARD_CONTRACT:
        raise BoardContractRuntimeError("runtime build requires BoardContract authority")

    active_catalog = catalog or load_default_catalog()
    contract = active_catalog.by_id(decision.board_id)
    if contract is None:
        raise BoardContractRuntimeError("selected contract disappeared from the catalog")
    variant = contract.variant(decision.hardware_variant_id)
    target = variant.target(decision.build_target_id) if variant else None
    if target is None or target.support_status not in {
        SupportStatus.RUNTIME_SUPPORTED,
        SupportStatus.DEPLOYMENT_VERIFIED,
    }:
        raise BoardContractRuntimeError("selected target is no longer runtime-authoritative")

    output_directory = str(
        user_data.get("board_contract_output_directory")
        or Path("~/kace/board-contract-builds").expanduser()
    )
    plan_directory = str(
        user_data.get("board_contract_plan_directory")
        or Path("~/kace/board-contract-plans").expanduser()
    )
    context = BoardContractBuildContext(
        output_directory=output_directory,
        staging_parent=user_data.get("board_contract_staging_parent"),
        source_checkout=(
            user_data.get("board_contract_source_checkout")
            or os.environ.get("KACE_BOARD_CONTRACT_SOURCE")
        ),
        git_command=_argv(user_data.get("git_command"), ("git",)),
        make_command=_argv(user_data.get("make_command"), ("make",)),
        concurrency=user_data.get("board_contract_build_concurrency"),
        progress_reporter=(
            user_data.get("board_contract_progress_reporter")
            or _runtime_build_progress
        ),
    )
    proof = BoardContractKconfigBuilder(catalog=active_catalog).build(
        contract.board_id,
        decision.hardware_variant_id,
        decision.build_target_id,
        context=context,
    )
    artifact = build_artifact_from_proof(proof, contract)
    plan = create_deployment_plan(
        contract,
        artifact,
        output_directory=plan_directory,
        last_successful_filename=user_data.get("last_successful_firmware_filename"),
    )
    return BoardContractRuntimeBundle(decision, proof, artifact, plan)
