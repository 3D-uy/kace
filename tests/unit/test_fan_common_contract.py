"""Shared Fan/FanTachometer contracts apply to every actual Fan consumer."""
from copy import deepcopy
import pytest
from core.exceptions import GenerationError
from core.part_fan import selected_part_fan, validate_part_fan_options

SECTIONS = ("fan", "fan_generic Aux", "heater_fan Aux", "controller_fan Aux", "temperature_fan Aux")


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("option,value", [
    ("max_power", "0"), ("max_power", "1.01"), ("max_power", "nan"),
    ("kick_start_time", "-1"), ("kick_start_time", "inf"),
    ("off_below", "-.01"), ("off_below", "1.01"),
    ("cycle_time", "0"), ("cycle_time", "nan"),
    ("shutdown_speed", "-.01"), ("shutdown_speed", "1.01"),
    ("hardware_pwm", "maybe"),
])
def test_common_scalars_reject_invalid_values_for_each_consumer(section, option, value):
    with pytest.raises(GenerationError, match=option):
        validate_part_fan_options({section: {option: value}})


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("option,value", [
    ("tachometer_ppr", "0"), ("tachometer_ppr", "1.5"), ("tachometer_ppr", "nan"),
    ("tachometer_poll_interval", "0"), ("tachometer_poll_interval", "-.01"),
    ("tachometer_poll_interval", "nan"), ("tachometer_poll_interval", "inf"),
])
def test_consumed_tachometer_values_are_validated(section, option, value):
    with pytest.raises(GenerationError, match=option):
        validate_part_fan_options({section: {"tachometer_pin": "^PG12", option: value}})


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("option,value", [("tachometer_ppr", "2"), ("tachometer_poll_interval", ".0015")])
def test_tachometer_options_require_their_actual_consumer_pin(section, option, value):
    with pytest.raises(GenerationError, match="requires tachometer_pin"):
        validate_part_fan_options({section: {option: value}})


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("values", [
    {}, {"max_power": "1", "kick_start_time": "0", "off_below": "0", "shutdown_speed": "0",
         "hardware_pwm": "false", "cycle_time": "0.01"},
    {"off_below": "1", "shutdown_speed": "1", "hardware_pwm": "YES"},
    {"enable_pin": "!PG13", "tachometer_pin": "^PG12"},
    {"tachometer_pin": "PG12", "tachometer_ppr": "1", "tachometer_poll_interval": ".0015"},
    {"tachometer_pin": "PG12", "tachometer_ppr": "1" + "0" * 400},
])
def test_valid_explicit_values_and_defaults_are_preserved_without_physical_caps(section, values):
    sections = {section: values}
    before = deepcopy(sections)
    validate_part_fan_options(sections)
    assert sections == before


def test_unrelated_section_options_are_not_interpreted_as_fan_options():
    validate_part_fan_options({"output_pin Aux": {"max_power": "0", "tachometer_ppr": "0"}})


@pytest.mark.parametrize("auxiliary", ["enable_pin", "tachometer_pin", "tachometer_ppr", "tachometer_poll_interval"])
def test_selected_source_auxiliary_preservation_stays_explicitly_unimplemented(auxiliary):
    with pytest.raises(GenerationError, match="not implemented"):
        selected_part_fan({"fan": {"pin": "PG10", auxiliary: "1"}}, "default")
