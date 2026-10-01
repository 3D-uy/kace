"""Electrical input tolerance is not inferred from a 3.3 V logic label."""
from unittest.mock import patch

import pytest

from core.display_checker import classify_hardware_combination, run_manual_selection_analysis
from core.exceptions import GenerationError
from core.generator import generate_config
from tests.unit.test_generator import _parsed, _user


@pytest.mark.parametrize('tolerance', ['3.3V_tolerant', 'unspecified', '5V_native'])
@pytest.mark.parametrize('matrix', [False, True])
def test_ambiguous_tolerance_cannot_authorize_five_volt_display(tolerance, matrix):
    board = {'mcu': 'lpc1768', 'voltage': '3.3V', 'gpio_voltage_tolerance': tolerance,
             'display_interfaces': ['UART']}
    overrides = {'known': {'dwin_set': {'compatibility_class': 'fully_compatible'}}} if matrix else {}
    with patch('core.display_checker._find_board_entry', return_value=board), patch(
            'core.display_checker._get_board_display_matrix', return_value=overrides):
        result = classify_hardware_combination('dwin_set', 'known.cfg', {})
        analysis = run_manual_selection_analysis('dwin_set', 'known.cfg')
    assert result['hardware_evidence'] == 'unknown'
    assert result['status'] == 'untested'
    assert analysis['voltage_validation']['result'] == 'unknown'
    assert analysis['confidence_level'] == 'Unknown'
    assert not analysis['adapter_requirements']


@pytest.mark.parametrize('choice', [None, 'manual:dwin_set', 'override:dwin_set'])
def test_uncertain_electrical_selection_cannot_write_active_display(tmp_path, choice):
    target = tmp_path/'printer.cfg'
    target.write_text('existing')
    with pytest.raises(GenerationError, match='Unknown display hardware'):
        generate_config(_parsed(dwin_set={'data_pin': 'P1.0'}),
            _user(board='generic-bigtreetech-skr-v1.3.cfg', mcu_type='lpc1768',
                  display_choice=choice, display_risk_accepted=True),
            output_path=str(target), verbose=False)
    assert target.read_text() == 'existing'


def test_explicit_five_volt_tolerance_does_not_establish_output_threshold():
    board = {'mcu': 'fixture', 'voltage': '3.3V', 'gpio_voltage_tolerance': '5V_tolerant',
             'display_interfaces': ['UART']}
    # Isolate the voltage rule with a hypothetical reviewed UART mapping.
    # A legacy MCU UART flag alone is explicitly rejected by bus-evidence tests.
    with patch('core.display_checker._find_board_entry', return_value=board), patch(
            'core.display_checker._infer_board_interfaces', return_value=['UART']):
        result = run_manual_selection_analysis('dwin_set', 'known.cfg')
    assert result['compatibility_class'] != 'fully_compatible'
    assert result['voltage_validation']['result'] == 'warn'
    assert result['confidence_level'] != 'High'


@pytest.mark.parametrize('display,board,mcu', [
    ('dwin_set', 'generic-bigtreetech-skr-pico-v1.0.cfg', 'rp2040'),
    ('uc1701', 'generic-ramps.cfg', 'atmega2560'),
])
def test_existing_voltage_dangers_stay_unsafe_without_generic_adapter_recipe(display, board, mcu):
    result = run_manual_selection_analysis(display, board, mcu)
    assert result['compatibility_class'] == 'unsafe'
    assert result['voltage_validation']['result'] == 'danger'
    text = str(result)
    assert '74AHCT125' not in text
    assert 'voltage divider' not in text
    assert 'bidirectional logic level shifter' not in text


def test_unsafe_oem_display_without_board_keeps_unknown_voltage():
    result = run_manual_selection_analysis('t5uid1', 'unlisted-board.cfg')
    assert result['compatibility_class'] == 'unsafe'
    assert result['voltage_validation']['result'] == 'unknown'
    assert 'Board MCU is 5V-tolerant' not in str(result)
