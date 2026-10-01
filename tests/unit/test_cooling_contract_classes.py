"""Cooling conservation by behavior, using explicit synthetic reviewed sources.

The catalog sweep binds these behaviors to official sources separately. These
fixtures do not impersonate a real board or certify a platform.
"""
import copy
import hashlib
import json
from unittest.mock import Mock

import pytest

from core.board_cooling import REVIEWED, SOURCE, cooling_settings, required_board_fans
from core.board_auxiliary import selected_board_electrical_source, validate_board_electrical_artifact
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.exceptions import GenerationError
from core.firmware_workflow import persistable_wizard_data
from core.generator import generate_config
from core.managed_config import _section_options, build_managed_config_plan
from core.scraper import parse_config
from tests.unit.test_generator import _parsed, _user
from tests.unit.test_config_transaction import FakeTransport

PROFILE = 'reviewed-cooling-class-test.cfg'
CLASSES = {
    'thermal_default': {'heater_fan Hotend': {'pin': 'PG0'}},
    'thermal_tuned': {'heater_fan Hotend': {'pin': 'PG0', 'heater': 'extruder, heater_bed',
        'heater_temp': '40', 'fan_speed': '.8', 'max_power': '.7', 'kick_start_time': '.5',
        'off_below': '.2', 'cycle_time': '.005', 'hardware_pwm': 'True', 'shutdown_speed': '1'}},
    'controller_default': {'controller_fan Board': {'pin': 'PG1'}},
    'controller_tuned': {'controller_fan Board': {'pin': 'PG1', 'heater': 'heater_bed, extruder',
        'stepper': 'stepper_x, stepper_y, extruder', 'fan_speed': '.8', 'idle_speed': '.3',
        'idle_timeout': '60', 'max_power': '.7', 'shutdown_speed': '1', 'hardware_pwm': 'true'}},
    'controller_motor_only': {'controller_fan Board': {'pin': 'PG1', 'heater': '', 'stepper': 'stepper_z'}},
    'combined': {'heater_fan Hotend': {'pin': 'PG0'}, 'controller_fan Board': {'pin': 'PG1'}},
}


def inputs(monkeypatch, family='combined', sections=None):
    fans = copy.deepcopy(sections if sections is not None else CLASSES[family])
    board = _parsed()
    board.update(fans)
    raw = '\n'.join('['+n+']\n'+'\n'.join(k+': '+v for k, v in f.items()) for n, f in board.items())+'\n'
    heaters = {}
    for fields in fans.values():
        for name in fields.get('heater', 'extruder').split(','):
            name = name.strip()
            if name:
                heaters[name] = board[name]['heater_pin']
    monkeypatch.setitem(REVIEWED, PROFILE, {'sha256': hashlib.sha256(raw.encode()).hexdigest(),
                                         'sections': fans, 'heaters': heaters})
    parsed = parse_config(raw, PROFILE, keep_comments=True)
    user = _user(board=PROFILE, printer_profile=PROFILE, board_raw_config=raw,
                 board_parsed=parsed, fan_hotend_pin='none')
    return raw, parsed, user


def generate(monkeypatch, tmp_path, family='combined'):
    _, board, user = inputs(monkeypatch, family)
    result = generate_config(board, user, output_path=str(tmp_path/'printer.cfg'), verbose=False)
    saved = json.loads(json.dumps(persistable_wizard_data(user)))
    context = selected_board_electrical_source({'workflow_checkpoint': {'wizard_data': saved}})
    return result['content'], context


@pytest.mark.parametrize('family', CLASSES)
def test_class_survives_none_recovery_and_repeat(monkeypatch, tmp_path, family):
    text, context = generate(monkeypatch, tmp_path, family)
    actual = _section_options(text)
    for name, fields in CLASSES[family].items():
        assert actual[name] == fields
    validate_board_electrical_artifact(context, text)
    transport = FakeTransport()
    for _ in range(2):
        result = ConfigDeploymentTransaction(transport, text.encode(), None, selected_board=context,
            activation='none', snapshot_root=str(tmp_path/'snapshots')).run()
        assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION


@pytest.mark.parametrize('family', CLASSES)
def test_omitted_selection_still_preserves_class(monkeypatch, tmp_path, family):
    _, parsed, user = inputs(monkeypatch, family)
    user.pop('fan_hotend_pin')
    text = generate_config(parsed, user, output_path=str(tmp_path/'printer.cfg'), verbose=False)['content']
    assert all(name in _section_options(text) for name in CLASSES[family])


@pytest.mark.parametrize('name,override', [
    ('heater_fan Hotend', 'pin: !PG0'), ('heater_fan Hotend', 'heater: heater_bed'),
    ('heater_fan Hotend', 'heater_temp: 150'), ('heater_fan Hotend', 'fan_speed: 0'),
    ('controller_fan Board', 'idle_speed: 0'), ('controller_fan Board', 'idle_timeout: 0'),
    ('controller_fan Board', 'stepper: stepper_x'), ('controller_fan Board', 'heater: heater_bed'),
    ('controller_fan Board', 'shutdown_speed: 1'), ('controller_fan Board', 'pin: !PG1'),
])
@pytest.mark.parametrize('noop', [False, True])
def test_effective_change_rejected_before_write(monkeypatch, tmp_path, name, override, noop):
    text, context = generate(monkeypatch, tmp_path)
    data = text.encode()
    remote = {'printer.cfg': data+b'\n[include user.cfg]\n', 'user.cfg': f'[{name}]\n{override}\n'.encode()}
    if noop:
        remote.update({a.remote_name: a.content for a in build_managed_config_plan(data, None, remote).artifacts})
        assert not build_managed_config_plan(data, None, remote).changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, data, None, selected_board=context, confirm=confirm,
        activation='none', snapshot_root=str(tmp_path/'snapshots'), verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED and 'cooling' in result.detail
    confirm.assert_not_called()
    assert transport.files == remote and all(c[0] == 'read' for c in transport.calls)


