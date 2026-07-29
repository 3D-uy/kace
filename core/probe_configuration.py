"""Typed probe strategies used by configuration generation.

The wizard and older callers still exchange a ``user_data`` dictionary.  This
module is the compatibility boundary: it maps legacy labels once, exposes a
small stable strategy interface to the generator, and keeps custom raw text
separate from structured KACE-owned probe sections.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable

from core.custom_probe import CustomProbeConfig
from core.exceptions import GenerationError


PROBE_KIND_NONE = "none"
PROBE_KIND_BLTOUCH = "bltouch"
PROBE_KIND_CR_TOUCH = "cr_touch"
PROBE_KIND_INDUCTIVE = "inductive"
PROBE_KIND_CUSTOM = "custom"


@dataclass(frozen=True)
class ProbeOffsets:
    """Resolved probe offsets in Klipper's nozzle-relative coordinate system."""

    x: float = 0.0
    y: float = 0.0
    z: Optional[float] = None


@runtime_checkable
class ProbeConfiguration(Protocol):
    """Minimal strategy contract for probe-specific generation behavior."""

    kind: str
    display_name: str
    resolved_offsets: ProbeOffsets
    uses_virtual_z_endstop: bool
    generates_safe_z_home: bool
    generates_bed_mesh: bool
    renders_structured_section: bool
    structured_section_name: Optional[str]

    def render_block(self) -> str:
        """Return verbatim custom content, or an empty string for structured probes."""


@dataclass(frozen=True)
class _BaseProbeConfiguration:
    kind: str
    display_name: str
    resolved_offsets: ProbeOffsets
    uses_virtual_z_endstop: bool
    generates_safe_z_home: bool
    generates_bed_mesh: bool
    renders_structured_section: bool
    structured_section_name: Optional[str] = None

    def render_block(self) -> str:
        return ""


class NoProbeConfiguration(_BaseProbeConfiguration):
    def __init__(self) -> None:
        super().__init__(
            kind=PROBE_KIND_NONE,
            display_name="None",
            resolved_offsets=ProbeOffsets(),
            uses_virtual_z_endstop=False,
            generates_safe_z_home=False,
            generates_bed_mesh=False,
            renders_structured_section=False,
        )


class StructuredProbeConfiguration(_BaseProbeConfiguration):
    """KACE-owned rendering for the existing BLTouch/CR-Touch/inductive paths."""

    def __init__(self, kind: str, display_name: str, offsets: ProbeOffsets) -> None:
        section_names = {
            PROBE_KIND_BLTOUCH: "bltouch",
            PROBE_KIND_CR_TOUCH: "cr-touch",
            PROBE_KIND_INDUCTIVE: "inductive",
        }
        if kind not in section_names:
            raise ValueError(f"Unsupported structured probe kind: {kind}")
        super().__init__(
            kind=kind,
            display_name=display_name,
            resolved_offsets=offsets,
            uses_virtual_z_endstop=True,
            generates_safe_z_home=True,
            generates_bed_mesh=True,
            renders_structured_section=True,
            structured_section_name=section_names[kind],
        )


class CustomRawProbeConfiguration(_BaseProbeConfiguration):
    """Strategy wrapper around a validated ``CustomProbeConfig`` raw block."""

    def __init__(self, custom_config: CustomProbeConfig) -> None:
        if custom_config.requires_offset_prompt:
            raise GenerationError("Custom Probe requires explicit X and Y offsets for safe geometry generation.")
        super().__init__(
            kind=PROBE_KIND_CUSTOM,
            display_name="Custom Probe",
            resolved_offsets=ProbeOffsets(
                x=custom_config.x_offset,
                y=custom_config.y_offset,
                z=custom_config.z_offset,
            ),
            uses_virtual_z_endstop=True,
            generates_safe_z_home=True,
            generates_bed_mesh=True,
            renders_structured_section=False,
        )
        object.__setattr__(self, "custom_config", custom_config)

    def render_block(self) -> str:
        return self.custom_config.config_text


