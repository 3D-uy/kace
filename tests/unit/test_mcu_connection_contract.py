"""MCU options mirror the pinned transport branches, without hardware claims."""
import copy
import pytest
from core.exceptions import GenerationError
from core import primary_mcu


@pytest.mark.parametrize('section', ['mcu', 'mcu toolhead'])
@pytest.mark.parametrize('value', ['0', '2399', '-1', '1.5', 'nan', 'inf', '', None, True])
def test_uart_baud_requires_integer_at_least_2400(section, value):
    with pytest.raises(GenerationError, match='baud'):
        primary_mcu.validate_mcu_connection_options({section: {'serial': '/dev/fixture', 'baud': value}})


@pytest.mark.parametrize('section', ['mcu', 'mcu toolhead'])
@pytest.mark.parametrize('value', ['2400', '250000', '10000000', '+002400'])
def test_uart_baud_has_no_invented_maximum_and_keeps_text(section, value):
    sections={section: {'serial': '/dev/fixture', 'baud': value}}
    original=copy.deepcopy(sections)
    primary_mcu.validate_mcu_connection_options(sections)
    assert sections==original


@pytest.mark.parametrize('connection', [{'canbus_uuid': 'aabbccddeeff'}, {'serial': '/tmp/klipper_host_mcu'}, {'serial': '/dev/rpmsg_pru30'}])
@pytest.mark.parametrize('section', ['mcu', 'mcu toolhead'])
@pytest.mark.parametrize('option,value', [('baud','250000'), ('restart_method','command')])
def test_non_uart_branches_reject_unused_options(section, connection, option, value):
    with pytest.raises(GenerationError, match=option):
        primary_mcu.validate_mcu_connection_options({section: {**connection, option:value}})


@pytest.mark.parametrize('method', ['arduino', 'cheetah', 'command', 'rpi_usb'])
def test_secondary_uart_restart_methods_remain_compatible(method):
    primary_mcu.validate_mcu_connection_options({'mcu aux': {'serial': '/dev/fixture', 'restart_method': method}})


def test_secondary_restart_rejects_unknown_choice():
    with pytest.raises(GenerationError, match='restart_method'):
        primary_mcu.validate_mcu_connection_options({'mcu aux': {'serial': '/dev/fixture', 'restart_method': 'invalid'}})


def test_omitted_defaults_and_unrelated_sections_are_not_invented():
    sections={'mcu': {},'mcu host': {'serial': '/tmp/klipper_host_mcu'},
        'mcu pru': {'serial': '/dev/rpmsg_pru30'},'mcu can': {'canbus_uuid':'aabbccddeeff'},
        'gcode_macro OTHER': {'baud':'bad','restart_method':'invalid'}}
    before=copy.deepcopy(sections)
    primary_mcu.validate_mcu_connection_options(sections)
    assert sections==before
