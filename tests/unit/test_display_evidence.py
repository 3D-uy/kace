"""LCD driver support does not imply a board's electrical compatibility."""
import copy
from unittest.mock import patch

import pytest

from core.display_checker import (classify_hardware_combination, run_manual_selection_analysis,
    get_recommended_displays, _infer_board_interfaces, _infer_board_voltage, _infer_board_tolerance)
from core.generator import generate_config
from core.exceptions import GenerationError
from tests.unit.test_generator import _parsed, _user


@pytest.mark.parametrize('board', ['', 'unlisted-board.cfg', 'unlisted-stm32.cfg', 'unlisted-rp2040.cfg'])
@pytest.mark.parametrize('parsed', [{}, {'board_pins': {'aliases': 'EXP1_1=PA1, EXP2_1=PA2'}}])
def test_unknown_board_never_claims_interfaces_or_compatibility(board, parsed):
    before = copy.deepcopy(parsed)
    result = classify_hardware_combination('st7920', board, parsed)
    assert result['status'] == 'untested'
    assert result['compatibility_class'] != 'fully_compatible'
    assert _infer_board_interfaces(board, parsed) == []
    assert _infer_board_voltage(board, parsed) is None
    assert _infer_board_tolerance(board, parsed) is None
    analysis = run_manual_selection_analysis('st7920', board, parsed_cfg=parsed)
    assert analysis['confidence_level'] == 'Unknown'
    assert analysis['interface_validation']['result'] == 'unknown'
    assert analysis['voltage_validation']['result'] == 'unknown'
    assert parsed == before


@pytest.mark.parametrize('missing', ['mcu', 'voltage', 'gpio_voltage_tolerance', 'display_interfaces'])
def test_missing_board_fact_cannot_be_supplied_by_matrix_or_alias(missing):
    board = {'mcu': 'stm32f4', 'voltage': '3.3V', 'gpio_voltage_tolerance': '3.3V_tolerant',
             'display_interfaces': ['EXP1_EXP2']}
    del board[missing]
    with patch('core.display_checker._find_board_entry', return_value=board), patch(
        'core.display_checker._get_board_display_matrix', return_value={
            'known': {'st7920': {'compatibility_class': 'fully_compatible'}}}):
        result = classify_hardware_combination('st7920', 'known.cfg', {'board_pins': {'aliases': 'EXP1_1=PA1'}})
    assert result['status'] == 'untested'


def test_known_board_retains_declared_interface_evidence():
    result = run_manual_selection_analysis('st7920', 'generic-bigtreetech-skr-v1.4.cfg', 'lpc1768', parsed_cfg={})
    assert result['interface_validation']['result'] == 'ok'
    assert result['confidence_level'] == 'Unknown'


def test_unknown_board_has_no_fully_compatible_recommendations():
    assert not get_recommended_displays('unlisted-board.cfg')['fully_compatible']


def test_software_only_menu_does_not_require_electrical_board_identity():
    assert classify_hardware_combination('lcd_menu', '', {})['status'] == 'supported'


def test_existing_unsafe_classification_is_not_downgraded():
    assert classify_hardware_combination('t5uid1', 'unlisted-board.cfg', {})['compatibility_class'] == 'unsafe'


def test_unknown_hardware_cannot_be_accepted_by_wizard():
    from core.display_wizard import _confirm_risk

    analysis = run_manual_selection_analysis('st7920', 'unlisted-board.cfg')
    with patch('core.display_wizard.yes_no') as yes_no, patch('core.display_wizard.simple_input') as text:
        assert not _confirm_risk(analysis, 'st7920')
    yes_no.assert_not_called()
    text.assert_not_called()


@pytest.mark.parametrize('choice', [None, 'recommended:display', 'manual:display', 'override:display'])
def test_unknown_hardware_cannot_generate_active_display(tmp_path, choice):
    board = _parsed()
    board['display'] = {'lcd_type': 'st7920', 'cs_pin': 'PB3', 'sclk_pin': 'PB4', 'sid_pin': 'PB5'}
    target = tmp_path/'printer.cfg'
    target.write_text('existing config')
    with pytest.raises(GenerationError, match='[Uu]nknown|evidence'):
        generate_config(board, _user(board='unlisted-board.cfg', display_choice=choice,
            display_risk_accepted=True), output_path=str(target), verbose=False)
    assert target.read_text() == 'existing config'


def test_no_display_path_still_generates_on_unknown_board(tmp_path):
    result = generate_config(_parsed(), _user(board='unlisted-board.cfg', display_choice='none'),
                             output_path=str(tmp_path/'printer.cfg'), verbose=False)
    assert '[display]' not in result['content']


def test_public_diagnostic_retains_missing_evidence():
    from core.display_checker import check_display_compatibility

    findings = check_display_compatibility({'display': {'lcd_type': 'st7920'}},
                                          board_filename='unlisted-board.cfg')
    assert findings[0]['hardware_evidence'] == 'unknown'
    assert 'board identity' in findings[0]['missing_evidence']


@pytest.mark.parametrize('language', ['English', 'Español', 'Português'])
def test_unknown_wizard_message_is_localized(language, capsys):
    from core.display_wizard import _confirm_risk, _print_risk_panel
    from core.translations import get_lang, set_lang, t

    previous = get_lang()
    try:
        set_lang(language)
        analysis = run_manual_selection_analysis('st7920', 'unlisted-board.cfg')
        _print_risk_panel(analysis, 'st7920')
        assert not _confirm_risk(analysis, 'st7920')
        output = capsys.readouterr().out
        assert t('display.class_unknown') in output
        assert t('display.hardware_evidence_required') in output
        assert 'display.hardware_evidence_required' not in output
    finally:
        set_lang(previous)
