"""Preserved display syntax is checked without certifying user hardware."""
import pytest

from core.configuration_review import build_configuration_review, validate_configuration_plan, render_configuration_review
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.managed_config import build_managed_config_plan
from tests.unit.test_config_transaction import FakeTransport, GENERATED


VALID = {
    'st7920': {'cs_pin': 'PC1', 'sclk_pin': 'PC2', 'sid_pin': 'PC3'},
    'hd44780': dict(zip(('rs_pin', 'e_pin', 'd4_pin', 'd5_pin', 'd6_pin', 'd7_pin'),
                       ('PC1', 'PC2', 'PC3', 'PC4', 'PC5', 'PC6'))),
    'emulated_st7920': {'en_pin': 'PC1', 'spi_software_sclk_pin': 'PC2',
                       'spi_software_mosi_pin': 'PC3', 'spi_software_miso_pin': 'PC4'},
    'hd44780_spi': {'latch_pin': 'PC1'}, 'aip31068_spi': {'latch_pin': 'PC1'},
    'uc1701': {'cs_pin': 'PC1', 'a0_pin': 'PC2'}, 'ssd1306': {}, 'sh1106': {},
}


def display(driver, fields, section='display'):
    return ('[' + section + ']\nlcd_type: ' + driver + '\n' + ''.join(
        f'{key}: {value}\n' for key, value in fields.items())).encode()


@pytest.mark.parametrize('driver,field', [(driver, field) for driver, fields in VALID.items() for field in fields])
def test_effective_display_requires_driver_fields(driver, field):
    fields = dict(VALID[driver]); fields.pop(field)
    plan = build_managed_config_plan(GENERATED + display(driver, fields), None, {})
    result = validate_configuration_plan(plan)
    assert any(e.code == 'display-config' and field in e.message for e in result.errors)


@pytest.mark.parametrize('driver', VALID)
def test_valid_display_structure_is_not_electrical_certification(driver):
    plan = build_managed_config_plan(GENERATED, None, {
        'printer.cfg': b'[include user.cfg]\n', 'user.cfg': display(driver, VALID[driver], 'display panel')})
    result = validate_configuration_plan(plan)
    assert result.valid, result.errors
    assert any(w.code == 'display-hardware-unverified' for w in result.warnings)


@pytest.mark.parametrize('driver', ['', 'ST7920', 'display_status', 'dwin_set'])
def test_invalid_lcd_type_cannot_pass_review(driver):
    result = validate_configuration_plan(build_managed_config_plan(GENERATED + display(driver, {}), None, {}))
    assert any(e.code == 'display-config' for e in result.errors)


@pytest.mark.parametrize('driver', ['ssd1306', 'sh1106'])
def test_oled_spi_requires_dc_without_disallowing_default_i2c(driver):
    result = validate_configuration_plan(build_managed_config_plan(
        GENERATED + display(driver, {'cs_pin': 'PC1'}), None, {}))
    assert any(e.code == 'display-config' and 'dc_pin' in e.message for e in result.errors)


