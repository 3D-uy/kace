"""Explicit, reviewable support promotion evidence.

Creating a request never edits the BoardContract catalog.  A maintainer must
review the referenced immutable DeploymentProof and change YAML separately.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Optional

from .catalog import BoardCatalog, load_default_catalog
from .executor import ContractDeploymentState, DeploymentProof
from .models import SupportStatus


class DeploymentPromotionError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


@dataclass(frozen=True)
class DeploymentPromotionRequest:
    schema: str
    request_id: str
    created_at: str
    review_required: bool
    source_status: SupportStatus
    requested_status: SupportStatus
    deployment_proof_digest: str
    deployment_id: str
    plan_digest: str
    board_id: str
    hardware_variant_id: str
    build_target_id: str
    board_contract_digest: str
    klipper_commit: str
    build_proof_digest: str
    artifact_staged_hash: str
    observed_fingerprint: str

    def to_mapping(self, *, include_digest: bool = False) -> dict[str, Any]:
        data = asdict(self)
        data["source_status"] = self.source_status.value
        data["requested_status"] = self.requested_status.value
        if include_digest:
            data["request_digest"] = self.digest
        return data

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.to_mapping(), sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def create_deployment_promotion_request(
    proof: DeploymentProof,
    *,
    catalog: Optional[BoardCatalog] = None,
) -> DeploymentPromotionRequest:
    if not isinstance(proof, DeploymentProof):
        raise DeploymentPromotionError("promotion requires a typed DeploymentProof")
    if proof.final_state is not ContractDeploymentState.VERIFIED:
        raise DeploymentPromotionError("only a VERIFIED physical deployment can be promoted")
    active = catalog or load_default_catalog()
    contract = active.by_id(proof.board_id)
    if contract is None or contract.contract_digest != proof.board_contract_digest:
        raise DeploymentPromotionError("DeploymentProof does not match the current contract")
    if contract.upstream.validated_commit != proof.klipper_commit:
        raise DeploymentPromotionError("DeploymentProof Klipper commit is not current")
    variant = contract.variant(proof.hardware_variant_id)
    target = variant.target(proof.build_target_id) if variant else None
    if target is None:
        raise DeploymentPromotionError("DeploymentProof target is absent from the contract")
    if target.support_status not in {
        SupportStatus.RUNTIME_SUPPORTED,
        SupportStatus.DEPLOYMENT_VERIFIED,
    }:
        raise DeploymentPromotionError(
            f"target status {target.support_status.value} is not eligible for promotion"
        )
    request_id = f"promote-{proof.deployment_id}-{proof.digest[:12]}"
    return DeploymentPromotionRequest(
        schema="kace-board-deployment-promotion/v1",
        request_id=request_id,
        created_at=_now(),
        review_required=True,
        source_status=target.support_status,
        requested_status=SupportStatus.DEPLOYMENT_VERIFIED,
        deployment_proof_digest=proof.digest,
        deployment_id=proof.deployment_id,
        plan_digest=proof.plan_digest,
        board_id=proof.board_id,
        hardware_variant_id=proof.hardware_variant_id,
        build_target_id=proof.build_target_id,
        board_contract_digest=proof.board_contract_digest,
        klipper_commit=proof.klipper_commit,
        build_proof_digest=proof.build_proof_digest,
        artifact_staged_hash=proof.artifact_staged_hash,
        observed_fingerprint=proof.observed_fingerprint,
    )


def write_deployment_promotion_request(
    request: DeploymentPromotionRequest, output_directory: str
) -> str:
    if not isinstance(request, DeploymentPromotionRequest):
        raise TypeError("only a typed DeploymentPromotionRequest can be persisted")
    root = Path(output_directory).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{request.request_id}.json"
    temporary = root / f".{request.request_id}.json.part"
    content = json.dumps(
        request.to_mapping(include_digest=True), sort_keys=True, indent=2,
        ensure_ascii=False, allow_nan=False,
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
