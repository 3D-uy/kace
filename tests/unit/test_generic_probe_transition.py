"""Replacing the probe input must not collide with itself or free other hardware."""
from unittest.mock import patch
import pytest
from core.wizard.steps.sensors import make_pin_validator_with_collision_check, _step_custom_probe_pin
from tests.unit.test_firmware_pin_reservations import artifact, resumed_user


@pytest.mark.parametrize("token", ["PA4", "^!PE4", "!PG9", "toolhead:gpio5", "^HEADER"])
def test_custom_transition_can_reuse_existing_probe_input(token):
    parsed = {"probe": {"pin": token}, "board_pins": {"aliases": "HEADER=PB8"}}
    with patch("core.wizard.steps.sensors._get_parsed", return_value=parsed):
        assert make_pin_validator_with_collision_check({}, for_custom_probe=True)(token) is True
        assert make_pin_validator_with_collision_check({})(token) is not True


@pytest.mark.parametrize("section,field", [("stepper_x", "endstop_pin"), ("stepper_z", "step_pin"),
    ("extruder", "heater_pin"), ("extruder", "sensor_pin"), ("fan", "pin"),
    ("bltouch", "control_pin"), ("output_pin power", "pin"), ("display", "encoder_pins")])
def test_other_consumers_still_block_the_same_probe_gpio(section, field):
    parsed = {"probe": {"pin": "^HEADER"}, "board_pins": {"aliases": "HEADER=PB8"},
              section: {field: "!PB8"}}
    with patch("core.wizard.steps.sensors._get_parsed", return_value=parsed):
        result = make_pin_validator_with_collision_check({}, for_custom_probe=True)("PB8")
    assert result is not True
    assert section.split()[0] in result or "stepper" in result


@pytest.mark.parametrize("resume", [False, True])
def test_existing_probe_cannot_bypass_firmware_reservations(tmp_path, resume):
    built = artifact(tmp_path, {"RESERVE_PINS_USB": "PB8,PB9"})
    user = resumed_user(built) if resume else {"firmware_artifact": built}
    with patch("core.wizard.steps.sensors._get_parsed", return_value={"probe": {"pin": "^PB8"}}):
        result = make_pin_validator_with_collision_check(user, for_custom_probe=True)("PB8")
    assert "reserved by firmware" in result


def test_manual_choice_reuses_pin_and_keeps_signal_flags():
    user = {}
    with patch("core.wizard.steps.sensors._get_parsed", return_value={"probe": {"pin": "^!PB8"}}), \
         patch("core.wizard.steps.sensors.simple_input", return_value="^!PB8"):
        assert _step_custom_probe_pin(user) == "done"
    assert user["custom_probe_pin"] == "PB8"
    assert user["custom_probe_pullup"] is True and user["custom_probe_inverted"] is True


def test_new_consumer_during_prompt_is_rechecked():
    parsed = {"probe": {"pin": "PB8"}}
    user = {}
    def answer(*args, **kwargs):
        parsed["fan"] = {"pin": "PB8"}
        return "PB8"
    with patch("core.wizard.steps.sensors._get_parsed", return_value=parsed), \
         patch("core.wizard.steps.sensors.simple_input", side_effect=answer):
        assert _step_custom_probe_pin(user) == "__retry__"
    assert "custom_probe_pin" not in user
