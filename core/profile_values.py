"""Resolve profile-derived Klipper values with explicit provenance."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
import re
from typing import Mapping, Optional

from core.exceptions import GenerationError


HARDWARE_SOURCE_POLICY = "selected-board/v1"
Z_MECHANICAL_OPTIONS = ("rotation_distance", "microsteps", "gear_ratio", "full_steps_per_rotation")
HOMING_OPTIONS = ("homing_speed", "second_homing_speed", "homing_retract_speed", "homing_retract_dist")
EXTRUDER_OPTIONS = ("max_extrude_only_distance", "max_extrude_only_velocity",
                    "max_extrude_only_accel", "instantaneous_corner_velocity",
                    "min_extrude_temp", "smooth_time")


class ValueProvenance(str, Enum):
    PROFILE = "PROFILE"
    USER_OVERRIDE = "USER_OVERRIDE"
    SAFE_DEFAULT = "SAFE_DEFAULT"
    KLIPPER_DEFAULT = "KLIPPER_DEFAULT"
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
    ProfileField("minimum_cruise_ratio", "printer", "minimum_cruise_ratio"),
    ProfileField("max_z_velocity", "printer", "max_z_velocity", "5"),
    ProfileField("max_z_accel", "printer", "max_z_accel", "100"),
    ProfileField("x_size", "stepper_x", "position_max", "235"),
    ProfileField("x_position_min", "stepper_x", "position_min", "0"),
    ProfileField("x_position_max", "stepper_x", "position_max", "235"),
    ProfileField("x_position_endstop", "stepper_x", "position_endstop", "0"),
    ProfileField("microsteps_x", "stepper_x", "microsteps", "16"),
    ProfileField("full_steps_per_rotation_x", "stepper_x", "full_steps_per_rotation", "200"),
    ProfileField("rotation_distance_x", "stepper_x", "rotation_distance", "40"),
    ProfileField("homing_speed_x", "stepper_x", "homing_speed", "50"),
    ProfileField("second_homing_speed_x", "stepper_x", "second_homing_speed"),
    ProfileField("homing_retract_speed_x", "stepper_x", "homing_retract_speed"),
    ProfileField("homing_retract_dist_x", "stepper_x", "homing_retract_dist"),
    ProfileField("homing_positive_dir_x", "stepper_x", "homing_positive_dir"),
    ProfileField("y_size", "stepper_y", "position_max", "235"),
    ProfileField("y_position_min", "stepper_y", "position_min", "0"),
    ProfileField("y_position_max", "stepper_y", "position_max", "235"),
    ProfileField("y_position_endstop", "stepper_y", "position_endstop", "0"),
    ProfileField("microsteps_y", "stepper_y", "microsteps", "16"),
    ProfileField("full_steps_per_rotation_y", "stepper_y", "full_steps_per_rotation", "200"),
    ProfileField("rotation_distance_y", "stepper_y", "rotation_distance", "40"),
    ProfileField("homing_speed_y", "stepper_y", "homing_speed", "50"),
    ProfileField("second_homing_speed_y", "stepper_y", "second_homing_speed"),
    ProfileField("homing_retract_speed_y", "stepper_y", "homing_retract_speed"),
    ProfileField("homing_retract_dist_y", "stepper_y", "homing_retract_dist"),
    ProfileField("homing_positive_dir_y", "stepper_y", "homing_positive_dir"),
    ProfileField("z_size", "stepper_z", "position_max", "250"),
    ProfileField("z_position_min", "stepper_z", "position_min", "0"),
    ProfileField("z_position_max", "stepper_z", "position_max", "250"),
    ProfileField("z_position_endstop", "stepper_z", "position_endstop", "0"),
    ProfileField("microsteps_z", "stepper_z", "microsteps", "16"),
    ProfileField("full_steps_per_rotation_z", "stepper_z", "full_steps_per_rotation", "200"),
    ProfileField("full_steps_per_rotation_z1", "stepper_z1", "full_steps_per_rotation", "200"),
    ProfileField("full_steps_per_rotation_z2", "stepper_z2", "full_steps_per_rotation", "200"),
    ProfileField("full_steps_per_rotation_z3", "stepper_z3", "full_steps_per_rotation", "200"),
    ProfileField("rotation_distance_z", "stepper_z", "rotation_distance", "8"),
    ProfileField("gear_ratio_z", "stepper_z", "gear_ratio", "1:1"),
    ProfileField("rotation_distance_z1", "stepper_z1", "rotation_distance", "8"),
    ProfileField("microsteps_z1", "stepper_z1", "microsteps", "16"),
    ProfileField("gear_ratio_z1", "stepper_z1", "gear_ratio", "1:1"),
    ProfileField("rotation_distance_z2", "stepper_z2", "rotation_distance", "8"),
    ProfileField("microsteps_z2", "stepper_z2", "microsteps", "16"),
    ProfileField("gear_ratio_z2", "stepper_z2", "gear_ratio", "1:1"),
    ProfileField("rotation_distance_z3", "stepper_z3", "rotation_distance", "8"),
    ProfileField("microsteps_z3", "stepper_z3", "microsteps", "16"),
    ProfileField("gear_ratio_z3", "stepper_z3", "gear_ratio", "1:1"),
    ProfileField("homing_positive_dir_z", "stepper_z", "homing_positive_dir"),
    ProfileField("homing_speed_z", "stepper_z", "homing_speed"),
    ProfileField("second_homing_speed_z", "stepper_z", "second_homing_speed"),
    ProfileField("homing_retract_speed_z", "stepper_z", "homing_retract_speed"),
    ProfileField("homing_retract_dist_z", "stepper_z", "homing_retract_dist"),
    ProfileField("microsteps_e", "extruder", "microsteps", "16"),
    ProfileField("full_steps_per_rotation_e", "extruder", "full_steps_per_rotation", "200"),
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
    *(ProfileField("extruder_" + option, "extruder", option) for option in EXTRUDER_OPTIONS),
    ProfileField("bed_thermistor", "heater_bed", "sensor_type", "EPCOS 100K B57560G104F"),
    ProfileField("bed_control", "heater_bed", "control", "pid"),
    ProfileField("bed_pid_kp", "heater_bed", "pid_kp", "54.027"),
    ProfileField("bed_pid_ki", "heater_bed", "pid_ki", "0.770"),
    ProfileField("bed_pid_kd", "heater_bed", "pid_kd", "948.182"),
    ProfileField("bed_min_temp", "heater_bed", "min_temp", "0"),
    ProfileField("bed_max_temp", "heater_bed", "max_temp", "130"),
)

_FIELD_BY_KEY = {field.key: field for field in FIELDS}
_HOMING_VALUE_KEYS = {f"{option}_{axis}" for option in HOMING_OPTIONS for axis in ("x", "y", "z")}
_OPTIONAL_VALUE_KEYS = _HOMING_VALUE_KEYS | {"minimum_cruise_ratio"} | {"extruder_" + option for option in EXTRUDER_OPTIONS}
_TMC_TARGETS = ("x", "y", "z", "z1", "z2", "z3", "e")
_TMC_VALUE_OPTIONS = ("run_current", "hold_current", "stealthchop_threshold")
_TMC_VALUE_KEYS = {f"{option}_{target}" for target in _TMC_TARGETS for option in _TMC_VALUE_OPTIONS}

# Klipper fe4eb865: extras/tmc*.py. Registers are model-specific; a similar
# connector or transport is not evidence that two driver chips are compatible.
_TMC_COMMON = set(
    "run_current hold_current stealthchop_threshold sense_resistor interpolate".split()
)
_TMC_UART = set("uart_pin tx_pin uart_address select_pins".split())
_TMC_SPI = set((
    "cs_pin spi_bus spi_speed spi_software_sclk_pin spi_software_mosi_pin "
    "spi_software_miso_pin chain_length chain_position diag0_pin diag1_pin "
    "coolstep_threshold high_velocity_threshold"
).split())
_TMC_REG_COMMON = set((
    "toff hstrt hend tbl iholddelay pwm_grad pwm_freq pwm_autoscale freewheel tpowerdown"
).split())
_TMC_REG_UART = set("multistep_filt pwm_ofs pwm_autograd pwm_reg pwm_lim".split())
_TMC_REG_COOL = set("semin seup semax sedn seimin".split())
_TMC_REG_WAVE = {f"mslut{i}" for i in range(8)} | set(
    "w0 w1 w2 w3 x1 x2 x3 start_sin start_sin90".split()
)
_TMC_REGISTERS = {
    "tmc2208": _TMC_REG_COMMON | _TMC_REG_UART,
    "tmc2209": _TMC_REG_COMMON | _TMC_REG_UART | _TMC_REG_COOL | {"sgthrs"},
    "tmc2130": (_TMC_REG_COMMON | _TMC_REG_COOL | _TMC_REG_WAVE
                | set("vhighfs vhighchm sgt sfilt pwm_ampl".split())),
    "tmc5160": (_TMC_REG_COMMON | _TMC_REG_UART | _TMC_REG_COOL | _TMC_REG_WAVE
                | set(("fd3 disfdcc chm vhighfs vhighchm tpfd diss2g diss2vs "
                       "sgt sfilt drvstrength bbmclks bbmtime filt_isense").split())),
}
# Parser bounds for fields already allowed above (Klipper fe4eb865, FieldHelper).
# These fields have the same width across the four supported native models.
# None denotes ConfigParser boolean syntax, not an arbitrary integer bit.
_TMC_REGISTER_BOUNDS = {
    **dict.fromkeys("pwm_autoscale pwm_autograd multistep_filt seimin sfilt vhighchm vhighfs chm disfdcc diss2g diss2vs fd3".split()),
    **dict.fromkeys("freewheel pwm_freq sedn seup tbl w0 w1 w2 w3 drvstrength filt_isense".split(), (0, 3)),
    "hstrt": (0, 7),
    **dict.fromkeys("hend iholddelay pwm_lim pwm_reg semax semin toff bbmclks tpfd".split(), (0, 15)),
    "bbmtime": (0, 31),
    **dict.fromkeys("pwm_grad pwm_ofs sgthrs tpowerdown pwm_ampl start_sin start_sin90 x1 x2 x3".split(), (0, 255)),
    **dict.fromkeys((f"mslut{i}" for i in range(8)), (0, 4294967295)),
    "sgt": (-64, 63),
}
SAFETY_CRITICAL_FIELDS = frozenset(field.key for field in FIELDS if field.safe_default is not None) | {
    f"{option}_{target}"
    for target in _TMC_TARGETS
    for option in _TMC_VALUE_OPTIONS
}


def canonical_tmc_model(driver_type: str) -> str:
    model = str(driver_type).lower()
    return "tmc2208" if model == "tmc2225" else model


def tmc_run_current(model: str, value: object) -> str:
    """Validate the official helper's numeric range, not motor suitability."""
    model = canonical_tmc_model(model)
    maximum = 10.0 if model == "tmc5160" else 2.0
    text = str(value).strip()
    try:
        current = float(text)
    except (TypeError, ValueError) as exc:
        raise GenerationError("run_current must be a finite positive RMS current.") from exc
    if not math.isfinite(current) or not 0 < current <= maximum:
        raise GenerationError(f"{model}: run_current must be > 0 and <= {maximum} A RMS.")
    return text


