"""SX1509 has its own PWM callback rules, not MCU software PWM limits."""
import copy
import pytest

from core.exceptions import GenerationError
from core.sx1509_pwm import validate_sx1509_pwm


FANS = ("fan", "fan_generic Aux", "heater_fan Aux", "controller_fan Aux", "temperature_fan Aux")


def sections(name, fields):
    return {"mcu": {}, "sx1509 Expander": {"i2c_address": "62", "i2c_bus": "i2c1"}, name: fields}


@pytest.mark.parametrize("name", FANS + ("output_pin Aux",))
@pytest.mark.parametrize("hardware", [None, "false", "0"])
def test_sx_pwm_needs_explicit_hardware_mode(name, hardware):
    fields = {"pin": "sx1509_Expander:PIN_0"}
    if name.startswith("output_pin "):
        fields["pwm"] = "true"
    if hardware is not None:
        fields["hardware_pwm"] = hardware
    with pytest.raises(GenerationError, match="hardware_pwm"):
        validate_sx1509_pwm(sections(name, fields))


@pytest.mark.parametrize("name", FANS + ("output_pin Aux",))
@pytest.mark.parametrize("hardware", ["true", "yes", "1", "on"])
def test_hardware_fractional_levels_and_inversion_remain_compatible(name, hardware):
    fields = {"pin": "!sx1509_Expander:PIN_0", "hardware_pwm": hardware}
    if name.startswith("output_pin "):
        fields.update(pwm="true", scale="255", shutdown_value="127.5", value="63.75")
    else:
        fields["shutdown_speed"] = ".5"
    config = sections(name, fields); original = copy.deepcopy(config)
    validate_sx1509_pwm(config)
    assert config == original


@pytest.mark.parametrize("name", ["extruder", "extruder1", "heater_bed", "heater_generic Chamber"])
@pytest.mark.parametrize("hardware", ["false", "true"])
def test_sx_heater_cannot_override_the_required_watchdog(name, hardware):
    with pytest.raises(GenerationError, match="cannot drive a Heater"):
        validate_sx1509_pwm(sections(name, {
            "heater_pin": "sx1509_Expander:PIN_0", "hardware_pwm": hardware}))


@pytest.mark.parametrize("cycle,valid", [(".1", True), ("3", True), ("3.000001", False)])
def test_output_pin_uses_the_underlying_mcu_nominal_ceiling(cycle, valid):
    config = sections("output_pin Aux", {"pin": "sx1509_Expander:PIN_0", "pwm": "true",
        "hardware_pwm": "true", "cycle_time": cycle})
    if valid:
        validate_sx1509_pwm(config)
    else:
        with pytest.raises(GenerationError, match="cycle_time"):
            validate_sx1509_pwm(config)


def test_fan_does_not_acquire_the_output_pin_period_ceiling():
    validate_sx1509_pwm(sections("fan", {"pin": "sx1509_Expander:PIN_0",
        "hardware_pwm": "true", "cycle_time": "1000", "shutdown_speed": ".5"}))


def test_nested_multi_pin_checks_every_declared_sx_leaf():
    config = sections("fan", {"pin": "multi_pin Outer"})
    config.update({"multi_pin Inner": {"pins": "sx1509_Expander:PIN_0"},
        "multi_pin Outer": {"pins": "PA0, multi_pin:Inner"}})
    config["fan"]["pin"] = "multi_pin:Outer"
    with pytest.raises(GenerationError, match="hardware_pwm"):
        validate_sx1509_pwm(config)
    config["fan"]["hardware_pwm"] = "true"
    validate_sx1509_pwm(config)


def test_nominal_period_uses_first_provider_and_does_not_infer_unknown_chips():
    config = sections("output_pin Aux", {"pin": "multi_pin Group", "pwm": "true",
        "hardware_pwm": "true", "cycle_time": "4"})
    config["output_pin Aux"]["pin"] = "multi_pin:Group"
    config["multi_pin Group"] = {"pins": "extension:OUT, sx1509_Expander:PIN_0"}
    validate_sx1509_pwm(config)  # The first provider's get_mcu is not demonstrated.
    config["multi_pin Group"]["pins"] = "sx1509_Expander:PIN_0, extension:OUT"
    with pytest.raises(GenerationError, match="cycle_time"):
        validate_sx1509_pwm(config)


@pytest.mark.parametrize("pin", ["sx1509_missing:PIN_0", "sx1509_expander:PIN_0", "scale:PIN_0", "multi_pin:Alias"])
def test_unknown_and_virtual_aliases_do_not_acquire_sx_capabilities(pin):
    config = sections("fan", {"pin": pin})
    config.update({"multi_pin Group": {"pins": "sx1509_Expander:PIN_0"},
        "board_pins aliases": {"mcu": "multi_pin", "aliases": "Alias=Group"},
        "adc_scaled scale": {"vref_pin": "PA0"}})
    validate_sx1509_pwm(config)


def test_named_mcu_is_not_an_sx_provider_by_name_resemblance():
    validate_sx1509_pwm({"mcu sx1509_Expander": {},
        "fan": {"pin": "sx1509_Expander:PA0", "hardware_pwm": "false"}})


def test_digital_outputs_and_fragments_remain_outside_this_pwm_gate():
    validate_sx1509_pwm(sections("output_pin Aux", {"pin": "sx1509_Expander:PIN_0", "pwm": "false"}))
    validate_sx1509_pwm(sections("fan", {"max_power": ".5"}))


def test_double_inversion_and_missing_multi_are_not_falsely_resolved():
    config = sections("fan", {"pin": "!multi_pin Group"})
    config["fan"]["pin"] = "!multi_pin:Group"
    config["multi_pin Group"] = {"pins": "!sx1509_Expander:PIN_0"}
    validate_sx1509_pwm(config)  # !! syntax is rejected by the pinned pin parser.
