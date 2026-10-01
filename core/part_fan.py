"""Preservation of the selected source [fan], not arbitrary fan-role migration."""
from collections.abc import Mapping
import math

from core.exceptions import GenerationError


SOURCE_OPTIONS = "_part_fan_active_options"
SCALAR_OPTIONS = (
    "max_power", "kick_start_time", "off_below", "cycle_time",
    "hardware_pwm", "shutdown_speed",
)


def selected_part_fan(parsed, choice):
    """Keep source settings only while retaining its exact electrical pin token.

    Parser evidence separates active options from commented discovery examples.
    Direct dictionary API callers supply their own active configuration. A custom
    socket must not inherit tuning from a different fan. Transferring a heater or
    controller fan into this role is deliberately outside this resolver.
    """
    source = parsed.get(SOURCE_OPTIONS, parsed.get("fan"))
    if choice == "none":
        return None
    from core.hotend_fan import active_fan_sources, match_fan_source
    sources = active_fan_sources(parsed, role="fan")
    explicit = bool(choice and choice != "default")
    if not explicit:
        if source is None:
            return None
        if not isinstance(source, Mapping) or not source.get("pin"):
            raise GenerationError("fan: configuration must contain a pin and options.")
        choice = source["pin"]
    match = match_fan_source(parsed, sources, choice, role="fan")
    if match:
        name, fields = match
        if name == "fan":
            source = fields
        elif name.startswith(("heater_fan ", "controller_fan ", "temperature_fan ")) or set(fields) != {"pin"}:
            raise GenerationError(f"fan: [{name}] cooling role conversion needs review; cannot silently replace its dependencies with a manual fan.")
        else:
            return {"pin": choice}
    elif explicit and (not isinstance(source, Mapping) or source.get("pin") != choice):
        return {"pin": choice}
    if source is None:
        return None
    if not isinstance(source, Mapping):
        raise GenerationError("fan: configuration must contain a pin and options.")
    unsupported = set(source) - {"pin", *SCALAR_OPTIONS}
    if unsupported:
        raise GenerationError(
            "fan: selected source requires preservation of "
            + ", ".join(sorted(unsupported))
            + "; this generation route is not implemented. Do not remove required hardware options."
        )
    result = dict(source)
    validate_part_fan_options({"fan": result})
    return result


def validate_part_fan_options(sections):
    """Klipper fan.Fan scalar bounds; finiteness is an extra KACE guard.

    This also checks preserved destination overrides, but does not forbid their
    auxiliary pins or claim MCU hardware-PWM capability validation.
    """
    options = sections.get("fan", {})
    for option in SCALAR_OPTIONS:
        if option not in options:
            continue
        text = str(options[option]).strip()
        if option == "hardware_pwm":
            if text.lower() not in ("1", "yes", "true", "on", "0", "no", "false", "off"):
                raise GenerationError("fan: hardware_pwm must be a Klipper boolean.")
            continue
        try:
            value = float(text)
        except (TypeError, ValueError) as exc:
            raise GenerationError(f"fan: {option} must be a finite number.") from exc
        exclusive_zero = option in ("max_power", "cycle_time")
        bounded = option in ("max_power", "off_below", "shutdown_speed")
        if (not math.isfinite(value) or value < 0
                or (exclusive_zero and value == 0) or (bounded and value > 1)):
            lower = "> 0" if exclusive_zero else ">= 0"
            upper = " and <= 1" if bounded else ""
            raise GenerationError(f"fan: {option} must be finite, {lower}{upper}.")
