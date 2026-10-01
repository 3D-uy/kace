"""Behavior-based conservation of reviewed A/B cooling resources."""
import copy
import hashlib
import json
import math
from pathlib import Path

from core.exceptions import GenerationError


SOURCE = "_required_board_cooling_source"
# The data is an index of reviewed A/B source obligations, not per-board logic.
# BX retains its existing coupled panel/cooling contract in board_bx_panel.
REVIEWED = json.loads((Path(__file__).resolve().parent.parent / "data/required_cooling.json")
                      .read_text(encoding="utf-8"))["profiles"]


def capture_required_cooling(raw, filename):
    if filename not in REVIEWED:
        return None
    return {"profile": filename, "sha256": hashlib.sha256(raw.replace("\r\n", "\n").encode("utf-8")).hexdigest()}


def required_board_fans(parsed, profile=None):
    parsed = parsed or {}
    source = parsed.get(SOURCE)
    if source is None and profile not in REVIEWED:
        return {}
    if not isinstance(source, dict) or source.get("profile") not in REVIEWED:
        raise GenerationError("Board cooling requires active source evidence; reload the selected board.")
    name = source["profile"]
    if profile and profile != name:
        raise GenerationError("Board cooling source differs from the selected board; reload it.")
    entry = REVIEWED[name]
    if source.get("sha256") != entry["sha256"]:
        raise GenerationError("Board cooling source changed from the reviewed contract; review it before generation.")
    from core.hotend_fan import SOURCE_OPTIONS
    active = parsed.get(SOURCE_OPTIONS, {})
    expected = entry["sections"]
    for section, fields in expected.items():
        family = section.split()[0]
        if family not in ("heater_fan", "controller_fan"):
            raise GenerationError(f"Required board cooling [{section}] has unsupported dependencies; this cooling class needs review before publication.")
        if (not isinstance(active, dict) or active.get(section) != fields
                or not isinstance(parsed.get(section), dict)
                or any(parsed[section].get(key) != value for key, value in fields.items())):
            raise GenerationError(f"Board cooling [{section}] lacks matching active source evidence; reload the board.")
        cooling_settings(fields, family)
    for heater, pin in entry["heaters"].items():
        if parsed.get(heater, {}).get("heater_pin") != pin:
            raise GenerationError("Board cooling heater circuit changed; reload the selected board.")
    return copy.deepcopy(expected)


def _names(value):
    # Klipper permits an empty whole list, but preserves empty comma elements.
    # Do not normalize an invalid heater/motor reference into a valid contract.
    value = str(value).strip()
    names = tuple(n.strip() for n in value.split(",")) if value else ()
    if any(not name for name in names):
        raise GenerationError("Board cooling has an empty heater or stepper reference.")
    return names


def cooling_settings(fields, family):
    """Semantic scalar contract shared with selected fans; never convert roles."""
    from core.fan_preservation import _settings
    if family == "heater_fan":
        return _settings(fields, thermal=True)
    if family != "controller_fan":
        raise GenerationError("Required board cooling family is unsupported.")
    controller = {"heater", "stepper", "fan_speed", "idle_speed", "idle_timeout"}
    values = _settings({k: v for k, v in fields.items() if k not in controller}, thermal=False)
    try:
        speed = float(fields.get("fan_speed", 1.))
        idle = float(fields.get("idle_speed", speed))
        timeout = int(str(fields.get("idle_timeout", 30)))
    except (ValueError, TypeError, OverflowError) as exc:
        raise GenerationError("Board cooling controller settings are invalid.") from exc
    if not all(math.isfinite(v) and 0 <= v <= 1 for v in (speed, idle)) or timeout < 0:
        raise GenerationError("Board cooling controller settings are out of bounds.")
    values.update(fan_speed=speed, idle_speed=idle, idle_timeout=timeout,
                  heater=_names(fields.get("heater", "extruder")),
                  stepper=_names(fields["stepper"]) if "stepper" in fields else None)
    return values


def validate_cooling_references(name, fields, sections):
    """Require actual generated heaters/motors; do not synthesize absent hardware."""
    family = name.split()[0]
    heaters = _names(fields.get("heater", "extruder"))
    for heater in heaters:
        section = heater if heater in sections else "heater_generic " + heater
        if "heater_pin" not in sections.get(section, {}):
            raise GenerationError(f"Board cooling [{name}] requires available heater {heater}.")
    if family == "controller_fan" and "stepper" in fields:
        for motor in _names(fields["stepper"]):
            if "step_pin" not in sections.get(motor, {}):
                raise GenerationError(f"Board cooling [{name}] requires available stepper {motor}.")


def validate_required_cooling(parsed, sections, *, firmware_reservations=None):
    expected = required_board_fans(parsed)
    if not expected:
        return
    from core.board_auxiliary import _validate_exclusive_output_pins
    from core.pin_validator import PinAliases, PinAliasError
    from core.validators import questionary_fan_pin_validator
    try:
        before, after = PinAliases(parsed), PinAliases(sections)
        for name, fields in expected.items():
            actual = sections.get(name, {})
            pin = actual.get("pin")
            if (not isinstance(pin, str)
                    or questionary_fan_pin_validator(pin) is not True
                    or before.resolve(fields["pin"]) != after.resolve(pin)
                    or fields["pin"].startswith("!") != pin.strip().startswith("!")
                    or cooling_settings(fields, name.split()[0]) != cooling_settings(actual, name.split()[0])):
                raise GenerationError(f"Required board cooling [{name}] is missing or changed; regenerate from the reviewed source.")
            validate_cooling_references(name, actual, sections)
        entry = REVIEWED[parsed[SOURCE]["profile"]]
        for heater, expected_heater in entry["heaters"].items():
            actual_heater = sections.get(heater, {}).get("heater_pin", "")
            if (questionary_fan_pin_validator(actual_heater) is not True
                    or after.resolve(actual_heater) != before.resolve(expected_heater)
                    or actual_heater.strip().startswith("!") != expected_heater.startswith("!")):
                raise GenerationError(f"Required board cooling {heater} heater circuit is missing or changed.")
        _validate_exclusive_output_pins(sections, {n: [f["pin"]] for n, f in expected.items()},
                                       firmware_reservations, "Required board cooling")
    except PinAliasError as exc:
        raise GenerationError(f"Board cooling validation failed: {exc}") from exc
