"""Fan auxiliary grammar and counter-provider boundaries, without hardware IO."""
from copy import deepcopy
import pytest

from core.exceptions import GenerationError
from core.fan_auxiliary import validate_fan_auxiliary


SECTIONS = ("fan", "fan_generic Aux", "heater_fan Aux", "controller_fan Aux", "temperature_fan Aux")


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("option,token", [
    ("tachometer_pin", "!PG12"), ("tachometer_pin", "^!PG12"),
    ("tachometer_pin", "^^PG12"), ("tachometer_pin", "~^PG12"),
    ("tachometer_pin", "PG 12"), ("tachometer_pin", "toolhead:!PG12"),
    ("tachometer_pin", "toolhead:PG12:extra"),
    ("enable_pin", "^PG13"), ("enable_pin", "~PG13"),
    ("enable_pin", "!!PG13"), ("enable_pin", "PG 13"),
    ("enable_pin", "toolhead:^PG13"), ("enable_pin", "!toolhead:!PG13"),
])
def test_invalid_auxiliary_pin_syntax_rejected(section, option, token):
    with pytest.raises(GenerationError, match=option):
        validate_fan_auxiliary({"mcu": {}, section: {option: token}})


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("provider,token", [
    ({"multi_pin Tach": {"pins": "PG12,PG14"}}, "multi_pin:Tach"),
    ({"sx1509 Exp": {}}, "sx1509_Exp:PIN_3"),
])
def test_counter_does_not_delegate_to_declared_output_providers(section, provider, token):
    with pytest.raises(GenerationError, match="direct MCU counter"):
        validate_fan_auxiliary({"mcu": {}, **provider, section: {"tachometer_pin": token}})


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("fields", [
    {"tachometer_pin": "PG12", "enable_pin": "PG13"},
    {"tachometer_pin": "^PG12", "enable_pin": "!PG13"},
    {"tachometer_pin": "~toolhead:PG12", "enable_pin": "!toolhead:PG13"},
    {"tachometer_pin": " ^ toolhead : PG12 ", "enable_pin": " ! toolhead : PG13 "},
    {"tachometer_pin": "^TACH_ALIAS", "enable_pin": "!ENABLE_ALIAS"},
])
def test_valid_grammar_and_cross_mcu_tokens_preserved(section, fields):
    sections = {"mcu": {}, "mcu toolhead": {}, section: fields}
    before = deepcopy(sections)
    validate_fan_auxiliary(sections)
    assert sections == before


@pytest.mark.parametrize("provider,token", [
    ({"multi_pin Enable": {"pins": "PG13,PG14"}}, "!multi_pin:Enable"),
    ({"sx1509 Exp": {}}, "!sx1509_Exp:PIN_3"),
])
def test_enable_pin_can_delegate_to_output_providers(provider, token):
    validate_fan_auxiliary({"mcu": {}, **provider, "fan": {"enable_pin": token}})


@pytest.mark.parametrize("chip", ["multi_pin", "sx1509_Exp"])
def test_named_mcu_is_not_inferred_to_be_virtual_from_its_name(chip):
    validate_fan_auxiliary({"mcu": {}, "mcu "+chip: {},
                           "multi_pin Tach": {"pins": "PG12"}, "sx1509 Exp": {},
                           "fan": {"tachometer_pin": chip+":PG12"}})


@pytest.mark.parametrize("token", ["extension:counter", "multi_pin:Missing", "sx1509_missing:PIN_3", "!toolhead:PG12", ""])
def test_unknown_provider_or_empty_pin_not_qualified_by_this_bounded_gate(token):
    validate_fan_auxiliary({"mcu": {}, "fan": {"tachometer_pin": token}})


def test_section_and_provider_names_remain_case_sensitive():
    validate_fan_auxiliary({"mcu": {}, "sx1509 Exp": {}, "fan": {"tachometer_pin": "sx1509_exp:PIN_3"}})
    validate_fan_auxiliary({"Fan": {"tachometer_pin": "!PG12"}})


def test_unrelated_sections_not_treated_as_fans():
    validate_fan_auxiliary({"extruder": {"enable_pin": "^PG13"}, "fan_genericity Other": {"tachometer_pin": "!PG12"}})
