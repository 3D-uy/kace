"""Heater fan references use Klipper heater-name whitespace semantics."""
import pytest
from core.exceptions import GenerationError
from core.hotend_fan import validate_heater_fan_options

@pytest.mark.parametrize('separator', [' ', '  ', '\t'])
def test_heater_generic_whitespace_keeps_reference(separator):
    text=f'[heater_generic{separator}Aux]\nheater_pin: PG11\n\n[heater_fan Audit]\npin: PG9\nheater: Aux\n'
    validate_heater_fan_options(text)

@pytest.mark.parametrize('reference', ['aux', 'Missing', 'Aux,'])
def test_unknown_or_empty_reference_still_rejected(reference):
    text=f'[heater_generic\tAux]\nheater_pin: PG11\n\n[heater_fan Audit]\npin: PG9\nheater: {reference}\n'
    with pytest.raises(GenerationError, match='heater references'):
        validate_heater_fan_options(text)
