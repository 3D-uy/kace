"""Sensor periods constrain explicit Heater PWM, not fan cycle_time."""
import copy
import pytest

from core.exceptions import GenerationError
from core.heater_options import validate_heater_options
from core.thermistor import BUILTIN_ADC_SENSORS


FIXED = [(sensor, .300) for sensor in sorted(BUILTIN_ADC_SENSORS)] + [
    (sensor, .300) for sensor in ("MAX6675", "MAX31855", "MAX31856", "MAX31865",
        "temperature_mcu", "temperature_combined")
] + [("BME280", .8), ("temperature_host", 1.)]
VARIABLE = [
    ("DS18B20", "ds18_report_time", 3., 1., False),
    ("LM75", "lm75_report_time", .8, .5, False),
    *[(sensor, "aht10_report_time", 30, 5, True)
      for sensor in ("AHT10", "AHT1X", "AHT2X", "AHT3X")],
    *[(sensor, "htu21d_report_time", 30, 5, True)
      for sensor in ("SI7013", "SI7020", "SI7021", "SHT21", "HTU21D")],
    ("SHT3X", "sht3x_report_time", 1, 1, True),
]


@pytest.mark.parametrize("sensor,limit", FIXED)
def test_fixed_sensor_boundary_is_inclusive_and_preserved(sensor, limit):
    sections = {"heater_bed": {"sensor_type": sensor, "pwm_cycle_time": str(limit)}}
    original = copy.deepcopy(sections)
    validate_heater_options(sections)
    assert sections == original
    sections["heater_bed"]["pwm_cycle_time"] = str(limit + .000001)
    with pytest.raises(GenerationError, match="pwm_cycle_time"):
        validate_heater_options(sections)


@pytest.mark.parametrize("sensor,option,default,minimum,integer", VARIABLE)
def test_report_time_uses_the_selected_factory_and_explicit_value(sensor, option, default, minimum, integer):
    fields = {"sensor_type": sensor, "pwm_cycle_time": str(default)}
    validate_heater_options({"heater_generic chamber": fields})
    fields["pwm_cycle_time"] = str(default + .001)
    with pytest.raises(GenerationError, match="pwm_cycle_time"):
        validate_heater_options({"heater_generic chamber": fields})
    # A lower and a higher explicit report period must both override the default.
    for report in (minimum, default * 2):
        fields.update({option: str(report), "pwm_cycle_time": str(report)})
        validate_heater_options({"extruder1": fields})
        fields["pwm_cycle_time"] = str(report + .001)
        with pytest.raises(GenerationError, match="pwm_cycle_time"):
            validate_heater_options({"extruder1": fields})


@pytest.mark.parametrize("sensor,option,default,minimum,integer", VARIABLE)
@pytest.mark.parametrize("invalid", ["nan", "inf", "-inf", "bad", "0"])
def test_invalid_consumed_report_period_rejected(sensor, option, default, minimum, integer, invalid):
    with pytest.raises(GenerationError, match=option):
        validate_heater_options({"heater_bed": {"sensor_type": sensor, option: invalid}})


@pytest.mark.parametrize("sensor,option,default,minimum,integer", [r for r in VARIABLE if r[-1]])
def test_integer_report_period_does_not_truncate_decimals(sensor, option, default, minimum, integer):
    with pytest.raises(GenerationError, match=option):
        validate_heater_options({"heater_bed": {"sensor_type": sensor, option: "30.5"}})
    # getint has no floating-point upper bound. Later runtime/provider limits
    # remain separate; this static gate must not convert an integer to float.
    validate_heater_options({"heater_bed": {"sensor_type": sensor,
        option: str(10**400), "pwm_cycle_time": ".1"}})


@pytest.mark.parametrize("definition", ["thermistor Custom sensor", "adc_temperature Custom sensor"])
def test_custom_adc_factory_has_same_report_period(definition):
    sections = {definition: {}, "heater_generic chamber": {
        "sensor_type": "Custom sensor", "pwm_cycle_time": ".3"}}
    validate_heater_options(sections)
    sections["heater_generic chamber"]["pwm_cycle_time"] = ".301"
    with pytest.raises(GenerationError, match="pwm_cycle_time"):
        validate_heater_options(sections)


def test_no_sensor_inference_from_unrelated_options_or_fan_registry():
    sections = {"extruder": {"pwm_cycle_time": "5"},
        "heater_generic extension": {"sensor_type": "extension", "pwm_cycle_time": "5"},
        "heater_bed": {"sensor_type": "BME280", "pwm_cycle_time": ".8", "ds18_report_time": "nan"},
        "temperature_fan cooling": {"sensor_type": "Generic 3950", "cycle_time": "1"}}
    original = copy.deepcopy(sections)
    validate_heater_options(sections)
    assert sections == original


def test_omitted_pwm_is_not_inserted():
    sections = {"extruder": {"sensor_type": "Generic 3950"}}
    validate_heater_options(sections)
    assert "pwm_cycle_time" not in sections["extruder"]


@pytest.mark.parametrize("sensor,option,period", [
    ("DS18B20", "ds18_report_time", "1.125"),
    ("LM75", "lm75_report_time", ".625"),
])
def test_float_report_period_keeps_fractional_boundary(sensor, option, period):
    sections = {"heater_bed": {"sensor_type": sensor, option: period, "pwm_cycle_time": period}}
    original = copy.deepcopy(sections)
    validate_heater_options(sections)
    assert sections == original
    sections["heater_bed"]["pwm_cycle_time"] = str(float(period) + .000001)
    with pytest.raises(GenerationError, match="pwm_cycle_time"):
        validate_heater_options(sections)