@pytest.mark.parametrize('noop', [False, True])
@pytest.mark.parametrize('valid', [False, True])
@pytest.mark.parametrize('origin', ['generated', 'root', 'nested'])
def test_display_review_precedes_upload_or_done(tmp_path, noop, valid, origin):
    fields = VALID['st7920'] if valid else {'cs_pin': 'PC1'}
    panel = display('st7920', fields)
    hardware = GENERATED
    if origin == 'generated':
        hardware += panel
        files = {}
    elif origin == 'root':
        files = {'printer.cfg': panel}
    else:
        files = {'printer.cfg': b'[include user.cfg]\n', 'user.cfg': b'[include panel.cfg]\n',
                 'panel.cfg': panel}
    if noop:
        files.update({a.remote_name: a.content for a in build_managed_config_plan(hardware, None, files).artifacts})
    original = dict(files)
    transport = FakeTransport(files)
    reviews = []
    transaction = ConfigDeploymentTransaction(transport, hardware, None, activation='none',
        confirm=lambda _: True, review=lambda review: reviews.append(review) or True, verify_existing_ready=noop,
        snapshot_root=str(tmp_path/'snapshots'), poll_interval=0)
    result = transaction.run()
    if valid and origin != 'generated':
        expected = ConfigTransactionState.COMMITTED if noop else ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
        assert result.state == expected, result
        if origin == 'nested':
            assert transport.files['panel.cfg'] == original['panel.cfg']
            assert transport.files['user.cfg'] == original['user.cfg']
        elif origin == 'root':
            assert panel in transport.files['printer.cfg']
        assert any(w.code == 'display-hardware-unverified' for w in reviews[0].validation.warnings)
    else:
        assert result.state == ConfigTransactionState.PRECONDITION_FAILED, result
        if origin == 'generated':
            assert 'display hardware' in result.detail
        assert transport.files == original
        assert not any(c[0] in ('upload', 'restart', 'delete') for c in transport.calls)


def test_include_override_is_checked_in_effective_order():
    data = GENERATED + display('st7920', VALID['st7920'])
    plan = build_managed_config_plan(data, None, {
        'printer.cfg': b'[include user.cfg]\n', 'user.cfg': b'[display]\nlcd_type: uc1701\n'})
    result = validate_configuration_plan(plan)
    assert any(e.code == 'display-config' and 'a0_pin' in e.message for e in result.errors)


def test_commented_display_does_not_require_hardware_review():
    plan = build_managed_config_plan(GENERATED + b'# [display]\n# lcd_type: invalid\n', None, {})
    result = validate_configuration_plan(plan)
    assert result.valid
    assert not any(w.code.startswith('display-') for w in result.warnings)


@pytest.mark.parametrize('language,phrase', [('English', 'electrical'), ('Español', 'eléctrica'), ('Português', 'elétrica')])
def test_display_evidence_limit_is_visible_in_normal_review(language, phrase):
    from unittest.mock import patch
    with patch('core.translations.get_mode', return_value='Simple'):
        review = build_configuration_review(build_managed_config_plan(
            GENERATED + display('st7920', VALID['st7920']), None, {}))
        assert phrase in render_configuration_review(review, language=language)


@pytest.mark.parametrize('driver,fields,missing', [
    ('uc1701', {'cs_pin': 'PC1', 'a0_pin': 'PC2', 'spi_software_sclk_pin': 'PC3'}, 'spi_software_mosi_pin'),
    ('ssd1306', {'i2c_software_scl_pin': 'PC3'}, 'i2c_software_sda_pin'),
    ('sh1106', {'cs_pin': 'PC1', 'dc_pin': 'PC2', 'spi_software_sclk_pin': 'PC3'}, 'spi_software_miso_pin'),
    ('st7920', {'cs_pin': '', 'sclk_pin': 'PC2', 'sid_pin': 'PC3'}, 'cs_pin'),
])
def test_incomplete_selected_transport_does_not_pass_review(driver, fields, missing):
    result = validate_configuration_plan(build_managed_config_plan(GENERATED + display(driver, fields), None, {}))
    assert any(e.code == 'display-config' and missing in e.message for e in result.errors)


@pytest.mark.parametrize('driver,fields', [
    ('uc1701', {'cs_pin': 'None', 'a0_pin': 'PC2'}),
    ('ssd1306', {'i2c_software_scl_pin': 'PC3', 'i2c_software_sda_pin': 'PC4'}),
    ('sh1106', {'cs_pin': 'PC1', 'dc_pin': 'PC2', 'spi_software_sclk_pin': 'PC3',
                'spi_software_mosi_pin': 'PC4', 'spi_software_miso_pin': 'PC5'}),
])
def test_explicit_transport_structure_retains_valid_options(driver, fields):
    result = validate_configuration_plan(build_managed_config_plan(GENERATED + display(driver, fields), None, {}))
    assert result.valid, result.errors
