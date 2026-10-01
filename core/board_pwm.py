"""Reviewed fixed-cycle beepers, not general-purpose PWM or macro support."""
import json
import math
from pathlib import Path

from core.exceptions import GenerationError
from core.reviewed_source import matches_reviewed_source

SOURCE_FIXED_PWM = "_fixed_pwm_beeper_source"


def reviewed_beepers():
    path = Path(__file__).resolve().parent.parent / "data/fixed_pwm_beepers.json"
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)["profiles"]


def fixed_pwm_source(raw, filename):
    """Bind qualification to reviewed source text, including its consumers.

    A familiar beeper name alone does not prove the absence of an obsolete M300
    or dynamic-frequency consumer. Modified sources require a separate review.
    """
    entry = reviewed_beepers().get(filename)
    if entry and matches_reviewed_source(raw, entry["source_sha256"]):
        return {"profile": filename, "source_sha256": entry["source_sha256"]}
    return None


def fixed_pwm_settings(fields, section):
    from core.validators import questionary_fan_pin_validator
    if (not isinstance(fields, dict) or not {"pin", "pwm", "cycle_time"} <= fields.keys()
            or set(fields) - {"pin", "pwm", "cycle_time", "hardware_pwm", "scale", "value", "shutdown_value"}):
        raise GenerationError(f"[{section}] requires explicit pin/pwm/cycle_time and only fixed PWM options.")
    if (str(fields["pwm"]).strip().lower() not in ("true", "yes", "on", "1")
            or str(fields.get("hardware_pwm", "false")).strip().lower() not in ("false", "no", "off", "0")):
        raise GenerationError(f"[{section}] requires software PWM; hardware PWM is not qualified.")
    if not isinstance(fields["pin"], str) or questionary_fan_pin_validator(fields["pin"]) is not True:
        raise GenerationError(f"[{section}] requires one output pin with optional ! inversion.")
    try:
        cycle, scale, start, shutdown = (float(fields.get(k, default)) for k, default in
            (("cycle_time", None), ("scale", "1"), ("value", "0"), ("shutdown_value", "0")))
    except (ValueError, TypeError, OverflowError) as exc:
        raise GenerationError(f"[{section}] requires finite PWM settings.") from exc
    if (not all(math.isfinite(v) for v in (cycle, scale, start, shutdown))
            or not 0 < cycle <= 3 or not scale > 0 or not 0 <= start <= scale or not 0 <= shutdown <= scale):
        raise GenerationError(f"[{section}] invalid cycle, scale or start/shutdown level.")
    # Scale is part of SET_PIN's public contract even for equal normalized levels.
    return cycle, scale, start / scale, shutdown / scale


def selected_fixed_pwm_beepers(parsed_board):
    from core.board_auxiliary import SOURCE_ACTIVITY, SOURCE_OPTIONS
    from core.pin_validator import PinAliases, PinAliasError
    source = parsed_board.get(SOURCE_FIXED_PWM)
    if not isinstance(source, dict) or not isinstance(source.get("profile"), str):
        return {}
    entry = reviewed_beepers().get(source.get("profile"))
    if not entry or source.get("source_sha256") != entry["source_sha256"]:
        return {}
    name = entry["section"]
    activity, active = parsed_board.get(SOURCE_ACTIVITY), parsed_board.get(SOURCE_OPTIONS)
    fields = parsed_board.get(name)
    options = active.get(name) if isinstance(active, dict) else None
    if (not isinstance(activity, dict) or activity.get(name) is not True
            or not isinstance(options, list) or any(not isinstance(k, str) for k in options)
            or not isinstance(fields, dict) or any(k not in fields for k in options)
            or {k: fields[k] for k in options} != entry["options"]):
        raise GenerationError(f"[{name}] reviewed PWM source is missing or changed; reload the selected board.")
    try:
        if PinAliases(parsed_board).resolve(fields["pin"]) != ("mcu", entry["physical_pin"]):
            raise GenerationError(f"[{name}] reviewed PWM alias is missing or changed; reload the selected board.")
    except PinAliasError as exc:
        raise GenerationError(f"[{name}] invalid PWM source alias: {exc}") from exc
    selected = {k: fields[k] for k in options}
    fixed_pwm_settings(selected, name)
    return {name: selected}


def validate_fixed_pwm_outputs(sections, expected, *, firmware_reservations=None):
    from core.board_auxiliary import _validate_exclusive_output_pins
    outputs = {}
    for name in expected:
        if name not in sections:
            raise GenerationError(f"Selected-board electrical dependency [{name}] is missing or changed.")
        fixed_pwm_settings(sections[name], name)
        outputs[name] = [sections[name]["pin"]]
    _validate_exclusive_output_pins(sections, outputs, firmware_reservations, "Fixed PWM beeper")