def tmc_setting_value(model: str, option: str, value: object) -> str:
    """Numeric parser contract for the three guided TMC settings."""
    if option in ("run_current", "hold_current"):
        return tmc_run_current(model, value)
    if option != "stealthchop_threshold":
        raise GenerationError(f"Unsupported guided TMC option: {option}")
    text = str(value).strip()
    try:
        threshold = float(text)
    except (ValueError, TypeError) as exc:
        raise GenerationError("stealthchop_threshold must be finite and >= 0.") from exc
    if not math.isfinite(threshold) or threshold < 0:
        raise GenerationError("stealthchop_threshold must be finite and >= 0.")
    return text


def validate_tmc_spi_options(sections: Mapping[str, object]) -> None:
    """Validate per-device SPI numbers, not shared-CS topology or wiring.

    Klipper tmc2130.lookup_tmc_spi_chain and bus.MCU_SPI_from_config own
    the defaults. Preserve omissions; a lone chain_position is unused upstream.
    """
    def integer(name, options, key, minimum, maximum=None):
        try:
            value = int(str(options.get(key)).strip())
        except (TypeError, ValueError) as exc:
            raise GenerationError(f"{name}: SPI {key} must be an integer.") from exc
        if value < minimum or maximum is not None and value > maximum:
            bound = f"{minimum}..{maximum}" if maximum is not None else f">= {minimum}"
            raise GenerationError(f"{name}: SPI {key} must be {bound}.")
        return value

    for name, options in sections.items():
        model, separator, _ = str(name).partition(" ")
        if not separator or model not in ("tmc2130", "tmc2240", "tmc2660", "tmc5160") or not isinstance(options, Mapping):
            continue
        if model == "tmc2240":
            if "uart_pin" in options:
                continue  # The official driver dispatches to UART by presence.
            unused = {"tx_pin", "uart_address", "select_pins"}.intersection(options)
            if unused:
                raise GenerationError(f"{name}: SPI unused UART options: {', '.join(sorted(unused))}.")
        if "spi_speed" in options:
            integer(name, options, "spi_speed", 100000)
        if model == "tmc2660":
            # Its independent MCU_TMC2660_SPI does not consume chain options.
            unused = {"chain_length", "chain_position"}.intersection(options)
            if unused:
                raise GenerationError(f"{name}: SPI unused options: {', '.join(sorted(unused))}.")
            continue
        if "chain_length" in options:
            length = integer(name, options, "chain_length", 2)
            integer(name, options, "chain_position", 1, length)
        elif "chain_position" in options:
            raise GenerationError(f"{name}: SPI chain_position requires chain_length.")


