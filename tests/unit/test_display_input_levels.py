"""A display's nominal logic label is not evidence of 5 V input tolerance."""
from unittest.mock import patch

import pytest

from core.display_checker import (
    _get_display_configs, classify_hardware_combination,
    get_recommended_displays, run_manual_selection_analysis,
)
from core.exceptions import GenerationError
from core.generator import generate_config
from tests.unit.test_generator import _parsed, _user


@pytest.mark.parametrize('display', ['st7920', 'ssd1306', 'hd44780_spi', 'btt_tft35'])
@pytest.mark.parametrize('matrix', [False, True])
def test_nominal_display_label_does_not_authorize_five_volt_board(display, matrix):
    overrides = {'ramps': {display: {'compatibility_class': 'fully_compatible'}}} if matrix else {}
    with patch('core.display_checker._get_board_display_matrix', return_value=overrides):
        result = run_manual_selection_analysis(display, 'generic-ramps.cfg', 'atmega2560')
    assert result['hardware_evidence'] == 'unknown'
    assert '5V input tolerance of the display module' in result['missing_evidence']
    assert result['voltage_validation']['result'] == 'unknown'
    assert result['confidence_level'] == 'Unknown'
    assert not result['required_modifications']
    assert not result['adapter_requirements']


@pytest.mark.parametrize('logic', [None, '', 'any', 'unspecified'])
def test_missing_physical_display_logic_is_not_unrestricted(logic):
    entries = {key: dict(value) for key, value in _get_display_configs().items()}
    if logic is None:
        entries['st7920'].pop('voltage_logic')
    else:
        entries['st7920']['voltage_logic'] = logic
    with patch('core.display_checker._get_display_configs', return_value=entries):
        result = classify_hardware_combination('st7920', 'generic-bigtreetech-skr-v1.3.cfg', {})
    assert result['hardware_evidence'] == 'unknown'
    assert 'display logic voltage' in result['missing_evidence']


@pytest.mark.parametrize('choice', [None, 'recommended:display', 'manual:display', 'override:display'])
def test_five_volt_unknown_blocks_generation_even_with_accepted_risk(tmp_path, choice):
    target = tmp_path / 'printer.cfg'
    target.write_text('existing config')
    parsed = _parsed(display={'lcd_type': 'st7920', 'cs_pin': 'PH1', 'sclk_pin': 'PA1', 'sid_pin': 'PH0'})
    with pytest.raises(GenerationError, match='Unknown display hardware'):
        generate_config(parsed, _user(board='generic-ramps.cfg', mcu_type='atmega2560',
            display_choice=choice, display_risk_accepted=True), output_path=str(target), verbose=False)
    assert target.read_text() == 'existing config'


def test_wizard_rejects_unknown_levels_without_offering_risk_override():
    from core.display_wizard import _confirm_risk

    result = run_manual_selection_analysis('st7920', 'generic-ramps.cfg', 'atmega2560')
    with patch('core.display_wizard.yes_no') as confirm, patch('core.display_wizard.simple_input') as text:
        assert not _confirm_risk(result, 'st7920')
    confirm.assert_not_called()
    text.assert_not_called()


def test_recommendations_do_not_promote_unknown_five_volt_inputs():
    buckets = get_recommended_displays('generic-ramps.cfg', 'atmega2560')
    assert not buckets['fully_compatible']
    unknown = {key for key, _, result in buckets['experimental'] if result.get('hardware_evidence') == 'unknown'}
    assert {'display', 'st7920', 'ssd1306', 'hd44780_spi', 'btt_tft35'} <= unknown


def test_three_volt_path_does_not_claim_five_volt_support():
    result = run_manual_selection_analysis('st7920', 'generic-bigtreetech-skr-v1.3.cfg')
    assert result['status'] == 'untested'
    assert result['voltage_validation']['result'] == 'unknown'
    assert result['interface_validation']['result'] == 'ok'
    assert 'accepts both 3.3V and 5V' not in result['voltage_validation']['detail']


def test_no_display_path_remains_available_on_five_volt_board(tmp_path):
    result = generate_config(_parsed(), _user(board='generic-ramps.cfg', mcu_type='atmega2560',
        display_choice='none'), output_path=str(tmp_path / 'printer.cfg'), verbose=False)
    assert '[display]' not in result['content']


def test_existing_unsafe_class_is_not_relabelled_unknown():
    result = run_manual_selection_analysis('t5uid1', 'generic-ramps.cfg', 'atmega2560')
    assert result['compatibility_class'] == 'unsafe'
    assert result['voltage_validation']['result'] == 'unknown'


def test_software_sections_keep_voltage_independence():
    result = run_manual_selection_analysis('display_status', '')
    assert result['status'] == 'supported'
    assert result['voltage_validation']['result'] == 'ok'
