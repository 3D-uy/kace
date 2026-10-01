"""Loaded raw config values must preserve command and template boundaries."""
from unittest.mock import patch

import pytest

from core.config_transaction import ConfigConflictError, MoonrakerConfigTransport, ConfigDeploymentTransaction
from core.managed_config import build_managed_config_plan
from tests.unit.test_config_transaction import FakeTransport, GENERATED


def plan_for(section, option, source):
    return build_managed_config_plan(f'[mcu]\nserial: test\n[{section}]\n{option}: {source}\n'.encode(), None, {})


def verify(plan, active):
    body = {'result': {'status': {'configfile': {'config': active}}}}
    with patch('core.moonraker._get', return_value=(True, '', body)):
        MoonrakerConfigTransport('localhost', 7125).verify_active_configuration(plan)


DIFFERENT = [
    ('gcode_macro TEST', 'gcode', '\n    M104 S0\n    M140 S0', 'M104 S0 M140 S0'),
    ('gcode_macro TEST', 'gcode', '\n    RESPOND MSG="a  b"', '\nRESPOND MSG="a b"'),
    ('gcode_macro TEST', 'gcode', '\n    M117 a\tb', '\nM117 a b'),
    ('gcode_macro TEST', 'gcode', '\n    {% set text = "a  b" %}\n    M117 {text}', '\n{% set text = "a b" %}\nM117 {text}'),
    ('gcode_macro TEST', 'gcode', '\n    {% if True %}\n    M104 S0\n    M140 S0\n    {% endif %}', '\n{% if True %} M104 S0 M140 S0 {% endif %}'),
    ('delayed_gcode TEST', 'gcode', '\n    M104 S0\n    M140 S0', '\nM104 S0 M140 S0'),
    ('probe', 'activate_gcode', '\n    M104 S0\n    M140 S0', '\nM104 S0 M140 S0'),
    ('probe', 'deactivate_gcode', '\n    M104 S0\n    M140 S0', '\nM104 S0 M140 S0'),
    ('gcode_macro TEST', 'variable_label', '"a  b"', '"a b"'),
    ('gcode_macro TEST', 'description', 'a  b', 'a b'),
    ('virtual_sdcard', 'path', '/tmp/two  spaces/gcodes', '/tmp/two spaces/gcodes'),
    ('printer', 'max_velocity', '300', 300),
    ('printer', 'max_velocity', '300', '300.0'),
]


@pytest.mark.parametrize('section,option,source,actual', DIFFERENT)
def test_different_or_ambiguous_values_are_not_verified(section, option, source, actual):
    with pytest.raises(ConfigConflictError):
        verify(plan_for(section, option, source), {'mcu': {'serial': 'test'}, section: {option: actual}})


@pytest.mark.parametrize('source,actual', [
    ('\n    M104 S0\n    M140 S0', '\nM104 S0\nM140 S0'),
    ('\r\n\tM104 S0\r\n\tM140 S0', '\nM104 S0\nM140 S0'),
    ('\n    M104 S0 # first\n    M140 S0 ; second', '\nM104 S0\nM140 S0'),
    ('\n    RESPOND MSG="a;b"', '\nRESPOND MSG="a;b"'),
    ('\n    {% if True %}\n      M117 a  b\n    {% endif %}', '\n{% if True %}\nM117 a  b\n{% endif %}'),
    ('\n    M104 S0\n\n    M140 S0', '\nM104 S0\n\nM140 S0'),
])
def test_only_official_parser_formatting_is_normalized(source, actual):
    verify(plan_for('gcode_macro TEST', 'gcode', source),
           {'mcu': {'serial': 'test'}, 'gcode_macro TEST': {'gcode': actual}})


def test_scalar_comments_and_outer_whitespace_are_parsed_once():
    verify(plan_for('printer', 'max_velocity', ' 300  # selected'),
           {'mcu': {'serial': 'test'}, 'printer': {'max_velocity': '300'}})


@pytest.mark.parametrize('active', [None, [], {'mcu': []}, {'mcu': {'serial': True}},
    {'mcu': {'serial': 'test'}, 'gcode_macro test': {'gcode': '\nG28'}},
    {'mcu': {'serial': 'test'}, 'gcode_macro TEST': {'GCODE': '\nG28'}}])
def test_unexpected_status_shape_or_identity_fails_closed(active):
    with pytest.raises(ConfigConflictError):
        verify(plan_for('gcode_macro TEST', 'gcode', '\n    G28'), active)


@pytest.mark.parametrize('body', [None, [], {'result': None}, {'result': {'status': []}}])
def test_malformed_response_is_a_verification_conflict(body):
    with patch('core.moonraker._get', return_value=(True, '', body)), pytest.raises(ConfigConflictError):
        MoonrakerConfigTransport('localhost', 7125).verify_active_configuration(
            plan_for('gcode_macro TEST', 'gcode', '\n    G28'))


@pytest.mark.parametrize('collapsed', [False, True])
def test_nested_user_macro_is_compared(collapsed):
    generated = b'[mcu]\nserial: test\n'
    remote = {'printer.cfg': generated+b'[include user.cfg]\n',
              'user.cfg': b'[include macros.cfg]\n',
              'macros.cfg': b'[gcode_macro TEST]\ngcode:\n    M104 S0\n    M140 S0\n'}
    plan = build_managed_config_plan(generated, None, remote)
    active = {'mcu': {'serial': 'test'}, 'gcode_macro TEST': {
        'gcode': '\nM104 S0 M140 S0' if collapsed else '\nM104 S0\nM140 S0'}}
    if collapsed:
        with pytest.raises(ConfigConflictError):
            verify(plan, active)
    else:
        verify(plan, active)


@pytest.mark.parametrize('matches', [False, True])
def test_noop_retry_cannot_complete_for_collapsed_commands(tmp_path, matches):
    macro = b'[gcode_macro TEST]\ngcode:\n    M104 S0\n    M140 S0\n'
    generated = GENERATED + macro
    remote = {a.remote_name: a.content for a in build_managed_config_plan(generated, None, {}).artifacts}
    transport = FakeTransport(remote)
    transport.verify_active_configuration = MoonrakerConfigTransport('localhost', 7125).verify_active_configuration
    active = {'mcu': {'serial': '/dev/serial/by-id/test'}, 'printer': {'kinematics': 'cartesian'},
              'stepper_x': {'step_pin': 'PA1'}, 'gcode_macro TEST': {
                  'gcode': '\nM104 S0\nM140 S0' if matches else 'M104 S0 M140 S0'}}
    body = {'result': {'status': {'configfile': {'config': active}}}}
    events = []
    with patch('core.moonraker._get', return_value=(True, '', body)):
        result = ConfigDeploymentTransaction(transport, generated, None,
            activation='none', verify_existing_ready=True, confirm=lambda _: True,
            snapshot_root=str(tmp_path/'snapshots'),
            state_sink=lambda state, detail: events.append(state), poll_interval=0).run()
    assert result.ok is matches, result
    assert not any(call[0] in ('upload', 'restart') for call in transport.calls)
    assert ('configuration already installed' in result.detail) is matches
    assert ('DONE' in events) is matches