def validate_tmc_register_values(sections: Mapping[str, object]) -> None:
    """Check explicit preserved fields, without emulating driver registers.

    Generation's model allowlist owns admissible fields. External sections may
    contain other upstream options; this gate covers only the reviewed subset.
    Omissions retain Klipper's defaults and explicit values are never rewritten.
    """
    from configparser import ConfigParser
    for name, options in sections.items():
        model, separator, _ = str(name).partition(" ")
        if not separator or model not in _TMC_REGISTERS or not isinstance(options, Mapping):
            continue
        for key, value in options.items():
            option = str(key).lower()
            if not option.startswith("driver_") or option[7:] not in _TMC_REGISTERS[model]:
                continue
            bounds = _TMC_REGISTER_BOUNDS[option[7:]]
            text = str(value).strip()
            try:
                if bounds is None:
                    valid = text.lower() in ConfigParser.BOOLEAN_STATES
                else:
                    valid = bounds[0] <= int(text) <= bounds[1]
            except ValueError:
                valid = False
            if not valid:
                expected = "a boolean" if bounds is None else f"an integer in {bounds[0]}..{bounds[1]}"
                raise GenerationError(f"{name}: {option} must be {expected}.")


def validate_tmc_current_settings(sections: Mapping[str, object]) -> None:
    """Validate current options of generated and explicitly handled external TMCs.

    Destination includes have no wizard provenance. Validate their final values
    without inventing optional settings or claiming physical motor suitability.
    """
    for name, options in sections.items():
        model, separator, _ = str(name).partition(" ")
        if separator and model == "tmc2660" and isinstance(options, Mapping):
            try:
                current = float(options.get("run_current"))
            except (TypeError, ValueError, OverflowError):
                current = math.nan
            if not math.isfinite(current) or not 0.1 <= current <= 2.4:
                raise GenerationError(f"{name}: run_current must be finite and between 0.1 and 2.4 A.")
            for option in ("hold_current", "stealthchop_threshold", "coolstep_threshold", "high_velocity_threshold"):
                if option in options:
                    raise GenerationError(f"{name}: {option} is not consumed by this model.")
            if "idle_current_percent" in options:
                try:
                    idle = int(str(options["idle_current_percent"]).strip())
                except (TypeError, ValueError, OverflowError):
                    idle = -1
                if not 0 <= idle <= 100:
                    raise GenerationError(f"{name}: idle_current_percent must be an integer between 0 and 100.")
            continue
        if not separator or model not in _TMC_REGISTERS or not isinstance(options, Mapping):
            continue
        for option in _TMC_VALUE_OPTIONS:
            if option != "run_current" and option not in options:
                continue
            try:
                tmc_setting_value(model, option, options.get(option))
            except GenerationError as exc:
                raise GenerationError(f"{name}: invalid {option}. {exc}") from exc


