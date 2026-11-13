"""Legacy phase identifiers must not misidentify the dispatched command."""
from unittest.mock import patch

import pytest

from core.config_transaction import ConfigDeploymentTransaction, MoonrakerConfigTransport
from core.deployer import _MoonrakerClient
from core.klipper_preflight import PreflightResult, plan_digest
from tests.unit.test_config_transaction import FakeTransport, GENERATED


@pytest.mark.parametrize('ok', [True, False])
def test_legacy_firmware_adapter_issues_restart_once_and_names_failure(ok):
    with patch('core.moonraker._post', return_value=(ok, 'synthetic refusal', {})) as post:
        client = _MoonrakerClient('127.0.0.1', 7125)
        if ok:
            client.firmware_restart()
        else:
            with pytest.raises(RuntimeError, match='^RESTART failed: synthetic refusal$'):
                client.firmware_restart()
        post.assert_called_once_with('http://127.0.0.1:7125/printer/restart',
                                    data=b'{}', content_type='application/json', api_key=None)


@pytest.mark.parametrize('activation,command,path', [
    ('firmware', 'RESTART', '/printer/restart'),
    ('service', 'SERVICE_RESTART', '/machine/services/restart?service=klipper'),
])
def test_activation_phase_keeps_wire_identity_but_names_actual_command(tmp_path, activation, command, path):
    transport = FakeTransport()
    events = []
    transaction = ConfigDeploymentTransaction(transport, GENERATED, None,
        activation=activation, snapshot_root=str(tmp_path), poll_interval=0,
        state_sink=lambda state, detail: events.append((state, detail)))
    # This unit isolates activation observability, not the Docker loader.
    # Preserve the real plan digest check instead of bypassing the gate.
    with patch('core.klipper_preflight.validate_plan', side_effect=lambda plan:
               PreflightResult('valid', 'explicit activation unit double', plan_digest(plan))):
        result = transaction.run()
    assert result.ok, result.detail
    activation_events = [event for event in events if event[0] == 'FIRMWARE_RESTART']
    assert len(activation_events) == 1
    assert activation_events[0][1].startswith(command + ':')
    assert [call for call in transport.calls if call[0] == 'restart'] == [('restart', activation)]
    # Bind the descriptive mode to the production HTTP transport as well.
    with patch('core.moonraker._post', return_value=(True, 'ok', {})) as post:
        MoonrakerConfigTransport('127.0.0.1', 7125).restart(activation)
        post.assert_called_once_with('http://127.0.0.1:7125' + path,
                                    data=b'{}', content_type='application/json', api_key=None)


@pytest.mark.parametrize('status', ['invalid', 'unverified'])
def test_failed_preflight_emits_no_activation_and_sends_no_restart(tmp_path, status):
    transport = FakeTransport()
    events = []
    transaction = ConfigDeploymentTransaction(transport, GENERATED, None,
        activation='firmware', snapshot_root=str(tmp_path),
        state_sink=lambda state, detail: events.append((state, detail)))
    with patch('core.klipper_preflight.validate_plan', return_value=PreflightResult(status, 'blocked', '')):
        result = transaction.run()
    assert not result.ok
    assert not any(state == 'FIRMWARE_RESTART' for state, _ in events)
    assert not any(call[0] in ('restart', 'upload') for call in transport.calls)
