"""Consumer-specific fan configuration bounds from Klipper fe4eb865.

Common Fan PWM and tachometer options belong to part_fan. These checks do not
qualify cooling, sensors or runtime SET_TEMPERATURE_FAN_TARGET commands.
"""
import math

from core.exceptions import GenerationError


def _number(fields, section, option, *, default=None, minimum=None,
            maximum=None, above=None, integer=False):
    if option not in fields:
        if default is not None:
            return default
        raise GenerationError(f"[{section}] {option} must be specified.")
    try:
        value = (int if integer else float)(str(fields[option]).strip())
    except (TypeError, ValueError, OverflowError) as exc:
        raise GenerationError(f"[{section}] {option} must be a finite {'integer' if integer else 'number'}.") from exc
    if ((not integer and not math.isfinite(value)) or (minimum is not None and value < minimum)
            or (maximum is not None and value > maximum)
            or (above is not None and value <= above)):
        bounds = []
        if minimum is not None:
            bounds.append(f">= {minimum}")
        if maximum is not None:
            bounds.append(f"<= {maximum}")
        if above is not None:
            bounds.append(f"> {above}")
        suffix = " and " + " and ".join(bounds) if bounds else ""
        raise GenerationError(f"[{section}] {option} must be finite{suffix}.")
    return value


def validate_fan_consumers(sections):
    """Validate complete effective controller/temperature fan sections.

    Klipper returns omitted defaults without checking bounds. In particular an
    omitted target_temp can be below min_temp, and its constructor does not
    require min_speed <= max_speed. Preserve those accepted configurations.
    Finite numbers are an additional KACE admission policy, not an upstream
    guarantee of physical cooling or correct tuning.
    """
    for section, fields in sections.items():
        parts = section.split()
        if len(parts) >= 2 and parts[0] == "controller_fan":
            speed = _number(fields, section, "fan_speed", default=1., minimum=0., maximum=1.)
            _number(fields, section, "idle_speed", default=speed, minimum=0., maximum=1.)
            _number(fields, section, "idle_timeout", default=30, minimum=0, integer=True)
        elif len(parts) >= 2 and parts[0] == "temperature_fan":
            minimum = _number(fields, section, "min_temp", minimum=-273.15)
            maximum = _number(fields, section, "max_temp", above=minimum)
            _number(fields, section, "max_speed", default=1., above=0., maximum=1.)
            _number(fields, section, "min_speed", default=.3, minimum=0., maximum=1.)
            _number(fields, section, "target_temp", default=min(40., maximum),
                    minimum=minimum, maximum=maximum)
            control = fields.get("control")
            if control == "watermark":
                _number(fields, section, "max_delta", default=2., above=0.)
            elif control == "pid":
                for option in ("pid_kp", "pid_ki", "pid_kd"):
                    _number(fields, section, option)
                _number(fields, section, "pid_deriv_time", default=2., above=0.)
            else:
                raise GenerationError(f"[{section}] control must be watermark or pid.")
