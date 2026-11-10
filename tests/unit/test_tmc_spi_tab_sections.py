"""SPI chain ownership must not depend on the section separator."""
import pytest
from core.exceptions import GenerationError
from core.tmc_spi import validate_spi_config, spi_transport_owners


def driver(model, separator, target, position, cs='PG13'):
    return (f'[{model}{separator}{target}]\ncs_pin: {cs}\nrun_current: .580\n'
            f'chain_length: 2\nchain_position: {position}\n')


@pytest.mark.parametrize('model', ['tmc2130', 'tmc5160', 'tmc2240'])
@pytest.mark.parametrize('separators', [(' ', '\t'), ('\t', ' '), ('\t', '\t')])
def test_duplicate_chain_position_rejected_with_tab(model, separators):
    text='[mcu]\nserial: /dev/null\n'+driver(model,separators[0],'stepper_x',1)+driver(model,separators[1],'stepper_y',1)
    with pytest.raises(GenerationError, match='duplicate chain_position'):
        validate_spi_config(text)


@pytest.mark.parametrize('model', ['tmc2130', 'tmc5160', 'tmc2240'])
@pytest.mark.parametrize('separators', [(' ', '\t'), ('\t', ' '), ('\t', '\t')])
def test_distinct_chain_positions_accepted_with_tab(model, separators):
    text='[mcu]\nserial: /dev/null\n'+driver(model,separators[0],'stepper_x',1)+driver(model,separators[1],'stepper_y',2)
    validate_spi_config(text)


def test_spi_owner_retains_literal_tabbed_name():
    data={'mcu': {}, 'tmc2130\tstepper_x': {'cs_pin': 'PG13','run_current': '.580'}}
    assert spi_transport_owners(data)=={'tmc2130\tstepper_x':'tmc2130\tstepper_x'}


def test_tmc2240_uart_remains_excluded_from_spi_owners():
    data={'mcu': {}, 'tmc2240\tstepper_x': {'uart_pin':'PG13','run_current':'.580'}}
    assert spi_transport_owners(data)=={}
