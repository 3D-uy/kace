"""Pinned direct MCU contracts for queued and variable-frequency PWM."""
import copy
import pytest

from core.exceptions import GenerationError
from core.pwm_output import validate_pwm_outputs


def validate(kind, fields, **sections):
    cfg = {"mcu": {}, **sections, kind + " Output": {"pin": "PA1", **fields}}
    original = copy.deepcopy(cfg)
    validate_pwm_outputs(cfg)
    assert cfg == original


@pytest.mark.parametrize("kind", ["pwm_tool", "pwm_cycle_time"])
@pytest.mark.parametrize("fields", [{}, {"cycle_time": "3"}, {"value": ".5"},
    {"scale": "255", "shutdown_value": "255"},
    {"pin": "!PA1", "shutdown_value": "1e-20"}])
def test_compatible_defaults_boundaries_and_fractional_start_survive(kind, fields):
    validate(kind, fields)


@pytest.mark.parametrize("kind", ["pwm_tool", "pwm_cycle_time"])
@pytest.mark.parametrize("option,value", [
    ("cycle_time", "0"), ("cycle_time", "3.000001"), ("cycle_time", "nan"),
    ("cycle_time", "inf"), ("scale", "0"), ("scale", "-1"), ("scale", "inf"),
    ("value", "-.1"), ("value", "1.1"), ("value", "nan"),
    ("shutdown_value", "-.1"), ("shutdown_value", "1.1"), ("shutdown_value", "nan"),
])
def test_consumed_numeric_bounds_and_finiteness(kind, option, value):
    with pytest.raises(GenerationError, match=option):
        validate(kind, {option: value})


@pytest.mark.parametrize("kind", ["pwm_tool", "pwm_cycle_time"])
@pytest.mark.parametrize("pin", ["PA1", "!PA1", "Toolhead:PA1", "!Toolhead:ALIAS"])
def test_software_shutdown_is_binary_after_scale_and_inversion(kind, pin):
    with pytest.raises(GenerationError, match="shutdown"):
        validate(kind, {"pin": pin, "scale": "255", "shutdown_value": "127.5"},
            **{"mcu Toolhead": {}, "board_pins names": {"mcu": "Toolhead", "aliases": "ALIAS=PA1"}})


@pytest.mark.parametrize("hardware", ["true", "on", "1"])
def test_tool_hardware_pwm_keeps_fractional_shutdown(hardware):
    validate("pwm_tool", {"hardware_pwm": hardware, "shutdown_value": ".5"})


def test_unused_hardware_field_does_not_change_variable_cycle_software_implementation():
    # The pinned loader separately rejects the unused option. It cannot turn
    # this software-only consumer into hardware PWM or bypass this bound.
    with pytest.raises(GenerationError, match="shutdown"):
        validate("pwm_cycle_time", {"hardware_pwm": "true", "shutdown_value": ".5"})


@pytest.mark.parametrize("value", ["0", ".499", "3.001", "nan", "inf", "bad"])
def test_explicit_watchdog_duration_has_pinned_bounds(value):
    with pytest.raises(GenerationError, match="maximum_mcu_duration"):
        validate("pwm_tool", {"maximum_mcu_duration": value})


@pytest.mark.parametrize("value", [".5", "3"])
def test_watchdog_boundaries_are_inclusive(value):
    validate("pwm_tool", {"maximum_mcu_duration": value})


@pytest.mark.parametrize("hardware", ["false", "true"])
def test_watchdog_compares_normalized_start_and_shutdown_in_both_branches(hardware):
    with pytest.raises(GenerationError, match="equal"):
        validate("pwm_tool", {"hardware_pwm": hardware, "maximum_mcu_duration": ".5", "value": ".5"})
    validate("pwm_tool", {"hardware_pwm": hardware, "maximum_mcu_duration": ".5",
        "pin": "!PA1", "value": "1e-20", "shutdown_value": "2e-20"})


def test_hardware_watchdog_accepts_equal_fractional_levels():
    validate("pwm_tool", {"hardware_pwm": "true", "maximum_mcu_duration": ".5",
        "scale": "255", "value": "127.5", "shutdown_value": "127.5"})


def test_bad_hardware_boolean_is_rejected():
    with pytest.raises(GenerationError, match="hardware_pwm"):
        validate("pwm_tool", {"hardware_pwm": "maybe"})


@pytest.mark.parametrize("kind", ["pwm_tool", "pwm_cycle_time"])
def test_direct_consumer_does_not_delegate_to_multi_pin(kind):
    with pytest.raises(GenerationError, match="direct MCU"):
        validate(kind, {"pin": "multi_pin:Outputs"}, **{"multi_pin Outputs": {"pins": "PA1,PA2"}})
    # A declared MCU named multi_pin is still a direct MCU; no virtual instance.
    validate(kind, {"pin": "multi_pin:PA1"}, **{"mcu multi_pin": {}})


@pytest.mark.parametrize("kind", ["pwm_tool", "pwm_cycle_time"])
def test_unknown_provider_and_missing_pin_remain_with_loader(kind):
    validate(kind, {"pin": "extension:OUT", "cycle_time": "10"})
    validate_pwm_outputs({kind + " incomplete": {"cycle_time": "10"}})


def test_macros_and_other_consumers_are_not_reinterpreted():
    validate_pwm_outputs({"gcode_macro M300": {"gcode": "SET_PIN PIN=beeper CYCLE_TIME=999"},
        "fan": {"pin": "PA1", "cycle_time": "10"}})
