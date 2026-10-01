"""MCU bus capabilities and user-supplied pins cannot certify display wiring."""
from unittest.mock import patch

import pytest

from core.display_checker import (
    _infer_board_interfaces, classify_hardware_combination, run_manual_selection_analysis,
)
from core.exceptions import GenerationError
from core.generator import generate_config
from tests.unit.test_generator import _parsed, _user


@pytest.mark.parametrize('display,bus', [('uc1701', 'SPI'), ('ssd1306', 'I2C'), ('tft_serial', 'UART')])
@pytest.mark.parametrize('declared', [True, False])
def test_bus_capability_or_its_absence_cannot_supply_display_wiring(display, bus, declared):
    board = {'mcu': 'fixture', 'voltage': '3.3V', 'gpio_voltage_tolerance': '3.3V_tolerant',
             'display_interfaces': [bus] if declared else ['unrelated']}
    with patch('core.display_checker._find_board_entry', return_value=board), patch(
        'core.display_checker._get_board_display_matrix', return_value={
            'known': {display: {'compatibility_class': 'fully_compatible'}}}):
        result = run_manual_selection_analysis(display, 'known.cfg')
        assert bus not in _infer_board_interfaces('known.cfg', {})
    assert result['hardware_evidence'] == 'unknown'
    assert result['interface_validation']['result'] == 'unknown'
    assert result['confidence_level'] == 'Unknown'
    assert not result['required_modifications']
    assert not result['adapter_requirements']


@pytest.mark.parametrize('driver', ['uc1701', 'ssd1306', 'sh1106', 'hd44780_spi'])
def test_display_lcd_type_cannot_bypass_bus_evidence(driver):
    parsed = {'display': {'lcd_type': driver, 'cs_pin': 'P0.1', 'spi_bus': 'spi1'},
              'board_pins': {'aliases': 'EXP1_1=P0.1, EXP2_1=P0.2'}}
    result = classify_hardware_combination('display', 'generic-bigtreetech-skr-v1.3.cfg', parsed)
    assert result['hardware_evidence'] == 'unknown'
    assert any('mapping' in value for value in result['missing_evidence'])


@pytest.mark.parametrize('choice', [None, 'recommended:display', 'manual:display', 'override:display'])
def test_unreviewed_bus_blocks_real_display_generation(tmp_path, choice):
    target = tmp_path / 'printer.cfg'
    target.write_text('existing')
    with pytest.raises(GenerationError, match='Unknown display hardware'):
        generate_config(_parsed(display={'lcd_type': 'ssd1306', 'i2c_bus': 'i2c1'}),
            _user(board='generic-bigtreetech-skr-v1.3.cfg', display_choice=choice,
                  display_risk_accepted=True), output_path=str(target), verbose=False)
    assert target.read_text() == 'existing'


@pytest.mark.parametrize('display,board,mcu', [
    ('uc1701', 'generic-ramps.cfg', 'atmega2560'),
    ('dwin_set', 'generic-bigtreetech-skr-pico-v1.0.cfg', 'rp2040'),
])
def test_missing_bus_mapping_does_not_erase_known_voltage_conflict(display, board, mcu):
    with patch('core.display_checker._get_board_display_matrix', return_value={
            board: {display: {'compatibility_class': 'fully_compatible'}}}):
        result = run_manual_selection_analysis(display, board, mcu)
    assert result['compatibility_class'] == 'unsafe'
    assert result['voltage_validation']['result'] == 'danger'
    assert result['interface_validation']['result'] == 'unknown'


def test_unsafe_catalog_entry_cannot_be_promoted_by_matrix():
    with patch('core.display_checker._get_board_display_matrix', return_value={
            'skr-v1.3': {'t5uid1': {'compatibility_class': 'fully_compatible'}}}):
        result = classify_hardware_combination('t5uid1', 'generic-bigtreetech-skr-v1.3.cfg', {})
    assert result['compatibility_class'] == 'unsafe'


def test_named_display_diagnostic_does_not_hide_unreviewed_bus():
    from core.display_checker import check_display_compatibility
    result = check_display_compatibility({'display oled': {'lcd_type': 'ssd1306'}},
                                         board_filename='generic-bigtreetech-skr-v1.3.cfg')
    assert result[0]['hardware_evidence'] == 'unknown'


def test_mixed_display_types_are_not_certified_as_generic_lcd():
    result = classify_hardware_combination('display', 'generic-bigtreetech-skr-v1.3.cfg', {
        'display': {'lcd_type': 'st7920'}, 'display oled': {'lcd_type': 'ssd1306'}})
    assert result['hardware_evidence'] == 'unknown'


def test_reviewed_exp_selection_keeps_connector_evidence():
    result = run_manual_selection_analysis('display', 'generic-bigtreetech-skr-v1.3.cfg',
                                          parsed_cfg={'display': {'lcd_type': 'st7920'}})
    assert result['interface_validation']['result'] == 'ok'


@pytest.mark.parametrize('driver', ['display_status', 'lcd_menu', 'dwin_set', 'uc1701 invented', '', None])
def test_invalid_driver_cannot_borrow_software_or_catalog_compatibility(driver):
    result = classify_hardware_combination('display', 'generic-bigtreetech-skr-v1.3.cfg',
                                           {'display': {'lcd_type': driver}})
    assert result['hardware_evidence'] == 'unknown'


def test_unreviewed_serial_adapter_selection_is_blocked(tmp_path):
    with pytest.raises(GenerationError, match='Unknown display hardware'):
        generate_config(_parsed(), _user(board='generic-ramps.cfg', mcu_type='atmega2560',
            display_choice='manual:dwin_set'), output_path=str(tmp_path / 'printer.cfg'), verbose=False)
