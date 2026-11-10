"""TMC validators must recognize Klipper's whitespace section separator."""
import pytest
from core.exceptions import GenerationError
from core.profile_values import (validate_tmc_spi_options, validate_tmc_register_values,
    validate_tmc_current_settings, validate_tmc_auxiliary_options, validate_tmc_sense_resistors)


@pytest.mark.parametrize('separator', [' ', '\t'])
@pytest.mark.parametrize('validator,model,fields,reason', [
    (validate_tmc_current_settings, 'tmc2209', {'run_current': '-1'}, 'run_current'),
    (validate_tmc_spi_options, 'tmc2130', {'spi_speed': '1'}, 'spi_speed'),
    (validate_tmc_register_values, 'tmc2209', {'driver_iholddelay': '99'}, 'driver_iholddelay'),
    (validate_tmc_auxiliary_options, 'tmc2209', {'coolstep_threshold': '-1'}, 'coolstep_threshold'),
    (validate_tmc_sense_resistors, 'tmc2209', {'sense_resistor': '0'}, 'sense_resistor'),
    (validate_tmc_current_settings, 'tmc2240', {'rref': '1000', 'run_current': '0.5'}, 'rref'),
    (validate_tmc_current_settings, 'tmc2660', {'run_current': '0.05'}, 'run_current'),
])
def test_invalid_option_is_rejected_with_either_separator(validator, model, fields, reason, separator):
    with pytest.raises(GenerationError, match=reason):
        validator({model + separator + 'stepper_x': fields})


@pytest.mark.parametrize('separator', [' ', '\t'])
def test_valid_current_remains_accepted(separator):
    fields = {'run_current': '0.580'}
    sections = {'tmc2209' + separator + 'stepper_x': fields.copy()}
    validate_tmc_current_settings(sections)
    assert sections == {'tmc2209' + separator + 'stepper_x': fields}


@pytest.mark.parametrize('separator', [' ', '\t'])
@pytest.mark.parametrize('validator,model,fields', [
    (validate_tmc_spi_options, 'tmc2130', {'spi_speed': '4000000'}),
    (validate_tmc_register_values, 'tmc2209', {'driver_iholddelay': '5'}),
    (validate_tmc_auxiliary_options, 'tmc2209', {'coolstep_threshold': '0'}),
    (validate_tmc_sense_resistors, 'tmc2209', {'sense_resistor': '0.110'}),
    (validate_tmc_current_settings, 'tmc2240', {'rref': '12000', 'run_current': '0.5'}),
    (validate_tmc_current_settings, 'tmc2660', {'run_current': '0.5'}),
])
def test_valid_options_preserve_input(validator, model, fields, separator):
    sections = {model + separator + 'stepper_x': fields.copy()}
    validator(sections)
    assert sections == {model + separator + 'stepper_x': fields}


def test_unrelated_and_nameless_sections_are_ignored():
    validate_tmc_current_settings({'tmc2209': {'run_current': '-1'}, 'unrelated\titem': {'run_current': '-1'}})
