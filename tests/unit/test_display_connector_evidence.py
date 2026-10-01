"""A source with one EXP mapping cannot authorize a dual-EXP recommendation."""
from unittest.mock import patch

import pytest

from core.display_checker import _infer_board_interfaces, classify_hardware_combination, run_manual_selection_analysis
from core.exceptions import GenerationError
from core.generator import generate_config
from tests.unit.test_generator import _parsed, _user


@pytest.mark.parametrize('board', [
    'generic-bigtreetech-manta-e3ez.cfg',
    'generic-bigtreetech-skr-mini-e3-v1.0.cfg',
    'generic-bigtreetech-skr-mini-e3-v1.2.cfg',
    'generic-bigtreetech-skr-mini-e3-v2.0.cfg',
    'generic-bigtreetech-skr-mini-e3-v3.0.cfg',
    'generic-creality-v4.2.7.cfg',
])
def test_exp1_mapping_does_not_supply_exp2(board):
    assert 'EXP1' in _infer_board_interfaces(board, {})
    assert 'EXP1_EXP2' not in _infer_board_interfaces(board, {})
    result = run_manual_selection_analysis('st7920', board)
    assert result['hardware_evidence'] == 'unknown'
    assert result['interface_validation']['result'] == 'unknown'
    assert not result['adapter_requirements']


@pytest.mark.parametrize('board', [
    'generic-bigtreetech-skr-pico-v1.0.cfg', 'generic-melzi.cfg',
    'generic-printrboard.cfg', 'generic-duet2.cfg', 'generic-duet2-duex.cfg',
])
def test_no_exp_mapping_is_unknown_without_invented_adapter(board):
    result = classify_hardware_combination('st7920', board, {})
    assert result['hardware_evidence'] == 'unknown'
    assert result['status'] == 'untested'
    assert not result['required_modifications']
    assert 'EXP1_EXP2' not in _infer_board_interfaces(board, {})


def test_runtime_aliases_and_matrix_cannot_supply_missing_connector_evidence():
    parsed = {'board_pins': {'aliases': 'EXP1_1=PA1, EXP2_1=PA2'}}
    with patch('core.display_checker._get_board_display_matrix', return_value={
            'skr-pico': {'st7920': {'compatibility_class': 'fully_compatible'}}}):
        result = classify_hardware_combination('st7920', 'generic-bigtreetech-skr-pico-v1.0.cfg', parsed)
    assert result['hardware_evidence'] == 'unknown'


@pytest.mark.parametrize('choice', [None, 'manual:display', 'override:display'])
def test_missing_connector_blocks_generation_before_write(tmp_path, choice):
    target = tmp_path/'printer.cfg'
    target.write_text('existing')
    with pytest.raises(GenerationError, match='Unknown display hardware'):
        generate_config(_parsed(display={'lcd_type': 'st7920', 'cs_pin': 'PC6', 'sclk_pin': 'PB13', 'sid_pin': 'PB15'}),
            _user(board='generic-creality-v4.2.7.cfg', display_choice=choice, display_risk_accepted=True),
            output_path=str(target), verbose=False)
    assert target.read_text() == 'existing'


def test_dual_exp_mapping_preserves_known_positive():
    result = run_manual_selection_analysis('st7920', 'generic-bigtreetech-skr-v1.3.cfg')
    assert result['interface_validation']['result'] == 'ok'
    assert 'EXP1_EXP2' in _infer_board_interfaces('generic-bigtreetech-skr-v1.3.cfg', {})


@pytest.mark.parametrize('mapping', [None, [], ['EXP1'], 'EXP1_EXP2', ['EXP1', 'invented']])
def test_missing_or_malformed_reviewed_map_cannot_use_legacy_exp_flag(mapping):
    from core.loader import load_boards_yaml
    from core.display_checker import _find_board_entry
    data = dict(load_boards_yaml())
    data['display_exp_mappings'] = {'generic-bigtreetech-skr-v1.3.cfg': mapping}
    board = dict(_find_board_entry('generic-bigtreetech-skr-v1.3.cfg'))
    board['display_interfaces'] = [*board['display_interfaces'], 'EXP1_EXP2']
    with patch('core.loader.load_boards_yaml', return_value=data), patch(
            'core.display_checker._find_board_entry', return_value=board):
        result = classify_hardware_combination('st7920', 'generic-bigtreetech-skr-v1.3.cfg', {})
    assert result['hardware_evidence'] == 'unknown'


@pytest.mark.parametrize('board,mapped', [
    ('generic-creality-v4.2.7.cfg', False), ('generic-bigtreetech-skr-v1.3.cfg', True),
])
def test_wizard_requires_more_than_connector_mapping(board, mapped):
    from core.display_wizard import run_display_setup_step
    assert ('EXP1_EXP2' in _infer_board_interfaces(board, {})) == mapped
    answers = ['cat:basic_lcd', 'pick:st7920', '__back__', 'none']
    with patch('core.display_wizard.numbered_select', side_effect=answers):
        result = run_display_setup_step({}, {}, board)
    assert result['display_choice'] == 'none'


def test_unmapped_pair_does_not_block_no_display_generation(tmp_path):
    result = generate_config(_parsed(), _user(board='generic-creality-v4.2.7.cfg', display_choice='none'),
                             output_path=str(tmp_path/'printer.cfg'), verbose=False)
    assert '[display]' not in result['content']
