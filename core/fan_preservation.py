"""Bind present wizard fan resources to their selected-board source.

This does not infer whether an absent optional fan was disabled intentionally.
Mandatory cooling has its separate board_cooling contract. Custom GPIO without
a source match and other fan families remain outside this equivalence check.
"""
import math

from core.exceptions import GenerationError
from core.hotend_fan import active_fan_sources, selected_hotend_fans, HEATER_OPTIONS
from core.part_fan import selected_part_fan, validate_part_fan_options, SCALAR_OPTIONS
from core.pin_validator import PinAliases, PinAliasError
from core.validators import questionary_fan_pin_validator


def _settings(fields, *, thermal):
    allowed = {"pin", *SCALAR_OPTIONS, *(HEATER_OPTIONS if thermal else ())}
    extra = set(fields) - allowed
    if extra:
        raise GenerationError(f"fan source equivalence has unreviewed options: {', '.join(sorted(extra))}.")
    validate_part_fan_options({"fan": fields})
    defaults = {"max_power": 1., "kick_start_time": .1, "off_below": 0., "cycle_time": .01,
                "shutdown_speed": 1. if thermal else 0.}
    values = {key: float(fields.get(key, value)) for key, value in defaults.items()}
    # fan.Fan clamps shutdown power to max_power, independently of duty scaling.
    values["shutdown_speed"] = min(values["max_power"], values["shutdown_speed"])
    values["hardware_pwm"] = str(fields.get("hardware_pwm", "false")).strip().lower() in ("1", "true", "on", "yes")
    if thermal:
        try:
            values["heater_temp"] = float(fields.get("heater_temp", 50.))
            values["fan_speed"] = float(fields.get("fan_speed", 1.))
        except (ValueError, TypeError) as exc:
            raise GenerationError("heater_fan source settings must be finite numbers.") from exc
        if (not math.isfinite(values["heater_temp"]) or not math.isfinite(values["fan_speed"])
                or not 0 <= values["fan_speed"] <= 1):
            raise GenerationError("heater_fan source settings are invalid.")
        values["heater"] = tuple(n.strip() for n in str(fields.get("heater", "extruder")).split(","))
    return values


def validate_present_fan_sources(parsed, sections):
    """Check known present [fan]/[heater_fan] outputs, including effective includes."""
    if parsed is None:
        return
    sources = active_fan_sources(parsed, role="fan")
    if not sources:
        return
    try:
        before, after = PinAliases(parsed), PinAliases(sections)
        for name, actual in sections.items():
            if name != "fan" and not name.startswith("heater_fan "):
                continue
            pin = actual.get("pin")
            if not isinstance(pin, str) or questionary_fan_pin_validator(pin) is not True:
                raise GenerationError(f"fan source [{name}] requires a valid PWM pin.")
            identity = after.resolve(pin)
            matches = [(source_name, fields) for source_name, fields in sources.items()
                       if isinstance(fields, dict) and isinstance(fields.get("pin"), str)
                       and before.resolve(fields["pin"]) == identity]
            if not matches:
                continue  # Custom socket; no source equivalence is inferred.
            if len(matches) != 1:
                raise GenerationError(f"fan source [{name}] has ambiguous GPIO ownership.")
            _, original = matches[0]
            # Reuse generation policy with the ORIGINAL token. An equivalent
            # alias in the final artifact must not be mistaken for a new socket.
            if name == "fan":
                expected = selected_part_fan(parsed, original["pin"])
            else:
                selected = selected_hotend_fans(parsed, original["pin"])
                if name not in selected:
                    raise GenerationError(f"heater_fan source identity changed: [{name}] does not retain its original name.")
                expected = selected[name]
            if (original["pin"].strip().startswith("!") != pin.strip().startswith("!")
                    or _settings(expected, thermal=name != "fan") != _settings(actual, thermal=name != "fan")):
                raise GenerationError(f"fan source settings changed for [{name}]; regenerate or review the selected hardware before publication.")
    except PinAliasError as exc:
        raise GenerationError(f"fan source GPIO validation failed: {exc}") from exc
