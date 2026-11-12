"""PWM output checks depend on the declared provider, not the board clock."""
import copy
import pytest

from core.exceptions import GenerationError


FANS = ("fan", "fan_generic auxiliary", "controller_fan drivers",
        "heater_fan HeatBreak", "temperature_fan enclosure")


def validate(sections):
    from core.pwm_output import validate_pwm_outputs
    return validate_pwm_outputs(sections)


@pytest.mark.parametrize("name", FANS)
@pytest.mark.parametrize("pin", ["PA1", "!PA1"])
def test_fractional_shutdown_rejected_on_known_software_mcu(name, pin):
    with pytest.raises(GenerationError, match="shutdown"):
        validate({"mcu": {}, name: {"pin": pin, "shutdown_speed": ".5"}})


@pytest.mark.parametrize("name", FANS)
@pytest.mark.parametrize("shutdown", ["0", "1"])
def test_binary_shutdown_preserved_without_forcing_hardware_pwm(name, shutdown):
    sections = {"mcu": {}, name: {"pin": "PA1", "shutdown_speed": shutdown}}
    original = copy.deepcopy(sections)
    validate(sections)
    assert sections == original


@pytest.mark.parametrize("name", FANS)
def test_default_shutdown_matches_the_fan_family(name):
    sections = {"mcu": {}, name: {"pin": "PA1", "max_power": ".5"}}
    if name.startswith(("heater_fan ", "temperature_fan ")):
        with pytest.raises(GenerationError, match="shutdown"):
            validate(sections)
    else:
        validate(sections)


@pytest.mark.parametrize("name", FANS)
def test_shutdown_is_clamped_by_max_power_before_provider_validation(name):
    with pytest.raises(GenerationError, match="shutdown"):
        validate({"mcu": {}, name: {"pin": "PA1", "max_power": ".5", "shutdown_speed": "1"}})


@pytest.mark.parametrize("name", FANS)
def test_hardware_pwm_keeps_fractional_shutdown_without_certifying_pin(name):
    sections = {"mcu": {}, name: {"pin": "PA1", "max_power": ".5",
        "shutdown_speed": ".4", "hardware_pwm": "True"}}
    original = copy.deepcopy(sections)
    validate(sections)
    assert sections == original


@pytest.mark.parametrize("pin,valid", [("PA1", False), ("!PA1", True)])
def test_inversion_uses_upstream_float_subtraction_before_binary_check(pin, valid):
    sections = {"mcu": {}, "fan": {"pin": pin, "shutdown_speed": "1e-20"}}
    if valid:
        validate(sections)
    else:
        with pytest.raises(GenerationError, match="shutdown"):
            validate(sections)


@pytest.mark.parametrize("chip", ["toolhead", "replicape"])
def test_named_mcu_is_not_confused_with_a_virtual_provider(chip):
    with pytest.raises(GenerationError, match="shutdown"):
        validate({f"mcu {chip}": {}, "fan": {"pin": f"{chip}:PA1", "shutdown_speed": ".5"}})


def test_ordinary_pin_alias_resolves_to_declared_mcu():
    with pytest.raises(GenerationError, match="shutdown"):
        validate({"mcu Toolhead": {}, "board_pins names": {
            "mcu": "Toolhead", "aliases": "Cooling=PA1"},
            "fan": {"pin": "Toolhead:Cooling", "shutdown_speed": ".5"}})


@pytest.mark.parametrize("pin", ["unverified:PA1", "scale:PA1", "multi_pin:missing"])
def test_unknown_or_adc_provider_does_not_acquire_mcu_pwm_capabilities(pin):
    # Other gates/loader own missing and unsupported providers. This return
    # does not approve the complete configuration or certify the extension.
    validate({"mcu": {}, "adc_scaled scale": {"vref_pin": "PA2"},
        "fan": {"pin": pin, "shutdown_speed": ".5"}})


def test_nested_multi_pin_checks_every_known_mcu_leaf():
    sections = {"mcu": {}, "mcu Toolhead": {},
        "multi_pin Inner": {"pins": "Toolhead:PA2"},
        "multi_pin Outer": {"pins": "unverified:OUT, multi_pin:Inner"},
        "fan": {"pin": "multi_pin:Outer", "shutdown_speed": ".5"}}
    with pytest.raises(GenerationError, match="shutdown"):
        validate(sections)


def test_multi_pin_namespace_alias_does_not_invent_an_instance():
    sections = {"mcu": {}, "multi_pin Fans": {"pins": "PA1, PA2"},
        "board_pins names": {"mcu": "multi_pin", "aliases": "Group=Fans"},
        "fan": {"pin": "multi_pin:Group", "shutdown_speed": ".5"}}
    # PrinterPins leaves the instance token unchanged; multi_pin looks up
    # "multi_pin Group" literally. Its missing-provider error belongs to the
    # loader, not to an invented alias traversal in this PWM-specific gate.
    validate(sections)


@pytest.mark.parametrize("shutdown,valid", [("0", True), ("255", True), ("127.5", False)])
def test_output_pwm_shutdown_is_normalized_by_scale(shutdown, valid):
    sections = {"mcu": {}, "output_pin led": {"pin": "PA1", "pwm": "true",
        "scale": "255", "shutdown_value": shutdown}}
    if valid:
        original = copy.deepcopy(sections)
        validate(sections)
        assert sections == original
    else:
        with pytest.raises(GenerationError, match="shutdown"):
            validate(sections)


@pytest.mark.parametrize("hardware", ["false", "true"])
def test_output_cycle_has_the_consumers_nominal_three_second_limit(hardware):
    sections = {"mcu": {}, "output_pin led": {"pin": "PA1", "pwm": "true",
        "cycle_time": "3", "hardware_pwm": hardware}}
    validate(sections)
    sections["output_pin led"]["cycle_time"] = "3.000001"
    with pytest.raises(GenerationError, match="cycle_time"):
        validate(sections)


def test_fan_does_not_inherit_the_output_pin_nominal_period_limit():
    validate({"mcu": {}, "fan": {"pin": "PA1", "cycle_time": "1000", "shutdown_speed": "0"}})


def test_digital_output_and_incomplete_fragments_do_not_gain_pwm_requirements():
    validate({"mcu": {}, "output_pin signal": {"pin": "PA1", "shutdown_value": ".5"},
        "fan": {"shutdown_speed": ".5"}})