_LEGACY_LABEL_TO_KIND = {
    "None": PROBE_KIND_NONE,
    "BLTouch": PROBE_KIND_BLTOUCH,
    "CR-Touch": PROBE_KIND_CR_TOUCH,
    "Inductive": PROBE_KIND_INDUCTIVE,
    "Custom Probe": PROBE_KIND_CUSTOM,
}

_KIND_TO_DISPLAY_NAME = {
    PROBE_KIND_NONE: "None",
    PROBE_KIND_BLTOUCH: "BLTouch",
    PROBE_KIND_CR_TOUCH: "CR-Touch",
    PROBE_KIND_INDUCTIVE: "Inductive",
    PROBE_KIND_CUSTOM: "Custom Probe",
}


def normalize_probe_kind(value: object) -> str:
    """Map a stable kind or a legacy display label to a stable kind."""
    text = str(value or "")
    if text in _KIND_TO_DISPLAY_NAME:
        return text
    return _LEGACY_LABEL_TO_KIND.get(text, PROBE_KIND_NONE)


def resolve_probe_configuration(user_data: dict) -> ProbeConfiguration:
    """Build the authoritative typed strategy from new or legacy wizard data."""
    kind = normalize_probe_kind(user_data.get("probe_kind") or user_data.get("probe"))
    if kind == PROBE_KIND_NONE:
        return NoProbeConfiguration()
    if kind == PROBE_KIND_CUSTOM:
        custom_config = user_data.get("custom_probe")
        if not isinstance(custom_config, CustomProbeConfig):
            raise GenerationError("Custom Probe selected but no validated custom probe configuration was provided.")
        return CustomRawProbeConfiguration(custom_config)

    offsets = ProbeOffsets(
        x=_float_offset(user_data.get("probe_x_offset"), "probe_x_offset"),
        y=_float_offset(user_data.get("probe_y_offset"), "probe_y_offset"),
    )
    return StructuredProbeConfiguration(kind, _KIND_TO_DISPLAY_NAME[kind], offsets)


def apply_probe_compatibility_context(user_ctx: dict, probe: ProbeConfiguration) -> None:
    """Derive legacy template/context keys once from the typed strategy.

    For custom probes, pre-existing legacy offsets must agree with the validated
    raw block.  Rejecting disagreement prevents mutable ``user_data`` from
    silently drifting away from the authoritative custom configuration.
    """
    if probe.kind == PROBE_KIND_CUSTOM:
        _assert_no_custom_offset_drift(user_ctx, probe)
    user_ctx["probe_kind"] = probe.kind
    user_ctx["probe"] = probe.display_name
    user_ctx["probe_x_offset"] = f"{probe.resolved_offsets.x:g}"
    user_ctx["probe_y_offset"] = f"{probe.resolved_offsets.y:g}"
    user_ctx["probe_uses_virtual_z_endstop"] = probe.uses_virtual_z_endstop
    user_ctx["probe_generates_safe_z_home"] = probe.generates_safe_z_home
    user_ctx["probe_generates_bed_mesh"] = probe.generates_bed_mesh


def _assert_no_custom_offset_drift(user_ctx: dict, probe: ProbeConfiguration) -> None:
    for key, expected in (
        ("probe_x_offset", probe.resolved_offsets.x),
        ("probe_y_offset", probe.resolved_offsets.y),
    ):
        if key not in user_ctx or user_ctx[key] in (None, ""):
            continue
        supplied = _float_offset(user_ctx[key], key)
        if supplied != expected:
            raise GenerationError(
                f"Custom Probe {key} conflicts with the validated custom probe configuration."
            )


def _float_offset(value: object, key: str) -> float:
    try:
        return float(value if value is not None else 0.0)
    except (TypeError, ValueError):
        raise GenerationError(f"Invalid {key} value for probe generation.") from None
