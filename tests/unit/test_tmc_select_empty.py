"""UART selector omission differs from an explicit zero-selector mux."""
from copy import deepcopy

import pytest

from core.exceptions import GenerationError
from core.profile_values import resolve_tmc_sections
from core.tmc_uart import validate_uart_config
from tests.unit.test_generator import _user


MODELS = ('tmc2208', 'tmc2209', 'tmc2240')


def uart(model, target='stepper_x', *, address=0, selector=None):
    fields = f'[{model} {target}]\nuart_pin: PG13\nrun_current: .4\nuart_address: {address}\n'
    if selector is not None:
        fields += f'select_pins: {selector}\n'
    return fields


@pytest.mark.parametrize('model', MODELS)
@pytest.mark.parametrize('selector', ['', '   ', '# empty list', '; empty list'])
def test_explicit_empty_selector_list_is_compatible(model, selector):
    validate_uart_config(uart(model, selector=selector))


@pytest.mark.parametrize('model', MODELS)
def test_omitted_selectors_remain_compatible(model):
    validate_uart_config(uart(model))


@pytest.mark.parametrize('model', ('tmc2209', 'tmc2240'))
def test_empty_mux_instances_can_share_rx_with_distinct_addresses(model):
    validate_uart_config(uart(model, selector='') + uart(model, 'stepper_y', address=1, selector=''))


@pytest.mark.parametrize('model', ('tmc2209', 'tmc2240'))
@pytest.mark.parametrize('first,second', [(None, ''), ('', None)])
def test_empty_and_omitted_mux_cannot_share_one_bus(model, first, second):
    with pytest.raises(GenerationError, match='shared UART'):
        validate_uart_config(uart(model, selector=first) + uart(model, 'stepper_y', address=1, selector=second))


@pytest.mark.parametrize('model', MODELS)
def test_empty_mux_does_not_allow_duplicate_address(model):
    with pytest.raises(GenerationError, match='unique address'):
        validate_uart_config(uart(model, selector='') + uart(model, 'stepper_y', selector=''))


@pytest.mark.parametrize('model', MODELS)
@pytest.mark.parametrize('selector', [',', ',PD0', 'PD0,', 'PD0,,PD1'])
def test_empty_token_inside_nonempty_selector_list_is_still_invalid(model, selector):
    with pytest.raises(GenerationError, match='select pin'):
        validate_uart_config(uart(model, selector=selector))


@pytest.mark.parametrize('model', ('tmc2208', 'tmc2209'))
@pytest.mark.parametrize('selector', ['', '  '])
def test_guided_source_resolution_preserves_explicit_empty_selector(model, selector):
    name = model+' stepper_x'
    board = {name: {'uart_pin': 'PG13', 'run_current': '.4', 'select_pins': selector}}
    original = deepcopy(board)
    result = resolve_tmc_sections(board, _user(driver_type=model.upper(), driver_mode='UART'))
    assert result[name]['select_pins'] == ''
    assert board == original


@pytest.mark.parametrize('option', ['uart_pin', 'tx_pin', 'uart_address', 'run_current'])
def test_other_blank_uart_options_are_not_authorized(option):
    board = {'tmc2209 stepper_x': {'uart_pin': 'PG13', option: ''}}
    with pytest.raises(GenerationError):
        resolve_tmc_sections(board, _user(driver_type='TMC2209', driver_mode='UART'))