@pytest.mark.parametrize('name', ['heater_fan Hotend', 'controller_fan Board'])
@pytest.mark.parametrize('mutation', ['missing', 'case', 'role', 'collision'])
def test_required_resource_identity_is_not_optional(monkeypatch, tmp_path, name, mutation):
    text, context = generate(monkeypatch, tmp_path)
    if mutation == 'missing':
        import re
        text = re.sub(r'(?ms)^\['+re.escape(name)+r'\].*?(?=^\[|\Z)', '', text)
    elif mutation == 'case':
        text = text.replace('['+name+']', '['+name.lower()+']')
    elif mutation == 'role':
        text = text.replace('['+name+']', '[fan_generic replaced]')
    else:
        text += '\n[output_pin conflict]\npin: '+CLASSES['combined'][name]['pin']+'\nvalue: 0\n'
    with pytest.raises(GenerationError, match='cooling'):
        validate_board_electrical_artifact(context, text)


@pytest.mark.parametrize('fan', [
    {'temperature_fan mcu': {'pin': 'PG0'}}, {'fan_generic side': {'pin': 'PG0'}},
    {'heater_fan Hotend': {'pin': 'PG0', 'tachometer_pin': 'PG2'}},
    {'controller_fan Board': {'pin': 'PG1', 'enable_pin': 'PG2'}},
])
def test_unsupported_dependency_blocks_even_unselected(monkeypatch, tmp_path, fan):
    _, board, user = inputs(monkeypatch, sections=fan)
    with pytest.raises(GenerationError, match='unsupported|unreviewed'):
        generate_config(board, user, output_path=str(tmp_path/'printer.cfg'), verbose=False)
    assert not (tmp_path/'printer.cfg').exists()
    with pytest.raises(GenerationError, match='unsupported|unreviewed'):
        validate_board_electrical_artifact(board, '[mcu]\nserial: /tmp/no\n')


@pytest.mark.parametrize('option,value', [('stepper', 'stepper_z1'), ('heater', 'heater_bed')])
def test_missing_real_association_never_creates_hardware(monkeypatch, tmp_path, option, value):
    fans = {'controller_fan Board': {'pin': 'PG1', option: value}}
    _, parsed, user = inputs(monkeypatch, sections=fans)
    if option == 'heater':
        # Valid source, but the output is missing its referenced bed circuit.
        text = '[mcu]\nserial: /tmp/no\n[controller_fan Board]\npin: PG1\nheater: heater_bed\n'
        with pytest.raises(GenerationError, match='heater'):
            validate_board_electrical_artifact(parsed, text)
    else:
        with pytest.raises(GenerationError, match='stepper_z1'):
            generate_config(parsed, user, output_path=str(tmp_path/'printer.cfg'), verbose=False)
        assert not (tmp_path/'printer.cfg').exists()


@pytest.mark.parametrize('mutation', ['hash', 'evidence', 'pin', 'heater'])
def test_stale_or_changed_source_blocks(monkeypatch, mutation):
    _, parsed, _ = inputs(monkeypatch)
    if mutation == 'hash':
        parsed[SOURCE]['sha256'] = '0'*64
    elif mutation == 'evidence':
        parsed.pop(SOURCE)
    elif mutation == 'pin':
        parsed['controller_fan Board']['pin'] = 'PG7'
    else:
        parsed['extruder']['heater_pin'] = 'PG8'
    with pytest.raises(GenerationError, match='cooling'):
        required_board_fans(parsed, PROFILE)


@pytest.mark.parametrize('family', ['heater_fan', 'controller_fan'])
def test_semantic_equivalence_keeps_aliases_and_shutdown_clamping(monkeypatch, tmp_path, family):
    kind = 'thermal_tuned' if family == 'heater_fan' else 'controller_tuned'
    text, context = generate(monkeypatch, tmp_path, kind)
    text = text.replace('shutdown_speed: 1', 'shutdown_speed: .7')
    pin = 'PG0' if family == 'heater_fan' else 'PG1'
    text = text.replace('pin: '+pin, 'pin: COOL') + f'\n[board_pins cooling]\naliases: COOL={pin}\n'
    validate_board_electrical_artifact(context, text)


@pytest.mark.parametrize('option,value', [('fan_speed', 'nan'), ('idle_speed', '2'),
    ('idle_timeout', '1.5'), ('idle_timeout', '-1'), ('cycle_time', '0'), ('hardware_pwm', 'maybe')])
def test_controller_bounds_are_not_accepted_as_equivalent(option, value):
    with pytest.raises(GenerationError):
        cooling_settings({'pin': 'PG1', option: value}, 'controller_fan')


@pytest.mark.parametrize('option,value', [('heater', 'extruder,'),
    ('heater', ',extruder'), ('heater', 'extruder,,heater_bed'), ('stepper', 'stepper_z,')])
def test_empty_reference_is_not_normalized_away(option, value):
    with pytest.raises(GenerationError, match='empty'):
        cooling_settings({'pin': 'PG1', option: value}, 'controller_fan')
