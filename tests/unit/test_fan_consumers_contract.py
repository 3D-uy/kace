"""Pinned consumer bounds; runtime and physical safety remain separate."""
import pytest

from core.exceptions import GenerationError
from core.fan_consumers import validate_fan_consumers


TEMP = {"min_temp": "0", "max_temp": "100", "control": "watermark"}


@pytest.mark.parametrize("option,value", [
    ("fan_speed", "-.1"), ("fan_speed", "1.1"), ("fan_speed", "nan"),
    ("idle_speed", "-.1"), ("idle_speed", "1.1"), ("idle_speed", "inf"),
    ("idle_timeout", "-1"), ("idle_timeout", "1.5"), ("idle_timeout", "nan"),
])
def test_controller_rejects_invalid_consumer_values(option, value):
    with pytest.raises(GenerationError, match=option):
        validate_fan_consumers({"controller_fan Audit": {option: value}})


@pytest.mark.parametrize("fields", [
    {}, {"fan_speed": "0", "idle_speed": "0", "idle_timeout": "0"},
    {"fan_speed": "1", "idle_timeout": "30"},
    {"heater": "", "stepper": ""},
    {"heater": "extension_heater", "stepper": "extension_motor"},
])
def test_controller_defaults_zero_and_deferred_registries_are_preserved(fields):
    validate_fan_consumers({"controller_fan Audit": fields})


@pytest.mark.parametrize("option,value", [
    ("min_temp", "-274"), ("min_temp", "nan"), ("max_temp", "0"),
    ("max_temp", "inf"), ("max_speed", "0"), ("max_speed", "1.1"),
    ("max_speed", "nan"), ("min_speed", "-.1"), ("min_speed", "1.1"),
    ("min_speed", "inf"), ("target_temp", "-1"), ("target_temp", "101"),
    ("target_temp", "nan"), ("max_delta", "0"), ("max_delta", "inf"),
    ("control", "bangbang"), ("control", "PID"),
])
def test_temperature_rejects_invalid_consumed_values(option, value):
    with pytest.raises(GenerationError, match=option):
        validate_fan_consumers({"temperature_fan Audit": dict(TEMP, **{option: value})})


@pytest.mark.parametrize("missing", ["min_temp", "max_temp", "control"])
def test_temperature_requires_constructor_options(missing):
    fields = dict(TEMP); del fields[missing]
    with pytest.raises(GenerationError, match=missing):
        validate_fan_consumers({"temperature_fan Audit": fields})


@pytest.mark.parametrize("option", ["pid_kp", "pid_ki", "pid_kd"])
@pytest.mark.parametrize("value", [None, "nan", "inf"])
def test_pid_requires_finite_coefficients(option, value):
    fields = dict(TEMP, control="pid", pid_kp="1", pid_ki="0", pid_kd="-1")
    if value is None:
        del fields[option]
    else:
        fields[option] = value
    with pytest.raises(GenerationError, match=option):
        validate_fan_consumers({"temperature_fan Audit": fields})


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf"])
def test_pid_derivative_period_must_be_finite_positive(value):
    with pytest.raises(GenerationError, match="pid_deriv_time"):
        validate_fan_consumers({"temperature_fan Audit": dict(TEMP, control="pid",
            pid_kp="1", pid_ki="0", pid_kd="-1", pid_deriv_time=value)})


@pytest.mark.parametrize("fields", [
    {}, {"min_speed": ".8", "max_speed": ".2"}, {"min_temp": "50"},
    {"min_temp": "-273.15"}, {"max_temp": "20"},
    {"target_temp": "0", "min_speed": "0"},
    {"control": "pid", "pid_kp": "-1", "pid_ki": "0", "pid_kd": "-1"},
])
def test_accepted_configuration_semantics_are_not_replaced_by_runtime_rules(fields):
    validate_fan_consumers({"temperature_fan Audit": dict(TEMP, **fields)})


def test_explicit_target_checked_but_omitted_default_not_rebounded():
    validate_fan_consumers({"temperature_fan Audit": dict(TEMP, min_temp="50")})
    for target in ("0", "40"):
        with pytest.raises(GenerationError, match="target_temp"):
            validate_fan_consumers({"temperature_fan Audit": dict(TEMP, min_temp="50", target_temp=target)})