def validate_tmc_auxiliary_options(sections: Mapping[str, object]) -> None:
    """Validate optional values KACE generates or preserves for supported TMCs."""
    from configparser import ConfigParser
    threshold_models = {
        "coolstep_threshold": ("tmc2209", "tmc2130", "tmc5160"),
        "high_velocity_threshold": ("tmc2130", "tmc5160"),
    }
    for name, options in sections.items():
        model, separator, _ = str(name).partition(" ")
        if not separator or model not in _TMC_REGISTERS or not isinstance(options, Mapping):
            continue
        if "interpolate" in options:
            if str(options["interpolate"]).strip().lower() not in ConfigParser.BOOLEAN_STATES:
                raise GenerationError(f"{name}: interpolate must be a boolean.")
        for option, models in threshold_models.items():
            if option not in options:
                continue
            if model not in models:
                raise GenerationError(f"{name}: {option} is not consumed by this model.")
            try:
                value = float(options[option])
            except (TypeError, ValueError, OverflowError):
                value = math.nan
            # Same finite-value policy as the guided stealthChop threshold.
            if not math.isfinite(value) or value < 0:
                raise GenerationError(f"{name}: {option} must be finite and >= 0.")


def validate_tmc_sense_resistors(sections: Mapping[str, object]) -> None:
    """Validate resistors, including the required external TMC2660 value.

    Positivity and finiteness are KACE policy for TMC2660 (its parser has no
    lower bound), not evidence that a declared resistance matches hardware.
    """
    for name, options in sections.items():
        model, separator, _ = str(name).partition(" ")
        if not separator or model not in (*_TMC_REGISTERS, "tmc2660"):
            continue
        if not isinstance(options, Mapping):
            continue
        if "sense_resistor" not in options:
            if model == "tmc2660":
                raise GenerationError(f"{name}: sense_resistor is required (ohms).")
            continue
        try:
            resistance = float(options["sense_resistor"])
        except (TypeError, ValueError, OverflowError):
            resistance = math.nan
        if not math.isfinite(resistance) or resistance <= 0:
            raise GenerationError(f"{name}: sense_resistor must be finite and greater than zero (ohms).")


def resolve_tmc_sections(parsed: Mapping[str, object], user: Mapping[str, object]) -> dict:
    """Preserve electrical options only from the explicitly selected chip.

    Reviewed removable sockets can supply missing sections with bus wiring
    only. Otherwise missing sections retain commented-template behavior; an
    incompatible/incomplete circuit is an error, never an arbitrary pin donor.
    UART pin sharing is checked using the selected board's aliases. Board/profile
    ownership is established by the caller; includes require later review.
    """
    from core.tmc_socket import selected_socket_sections
    parsed = selected_socket_sections(parsed, user)
    model = canonical_tmc_model(user.get("driver_type", ""))
    mode = user.get("driver_mode")
    if mode == "Standalone" or not model.startswith("tmc"):
        return {}
    if model not in _TMC_REGISTERS:
        raise GenerationError(f"Unsupported TMC model: {model}")
    expected_mode = "UART" if model in ("tmc2208", "tmc2209") else "SPI"
    if mode != expected_mode:
        raise GenerationError(f"{model} requires {expected_mode}, not {mode}.")
    allowed = _TMC_COMMON | (_TMC_UART if mode == "UART" else _TMC_SPI)
    if model == "tmc2209":
        allowed |= {"diag_pin", "coolstep_threshold"}
    allowed |= {"driver_" + field for field in _TMC_REGISTERS[model]}
    # Match printer.cfg.j2 load order: shared SPI transport belongs to the
    # first emitted member, including when a Z driver precedes the extruder.
    targets = ["stepper_x", "stepper_y", "stepper_z"]
    targets += [f"stepper_z{i}" for i in range(1, int(user.get("z_motors") or 1))]
    targets.append("extruder")
    sections = {}
    for target in targets:
        name = f"{model} {target}"
        source = parsed.get(name)
        if source is None:
            foreign = [str(key) for key in parsed
                       if str(key).startswith("tmc") and str(key).endswith(" " + target)]
            if foreign:
                raise GenerationError(f"{name}: incompatible source driver ({', '.join(foreign)}).")
            continue
        if not isinstance(source, Mapping):
            raise GenerationError(f"Invalid TMC section: {name}")
        options = {str(key).lower(): str(value).strip() if value is not None else ""
                   for key, value in source.items()}
        unsupported = set(options) - allowed
        if unsupported:
            raise GenerationError(f"{name}: unsupported options: {', '.join(sorted(unsupported))}")
        validate_tmc_spi_options({name: options})
        validate_tmc_register_values({name: options})
        validate_tmc_auxiliary_options({name: options})
        validate_tmc_sense_resistors({name: options})
        required_pin = "uart_pin" if mode == "UART" else "cs_pin"
        if not options.get(required_pin) or any(not value for value in options.values()):
            raise GenerationError(f"{name}: missing {required_pin} or empty TMC option.")
        if mode == "UART":
            try:
                address = int(options.get("uart_address", "0"))
            except ValueError as exc:
                raise GenerationError(f"{name}: invalid uart_address.") from exc
            if not 0 <= address <= (3 if model == "tmc2209" else 0):
                raise GenerationError(f"{name}: uart_address out of range.")
        sections[name] = options
    if mode == "UART":
        from core.tmc_uart import validate_uart_sections
        validate_uart_sections(parsed, sections)
    return sections


