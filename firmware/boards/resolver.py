"""Exact board/variant/target resolution and fail-open shadow comparison."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Optional

from .catalog import BoardCatalog, load_default_catalog, normalize_exact_alias
from .models import BoardContract, BuildTarget, HardwareVariant


class ResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    NOT_FOUND = "NOT_FOUND"
    AMBIGUOUS_VARIANT = "AMBIGUOUS_VARIANT"
    VARIANT_NOT_FOUND = "VARIANT_NOT_FOUND"
    AMBIGUOUS_TARGET = "AMBIGUOUS_TARGET"
    TARGET_NOT_FOUND = "TARGET_NOT_FOUND"


@dataclass(frozen=True)
class ResolutionResult:
    status: ResolutionStatus
    contract: Optional[BoardContract] = None
    variant: Optional[HardwareVariant] = None
    target: Optional[BuildTarget] = None
    candidates: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status is ResolutionStatus.RESOLVED

    @property
    def qualified_target_id(self) -> str:
        if not self.ok or not self.contract or not self.variant or not self.target:
            return ""
        return f"{self.contract.board_id}/{self.variant.id}/{self.target.id}"


class BoardResolver:
    def __init__(self, catalog: Optional[BoardCatalog] = None):
        self.catalog = catalog or load_default_catalog()

    def resolve(
        self,
        alias: object,
        *,
        hardware_variant_id: Optional[str] = None,
        build_target_id: Optional[str] = None,
    ) -> ResolutionResult:
        contract = self.catalog.resolve_exact(alias)
        if contract is None:
            return ResolutionResult(ResolutionStatus.NOT_FOUND)

        if hardware_variant_id is None:
            if len(contract.hardware_variants) != 1:
                return ResolutionResult(
                    ResolutionStatus.AMBIGUOUS_VARIANT,
                    contract=contract,
                    candidates=tuple(item.id for item in contract.hardware_variants),
                )
            variant = contract.hardware_variants[0]
        else:
            variant = contract.variant(hardware_variant_id)
            if variant is None:
                return ResolutionResult(
                    ResolutionStatus.VARIANT_NOT_FOUND,
                    contract=contract,
                    candidates=tuple(item.id for item in contract.hardware_variants),
                )

        if build_target_id is None:
            if len(variant.build_targets) != 1:
                return ResolutionResult(
                    ResolutionStatus.AMBIGUOUS_TARGET,
                    contract=contract,
                    variant=variant,
                    candidates=tuple(item.id for item in variant.build_targets),
                )
            target = variant.build_targets[0]
        else:
            target = variant.target(build_target_id)
            if target is None:
                return ResolutionResult(
                    ResolutionStatus.TARGET_NOT_FOUND,
                    contract=contract,
                    variant=variant,
                    candidates=tuple(item.id for item in variant.build_targets),
                )
        return ResolutionResult(
            ResolutionStatus.RESOLVED,
            contract=contract,
            variant=variant,
            target=target,
        )


class ShadowDivergence(str, Enum):
    AGREES = "AGREES"
    BOARD_NOT_COVERED = "BOARD_NOT_COVERED"
    LEGACY_MCU_UNAVAILABLE = "LEGACY_MCU_UNAVAILABLE"
    MCU_DIVERGENCE = "MCU_DIVERGENCE"
    VARIANT_AMBIGUOUS = "VARIANT_AMBIGUOUS"
    SHADOW_ERROR = "SHADOW_ERROR"


@dataclass(frozen=True)
class ShadowComparison:
    legacy_board: str
    legacy_mcu: str
    board_contract_id: str
    matching_variant_ids: tuple[str, ...]
    divergence: ShadowDivergence
    detail: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["divergence"] = self.divergence.value
        return data


def compare_legacy_resolution(
    legacy_board: object,
    legacy_mcu: object,
    *,
    catalog: Optional[BoardCatalog] = None,
) -> ShadowComparison:
    """Compare a result already chosen by legacy code; never resolve it fuzzily."""
    board_text = str(legacy_board or "")
    mcu_text = str(legacy_mcu or "")
    try:
        active_catalog = catalog or load_default_catalog()
        contract = active_catalog.resolve_exact(board_text)
        if contract is None:
            return ShadowComparison(
                board_text, mcu_text, "", (), ShadowDivergence.BOARD_NOT_COVERED,
                "legacy selection has no exact BoardContract alias",
            )
        if not mcu_text.strip():
            return ShadowComparison(
                board_text, "", contract.board_id, (),
                ShadowDivergence.LEGACY_MCU_UNAVAILABLE,
                "legacy runtime did not provide an MCU identity",
            )
        normalized_mcu = normalize_exact_alias(mcu_text)
        matches = tuple(
            variant.id for variant in contract.hardware_variants
            if normalize_exact_alias(variant.processor.model) == normalized_mcu
            or normalize_exact_alias(variant.processor.resolved_mcu) == normalized_mcu
        )
        if not matches:
            return ShadowComparison(
                board_text, mcu_text, contract.board_id, (),
                ShadowDivergence.MCU_DIVERGENCE,
                "legacy MCU does not exactly equal any declared hardware variant",
            )
        divergence = ShadowDivergence.AGREES
        if len(matches) > 1:
            divergence = ShadowDivergence.VARIANT_AMBIGUOUS
        return ShadowComparison(board_text, mcu_text, contract.board_id, matches, divergence)
    except Exception as exc:  # Shadow mode must never alter the legacy decision.
        return ShadowComparison(
            board_text, mcu_text, "", (), ShadowDivergence.SHADOW_ERROR, str(exc)
        )


def capture_shadow_comparison(user_data: dict, legacy_board: object) -> None:
    """Record diagnostics without raising, prompting, printing, or changing decisions."""
    comparison = compare_legacy_resolution(legacy_board, user_data.get("mcu_type"))
    user_data["board_contract_shadow"] = comparison.to_dict()
