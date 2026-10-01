"""Dedicated suggestions must not bypass probe allocation checks."""
import copy
from unittest.mock import patch

import pytest

from core.wizard.steps.sensors import (
    _get_dedicated_probe_pin, _step_custom_probe_pin, _get_unused_pins,
    make_pin_validator_with_collision_check,
)
from tests.unit.test_firmware_pin_reservations import artifact, resumed_user, FINGERPRINT


@pytest.mark.parametrize("section,field", [
    ("stepper_x", "endstop_pin"), ("stepper_y", "endstop_pin"),
    ("stepper_z", "step_pin"), ("stepper_z", "enable_pin"),
    ("extruder", "heater_pin"), ("extruder", "sensor_pin"),
    ("fan", "pin"), ("display", "encoder_pins"),
])
def test_dedicated_input_cannot_reuse_another_consumer(section, field):
    parsed = {"bltouch": {"sensor_pin": "^PB8"}, section: {field: "!PB8"}}
    before = copy.deepcopy(parsed)
    with patch("core.wizard.steps.sensors._get_parsed", return_value=parsed):
        assert _get_dedicated_probe_pin({"mcu_type": "stm32"}) is None
    assert parsed == before


def test_dedicated_input_may_reuse_only_the_replaced_z_endstop():
    parsed = {"bltouch": {"sensor_pin": "^!PB8"}, "stepper_z": {"endstop_pin": "^PB8"}}
    with patch("core.wizard.steps.sensors._get_parsed", return_value=parsed):
        assert _get_dedicated_probe_pin({"mcu_type": "stm32"}) == ("PB8", True, True)


@pytest.mark.parametrize("token", ["^HEADER", "^mcu:HEADER", "^PB8"])
def test_alias_collision_cannot_bypass_dedicated_input_check(token):
    parsed = {"board_pins": {"aliases": "HEADER=PB8"},
              "bltouch": {"sensor_pin": token}, "fan": {"pin": "!PB8"}}
    with patch("core.wizard.steps.sensors._get_parsed", return_value=parsed):
        assert _get_dedicated_probe_pin({}) is None


@pytest.mark.parametrize("token", ["^GND", "toolhead:!PB8", "!^PB8", "~PB8"])
def test_reserved_alias_or_unrepresentable_modifiers_are_not_offered(token):
    parsed = {"board_pins": {"aliases": "GND=<GND>"}, "bltouch": {"sensor_pin": token}}
    with patch("core.wizard.steps.sensors._get_parsed", return_value=parsed):
        assert _get_dedicated_probe_pin({}) is None


@pytest.mark.parametrize("choice", ["PB10", "__manual__", "__back__"])
def test_unselected_dedicated_input_does_not_set_signal_flags(choice):
    from core.wizard.runner import _BACK
    answer = _BACK if choice == "__back__" else choice
    user = {"mcu_type": "stm32"}
    with patch("core.wizard.steps.sensors._get_parsed", return_value={
        "bltouch": {"sensor_pin": "^!PB8"}
    }), patch("core.wizard.steps.sensors._get_unused_pins", return_value=[("HEADER", "PB10")]), patch(
        "core.wizard.steps.sensors.autocomplete_select", return_value=answer
    ), patch("core.wizard.steps.sensors.simple_input", return_value="PB10"):
        _step_custom_probe_pin(user)
    assert not user.get("custom_probe_pullup")
    assert not user.get("custom_probe_inverted")


def test_menu_selection_is_revalidated_before_storing():
    parsed = {"bltouch": {"sensor_pin": "^PB8"}}
    user = {"mcu_type": "stm32"}
    def select(*_, **__):
        parsed["fan"] = {"pin": "PB8"}
        return "PB8"
    with patch("core.wizard.steps.sensors._get_parsed", return_value=parsed), patch(
        "core.wizard.steps.sensors.autocomplete_select", side_effect=select
    ):
        assert _step_custom_probe_pin(user) == "__retry__"
    assert "custom_probe_pin" not in user
    assert "custom_probe_pullup" not in user


def test_known_firmware_reservation_suppresses_suggestion(tmp_path):
    built = artifact(tmp_path, {"RESERVE_PINS_CAN": "PB8,PB9"})
    with patch("core.wizard.steps.sensors._get_parsed", return_value={"bltouch": {"sensor_pin": "^PB8"}}):
        assert _get_dedicated_probe_pin({"firmware_artifact": built}) is None