def _profile_value(parsed: Mapping[str, object], field: ProfileField) -> Optional[str]:
    section = parsed.get(field.section)
    if not isinstance(section, Mapping):
        return None
    value = section.get(field.option)
    if (field.option in ("full_steps_per_rotation", "minimum_cruise_ratio") or field.option in HOMING_OPTIONS or field.option in EXTRUDER_OPTIONS or field.section.startswith("stepper_z")
            and field.option in ("rotation_distance", "microsteps", "gear_ratio")) and field.option in section:
        # Preserve present blanks for validation (empty gearing means no ratio
        # upstream; empty step counts/distances never authorize a default).
        return "" if value is None else str(value).strip()
    return None if value in (None, "") else str(value).strip()


def _tmc_section(parsed: Mapping[str, object], target: str, model: Optional[str] = None) -> Mapping[str, object]:
    suffix = "extruder" if target == "e" else f"stepper_{target}"
    if model is not None:
        values = parsed.get(f"{model} {suffix}", {})
        return values if isinstance(values, Mapping) else {}
    for name, values in parsed.items():
        if str(name).split(" ", 1)[0].startswith("tmc") and str(name).endswith(f" {suffix}"):
            if isinstance(values, Mapping):
                return values
    return {}


def extract_profile_values(parsed: Mapping[str, object], *, driver_type: Optional[str] = None) -> dict[str, str]:
    values = {}
    for field in FIELDS:
        value = _profile_value(parsed, field)
        if value is not None:
            values[field.key] = value
    for target in _TMC_TARGETS:
        section = _tmc_section(parsed, target, canonical_tmc_model(driver_type) if driver_type is not None else None)
        for option in _TMC_VALUE_OPTIONS:
            value = section.get(option)
            if value not in (None, ""):
                values[f"{option}_{target}"] = str(value).strip()
    return values


def safe_defaults() -> dict[str, str]:
    return {field.key: field.safe_default for field in FIELDS if field.safe_default is not None}


def validate_homing_options(sections: Mapping[str, object]) -> None:
    """Primary XYZ rail bounds from Klipper PrinterRail; finiteness is KACE policy.

    Leave omissions to upstream, including second/retract speeds derived from
    homing_speed. Secondary steppers and other kinematics are not rail clones.
    """
    for axis in ("x", "y", "z"):
        section = f"stepper_{axis}"
        options = sections.get(section, {})
        if not isinstance(options, Mapping):
            continue
        for option in HOMING_OPTIONS:
            if option not in options:
                continue
            try:
                value = float(str(options[option]).strip())
            except (TypeError, ValueError) as exc:
                raise GenerationError(f"{section}: {option} must be a finite number.") from exc
            minimum_ok = value >= 0 if option == "homing_retract_dist" else value > 0
            if not math.isfinite(value) or not minimum_ok:
                bound = ">= 0" if option == "homing_retract_dist" else "> 0"
                raise GenerationError(f"{section}: {option} must be finite and {bound}.")


def validate_motion_timing(sections: Mapping[str, object]) -> None:
    """Check explicit timing numbers, leaving driver/MCU defaults to Klipper."""
    for name, options in sections.items():
        if not isinstance(options, Mapping):
            continue
        if name == "printer":
            option, maximum, inclusive = "minimum_cruise_ratio", 1., False
        elif (re.fullmatch(r"stepper_[xyz]\d*|extruder\d*", name)
              or name.startswith(("manual_stepper ", "extruder_stepper "))):
            option, maximum, inclusive = "step_pulse_duration", .001, True
        else:
            continue
        if option not in options:
            continue
        try:
            value = float(str(options[option]).strip())
        except (TypeError, ValueError) as exc:
            raise GenerationError(f"{name}: {option} must be a finite number.") from exc
        valid_max = value <= maximum if inclusive else value < maximum
        if not math.isfinite(value) or value < 0 or not valid_max:
            bound = "<= 0.001 seconds" if inclusive else "< 1"
            raise GenerationError(f"{name}: {option} must be finite, >= 0 and {bound}.")


def validate_sensor_resistors(sections: Mapping[str, object]) -> None:
    """Check explicit ADC circuit values; omission leaves defaults to Klipper.

    thermistor.PrinterThermistor requires pullup > 0 and inline >= 0;
    adc_temperature.LinearResistance uses the same pullup bound. Finiteness
    is an additional KACE preflight rule. This does not certify sensor types
    or their custom calibration dependencies.
    """
    for name, options in sections.items():
        if not isinstance(options, Mapping):
            continue
        if name not in ("extruder", "heater_bed") and "sensor_type" not in options:
            continue
        for option in ("pullup_resistor", "inline_resistor"):
            if option not in options:
                continue
            try:
                value = float(str(options[option]).strip())
            except (TypeError, ValueError) as exc:
                raise GenerationError(f"{name}: {option} must be a finite resistance.") from exc
            if not math.isfinite(value) or value < 0 or option == "pullup_resistor" and value == 0:
                bound = "> 0" if option == "pullup_resistor" else ">= 0"
                raise GenerationError(f"{name}: {option} must be finite and {bound} ohms.")


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
    current_keys = [key for key in keys if key in _TMC_VALUE_KEYS]
    if current_keys:
        stored = user_data.get("_tmc_current_confirmations")
        receipts = dict(stored) if isinstance(stored, Mapping) else {}
        board = user_data.get("board_parsed")
        for key in current_keys:
            receipts.pop(key, None)
            if isinstance(board, Mapping):
                receipts[key] = {"schema": 1, "value": str(user_data.get(key, "")).strip(),
                                 "context": tmc_current_context(board, user_data, key)}
        user_data["_tmc_current_confirmations"] = receipts


