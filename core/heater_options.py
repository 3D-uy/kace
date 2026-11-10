"""Static heater option bounds; no thermal tuning or physical certification."""
import math
import re
from collections.abc import Mapping

from core.exceptions import GenerationError
from core.thermistor import BUILTIN_ADC_SENSORS


# Sensor factories in Klipper fe4eb865. These are reporting periods in seconds,
# not electrical limits of the heater output or evidence of safe thermal tuning.
_FIXED_REPORT_TIMES = {
    **dict.fromkeys(BUILTIN_ADC_SENSORS, .300),
    **dict.fromkeys(("MAX6675", "MAX31855", "MAX31856", "MAX31865",
                    "temperature_mcu", "temperature_combined"), .300),
    "BME280": .8,
    "temperature_host": 1.,
}
_CONFIGURED_REPORT_TIMES = {
    "DS18B20": ("ds18_report_time", 3., 1., float),
    "LM75": ("lm75_report_time", .8, .5, float),
    **dict.fromkeys(("AHT10", "AHT1X", "AHT2X", "AHT3X"),
                    ("aht10_report_time", 30, 5, int)),
    **dict.fromkeys(("SI7013", "SI7020", "SI7021", "SHT21", "HTU21D"),
                    ("htu21d_report_time", 30, 5, int)),
    "SHT3X": ("sht3x_report_time", 1, 1, int),
}


def _sensor_report_time(sections, fields, name):
    """Resolve only known factories; other validators own references/order.

    Custom thermistor/ADC factories use PrinterADCtoTemperature's .300 period.
    Unknown sensors and fragments do not acquire an assumed reporting interval.
    Peripheral generation support is unchanged by recognition of this bound.
    """
    sensor = fields.get("sensor_type")
    if not isinstance(sensor, str):
        return None
    if sensor in _FIXED_REPORT_TIMES:
        return _FIXED_REPORT_TIMES[sensor]
    if sensor in _CONFIGURED_REPORT_TIMES:
        option, default, minimum, convert = _CONFIGURED_REPORT_TIMES[sensor]
        try:
            period = convert(str(fields.get(option, default)).strip())
            valid = period >= minimum and (convert is int or math.isfinite(period))
        except (TypeError, ValueError, OverflowError):
            valid = False
        if not valid:
            kind = "integer" if convert is int else "number"
            raise GenerationError(
                f"[{name}] {option} must be a finite {kind} >= {minimum} seconds.")
        return period
    for section in sections:
        parts = str(section).split()
        if (len(parts) >= 2 and parts[0] in ("thermistor", "adc_temperature")
                and " ".join(parts[1:]) == sensor):
            return .300
    return None


def validate_heater_options(sections):
    """Check supplied fields of Heater consumers without inventing missing ones.

    Explicit PWM periods cannot exceed the known sensor's reporting period.
    Output-provider limits and unknown factories remain with the pinned loader.
    PID coefficients may be zero or negative upstream; only finiteness is added
    here. Temperature targets, electrical ratings and tuning require other proof.
    """
    for name, fields in sections.items():
        if not (re.fullmatch(r"extruder\d*", name) or name == "heater_bed"
                or name.startswith("heater_generic ")) or not isinstance(fields, Mapping):
            continue
        options = ("min_temp", "max_temp", "min_extrude_temp", "max_power",
                   "smooth_time", "pwm_cycle_time")
        if fields.get("control") == "pid":
            options += ("pid_kp", "pid_ki", "pid_kd")
        elif fields.get("control") == "watermark":
            options += ("max_delta",)
        values = {}
        for option in options:
            if option not in fields:
                continue
            try:
                value = float(str(fields[option]).strip())
            except (TypeError, ValueError, OverflowError):
                raise GenerationError(f"[{name}] {option} must be finite.") from None
            if not math.isfinite(value):
                raise GenerationError(f"[{name}] {option} must be finite.")
            if option == "min_temp" and value < -273.15:
                raise GenerationError(f"[{name}] min_temp must be at least -273.15 Celsius.")
            if option in ("max_power", "smooth_time", "pwm_cycle_time", "max_delta") and value <= 0:
                raise GenerationError(f"[{name}] {option} must be greater than zero.")
            if option == "max_power" and value > 1:
                raise GenerationError(f"[{name}] max_power must be at most 1.")
            values[option] = value
        if {"min_temp", "max_temp"} <= values.keys() and values["max_temp"] <= values["min_temp"]:
            raise GenerationError(f"[{name}] max_temp must be greater than min_temp.")
        if "min_extrude_temp" in values:
            threshold = values["min_extrude_temp"]
            if (("min_temp" in values and threshold < values["min_temp"])
                    or ("max_temp" in values and threshold > values["max_temp"])):
                raise GenerationError(
                    f"[{name}] min_extrude_temp must be within min_temp and max_temp.")
        report_time = _sensor_report_time(sections, fields, name)
        if (report_time is not None and "pwm_cycle_time" in values
                and values["pwm_cycle_time"] > report_time):
            raise GenerationError(
                f"[{name}] pwm_cycle_time must be at most {report_time} seconds "
                f"for sensor {fields['sensor_type']!r}.")
