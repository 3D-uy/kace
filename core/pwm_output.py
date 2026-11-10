"""Static PWM provider checks; no inferred MCU clock or electrical capability."""
import math

from core.exceptions import GenerationError


_TRUE = ("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "off")
_FAN_DEFAULTS = {"fan": 0., "fan_generic": 0., "controller_fan": 0.,
                 "heater_fan": 1., "temperature_fan": 1.}


def _mcu_leaves(sections, token, seen=()):
    """Return inversion flags for MCU leaves, None for unproved providers.

    MCU aliases cannot change chip or inversion. Do not use ADC pin resolution:
    adc_scaled maps to an MCU for ADC but does not provide PWM. multi_pin passes
    its inversion prefix to each child exactly as the pinned provider does.
    Missing providers, cycles and pin syntax remain with their existing owners.
    """
    if not isinstance(token, str):
        return [None]
    token = token.strip()
    invert = token.startswith("!")
    if invert:
        token = token[1:].strip()
    if any(c in token for c in "!^~"):
        return [None]
    chip, pin = (token.split(":", 1) if ":" in token else ("mcu", token))
    chip, pin = chip.strip(), pin.strip()
    if (chip == "mcu" and "mcu" in sections) or "mcu " + chip in sections:
        return [invert]
    name = "multi_pin " + pin
    if chip != "multi_pin" or name not in sections or name in seen:
        return [None]
    children = sections[name].get("pins", "")
    if not isinstance(children, str) or not children.strip():
        return [None]
    return [leaf for child in children.split(",")
            for leaf in _mcu_leaves(sections, ("!" if invert else "") + child.strip(),
                                    (*seen, name))]


def _number(fields, key, default):
    # This gate adds provider constraints, not a new parser for every consumer.
    # Invalid scalar syntax/ranges remain with their consumer validators/loader.
    try:
        value = float(str(fields.get(key, default)).strip())
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def _validate_direct_pwm(sections, name, fields, kind):
    """Queued/variable-cycle consumers construct MCU objects directly.

    They do not delegate through multi_pin. Unknown extension chips remain with
    their loader; declared MCUs have the pinned 3 s nominal limit. Runtime
    SET_PIN, timer ticks and firmware capabilities are not inferred here.
    """
    token = fields.get("pin")
    if not isinstance(token, str):
        return
    token = token.strip()
    invert = token.startswith("!")
    if invert:
        token = token[1:].strip()
    if any(c in token for c in "!^~"):
        return
    chip = token.split(":", 1)[0].strip() if ":" in token else "mcu"
    if not ((chip == "mcu" and "mcu" in sections) or "mcu " + chip in sections):
        if chip == "multi_pin" and any(n.startswith("multi_pin ") for n in sections):
            raise GenerationError(f"[{name}] requires a direct MCU pin; multi_pin is not supported by {kind}.")
        return

    def number(key, default, minimum=None, maximum=None, above=None):
        value = _number(fields, key, default)
        if (value is None or (minimum is not None and value < minimum)
                or (maximum is not None and value > maximum)
                or (above is not None and value <= above)):
            raise GenerationError(f"[{name}] {key} must be finite and within the pinned {kind} bounds.")
        return value

    number("cycle_time", .100, above=0., maximum=3.)
    scale = number("scale", 1., above=0.)
    start = number("value", 0., minimum=0., maximum=scale) / scale
    shutdown = number("shutdown_value", 0., minimum=0., maximum=scale) / scale
    hardware = False
    duration = 0.
    if kind == "pwm_tool":
        raw = str(fields.get("hardware_pwm", "false")).strip().lower()
        if raw not in (*_TRUE, *_FALSE):
            raise GenerationError(f"[{name}] hardware_pwm must be a Klipper boolean.")
        hardware = raw in _TRUE
        # The official omitted default is zero; explicit zero is below minval.
        if "maximum_mcu_duration" in fields:
            duration = number("maximum_mcu_duration", 0., minimum=.500, maximum=3.)
    if invert:
        start, shutdown = 1. - start, 1. - shutdown
    if duration and start != shutdown:
        raise GenerationError(f"[{name}] maximum_mcu_duration requires value equal to shutdown_value after scale and inversion.")
    if not hardware and shutdown not in (0., 1.):
        raise GenerationError(f"[{name}] MCU software PWM requires shutdown power 0 or 1 after scale and inversion.")


def validate_pwm_outputs(sections):
    """Match MCU_pwm shutdown and output_pin's nominal-period contract.

    The 3 s output_pin ceiling is MCU.max_nominal_duration(), not a clock/tick
    bound and not a limit for fans/heaters. Hardware PWM does not inherit the
    binary software shutdown rule. Queued consumers have direct-MCU checks;
    other providers retain separate contracts. Recognition does not enable
    generation or certify peripheral/runtime behavior.
    """
    for name, fields in sections.items():
        parts = name.split()
        kind = parts[0] if parts else ""
        if kind in ("pwm_tool", "pwm_cycle_time"):
            _validate_direct_pwm(sections, name, fields, kind)
            continue
        if kind in _FAN_DEFAULTS:
            power = _number(fields, "max_power", 1.)
            shutdown = _number(fields, "shutdown_speed", _FAN_DEFAULTS[kind])
            if power is None or shutdown is None or not 0 < power <= 1 or not 0 <= shutdown <= 1:
                continue
            shutdown = min(power, shutdown)
        elif kind == "output_pin" and str(fields.get("pwm", "false")).strip().lower() in _TRUE:
            scale = _number(fields, "scale", 1.)
            shutdown = _number(fields, "shutdown_value", 0.)
            if scale is None or shutdown is None or scale <= 0 or not 0 <= shutdown <= scale:
                continue
            shutdown /= scale
        else:
            continue
        leaves = _mcu_leaves(sections, fields.get("pin"))
        if kind == "output_pin" and leaves[0] is not None:
            cycle = _number(fields, "cycle_time", .100)
            if cycle is not None and cycle > 3.:
                raise GenerationError(
                    f"[{name}] cycle_time must be at most 3 seconds for its MCU provider.")
        if str(fields.get("hardware_pwm", "false")).strip().lower() not in _FALSE:
            continue
        for invert in leaves:
            if invert is None:
                continue
            actual_shutdown = 1. - shutdown if invert else shutdown
            if actual_shutdown not in (0., 1.):
                raise GenerationError(
                    f"[{name}] MCU software PWM requires shutdown power 0 or 1 "
                    "after max_power/scale and pin inversion. Review the shutdown configuration.")