def tmc_current_context(parsed_data, user_data, key):
    """Recorded circuit/motor inputs, not an identity of the physical motor."""
    from core.tmc_socket import selected_socket_sections
    parsed_data = selected_socket_sections(parsed_data, user_data)
    target = key.rsplit("_", 1)[1]
    section = "extruder" if target == "e" else f"stepper_{target}"
    model = canonical_tmc_model(user_data.get("driver_type", ""))
    profile = user_data.get("_profile_parsed")
    if not isinstance(profile, Mapping):
        profile = parsed_data
    def fields(data, name, options=None):
        source = data.get(name)
        if not isinstance(source, Mapping):
            return {}
        return {str(k): None if v is None else str(v).strip() for k, v in source.items()
                if options is None or k in options}
    motor_options = ("rotation_distance", "microsteps", "gear_ratio", "full_steps_per_rotation")
    ownership = user_data.get("_value_provenance") or {}
    assignments = user_data.get("z_socket_assignments") or {}
    return {
        "board": user_data.get("board"), "driver": user_data.get("driver_type"),
        "mode": user_data.get("driver_mode"), "profile": user_data.get("printer_profile"),
        "motor": section, "socket": assignments.get(section, section),
        "z_motors": str(user_data.get("z_motors") or 1) if target.startswith("z") else None,
        "circuit": fields(parsed_data, f"{model} {section}"),
        "motor_pins": fields(parsed_data, section, ("step_pin", "dir_pin", "enable_pin")),
        "motor_source": fields(profile, section, motor_options),
        "motor_overrides": {option: str(user_data.get(f"{option}_{target}")).strip()
                            for option in motor_options if ownership.get(f"{option}_{target}") == "USER_OVERRIDE"},
        "mcu": {str(name): fields(parsed_data, name, ("serial", "canbus_uuid", "canbus_interface", "baud", "restart_method"))
                for name in parsed_data if name == "mcu" or str(name).startswith("mcu ")},
        "aliases": {str(name): fields(parsed_data, name, ("mcu", "aliases"))
                    for name in parsed_data if name == "board_pins" or str(name).startswith("board_pins ")},
    }


def tmc_current_confirmation_matches(parsed_data, user_data, key):
    receipts = user_data.get("_tmc_current_confirmations")
    receipt = receipts.get(key) if isinstance(receipts, Mapping) else None
    return (isinstance(receipt, Mapping) and receipt.get("schema") == 1
            and receipt.get("value") == str(user_data.get(key, "")).strip()
            and receipt.get("context") == tmc_current_context(parsed_data, user_data, key))


def mark_profile_values(user_data: dict, parsed_profile: Mapping[str, object]) -> None:
    actual = extract_profile_values(parsed_profile)
    provenance = dict(user_data.get("_value_provenance") or {})
    for key in set(safe_defaults()) | _TMC_VALUE_KEYS | _OPTIONAL_VALUE_KEYS:
        provenance[key] = (
            ValueProvenance.PROFILE.value if key in actual else
            ValueProvenance.KLIPPER_DEFAULT.value if key in _OPTIONAL_VALUE_KEYS and key not in safe_defaults() else
            ValueProvenance.SAFE_DEFAULT.value
        )
    user_data["_value_provenance"] = provenance


def infer_homing_positive_dir(position_endstop, position_min, position_max) -> Optional[str]:
    """Infer Klipper's rail direction only within the outer travel quarters.

    An endstop in the middle half is ambiguous. Returning ``None`` makes
    the wizard request an explicit answer instead of guessing a motion-safety
    setting.
    """
    try:
        endstop = float(position_endstop)
        minimum = float(position_min)
        maximum = float(position_max)
    except (TypeError, ValueError):
        return None
    if (not all(math.isfinite(value) for value in (endstop, minimum, maximum))
            or not minimum < maximum or not minimum <= endstop <= maximum):
        return None
    quarter = (maximum - minimum) / 4.
    if endstop <= minimum + quarter:
        return "False"
    if endstop >= maximum - quarter:
        return "True"
    return None


def _z_mechanical_number(key: str, value: str) -> float:
    """Validate selected Z scaling; gear stages must be physically meaningful."""
    try:
        if key.startswith("gear_ratio_"):
            ratio = 1.0
            for stage in value.split(",") if value else ():
                numerator, denominator = (float(part.strip()) for part in stage.split(":"))
                if not all(math.isfinite(part) and part > 0 for part in (numerator, denominator)):
                    raise ValueError("gear teeth must be positive and finite")
                ratio *= numerator / denominator
            number = ratio
        elif key.startswith("microsteps_"):
            number = int(value)
        else:
            number = float(value)
        if not math.isfinite(number) or number <= 0:
            raise ValueError("scale must be positive and finite")
        return number
    except (TypeError, ValueError, OverflowError, ZeroDivisionError) as exc:
        raise GenerationError(f"{key} has an invalid motor scale: {value!r}.") from exc


def _validate_z_mechanics(resolved, provenance, profile_source, z_count):
    values = {}
    defaults = {"rotation_distance": 8.0, "microsteps": 16, "gear_ratio": 1.0}
    for index in range(z_count):
        target = "z" + (str(index) if index else "")
        for option in defaults:
            key = f"{option}_{target}"
            if key in resolved:
                values[key] = _z_mechanical_number(key, resolved[key])
    for index in range(1, z_count):
        source = profile_source.get(f"stepper_z{index}", {})
        independently_defined = isinstance(source, Mapping) and all(
            option in source for option in ("rotation_distance", "microsteps"))
        for option, default in defaults.items():
            key = f"{option}_z{index}"
            if provenance.get(key) != ValueProvenance.SAFE_DEFAULT.value:
                continue
            # A complete independent Klipper section may omit gear_ratio: 1:1
            # is then its own contract, regardless of the primary Z reduction.
            if option == "gear_ratio" and independently_defined:
                continue
            if values.get(f"{option}_z", default) != default:
                raise GenerationError(
                    f"{key} requires an explicit value: the additional motor has no "
                    "verified matching mechanics. Confirm the same assembly or configure it separately.")


