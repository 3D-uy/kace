"""Explicit motor inversion relative to the selected board/socket source."""
from collections.abc import Mapping
import copy

from core.exceptions import GenerationError
from core.pin_validator import PinAliases, PinAliasError
from core.validators import validate_klipper_pin


def motor_sections(user):
    try:
        count = int(user.get("z_motors") or 1)
    except (ValueError, TypeError):
        raise GenerationError("z_motors must be between 1 and 4.") from None
    if not 1 <= count <= 4:
        raise GenerationError("z_motors must be between 1 and 4.")
    return ("stepper_x", "stepper_y", "stepper_z",
            *(f"stepper_z{i}" for i in range(1, count)), "extruder")


def source_direction_pin(parsed, section):
    options = parsed.get(section)
    pin = options.get("dir_pin") if isinstance(options, Mapping) else None
    if (not isinstance(pin, str) or "TODO" in pin.upper()
            or not validate_klipper_pin(pin)
            or any(char in pin.strip().removeprefix("!") for char in "!^~")):
        raise GenerationError(f"[{section}]: a valid source dir_pin is required to choose motor direction.")
    return pin.strip()


def available_motor_sections(parsed, user):
    result = []
    for section in motor_sections(user):
        try:
            source_direction_pin(parsed, section)
        except GenerationError:
            continue
        result.append(section)
    return result


def _source_context(parsed, user, section):
    pin = source_direction_pin(parsed, section)
    try:
        identity = list(PinAliases(parsed).resolve(pin))
    except PinAliasError as exc:
        raise GenerationError(str(exc)) from exc
    fields = parsed[section]
    return {
        "board": user.get("board"), "dir_pin": pin, "dir_identity": identity,
        "step_pin": fields.get("step_pin"), "enable_pin": fields.get("enable_pin"),
        "socket": (user.get("z_socket_assignments") or {}).get(section, section),
    }


def direction_mode(parsed, user, section):
    choices = user.get("motor_directions", {})
    if not isinstance(choices, Mapping):
        raise GenerationError("motor_directions must be a mapping.")
    if section not in choices:
        return "keep"
    record = choices[section]
    if (not isinstance(record, Mapping) or record.get("mode") != "invert"
            or record.get("source") != _source_context(parsed, user, section)):
        raise GenerationError(f"[{section}]: motor direction source changed; review this motor again.")
    return "invert"


def effective_direction_pin(parsed, user, section):
    pin = source_direction_pin(parsed, section)
    return (pin[1:] if pin.startswith("!") else "!" + pin) if direction_mode(parsed, user, section) == "invert" else pin


def set_motor_direction(user, parsed, section, mode):
    if section not in motor_sections(user) or mode not in ("keep", "invert"):
        raise GenerationError("Invalid motor direction selection.")
    context = _source_context(parsed, user, section)
    choices = copy.deepcopy(user.get("motor_directions", {}))
    if not isinstance(choices, dict):
        raise GenerationError("motor_directions must be a mapping.")
    if mode == "keep":
        choices.pop(section, None)
    else:
        choices[section] = {"mode": "invert", "source": context}
    user["motor_directions"] = choices


def apply_motor_directions(pins, user):
    """Modify only the local render copy; repeated generation never toggles it."""
    choices = user.get("motor_directions", {})
    if not isinstance(choices, Mapping):
        raise GenerationError("motor_directions must be a mapping.")
    if set(choices) - set(motor_sections(user)):
        raise GenerationError("Motor direction selected for an inactive motor; review motor configuration.")
    # Compute all results before publishing any of them into the local copy.
    effective = {section: effective_direction_pin(pins, user, section) for section in choices}
    for section, pin in effective.items():
        pins[section]["dir_pin"] = pin
