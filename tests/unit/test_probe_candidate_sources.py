"""A MCU family is not evidence that a GPIO is exposed on a board."""
from unittest.mock import patch

import pytest

from core.wizard.steps.sensors import _get_unused_pins, _step_custom_probe_pin


@pytest.mark.parametrize("mcu", [
    "atmega1284p", "atmega2560", "stm32f103", "stm32f446", "stm32h723",
    "rp2040", "lpc1768", "lpc1769", "linux", "unknown", "",
])
def test_mcu_family_without_board_aliases_offers_no_candidates(mcu):
    with patch("core.wizard.steps.sensors._get_parsed", return_value={}):
        assert _get_unused_pins({"mcu_type": mcu}) == []


def test_known_catalog_board_without_aliases_does_not_manufacture_pads():
    with patch("core.wizard.steps.sensors._get_parsed", return_value={}):
        assert _get_unused_pins({"board": "generic-bigtreetech-octopus-max-ez.cfg"}) == []


def test_only_declared_aliases_are_candidates_and_occupied_gpio_is_excluded():
    sections = {
        "board_pins header": {"aliases": "EXP1_1=PB5,EXP1_2=PB6,GND=<GND>"},
        "board_pins tool": {"mcu": "toolhead", "aliases": "INPUT=gpio5"},
        "fan": {"pin": "!PB5"},
    }
    with patch("core.wizard.steps.sensors._get_parsed", return_value=sections):
        assert _get_unused_pins({"mcu_type": "stm32"}) == [
            ("EXP1_2", "PB6"), ("toolhead:INPUT", "toolhead:gpio5")]


def test_no_candidates_reaches_manual_prompt_with_collision_validation():
    user = {"mcu_type": "rp2040"}
    with patch("core.wizard.steps.sensors._get_parsed", return_value={
        "fan": {"pin": "gpio5"}
    }), patch("core.wizard.steps.sensors.autocomplete_select") as select, patch(
        "core.wizard.steps.sensors.simple_input", return_value="^gpio6"
    ) as prompt:
        assert _step_custom_probe_pin(user) == "done"
        select.assert_not_called()
        check = prompt.call_args.kwargs["validate"]
        assert check("gpio5") is not True
        assert check("gpio6") is True
    assert user["custom_probe_pin"] == "gpio6"
    assert user["custom_probe_pullup"] is True


def test_no_candidates_manual_back_preserves_existing_selection():
    user = {"mcu_type": "stm32", "custom_probe_pin": "PB6"}
    with patch("core.wizard.steps.sensors._get_parsed", return_value={}), patch(
        "core.wizard.steps.sensors.simple_input", return_value="<"
    ):
        from core.wizard.runner import _BACK
        assert _step_custom_probe_pin(user) == _BACK
    assert user["custom_probe_pin"] == "PB6"