def z_mechanics_context(parsed_data, user_data, resolved):
    """Inputs whose change requires reviewing a guided Z mechanics choice."""
    source = user_data.get("_profile_parsed")
    if not isinstance(source, Mapping):
        source = parsed_data
    count = int(user_data.get("z_motors") or 1)
    primary = {option: resolved.get(f"{option}_z") for option in Z_MECHANICAL_OPTIONS}
    if primary["full_steps_per_rotation"] is not None:
        primary["full_steps_per_rotation"] = str(int(primary["full_steps_per_rotation"]))
    return {
        "board": user_data.get("board"), "profile": user_data.get("printer_profile"),
        "z_motors": count, "primary": primary,
        "source": {section: {option: str(source[section][option])
                             for option in Z_MECHANICAL_OPTIONS if option in source[section]}
                   for section in ["stepper_z" + (str(i) if i else "") for i in range(count)]
                   if isinstance(source.get(section), Mapping)},
    }


def z_mechanics_confirmation_matches(parsed_data, user_data, resolved):
    receipt = user_data.get("_z_mechanics_confirmation")
    if not isinstance(receipt, Mapping) or receipt.get("schema") != 1:
        return False
    keys = {f"{option}_z{i}" for i in range(1, int(user_data.get("z_motors") or 1))
            for option in Z_MECHANICAL_OPTIONS}
    owned = receipt.get("owned_values")
    if not isinstance(owned, Mapping) or not set(owned).issubset(keys):
        return False
    values = {key: resolved.get(key) for key in keys}
    for key in values:
        if key.startswith("full_steps_per_rotation_") and values[key] is not None:
            values[key] = str(int(values[key]))
    return (receipt.get("context") == z_mechanics_context(parsed_data, user_data, resolved)
            and receipt.get("values") == values)


def resolve_generation_values(
    parsed_data: Mapping[str, object], user_data: Mapping[str, object], *, validate_motors: bool = True,
) -> tuple[dict[str, str], dict[str, str]]:
    """Resolve values without allowing generic defaults to hide profile data.

    ``validate_motors=False`` supplies an unvalidated draft to the motor editor.
    Generation and all other callers retain the default validation gate.
    """
    from core.tmc_socket import selected_socket_sections
    parsed_data = selected_socket_sections(parsed_data, user_data)
    explicit_provenance = dict(user_data.get("_value_provenance") or {})
    profile_source = user_data.get("_profile_parsed")
    if not isinstance(profile_source, Mapping):
        profile_source = parsed_data
    profile_values = extract_profile_values(profile_source, driver_type=user_data.get("driver_type"))
    # The selected board supplies the driver circuit. A separate printer
    # profile may supply mechanics/thermal settings, never its TMC currents.
    board_values = extract_profile_values(parsed_data, driver_type=user_data.get("driver_type"))
    for key in _TMC_VALUE_KEYS:
        profile_values.pop(key, None)
        if key in board_values:
            profile_values[key] = board_values[key]
    defaults = safe_defaults()
    keys = set(_FIELD_BY_KEY) | set(defaults) | set(profile_values) | set(explicit_provenance) | _TMC_VALUE_KEYS
    try:
        z_count = int(user_data.get("z_motors") or 1)
    except (TypeError, ValueError) as exc:
        raise GenerationError("z_motors must be an integer.") from exc
    if not 1 <= z_count <= 4:
        raise GenerationError("z_motors must be between 1 and 4.")
    model = canonical_tmc_model(user_data.get("driver_type", ""))
    if user_data.get("driver_mode") == "Standalone" or model not in _TMC_REGISTERS:
        keys.difference_update(_TMC_VALUE_KEYS)
    else:
        # Missing sections remain commented examples in the template. They do
        # not authorize a current choice and must not block unrelated motors.
        for target in _TMC_TARGETS:
            section = "extruder" if target == "e" else f"stepper_{target}"
            if f"{model} {section}" not in parsed_data:
                keys.discard(f"run_current_{target}")
    for index in range(1, 4):
        if index >= z_count:
            keys.difference_update(f"{option}_z{index}" for option in _TMC_VALUE_OPTIONS)
            for option in ("full_steps_per_rotation", "rotation_distance", "microsteps", "gear_ratio"):
                keys.discard(f"{option}_z{index}")
    resolved: dict[str, str] = {}
    provenance: dict[str, str] = {}

    for key in sorted(keys):
        explicit_source = explicit_provenance.get(key)
        supplied = user_data.get(key)
        if key.startswith(("hold_current_", "stealthchop_threshold_")):
            option, target = key.rsplit("_", 1)
            source = _tmc_section(parsed_data, target, canonical_tmc_model(user_data.get("driver_type", "")))
            legacy_override = (not explicit_provenance and supplied not in (None, "")
                               and not isinstance(user_data.get("_profile_parsed"), Mapping))
            if option not in source and explicit_source != ValueProvenance.USER_OVERRIDE.value and not legacy_override:
                provenance[key] = ValueProvenance.KLIPPER_DEFAULT.value
                continue
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
        elif explicit_source == ValueProvenance.INFERRED.value and key not in _TMC_VALUE_KEYS:
            if supplied not in (None, ""):
                resolved[key] = str(supplied).strip()
                provenance[key] = ValueProvenance.INFERRED.value
            else:
                provenance[key] = ValueProvenance.UNRESOLVED.value
        elif explicit_source == ValueProvenance.UNRESOLVED.value:
            provenance[key] = ValueProvenance.UNRESOLVED.value
        elif (not explicit_provenance and supplied not in (None, "")
              and not (key in _TMC_VALUE_KEYS and isinstance(user_data.get("_profile_parsed"), Mapping))):
            resolved[key] = str(supplied).strip()
            provenance[key] = ValueProvenance.USER_OVERRIDE.value
        elif key in profile_values:
            resolved[key] = profile_values[key]
            provenance[key] = ValueProvenance.PROFILE.value
        elif key in defaults:
            resolved[key] = defaults[key]
            provenance[key] = ValueProvenance.SAFE_DEFAULT.value
        elif key in _OPTIONAL_VALUE_KEYS:
            provenance[key] = ValueProvenance.KLIPPER_DEFAULT.value
        else:
            provenance[key] = ValueProvenance.UNRESOLVED.value

    for key in list(resolved):
        if key in _TMC_VALUE_KEYS:
            if provenance.get(key) == ValueProvenance.USER_OVERRIDE.value and not tmc_current_confirmation_matches(parsed_data, user_data, key):
                resolved.pop(key)
                provenance[key] = ValueProvenance.UNRESOLVED.value
                continue
            try:
                tmc_setting_value(model, key.rsplit("_", 1)[0], resolved[key])
            except GenerationError:
                provenance[key] = ValueProvenance.UNRESOLVED.value

    if validate_motors:
        # Klipper stepper.parse_step_distance uses getint(default=200, minval=1)
        # and requires a multiple of four. Validate only selected motor sections;
        # an explicit override can replace an invalid profile value.
        for key in resolved:
            if not key.startswith("full_steps_per_rotation_"):
                continue
            value = resolved[key]
            try:
                steps = int(value)
            except (TypeError, ValueError) as exc:
                raise GenerationError(f"{key} must be a positive integer multiple of four; received {value!r}.") from exc
            if steps < 1 or steps % 4:
                raise GenerationError(f"{key} must be a positive integer multiple of four; received {value!r}.")
            resolved[key] = str(steps)

        if "_z_mechanics_confirmation" in user_data and not z_mechanics_confirmation_matches(parsed_data, user_data, resolved):
            raise GenerationError("Z mechanics confirmation is stale; review the Z mechanics step again.")
        _validate_z_mechanics(resolved, provenance, profile_source, z_count)

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


