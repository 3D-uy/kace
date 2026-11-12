"""Static heater limits follow the pin; numeric checks are not thermal tuning."""
import copy
import pytest
from core.exceptions import GenerationError


@pytest.mark.parametrize("section", ["extruder", "extruder1", "heater_bed", "heater_generic chamber"])
@pytest.mark.parametrize("option,value", [
    ("min_temp", "-274"), ("max_temp", "nan"), ("max_power", "0"),
    ("max_power", "1.01"), ("max_power", "inf"), ("smooth_time", "0"),
    ("pwm_cycle_time", "-1"), ("pwm_cycle_time", "bad"),
    ("pid_kp", "nan"), ("pid_ki", "inf"), ("pid_kd", "bad"),
])
def test_invalid_explicit_heater_values_rejected(section, option, value):
    from core.heater_options import validate_heater_options
    with pytest.raises(GenerationError, match=option):
        validate_heater_options({section: {"control": "pid", option: value}})


@pytest.mark.parametrize("minimum,maximum", [("10", "10"), ("11", "10")])
def test_maximum_must_exceed_known_minimum(minimum, maximum):
    from core.heater_options import validate_heater_options
    with pytest.raises(GenerationError, match="max_temp"):
        validate_heater_options({"heater_bed": {"min_temp": minimum, "max_temp": maximum}})


@pytest.mark.parametrize("section", ["extruder", "extruder1", "heater_bed", "heater_generic chamber"])
def test_compatible_values_are_preserved_without_invented_pid_or_pwm_limits(section):
    from core.heater_options import validate_heater_options
    sections = {section: {"control": "pid", "min_temp": "-273.15", "max_temp": "400",
        "max_power": "1", "smooth_time": ".001", "pwm_cycle_time": "5",
        "pid_kp": "-1", "pid_ki": "0", "pid_kd": "-2"}}
    original = copy.deepcopy(sections)
    validate_heater_options(sections)
    assert sections == original


def test_fragments_and_other_sensor_registries_do_not_acquire_heater_requirements():
    from core.heater_options import validate_heater_options
    sections = {"heater_bed": {"max_temp": "130"}, "extruder": {"min_temp": "0"},
        "heater_generic chamber": {}, "temperature_sensor room": {"max_power": "0"},
        "gcode_macro HEAT": {"gcode": "SET_HEATER_TEMPERATURE HEATER=extruder TARGET=300"}}
    original = copy.deepcopy(sections)
    validate_heater_options(sections)
    assert sections == original


def test_pid_parameters_are_only_consumed_when_pid_is_selected():
    from core.heater_options import validate_heater_options
    # Unused-option validation and the existing watermark/PID review remain
    # responsible for these fields; this function does not invent PID activation.
    validate_heater_options({"heater_bed": {"control": "watermark", "pid_ki": "nan"}})

