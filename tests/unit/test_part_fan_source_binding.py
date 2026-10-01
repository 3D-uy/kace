"""A different spelling or selected fan role must not discard hardware settings."""
import json
from unittest.mock import patch

import pytest

from core.exceptions import GenerationError
from core.generator import generate_config
from core.part_fan import selected_part_fan
from core.scraper import parse_config
from core.wizard.steps.hardware import _step_fan_assignment
from tests.unit.test_generator import _parsed, _user


def board(raw):
    parsed = _parsed()
    parsed.update(parse_config(raw, keep_comments=True))
    return json.loads(json.dumps(parsed))  # Same source metadata after resume.


@pytest.mark.parametrize("choice", ["!PC5", "mcu:PC5", "COOLING"])
@pytest.mark.parametrize("options", ["max_power: 0.6", "enable_pin: PA8", "tachometer_pin: PA8"])
def test_source_alias_cannot_erase_options(tmp_path, choice, options):
    parsed = board(f"[fan]\npin: PC5\n{options}\n[board_pins aliases]\naliases: COOLING=PC5\n")
    with pytest.raises(GenerationError, match="fan.*(alias|polarity|source)"):
        generate_config(parsed, _user(fan_part_cooling_pin=choice), output_path=str(tmp_path / "printer.cfg"), verbose=False)
    assert not (tmp_path / "printer.cfg").exists()


@pytest.mark.parametrize("section,extra", [
    ("heater_fan heatbreak", ""),
    ("heater_fan heatbreak", "heater: heater_bed\nheater_temp: 40"),
    ("controller_fan drivers", ""),
    ("temperature_fan electronics", "sensor_type: temperature_mcu\ncontrol: watermark"),
    ("fan_generic aux", "max_power: 0.5"),
    ("fan_generic aux", "enable_pin: PA9"),
])
@pytest.mark.parametrize("choice", ["PA8", "!PA8", "mcu:PA8", "COOLING"])
def test_other_role_is_not_silently_made_manual(tmp_path, section, extra, choice):
    parsed = board(f"[fan]\npin: PC5\n[{section}]\npin: PA8\n{extra}\n[board_pins aliases]\naliases: COOLING=PA8\n")
    with pytest.raises(GenerationError, match="fan.*(role|alias|polarity)"):
        generate_config(parsed, _user(fan_part_cooling_pin=choice, fan_hotend_pin="none"), output_path=str(tmp_path / "printer.cfg"), verbose=False)
    assert not (tmp_path / "printer.cfg").exists()


@pytest.mark.parametrize("choice", [None, "default", "PC5"])
def test_ambiguous_active_gpio_rejected_even_for_default(choice):
    parsed = board("[fan]\npin: PC5\n[heater_fan aux]\npin: !mcu:PC5\n")
    with pytest.raises(GenerationError, match="fan.*ambiguous"):
        selected_part_fan(parsed, choice)


@pytest.mark.parametrize("choice", [None, "default", "PC5"])
def test_exact_source_still_preserves_all_scalar_options(choice):
    parsed = board("[fan]\npin: PC5\nmax_power: 0.6\nkick_start_time: 0.5\n")
    assert selected_part_fan(parsed, choice) == {"pin": "PC5", "max_power": "0.6", "kick_start_time": "0.5"}


@pytest.mark.parametrize("choice", ["PA8", "toolhead:PC5"])
def test_distinct_custom_socket_does_not_inherit_settings(choice):
    assert selected_part_fan(board("[fan]\npin: PC5\nmax_power: 0.6\n"), choice) == {"pin": choice}


def test_pin_only_manual_generic_can_be_explicitly_selected():
    parsed = board("[fan_generic aux]\npin: PA8\n")
    assert selected_part_fan(parsed, "PA8") == {"pin": "PA8"}


def test_commented_automatic_example_is_not_active_source():
    parsed = board("#[heater_fan aux]\n#pin: PA8\n#heater: heater_bed\n")
    assert selected_part_fan(parsed, "PA8") == {"pin": "PA8"}


def test_none_does_not_activate_an_automatic_fan():
    assert selected_part_fan(board("[heater_fan aux]\npin: PA8\n"), "none") is None


def test_wizard_excludes_active_automatic_and_tuned_generic_sources():
    raw = "[fan]\npin: PC5\n[heater_fan aux]\npin: PA8\n[controller_fan drivers]\npin: PA9\n[fan_generic tuned]\npin: PA10\nmax_power: 0.6\n[fan_generic manual]\npin: PA11\n"
    with patch("core.wizard.steps.hardware.numbered_select", side_effect=["default", "none"]) as choose:
        _step_fan_assignment({"board_raw_config": raw})
    values = [c.get("value") for c in choose.call_args_list[0].kwargs["choices"] if isinstance(c, dict)]
    assert "default" in values and "PA11" in values and "custom" in values
    assert not {"PA8", "PA9", "PA10"} & set(values)


def test_malformed_activity_evidence_is_not_ignored():
    parsed = _parsed()
    parsed["_active_fan_sections"] = []
    with pytest.raises(GenerationError, match="fan.*source"):
        selected_part_fan(parsed, "PC5")