def tmc_option_sources(user, selected_sections, rendered_sections, provenance):
    """Describe emitted options, keeping generic legacy provenance compatible."""
    result = {}
    for name, source in selected_sections.items():
        if name not in rendered_sections:
            continue
        model, target = name.split(" ", 1)
        suffix = "e" if target == "extruder" else target.removeprefix("stepper_")
        options = {}
        for option, value in rendered_sections[name].items():
            origin, input_value = "SELECTED_BOARD", source.get(option)
            if option in _TMC_VALUE_OPTIONS:
                key = f"{option}_{suffix}"
                owner = provenance.get(key)
                if owner == ValueProvenance.USER_OVERRIDE.value:
                    origin, input_value = "USER_OVERRIDE", user.get(key)
                elif owner == ValueProvenance.SAFE_DEFAULT.value:
                    origin, input_value = "KACE_DEFAULT", safe_defaults().get(key)
                elif owner != ValueProvenance.PROFILE.value:
                    origin, input_value = owner or "UNRESOLVED", user.get(key)
            options[option] = {"value": value, "origin": origin, "input_value": input_value}
        result[name] = {"board": user.get("board"), "model": model,
                        "socket": (user.get("z_socket_assignments") or {}).get(target, target),
                        "omitted_options": [option for option in ("hold_current", "stealthchop_threshold")
                                            if provenance.get(f"{option}_{suffix}") == ValueProvenance.KLIPPER_DEFAULT.value]
                                           + (["sense_resistor"] if "sense_resistor" not in options else []),
                        "options": options}
    return result


def validate_primary_extruder_options(sections: Mapping[str, object]) -> None:
    """Explicit primary limits follow Klipper bounds; omitted defaults stay upstream.

    Finiteness is additional KACE policy. This validates values and their heater
    range, not physical extrusion capability or a user's chosen print strategy.
    """
    fields = sections.get("extruder", {})
    if not isinstance(fields, Mapping):
        return
    for option in EXTRUDER_OPTIONS:
        if option not in fields:
            continue
        try:
            value = float(str(fields[option]).strip())
        except (TypeError, ValueError, OverflowError) as exc:
            raise GenerationError(f"extruder: {option} must be finite.") from exc
        strict = option in ("max_extrude_only_velocity", "max_extrude_only_accel", "smooth_time")
        if not math.isfinite(value) or (option != "min_extrude_temp" and (value <= 0 if strict else value < 0)):
            raise GenerationError(f"extruder: invalid {option}; require a finite {'positive' if strict else 'nonnegative'} value.")
        if option == "min_extrude_temp":
            for bound, lower in (("min_temp", True), ("max_temp", False)):
                if bound not in fields:
                    continue  # This subset does not supply missing heater definitions.
                try:
                    limit = float(str(fields[bound]).strip())
                except (TypeError, ValueError, OverflowError) as exc:
                    raise GenerationError(f"extruder: {option} requires a valid {bound}.") from exc
                if not math.isfinite(limit) or (value < limit if lower else value > limit):
                    raise GenerationError(f"extruder: {option} must be within min_temp and max_temp.")


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
