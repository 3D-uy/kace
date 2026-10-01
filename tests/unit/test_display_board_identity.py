"""Display advice must resolve a reviewed filename and an unambiguous MCU."""
import pytest

from core.display_checker import _find_board_entry, classify_hardware_combination, run_manual_selection_analysis
from core.exceptions import GenerationError
from core.generator import generate_config
from tests.unit.test_generator import _parsed, _user


@pytest.mark.parametrize('name', [
    'unlisted-skr-v1.4-custom.cfg', 'generic-bigtreetech-skr-mini-e3-v30.cfg',
    'generic-bigtreetech-octopus-pro-v1.9.cfg', 'generic-cramps.cfg',
    'generic-ruramps-v1.3.cfg', 'generic-printrboard-g2.cfg', 'generic-duet2-maestro.cfg',
    'generic-duet3-mini.cfg', 'generic-fysetc-cheetah-v2.0.cfg',
])
def test_partial_name_or_unreviewed_identity_does_not_supply_board_facts(name):
    assert _find_board_entry(name) is None
    assert classify_hardware_combination('st7920', name, {})['hardware_evidence'] == 'unknown'


@pytest.mark.parametrize('name,mcu', [
    ('generic-bigtreetech-skr-mini-e3-v3.0.cfg', 'stm32g0b1'),
    ('generic-bigtreetech-octopus-max-ez.cfg', 'stm32h723'),
    ('generic-bigtreetech-octopus-pro-v1.1.cfg', 'stm32h723'),
    ('generic-bigtreetech-skr-v1.3.cfg', 'lpc1768'),
])
def test_exact_revision_resolves_its_own_mcu(name, mcu):
    assert _find_board_entry(name)['mcu'] == mcu


@pytest.mark.parametrize('name', [
    'generic-bigtreetech-skr-v1.4.cfg', 'generic-bigtreetech-skr-2.cfg',
    'generic-bigtreetech-octopus-v1.1.cfg', 'generic-bigtreetech-octopus-pro-v1.0.cfg',
    'generic-ramps.cfg',
])
def test_multi_processor_source_requires_explicit_variant(name):
    assert _find_board_entry(name) is None


@pytest.mark.parametrize('mcu', ['lpc1768', 'lpc1769'])
def test_explicit_skr_variant_retains_board_evidence(mcu):
    assert _find_board_entry('generic-bigtreetech-skr-v1.4.cfg', mcu)['mcu'] == mcu
    result = run_manual_selection_analysis('st7920', 'generic-bigtreetech-skr-v1.4.cfg', mcu)
    assert result['interface_validation']['result'] == 'ok'
    assert result['confidence_level'] == 'Unknown'


def test_conflicting_mcu_does_not_override_exact_filename():
    result = run_manual_selection_analysis('st7920', 'generic-bigtreetech-skr-mini-e3-v3.0.cfg', 'stm32f103')
    assert result['hardware_evidence'] == 'unknown'


@pytest.mark.parametrize('choice', [None, 'manual:display'])
def test_saved_generation_with_conflicting_identity_cannot_write(tmp_path, choice):
    target = tmp_path/'printer.cfg'
    target.write_text('existing')
    parsed = _parsed(display={'lcd_type': 'st7920', 'cs_pin': 'PB3', 'sclk_pin': 'PB4', 'sid_pin': 'PB5'})
    with pytest.raises(GenerationError, match='Unknown display hardware'):
        generate_config(parsed, _user(board='generic-bigtreetech-skr-v1.4.cfg',
            mcu_type='stm32f103', display_choice=choice, display_risk_accepted=True),
            output_path=str(target), verbose=False)
    assert target.read_text() == 'existing'


def test_duplicate_exact_binding_cannot_be_resolved_by_order():
    from unittest.mock import patch
    board = {'mcu': 'lpc1768', 'display_config_filenames': ['known.cfg']}
    with patch('core.display_checker._get_boards', return_value=[board, dict(board)]):
        assert _find_board_entry('known.cfg', 'lpc1768') is None


def test_diagnostic_and_recommendations_use_explicit_variant():
    from core.display_checker import check_display_compatibility, get_recommended_displays
    board = 'generic-bigtreetech-skr-v1.4.cfg'
    parsed = {'display': {'lcd_type': 'st7920'}}
    assert check_display_compatibility(parsed, board_filename=board)[0]['status'] == 'untested'
    result = check_display_compatibility(parsed, board_filename=board, detected_mcu='lpc1768')[0]
    assert result['hardware_evidence'] == 'unknown'
    assert not any('board identity' in item for item in result['missing_evidence'])
    assert any('display module' in item for item in result['missing_evidence'])
    assert not get_recommended_displays(board)['fully_compatible']
    assert not get_recommended_displays(board, 'lpc1769')['fully_compatible']


@pytest.mark.parametrize('mcu', ['lpc1768', 'lpc1769', '', 'stm32f103'])
def test_actual_wizard_requires_module_evidence_even_with_selected_variant(mcu):
    from unittest.mock import patch
    from core.display_wizard import run_display_setup_step

    valid = mcu in ('lpc1768', 'lpc1769')
    assert bool(_find_board_entry('generic-bigtreetech-skr-v1.4.cfg', mcu)) == valid
    answers = ['cat:basic_lcd', 'pick:st7920', '__back__', 'none']
    with patch('core.display_wizard.numbered_select', side_effect=answers):
        result = run_display_setup_step({'mcu_type': mcu}, {}, 'generic-bigtreetech-skr-v1.4.cfg')
    assert result['display_choice'] == 'none'
