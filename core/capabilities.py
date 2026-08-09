"""Authoritative KACE capability and configuration validation rules.

The wizard and generator intentionally consume the same rules from this
module.  UI validators may provide friendlier messages, but they must not
accept a value that this boundary rejects.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

from core.exceptions import GenerationError


SUPPORTED_KINEMATICS = ("cartesian", "corexy")
SUPPORTED_PROBE_KINDS = ("none", "bltouch", "cr_touch", "inductive", "custom")
SUPPORTED_DISPLAY_PREFIXES = ("recommended", "manual", "override")


@dataclass(frozen=True)
class NumericRule:
    minimum: float
    maximum: float
    integer: bool = False
    minimum_inclusive: bool = True


NUMERIC_RULES = {
    "x_size": NumericRule(1.0, 2000.0),
    "y_size": NumericRule(1.0, 2000.0),
    "z_size": NumericRule(1.0, 2000.0),
    "x_position_min": NumericRule(-2000.0, 2000.0),
    "x_position_max": NumericRule(-2000.0, 2000.0),
    "x_position_endstop": NumericRule(-2000.0, 2000.0),
    "y_position_min": NumericRule(-2000.0, 2000.0),
    "y_position_max": NumericRule(-2000.0, 2000.0),
    "y_position_endstop": NumericRule(-2000.0, 2000.0),
    "z_position_min": NumericRule(-2000.0, 2000.0),
    "z_position_max": NumericRule(-2000.0, 2000.0),
    "z_position_endstop": NumericRule(-2000.0, 2000.0),
    "printable_x_min": NumericRule(-2000.0, 2000.0),
    "printable_x_max": NumericRule(-2000.0, 2000.0),
    "printable_y_min": NumericRule(-2000.0, 2000.0),
    "printable_y_max": NumericRule(-2000.0, 2000.0),
    "printable_z_max": NumericRule(0.0, 2000.0, minimum_inclusive=False),
    "probe_x_offset": NumericRule(-1000.0, 1000.0),
    "probe_y_offset": NumericRule(-1000.0, 1000.0),
    "max_velocity": NumericRule(0.0, 2000.0, minimum_inclusive=False),
    "max_accel": NumericRule(0.0, 200000.0, minimum_inclusive=False),
    "max_z_velocity": NumericRule(0.0, 1000.0, minimum_inclusive=False),
    "max_z_accel": NumericRule(0.0, 100000.0, minimum_inclusive=False),
    "nozzle_diameter": NumericRule(0.05, 10.0),
    "filament_diameter": NumericRule(0.1, 10.0),
}

_DISPLAY_KEY_RE = re.compile(r"^[a-z0-9_]+$")


def supported_kinematics() -> tuple[str, ...]:
    return SUPPORTED_KINEMATICS


def validate_kinematics(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in SUPPORTED_KINEMATICS:
        expected = ", ".join(SUPPORTED_KINEMATICS)
        raise GenerationError(
            f"kinematics must be one of [{expected}]; received {normalized or 'empty'}."
        )
    return normalized


def finite_number(
    field: str,
    value: object,
    *,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
    integer: bool = False,
    minimum_inclusive: bool = True,
) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise GenerationError(f"{field} must be a finite number; received {value!r}.") from None
    if not math.isfinite(number):
        raise GenerationError(f"{field} must be finite; received {value!r}.")
    if integer and not number.is_integer():
        raise GenerationError(f"{field} must be an integer; received {value!r}.")
    if minimum is not None:
        invalid = number < minimum if minimum_inclusive else number <= minimum
        if invalid:
            operator = ">=" if minimum_inclusive else ">"
            raise GenerationError(f"{field} must be {operator} {minimum:g}; received {number:g}.")
    if maximum is not None and number > maximum:
        raise GenerationError(f"{field} must be <= {maximum:g}; received {number:g}.")
    return number


def validate_sensor_type(field: str, value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise GenerationError(f"{field} must be a non-empty Klipper sensor_type.")
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise GenerationError(f"{field} contains a control character.")
    return text


def validate_probe_kind(value: object) -> str:
    from core.probe_configuration import normalize_probe_kind

    raw = str(value or "")
    normalized = normalize_probe_kind(raw)
    known_labels = {"None", "BLTouch", "CR-Touch", "Inductive", "Custom Probe"}
    if raw not in SUPPORTED_PROBE_KINDS and raw not in known_labels:
        expected = ", ".join(SUPPORTED_PROBE_KINDS)
        raise GenerationError(f"probe must be one of [{expected}]; received {raw or 'empty'}.")
    return normalized


def validate_optional_boolean(field: str, value: object) -> object:
    """Normalize a Klipper boolean while preserving an omitted profile value."""
    if value in (None, ""):
        return value
    if isinstance(value, bool):
        return "True" if value else "False"
    text = str(value).strip().lower()
    if text not in ("true", "false"):
        raise GenerationError(f"{field} must be true or false; received {value!r}.")
    return "True" if text == "true" else "False"


def validate_display_selection(user_data: Mapping[str, object], parsed_data: Mapping[str, object]) -> None:
    choice = user_data.get("display_choice")
    if choice in (None, "none"):
        return
    text = str(choice)
    if text.startswith("__") or ":" not in text:
        raise GenerationError(f"display_choice has an invalid workflow value: {text!r}.")
    prefix, key = text.split(":", 1)
    if prefix not in SUPPORTED_DISPLAY_PREFIXES or not _DISPLAY_KEY_RE.fullmatch(key):
        raise GenerationError(f"display_choice has an unsupported renderer: {text!r}.")
    selected_section = user_data.get("display_section")
    if selected_section not in (None, "", key):
        raise GenerationError(
            f"display_section ({selected_section!r}) conflicts with display_choice ({key!r})."
        )
    from core.display_checker import classify_hardware_combination
    hardware = classify_hardware_combination(
        key,
        str(user_data.get("board") or ""),
        dict(parsed_data),
    )
    compatibility = hardware.get("compatibility_class", "experimental")
    if compatibility == "unsafe" and user_data.get("display_risk_accepted") is not True:
        raise GenerationError("Unsafe display selection requires explicit risk acceptance.")
    fields = parsed_data.get(key)
    if compatibility not in ("unsafe", "compatible_with_adapter") and not isinstance(fields, dict):
        raise GenerationError(
            f"Display [{key}] has no complete profile section; KACE cannot render it safely."
        )


def _rule_for_field(field: str) -> Optional[NumericRule]:
    if field in NUMERIC_RULES:
        return NUMERIC_RULES[field]
    if field.startswith("microsteps_"):
        return NumericRule(1.0, 256.0, integer=True)
    if field.startswith("rotation_distance_"):
        return NumericRule(0.0, 2000.0, minimum_inclusive=False)
    if field.startswith(("run_current_", "hold_current_")):
        return NumericRule(0.0, 20.0, minimum_inclusive=False)
    if field.startswith(("hotend_pid_", "bed_pid_")):
        return NumericRule(0.0, 1000000.0)
    if field.startswith(("hotend_min_temp", "hotend_max_temp", "bed_min_temp", "bed_max_temp")):
        return NumericRule(-273.15, 2000.0)
    if field.startswith("homing_speed_"):
        return NumericRule(0.0, 2000.0, minimum_inclusive=False)
    return None


def normalize_and_validate_configuration(user_data: dict) -> None:
    """Normalize derived geometry and enforce the shared generation contract."""
    user_data["kinematics"] = validate_kinematics(user_data.get("kinematics"))
    validate_probe_kind(user_data.get("probe_kind") or user_data.get("probe") or "none")
    user_data["hotend_thermistor"] = validate_sensor_type(
        "hotend_thermistor", user_data.get("hotend_thermistor")
    )
    user_data["bed_thermistor"] = validate_sensor_type(
        "bed_thermistor", user_data.get("bed_thermistor")
    )
    for axis in ("x", "y", "z"):
        field = f"homing_positive_dir_{axis}"
        if field in user_data:
            user_data[field] = validate_optional_boolean(field, user_data[field])

    for field, value in tuple(user_data.items()):
        if value in (None, ""):
            continue
        rule = _rule_for_field(field)
        if rule is not None:
            finite_number(
                field,
                value,
                minimum=rule.minimum,
                maximum=rule.maximum,
                integer=rule.integer,
                minimum_inclusive=rule.minimum_inclusive,
            )

    uses_probe = bool(user_data.get("probe_uses_virtual_z_endstop"))
    axes = {}
    for axis, size_default in (("x", 235.0), ("y", 235.0), ("z", 250.0)):
        size = finite_number(
            f"{axis}_size", user_data.get(f"{axis}_size", size_default), minimum=1.0, maximum=2000.0
        )
        minimum = finite_number(
            f"{axis}_position_min", user_data.get(f"{axis}_position_min", 0.0), minimum=-2000.0, maximum=2000.0
        )
        maximum = finite_number(
            f"{axis}_position_max", user_data.get(f"{axis}_position_max", size), minimum=-2000.0, maximum=2000.0
        )
        if minimum >= maximum:
            raise GenerationError(
                f"{axis}_position_min ({minimum:g}) must be less than {axis}_position_max ({maximum:g})."
            )
        endstop = finite_number(
            f"{axis}_position_endstop", user_data.get(f"{axis}_position_endstop", 0.0), minimum=-2000.0, maximum=2000.0
        )
        if not (axis == "z" and uses_probe) and not minimum <= endstop <= maximum:
            raise GenerationError(
                f"{axis}_position_endstop ({endstop:g}) must be within mechanical limits "
                f"[{minimum:g}, {maximum:g}]."
            )
        axes[axis] = (size, minimum, maximum)

    x_size, x_min, x_max = axes["x"]
    y_size, y_min, y_max = axes["y"]
    _, z_min, z_max = axes["z"]

    printable_x_min = finite_number(
        "printable_x_min",
        user_data.get("printable_x_min", x_min if x_min > 0.0 else 0.0),
        minimum=-2000.0,
        maximum=2000.0,
    )
    printable_x_max = finite_number(
        "printable_x_max", user_data.get("printable_x_max", x_size), minimum=-2000.0, maximum=2000.0
    )
    printable_y_min = finite_number(
        "printable_y_min",
        user_data.get("printable_y_min", y_min if y_min > 0.0 else 0.0),
        minimum=-2000.0,
        maximum=2000.0,
    )
    printable_y_max = finite_number(
        "printable_y_max", user_data.get("printable_y_max", y_size), minimum=-2000.0, maximum=2000.0
    )
    printable_z_max = finite_number(
        "printable_z_max", user_data.get("printable_z_max", user_data.get("z_size", z_max)), minimum=0.0,
        maximum=2000.0, minimum_inclusive=False,
    )

    for axis, printable_min, printable_max, travel_min, travel_max in (
        ("x", printable_x_min, printable_x_max, x_min, x_max),
        ("y", printable_y_min, printable_y_max, y_min, y_max),
    ):
        if printable_min >= printable_max:
            raise GenerationError(
                f"printable_{axis}_min ({printable_min:g}) must be less than "
                f"printable_{axis}_max ({printable_max:g})."
            )
        if printable_min < travel_min or printable_max > travel_max:
            raise GenerationError(
                f"Printable {axis.upper()} boundary [{printable_min:g}, {printable_max:g}] is outside "
                f"physical {axis.upper()} travel limits [{travel_min:g}, {travel_max:g}]."
            )
    if not z_min < printable_z_max <= z_max:
        raise GenerationError(
            f"printable_z_max ({printable_z_max:g}) must be within Z travel "
            f"({z_min:g}, {z_max:g}]."
        )

    user_data["printable_x_min"] = f"{printable_x_min:g}"
    user_data["printable_x_max"] = f"{printable_x_max:g}"
    user_data["printable_y_min"] = f"{printable_y_min:g}"
    user_data["printable_y_max"] = f"{printable_y_max:g}"
    user_data["printable_z_max"] = f"{printable_z_max:g}"
    user_data["printable_center_x"] = f"{(printable_x_min + printable_x_max) / 2:g}"
    user_data["printable_center_y"] = f"{(printable_y_min + printable_y_max) / 2:g}"


def supported_firmware_architectures() -> tuple[str, ...]:
    from firmware.derivation import _get_fw_db

    return tuple(dict.fromkeys(str(entry.get("arch")) for entry in _get_fw_db() if entry.get("arch")))


def supported_firmware_processors() -> tuple[str, ...]:
    from firmware.derivation import _get_fw_db

    return tuple(dict.fromkeys(str(entry.get("pattern")) for entry in _get_fw_db() if entry.get("pattern")))


def validate_firmware_architecture(value: object) -> str:
    text = str(value or "").strip().lower()
    supported = supported_firmware_architectures()
    if text not in supported:
        raise ValueError(f"Unsupported firmware architecture {text!r}; expected one of {supported}.")
    return text


def validate_firmware_processor(value: object) -> str:
    text = str(value or "").strip().lower()
    if not text or not any(pattern in text for pattern in supported_firmware_processors()):
        raise ValueError(f"Unsupported firmware processor {text!r}.")
    return text
