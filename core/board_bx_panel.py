"""Reviewed BX panel and cooling dependencies; no general profile compiler."""
import copy
import json
from pathlib import Path

from core.exceptions import GenerationError
from core.reviewed_source import matches_reviewed_source

SOURCE_PANEL = "_board_bx_panel_source"
PROFILE = "printer-biqu-bx-2021.cfg"
COOLING = {
    "heater_fan extruder_fan": {"pin": "PA6", "heater": "extruder"},
    "controller_fan controller_fan": {"pin": "PA7", "idle_timeout": "300"},
}


def reviewed_panel():
    path = Path(__file__).resolve().parent.parent / "data/bx_panel.json"
    return json.loads(path.read_text(encoding="utf-8"))


def capture_panel_source(raw, filename):
    if filename != PROFILE:
        return None
    entry = reviewed_panel()
    if not matches_reviewed_source(raw, entry["source_sha256"]):
        return None
    return copy.deepcopy(entry)


def selected_bx_panel(parsed):
    from core.board_auxiliary import SOURCE_ACTIVITY
    source = parsed.get(SOURCE_PANEL)
    pwm_source = parsed.get("_fixed_pwm_beeper_source", {})
    activity = parsed.get(SOURCE_ACTIVITY, {})
    inactive_screen = isinstance(activity, dict) and activity.get("output_pin screen") is False
    selected = (source is not None or
                (isinstance(pwm_source, dict) and pwm_source.get("profile") == PROFILE) or
                ("gcode_button lcd_button" in parsed and "output_pin screen" in parsed and not inactive_screen))
    if not selected:
        return {}
    entry = reviewed_panel()
    if source != entry:
        raise GenerationError("BX panel requires the complete reviewed source; reload the selected board.")
    if parsed.get("output_pin screen") != {"pin": "PB5", "value": "1"}:
        raise GenerationError("BX panel screen circuit changed; reload the selected board.")
    # The general scraper does not preserve multiline commands. Their complete
    # source is bound separately; hardware fields must also agree with that source.
    for name in ("neopixel led", "neopixel knob"):
        if parsed.get(name) != entry["sections"][name]:
            raise GenerationError(f"BX panel [{name}] source changed; reload the selected board.")
    button = parsed.get("gcode_button lcd_button")
    if not isinstance(button, dict) or button.get("pin") != "PH8":
        raise GenerationError("BX panel button pin changed; reload the selected board.")
    return copy.deepcopy(entry["sections"])


def _normalized(fields):
    return {key: tuple(line.strip() for line in value.splitlines() if line.strip())
            for key, value in fields.items()}


def selected_bx_cooling(parsed):
    """Finite cooling dependency of the existing, hash-bound BX source route."""
    if not selected_bx_panel(parsed or {}):
        return {}
    active = parsed.get("_active_fan_sections", {})
    for name, fields in COOLING.items():
        if not isinstance(active, dict) or active.get(name) != fields or parsed.get(name) != fields:
            raise GenerationError(f"BX cooling [{name}] requires matching active source evidence; reload the board.")
    if parsed.get("extruder", {}).get("heater_pin") != "PC4":
        raise GenerationError("BX cooling extruder circuit changed; reload the selected board.")
    return copy.deepcopy(COOLING)


def render_bx_panel(parsed, text):
    from core.pin_validator import _read_pin_config
    sections = _read_pin_config(text)[0]
    panel = {**selected_bx_panel(parsed), **selected_bx_cooling(parsed)}
    for name, fields in panel.items():
        if name in sections:
            if _normalized(sections[name]) != _normalized(fields):
                raise GenerationError(f"BX panel [{name}] conflicts with the generated configuration.")
            continue
        text += "\n[" + name + "]\n"
        for key, value in fields.items():
            text += key + ": " + value.replace("\n", "\n    ") + "\n"
    return text


def validate_bx_panel(parsed, sections, *, firmware_reservations=None):
    from core.board_auxiliary import _validate_exclusive_output_pins
    expected = selected_bx_panel(parsed or {})
    for name, fields in expected.items():
        if name not in sections or _normalized(sections[name]) != _normalized(fields):
            raise GenerationError(f"BX panel [{name}] is missing or changed; regenerate from the reviewed board source.")
    cooling = selected_bx_cooling(parsed)
    for name, fields in cooling.items():
        if name not in sections or _normalized(sections[name]) != _normalized(fields):
            raise GenerationError(f"BX cooling [{name}] is missing or changed; regenerate from the reviewed board source.")
    if cooling and (sections.get("extruder", {}).get("heater_pin") != "PC4"
                    or not any(name.startswith("stepper_") for name in sections)):
        raise GenerationError("BX cooling requires its extruder circuit and configured steppers.")
    # Fixed panel and cooling pins are exclusive, including the button input.
    pins = {name: [fields["pin"]] for name, fields in {**expected, **cooling}.items() if "pin" in fields}
    _validate_exclusive_output_pins(sections, pins, firmware_reservations, "BX panel")
