"""Resolve profile-derived Klipper values with explicit provenance."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Optional

from core.exceptions import GenerationError


class ValueProvenance(str, Enum):
    PROFILE = "PROFILE"
    USER_OVERRIDE = "USER_OVERRIDE"
    SAFE_DEFAULT = "SAFE_DEFAULT"
    INFERRED = "INFERRED"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class ProfileField:
    key: str
    section: str
    option: str
    safe_default: Optional[str] = None


FIELDS = (
    ProfileField("kinematics", "printer", "kinematics", "cartesian"),
    ProfileField("max_velocity", "printer", "max_velocity", "300"),
    ProfileField("max_accel", "printer", "max_accel", "3000"),
    ProfileField("max_z_velocity", "printer", "max_z_velocity", "5"),
    ProfileField("max_z_accel", "printer", "max_z_accel", "100"),
    ProfileField("x_size", "stepper_x", "position_max", "235"),
    ProfileField("x_position_min", "stepper_x", "position_min", "0"),
    ProfileField("x_position_max", "stepper_x", "position_max", "235"),
    ProfileField("x_position_endstop", "stepper_x", "position_endstop", "0"),
    ProfileField("microsteps_x", "stepper_x", "microsteps", "16"),
    ProfileField("rotation_distance_x", "stepper_x", "rotation_distance", "40"),
    ProfileField("homing_speed_x", "stepper_x", "homing_speed", "50"),
    ProfileField("homing_positive_dir_x", "stepper_x", "homing_positive_dir"),
    ProfileField("y_size", "stepper_y", "position_max", "235"),
    ProfileField("y_position_min", "stepper_y", "position_min", "0"),
    ProfileField("y_position_max", "stepper_y", "position_max", "235"),
    ProfileField("y_position_endstop", "stepper_y", "position_endstop", "0"),
    ProfileField("microsteps_y", "stepper_y", "microsteps", "16"),
    ProfileField("rotation_distance_y", "stepper_y", "rotation_distance", "40"),
    ProfileField("homing_speed_y", "stepper_y", "homing_speed", "50"),
    ProfileField("homing_positive_dir_y", "stepper_y", "homing_positive_dir"),
    ProfileField("z_size", "stepper_z", "position_max", "250"),
    ProfileField("z_position_min", "stepper_z", "position_min", "0"),
    ProfileField("z_position_max", "stepper_z", "position_max", "250"),
    ProfileField("z_position_endstop", "stepper_z", "position_endstop", "0"),
    ProfileField("microsteps_z", "stepper_z", "microsteps", "16"),
    ProfileField("rotation_distance_z", "stepper_z", "rotation_distance", "8"),
    ProfileField("homing_positive_dir_z", "stepper_z", "homing_positive_dir"),
    ProfileField("microsteps_e", "extruder", "microsteps", "16"),
    ProfileField("rotation_distance_e", "extruder", "rotation_distance", "33.5"),
    ProfileField("nozzle_diameter", "extruder", "nozzle_diameter", "0.400"),
    ProfileField("filament_diameter", "extruder", "filament_diameter", "1.750"),
    ProfileField("hotend_thermistor", "extruder", "sensor_type", "EPCOS 100K B57560G104F"),
    ProfileField("hotend_control", "extruder", "control", "pid"),
    ProfileField("hotend_pid_kp", "extruder", "pid_kp", "22.2"),
    ProfileField("hotend_pid_ki", "extruder", "pid_ki", "1.08"),
    ProfileField("hotend_pid_kd", "extruder", "pid_kd", "114"),
    ProfileField("hotend_min_temp", "extruder", "min_temp", "0"),
    ProfileField("hotend_max_temp", "extruder", "max_temp", "250"),
    ProfileField("bed_thermistor", "heater_bed", "sensor_type", "EPCOS 100K B57560G104F"),
    ProfileField("bed_control", "heater_bed", "control", "pid"),
    ProfileField("bed_pid_kp", "heater_bed", "pid_kp", "54.027"),
    ProfileField("bed_pid_ki", "heater_bed", "pid_ki", "0.770"),
    ProfileField("bed_pid_kd", "heater_bed", "pid_kd", "948.182"),
    ProfileField("bed_min_temp", "heater_bed", "min_temp", "0"),
    ProfileField("bed_max_temp", "heater_bed", "max_temp", "130"),
)

_FIELD_BY_KEY = {field.key: field for field in FIELDS}
_TMC_TARGETS = ("x", "y", "z", "z1", "z2", "z3", "e")
SAFETY_CRITICAL_FIELDS = frozenset(field.key for field in FIELDS if field.safe_default is not None) | {
    f"{option}_{target}"
    for target in _TMC_TARGETS
    for option in ("run_current", "hold_current")
}


def _profile_value(parsed: Mapping[str, object], field: ProfileField) -> Optional[str]:
    section = parsed.get(field.section)
    if not isinstance(section, Mapping):
        return None
    value = section.get(field.option)
    return None if value in (None, "") else str(value).strip()


def _tmc_section(parsed: Mapping[str, object], target: str) -> Mapping[str, object]:
    suffix = "extruder" if target == "e" else f"stepper_{target}"
    for name, values in parsed.items():
        if str(name).split(" ", 1)[0].startswith("tmc") and str(name).endswith(f" {suffix}"):
            if isinstance(values, Mapping):
                return values
    return {}


def extract_profile_values(parsed: Mapping[str, object]) -> dict[str, str]:
    values = {}
    for field in FIELDS:
        value = _profile_value(parsed, field)
        if value is not None:
            values[field.key] = value
    for target in _TMC_TARGETS:
        section = _tmc_section(parsed, target)
        for option, default in (
            ("run_current", "0.650" if target not in ("x", "y") else "0.800"),
            ("hold_current", "0.400"),
            ("stealthchop_threshold", "999999"),
        ):
            value = section.get(option)
            if value not in (None, ""):
                values[f"{option}_{target}"] = str(value).strip()
    return values


def safe_defaults() -> dict[str, str]:
    values = {field.key: field.safe_default for field in FIELDS if field.safe_default is not None}
    for target in _TMC_TARGETS:
        values[f"run_current_{target}"] = "0.650" if target not in ("x", "y") else "0.800"
        values[f"hold_current_{target}"] = "0.400"
        values[f"stealthchop_threshold_{target}"] = "999999"
    return values


def safe_default_provenance(user_data: Mapping[str, object]) -> dict[str, str]:
    defaults = safe_defaults()
    return {
        key: ValueProvenance.SAFE_DEFAULT.value
        for key in defaults
        if key in user_data or key in ("kinematics", "hotend_thermistor", "bed_thermistor")
    }


def mark_user_override(user_data: dict, *keys: str) -> None:
    provenance = dict(user_data.get("_value_provenance") or {})
    for key in keys:
        provenance[key] = ValueProvenance.USER_OVERRIDE.value
    user_data["_value_provenance"] = provenance


def mark_profile_values(user_data: dict, parsed_profile: Mapping[str, object]) -> None:
    actual = extract_profile_values(parsed_profile)
    provenance = dict(user_data.get("_value_provenance") or {})
    for key in safe_defaults():
        provenance[key] = (
            ValueProvenance.PROFILE.value if key in actual else ValueProvenance.SAFE_DEFAULT.value
        )
    user_data["_value_provenance"] = provenance


def infer_homing_positive_dir(position_endstop, position_min, position_max) -> Optional[str]:
    """Infer Klipper's homing direction when the endstop is nearer one limit.

    A midpoint endstop is deliberately ambiguous.  Returning ``None`` makes
    the wizard request an explicit answer instead of guessing a motion-safety
    setting.
    """
    try:
        endstop = float(position_endstop)
        minimum = float(position_min)
        maximum = float(position_max)
    except (TypeError, ValueError):
        return None
    if not minimum < maximum:
        return None
    distance_to_min = abs(endstop - minimum)
    distance_to_max = abs(maximum - endstop)
    if distance_to_min < distance_to_max:
        return "False"
    if distance_to_max < distance_to_min:
        return "True"
    return None


def resolve_generation_values(
    parsed_data: Mapping[str, object], user_data: Mapping[str, object]
) -> tuple[dict[str, str], dict[str, str]]:
    """Resolve values without allowing generic defaults to hide profile data."""
    explicit_provenance = dict(user_data.get("_value_provenance") or {})
    profile_source = user_data.get("_profile_parsed")
    if not isinstance(profile_source, Mapping):
        profile_source = parsed_data
    profile_values = extract_profile_values(profile_source)
    defaults = safe_defaults()
    keys = set(_FIELD_BY_KEY) | set(defaults) | set(profile_values) | set(explicit_provenance)
    resolved: dict[str, str] = {}
    provenance: dict[str, str] = {}

    for key in sorted(keys):
        explicit_source = explicit_provenance.get(key)
        supplied = user_data.get(key)
        if explicit_source == ValueProvenance.USER_OVERRIDE.value:
            if supplied not in (None, ""):
                resolved[key] = str(supplied).strip()
                provenance[key] = ValueProvenance.USER_OVERRIDE.value
            else:
                provenance[key] = ValueProvenance.UNRESOLVED.value
        elif explicit_source == ValueProvenance.PROFILE.value:
            if key in profile_values:
                resolved[key] = profile_values[key]
                provenance[key] = ValueProvenance.PROFILE.value
            else:
                provenance[key] = ValueProvenance.UNRESOLVED.value
        elif explicit_source == ValueProvenance.INFERRED.value:
            if supplied not in (None, ""):
                resolved[key] = str(supplied).strip()
                provenance[key] = ValueProvenance.INFERRED.value
            else:
                provenance[key] = ValueProvenance.UNRESOLVED.value
        elif explicit_source == ValueProvenance.UNRESOLVED.value:
            provenance[key] = ValueProvenance.UNRESOLVED.value
        elif not explicit_provenance and supplied not in (None, ""):
            resolved[key] = str(supplied).strip()
            provenance[key] = ValueProvenance.USER_OVERRIDE.value
        elif key in profile_values:
            resolved[key] = profile_values[key]
            provenance[key] = ValueProvenance.PROFILE.value
        elif key in defaults:
            resolved[key] = defaults[key]
            provenance[key] = ValueProvenance.SAFE_DEFAULT.value
        else:
            provenance[key] = ValueProvenance.UNRESOLVED.value

    # Axis maximum defaults are geometry-dependent, not universal constants.
    # When neither a profile nor the user supplied a mechanical maximum, keep
    # the historical relationship position_max == selected build size without
    # hiding an explicit/profile value.
    for axis in ("x", "y", "z"):
        maximum_key = f"{axis}_position_max"
        size_key = f"{axis}_size"
        if provenance.get(maximum_key) == ValueProvenance.SAFE_DEFAULT.value:
            resolved[maximum_key] = resolved[size_key]

    for axis in ("x", "y", "z"):
        direction_key = f"homing_positive_dir_{axis}"
        if provenance.get(direction_key) != ValueProvenance.UNRESOLVED.value:
            continue
        inferred = infer_homing_positive_dir(
            resolved.get(f"{axis}_position_endstop"),
            resolved.get(f"{axis}_position_min"),
            resolved.get(f"{axis}_position_max"),
        )
        if inferred is not None:
            resolved[direction_key] = inferred
            provenance[direction_key] = ValueProvenance.INFERRED.value

    return resolved, provenance


def require_resolved_safety_values(provenance: Mapping[str, str]) -> None:
    unresolved = sorted(
        key
        for key in SAFETY_CRITICAL_FIELDS
        if provenance.get(key) == ValueProvenance.UNRESOLVED.value
    )
    if unresolved:
        raise GenerationError(
            "Safety-critical configuration values are unresolved: " + ", ".join(unresolved) + "."
        )


def require_resolved_homing_values(
    provenance: Mapping[str, str], *, uses_virtual_z_endstop: bool
) -> None:
    axes = ("x", "y") if uses_virtual_z_endstop else ("x", "y", "z")
    unresolved = [
        f"homing_positive_dir_{axis}"
        for axis in axes
        if provenance.get(f"homing_positive_dir_{axis}") == ValueProvenance.UNRESOLVED.value
    ]
    if unresolved:
        raise GenerationError(
            "Homing direction cannot be inferred safely; answer the wizard question for: "
            + ", ".join(unresolved)
            + "."
        )
