"""Reviewed EXP mappings are not board/display module qualification."""
from unittest.mock import patch

import pytest

from core.display_checker import (
    check_display_compatibility, classify_hardware_combination, get_display_compat, get_recommended_displays,
    run_manual_selection_analysis,
)
from core.exceptions import GenerationError
from core.generator import generate_config
from tests.unit.test_generator import _parsed, _user


@pytest.mark.parametrize('display', ['display', 'st7920', 'hd44780'])
def test_reviewed_connector_cannot_certify_generic_display_module(display):
    result = run_manual_selection_analysis(display, 'generic-bigtreetech-skr-v1.3.cfg')
    assert result['hardware_evidence'] == 'unknown'
    assert result['status'] == 'untested'
    assert result['confidence_level'] == 'Unknown'
    assert result['voltage_validation']['result'] == 'unknown'
    assert result['interface_validation']['result'] == 'ok'
    assert any('display module' in item for item in result['missing_evidence'])


def test_positive_matrix_and_complete_pins_cannot_qualify_module():
    with patch('core.display_checker._get_board_display_matrix', return_value={
        'skr-v1.3': {'display': {'compatibility_class': 'fully_compatible'}}}):
        result = classify_hardware_combination('display', 'generic-bigtreetech-skr-v1.3.cfg', {
            'display': {'lcd_type': 'st7920', 'cs_pin': 'P1.1', 'sclk_pin': 'P1.2', 'sid_pin': 'P1.3'}})
    assert result['hardware_evidence'] == 'unknown'


@pytest.mark.parametrize('choice', [None, 'recommended:display', 'manual:display', 'override:display'])
def test_module_without_evidence_cannot_write_active_display(tmp_path, choice):
    target = tmp_path/'printer.cfg'
    target.write_text('existing')
    with pytest.raises(GenerationError, match='Unknown display hardware'):
        generate_config(_parsed(display={'lcd_type': 'st7920', 'cs_pin': 'P1.1', 'sclk_pin': 'P1.2', 'sid_pin': 'P1.3'}),
            _user(board='generic-bigtreetech-skr-v1.3.cfg', display_choice=choice,
                  display_risk_accepted=True), output_path=str(target), verbose=False)
    assert target.read_text() == 'existing'


def test_wizard_module_selection_remains_blocked_despite_risk_acceptance():
    from core.display_wizard import _confirm_risk
    result = run_manual_selection_analysis('st7920', 'generic-bigtreetech-skr-v1.3.cfg')
    with patch('core.display_wizard.yes_no') as consent:
        assert not _confirm_risk(result, 'st7920')
    consent.assert_not_called()


def test_recommendation_does_not_promote_connectors_to_hardware_support():
    groups = get_recommended_displays('generic-bigtreetech-skr-v1.3.cfg')
    assert not groups['fully_compatible']
    result = next(result for key, _, result in groups['experimental'] if key == 'st7920')
    assert result['hardware_evidence'] == 'unknown'


@pytest.mark.parametrize('display', ['display', 'st7920', 'ssd1306', 'tft_serial'])
def test_static_lookup_does_not_bypass_missing_board_evidence(display):
    result = get_display_compat(display)
    assert result['hardware_evidence'] == 'unknown'
    assert result['status'] == 'untested'


def test_static_oem_lookup_cannot_claim_adapter_without_board():
    result = get_display_compat('display', 'printer-artillery-sidewinder-x1.cfg')
    assert result['source'] == 'printer_profile'
    assert result['hardware_evidence'] == 'unknown'
    assert not result['required_modifications']


@pytest.mark.parametrize('board', ['', 'generic-bigtreetech-skr-v1.3.cfg'])
def test_oem_diagnostic_cannot_bypass_hardware_evidence(board):
    results = check_display_compatibility({}, 'printer-artillery-sidewinder-x1.cfg', board)
    assert len(results) == 1
    assert results[0]['source'] == 'printer_profile'
    assert results[0]['hardware_evidence'] == 'unknown'
    assert not results[0]['required_modifications']


def test_software_and_unsafe_entries_keep_their_distinct_contracts():
    assert get_display_compat('display_status')['status'] == 'supported'
    assert get_display_compat('t5uid1')['compatibility_class'] == 'unsafe'
