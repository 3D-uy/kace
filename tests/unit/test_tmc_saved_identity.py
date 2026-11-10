"""TMC sections retain exact identity across active and autosaved settings."""
import pytest

from core.managed_config import ManagedConfigPlan, _section_options, effective_hardware_text
from core.pin_validator import _read_pin_config
from core.scraper import parse_config
from tests.unit.test_saved_sensor_case import block, saved


def effective(active, autosave, source):
    files = {'printer.cfg': (active + autosave).encode()}
    if source == 'include':
        files = {'printer.cfg': ('[include user.cfg]\n' + autosave).encode(),
                 'user.cfg': b'[include nested.cfg]\n', 'nested.cfg': active.encode()}
    return _read_pin_config(effective_hardware_text(
        ManagedConfigPlan(artifacts=(), source_files=tuple(files.items()))))[0]


@pytest.mark.parametrize('sep', [' ', '\t'])
@pytest.mark.parametrize('source', ['root', 'include'])
def test_saved_option_joins_exact_mixed_case_header(sep, source):
    name = f'tmc2209{sep}extruder_stepper Mix'
    active = {'uart_pin': 'PA1', 'run_current': '0.5'}
    assert effective(block(name, active), saved(name, {'uart_address': '3'}), source) == {
        name: {**active, 'uart_address': '3'}}


@pytest.mark.parametrize('sep', [' ', '\t'])
@pytest.mark.parametrize('source', ['root', 'include'])
def test_active_option_wins_only_same_header(sep, source):
    name = f'tmc2209{sep}extruder_stepper Mix'
    active = {'uart_pin': 'PA1', 'run_current': '0.5', 'uart_address': '2'}
    assert effective(block(name, active), saved(name, {'UART_ADDRESS': '3'}), source) == {name: active}


@pytest.mark.parametrize('sep', [' ', '\t'])
def test_case_distinct_active_headers_keep_independent_saved_fields(sep):
    upper = f'tmc2209{sep}extruder_stepper Mix'
    lower = f'tmc2209{sep}extruder_stepper mix'
    one = {'uart_pin': 'PA1', 'run_current': '0.5'}
    two = {'uart_pin': 'PA2', 'run_current': '0.4', 'uart_address': '2'}
    assert effective(block(upper, one) + block(lower, two), saved(upper, {'uart_address': '3'}), 'root') == {
        upper: {**one, 'uart_address': '3'}, lower: two}


@pytest.mark.parametrize('parse', [parse_config, _section_options], ids=['source', 'planning'])
def test_source_and_plan_keep_case_distinct_tmc_sections(parse):
    upper, lower = 'tmc2209 extruder_stepper Mix', 'tmc2209 extruder_stepper mix'
    actual = parse(block(upper, {'run_current': '0.5'}) + block(lower, {'run_current': '0.4'}))
    assert actual[upper] == {'run_current': '0.5'}
    assert actual[lower] == {'run_current': '0.4'}
