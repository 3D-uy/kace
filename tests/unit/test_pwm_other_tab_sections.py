"""Named PWM consumers retain provider checks with whitespace separators."""
import copy
import pytest

from core.exceptions import GenerationError
from core.pwm_output import validate_pwm_outputs
from core.sx1509_pwm import validate_sx1509_pwm


@pytest.mark.parametrize('family', ['pwm_tool', 'pwm_cycle_time'])
@pytest.mark.parametrize('separator', [' ', '\t'])
def test_queued_pwm_period(family, separator):
    name = family + separator + 'Audit'
    sections = {'mcu': {}, name: {'pin': 'PA1', 'cycle_time': '4'}}
    with pytest.raises(GenerationError, match='cycle_time'):
        validate_pwm_outputs(sections)
    sections[name]['cycle_time'] = '3'
    before = copy.deepcopy(sections)
    validate_pwm_outputs(sections)
    assert sections == before


@pytest.mark.parametrize('separator', [' ', '\t'])
def test_output_pin_sx1509_hardware_mode(separator):
    name = 'output_pin' + separator + 'Audit'
    sections = {'sx1509 Expander': {}, name: {'pin': 'sx1509_Expander:PIN_0', 'pwm': 'true', 'hardware_pwm': 'false'}}
    with pytest.raises(GenerationError, match='hardware_pwm'):
        validate_sx1509_pwm(sections)
    sections[name]['hardware_pwm'] = 'true'
    before = copy.deepcopy(sections)
    validate_sx1509_pwm(sections)
    assert sections == before


@pytest.mark.parametrize('separator', [' ', '\t'])
def test_heater_sx1509_unsupported(separator):
    sections = {'sx1509 Expander': {}, 'heater_generic' + separator + 'Audit': {'heater_pin': 'sx1509_Expander:PIN_0'}}
    with pytest.raises(GenerationError, match='cannot drive a Heater'):
        validate_sx1509_pwm(sections)


def test_empty_and_unrelated_sections_are_ignored():
    sections = {'': {}, 'extension\tAudit': {'pin': 'PA1', 'cycle_time': '4'}}
    validate_pwm_outputs(sections)
    validate_sx1509_pwm(sections)