def test_default_validator_does_not_gain_custom_probe_reuse_exemptions():
    parsed = {"bltouch": {"sensor_pin": "^PB8"}, "stepper_z": {"endstop_pin": "PB10"}}
    with patch("core.wizard.steps.sensors._get_parsed", return_value=parsed):
        ordinary = make_pin_validator_with_collision_check({})
        custom = make_pin_validator_with_collision_check({}, for_custom_probe=True)
    assert ordinary("PB8") is not True
    assert ordinary("PB10") is not True
    assert custom("PB8") is True
    assert custom("PB10") is True


def test_secondary_mcu_with_same_gpio_is_not_removed_from_the_menu():
    parsed = {"bltouch": {"sensor_pin": "^PB8"},
              "board_pins": {"aliases": "ALIAS=PB8"},
              "board_pins tool": {"mcu": "toolhead", "aliases": "INPUT=PB8"}}
    with patch("core.wizard.steps.sensors._get_parsed", return_value=parsed), patch(
        "core.wizard.steps.sensors.autocomplete_select", return_value="toolhead:PB8"
    ) as select:
        user = {}
        assert _step_custom_probe_pin(user) == "done"
    values = [item["value"] for item in select.call_args.kwargs["choices"]]
    assert "PB8" in values and "toolhead:PB8" in values
    assert "ALIAS" not in values
    assert user["custom_probe_pin"] == "toolhead:PB8"
    assert user["custom_probe_pullup"] is False


@pytest.mark.parametrize("resume", [False, True])
def test_reserved_aliases_and_manual_pins_are_filtered_by_build_evidence(tmp_path, resume):
    built = artifact(tmp_path, {"RESERVE_PINS_USB": "PB8,PB9"})
    user = resumed_user(built) if resume else {"firmware_artifact": built}
    parsed = {"board_pins": {"aliases": "BUSY=PB8,FREE=PB10"}}
    with patch("core.wizard.steps.sensors._get_parsed", return_value=parsed):
        assert _get_unused_pins(user) == [("FREE", "PB10")]
        check = make_pin_validator_with_collision_check(user)
    assert "reserved by firmware" in check("BUSY")
    assert check("PB10") is True


def test_unavailable_firmware_metadata_is_visible_and_allows_back(tmp_path):
    built = artifact(tmp_path, payload=FINGERPRINT.encode())
    with patch("core.wizard.steps.sensors._get_parsed", return_value={"bltouch": {"sensor_pin": "PB8"}}):
        assert _get_dedicated_probe_pin({"firmware_artifact": built}) is None
        check = make_pin_validator_with_collision_check({"firmware_artifact": built})
    assert "identify dictionary" in check("PB10")
    assert check("<") is True


def test_valid_early_checkpoint_does_not_require_a_firmware_build_yet():
    from core.firmware_workflow import create_checkpoint
    user = {"board": "custom.cfg", "mcu_type": "stm32f446xx"}
    user["workflow_checkpoint"] = create_checkpoint(user)
    with patch("core.wizard.steps.sensors._get_parsed", return_value={}):
        check = make_pin_validator_with_collision_check(user)
    assert check("PB8") is True
    user["workflow_checkpoint"]["sequence"] += 1
    with patch("core.wizard.steps.sensors._get_parsed", return_value={}):
        check = make_pin_validator_with_collision_check(user)
    assert check("PB8") is not True


def test_firmware_change_during_menu_does_not_store_the_selection(tmp_path):
    from pathlib import Path
    built = artifact(tmp_path)
    user = {"firmware_artifact": built}
    def select(*_, **__):
        Path(built.path).write_bytes(b"changed while choosing")
        return "PB8"
    with patch("core.wizard.steps.sensors._get_parsed", return_value={"bltouch": {"sensor_pin": "^PB8"}}), patch(
        "core.wizard.steps.sensors.autocomplete_select", side_effect=select
    ):
        assert _step_custom_probe_pin(user) == "__retry__"
    assert "custom_probe_pin" not in user


def test_manual_pull_down_is_not_silently_converted_to_an_unbiased_pin():
    user = {}
    with patch("core.wizard.steps.sensors._get_parsed", return_value={}), patch(
        "core.wizard.steps.sensors.simple_input", return_value="~PB8"
    ):
        assert _step_custom_probe_pin(user) == "__retry__"
    assert "custom_probe_pin" not in user
