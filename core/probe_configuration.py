"""Typed probe strategies used by configuration generation.

The wizard and older callers still exchange a ``user_data`` dictionary.  This
module is the compatibility boundary: it maps legacy labels once, exposes a
small stable strategy interface to the generator, and keeps custom raw text
separate from structured KACE-owned probe sections.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from configparser import ConfigParser
from typing import Optional, Protocol, runtime_checkable

from core.custom_probe import CustomProbeConfig
from core.exceptions import GenerationError


PROBE_KIND_NONE = "none"
PROBE_KIND_BLTOUCH = "bltouch"
PROBE_KIND_CR_TOUCH = "cr_touch"
PROBE_KIND_INDUCTIVE = "inductive"
PROBE_KIND_CUSTOM = "custom"

# Preserve explicit device behavior; omitted flags belong to Klipper's defaults.
# A parsed boolean is not evidence that a particular physical probe needs it.
BLTOUCH_BOOLEAN_OPTIONS = (
    "pin_up_touch_mode_reports_triggered", "probe_with_touch_mode",
    "pin_up_reports_not_triggered", "stow_on_each_sample",
)


def is_probe_virtual_endstop(token: str) -> bool:
    """Identify the probe dependency using Klipper's chip/pin whitespace rule.

    This identifies the resource, not the legality of pin modifiers or wiring.
    Reuse the pin splitter so generation, review and guidance agree.
    """
    from core.pin_validator import PinAliases
    return PinAliases.split_pin(token) == ("probe", "z_virtual_endstop")


def _bltouch_boolean(option: str, value: object) -> bool:
    token = str(value).strip().lower()
    if token not in ConfigParser.BOOLEAN_STATES:
        raise GenerationError(f"[bltouch] {option}: invalid boolean {value!r}.")
    return ConfigParser.BOOLEAN_STATES[token]


def validate_bltouch_flags(sections: Mapping) -> None:
    """Validate flags in the rendered/effective configuration, including includes."""
    options = sections.get("bltouch", {})
    for option in BLTOUCH_BOOLEAN_OPTIONS:
        if option in options:
            _bltouch_boolean(option, options[option])


def selected_bltouch_flags(board: Mapping, user: dict) -> dict:
    """Resolve explicit probe flags independently from board-owned wiring.

    Both a board config and a printer profile may define probe behavior. A
    disagreement requires resolution instead of silently changing a safety
    check. No values are inferred from BLTouch/CR-Touch names or clone labels.
    """
    selected = {}
    for source, config in (("board", board), ("printer_profile", user.get("_profile_parsed"))):
        if not isinstance(config, Mapping):
            continue
        for option in BLTOUCH_BOOLEAN_OPTIONS:
            options = config.get("bltouch", {})
            if option not in options:
                continue
            value = str(_bltouch_boolean(option, options[option]))
            if option in selected and selected[option]["value"] != value:
                raise GenerationError(f"conflicting [bltouch] {option} in board and printer profile.")
            entry = selected.setdefault(option, {"value": value, "sources": []})
            entry["sources"].append(source)
    return selected


BLTOUCH_HARDWARE_SOURCE = "_bltouch_hardware_source"
BLTOUCH_HARDWARE_OPTIONS = ("set_output_mode", "pin_move_time")


def _bltouch_hardware_value(option, value):
    import math
    text = str(value).strip()
    if option == "set_output_mode":
        if text not in ("5V", "OD"):
            raise GenerationError(f"[bltouch] {option}: expected exactly 5V or OD.")
        return text
    try:
        number = float(text)
    except (ValueError, TypeError) as exc:
        raise GenerationError(f"[bltouch] {option}: expected a positive finite duration.") from exc
    if not math.isfinite(number) or number <= 0:
        raise GenerationError(f"[bltouch] {option}: expected a positive finite duration.")
    return str(number)


def validate_bltouch_hardware_options(sections, *, expected=None):
    options = sections.get("bltouch", {})
    for key in BLTOUCH_HARDWARE_OPTIONS:
        if key in options:
            _bltouch_hardware_value(key, options[key])
    for key, entry in (expected or {}).items():
        if key not in options or _bltouch_hardware_value(key, options[key]) != entry["value"]:
            raise GenerationError(f"[bltouch] {key}: selected hardware setting is missing or changed; regenerate before publication.")


def _bltouch_hardware_source(parsed):
    source = parsed.get(BLTOUCH_HARDWARE_SOURCE, parsed.get("bltouch", {}))
    if not isinstance(source, Mapping):
        raise GenerationError("[bltouch] invalid active hardware source; reload the board.")
    return source


def selected_bltouch_hardware_options(board, user, rendered):
    """Keep explicit board hardware settings without transferring voltage to new wiring.

    A printer profile cannot authorize an electrical setting for another board.
    Legacy dictionary inputs are treated as explicit source; parser inputs carry
    active-option evidence so commented examples never activate output voltage.
    """
    source = _bltouch_hardware_source(board)
    selected = {key: {"value": _bltouch_hardware_value(key, source[key]), "sources": ["board"]}
                for key in BLTOUCH_HARDWARE_OPTIONS if key in source}
    profile = user.get("_profile_parsed")
    if isinstance(profile, Mapping):
        profile_source = _bltouch_hardware_source(profile)
        for key in BLTOUCH_HARDWARE_OPTIONS:
            if key not in profile_source:
                continue
            value = _bltouch_hardware_value(key, profile_source[key])
            if key not in selected or selected[key]["value"] != value:
                raise GenerationError(f"[bltouch] {key}: printer profile hardware setting requires agreement with the selected board source.")
            selected[key]["sources"].append("printer_profile")
    if selected:
        # Deliberately require the same source connection. Alias/pin remapping
        # needs electrical review; a syntactically legal GPIO is not that proof.
        for key in ("sensor_pin", "control_pin"):
            original = source.get(key)
            actual = rendered.get("bltouch", {}).get(key)
            if not isinstance(original, str) or not original.strip() or original.strip() != str(actual).strip():
                raise GenerationError(f"[bltouch] {key}: explicit hardware settings cannot move to unreviewed wiring.")
    return selected


def validate_source_bltouch_hardware(board, sections):
    validate_bltouch_hardware_options(sections)
    if board is not None and "bltouch" in sections:
        expected = selected_bltouch_hardware_options(board, {}, sections)
        validate_bltouch_hardware_options(sections, expected=expected)


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
            PROBE_KIND_CR_TOUCH: "bltouch",
            PROBE_KIND_INDUCTIVE: "probe",
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
        if custom_config.primary_section == "dockable_probe":
            raise GenerationError(
                "Dockable Probe requires a Klipper extension that is not part of stock Klipper; "
                "KACE cannot generate it safely without an explicit extension contract."
            )
        if custom_config.z_offset is None:
            raise GenerationError(
                "Custom Probe requires an explicit z_offset because stock Klipper cannot load "
                "a [probe] section without it. Use 0 as the pre-calibration value if needed."
            )
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
