"""Selected-board restart policy survives generation and every publication path."""
import json
from unittest.mock import Mock

import pytest

from core.board_auxiliary import selected_board_electrical_source
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.exceptions import GenerationError
from core.firmware_workflow import persistable_wizard_data
from core.generator import generate_config
from core.managed_config import build_managed_config_plan
from core.pin_validator import _read_pin_config
from core.scraper import parse_config
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_generator import _parsed, _user
from tests.unit.test_board_dependency_recovery import test_real_cli_resume_rechecks_saved_artifact_before_deployment as resume_scenario

METHODS = ('command', 'arduino', 'cheetah', 'rpi_usb')


def render(tmp_path, method='command', **kwargs):
    board = _parsed(mcu={'serial': '/dev/source_example', 'restart_method': method})
    return generate_config(board, _user(**kwargs), output_path=str(tmp_path/'printer.cfg'), verbose=False)['content']


@pytest.mark.parametrize('method', METHODS)
def test_board_policy_keeps_wizard_endpoint_and_ignores_foreign_profile(tmp_path, method):
    text = render(tmp_path, method, mcu_path='/dev/serial/by-id/selected',
                  _profile_parsed={'mcu': {'serial': '/dev/foreign', 'restart_method': 'invalid'}})
    assert _read_pin_config(text)[0]['mcu'] == {'serial': '/dev/serial/by-id/selected', 'restart_method': method}


@pytest.mark.parametrize('raw', ['#[mcu]\n#restart_method: cheetah\n', '[mcu]\n#restart_method: cheetah\n'])
def test_commented_restart_is_not_activated(tmp_path, raw):
    board = {**_parsed(), **parse_config(raw, keep_comments=True)}
    text = generate_config(board, _user(), output_path=str(tmp_path/'printer.cfg'), verbose=False)['content']
    assert 'restart_method' not in _read_pin_config(text)[0]['mcu']


@pytest.mark.parametrize('method', ['', 'COMMAND', 'unknown', 'command\n[fan]', None])
def test_invalid_restart_does_not_write_artifacts(tmp_path, method):
    (tmp_path/'printer.cfg').write_bytes(b'previous')
    with pytest.raises(GenerationError, match='MCU restart'):
        render(tmp_path, method)
    assert (tmp_path/'printer.cfg').read_bytes() == b'previous'
    assert not (tmp_path/'printer.cfg.provenance.json').exists()


@pytest.mark.parametrize('endpoint', ['/tmp/klipper_host_mcu', '/dev/rpmsg_pru30'])
def test_serial_restart_cannot_be_silently_moved_to_pipe(tmp_path, endpoint):
    with pytest.raises(GenerationError, match='MCU restart'):
        render(tmp_path, mcu_path=endpoint)


@pytest.mark.parametrize('noop', [False, True])
@pytest.mark.parametrize('change', ['restart_method: arduino', 'restart_method: invalid', 'canbus_uuid: aabbccddeeff', 'serial: /tmp/klipper_host_mcu'])
def test_late_include_cannot_change_or_disable_generated_restart(tmp_path, noop, change):
    content = render(tmp_path).encode()
    remote = {'printer.cfg': content+b'\n[include user.cfg]\n', 'user.cfg': f'[mcu]\n{change}\n'.encode()}
    if noop:
        remote.update({a.remote_name: a.content for a in build_managed_config_plan(content, None, remote).artifacts})
        assert not build_managed_config_plan(content, None, remote).changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, content, None, confirm=confirm, activation='none',
        verify_existing_ready=noop, snapshot_root=str(tmp_path/'snapshots')).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert 'MCU restart' in result.detail
    confirm.assert_not_called()
    assert transport.files == remote


@pytest.mark.parametrize('method', METHODS)
@pytest.mark.parametrize('missing', [False, True])
def test_saved_source_rejects_old_or_changed_artifact_before_transport(tmp_path, method, missing):
    content = render(tmp_path, method).encode()
    bad = content.replace(f'restart_method: {method}'.encode(), b'# omitted' if missing else b'restart_method: invalid')
    saved = json.loads(json.dumps(persistable_wizard_data({'board': 'selected.cfg',
        'board_raw_config': f'[mcu]\nrestart_method: {method}\n'})))
    source = selected_board_electrical_source({'workflow_checkpoint': {'wizard_data': saved}})
    transport, confirm = FakeTransport(), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, bad, None, selected_board=source, confirm=confirm,
        activation='firmware', snapshot_root=str(tmp_path/'snapshots')).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert 'MCU restart' in result.detail
    assert not transport.calls
    confirm.assert_not_called()


@pytest.mark.parametrize('state', ['CONFIG_GENERATED', 'READY_TO_DEPLOY', 'DEPLOYING'])
def test_real_cli_resume_rejects_missing_restart(state, tmp_path):
    resume_scenario(state, '[mcu]\nrestart_method: command\n', 'MCU restart', tmp_path)


@pytest.mark.parametrize('method', METHODS)
def test_valid_restart_publishes_and_repeats(tmp_path, method):
    content = render(tmp_path, method).encode()
    source = parse_config(f'[mcu]\nrestart_method: {method}\n')
    transport = FakeTransport()
    for _ in range(2):
        result = ConfigDeploymentTransaction(transport, content, None, selected_board=source,
            activation='none', snapshot_root=str(tmp_path/'snapshots')).run()
        assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION


def test_legacy_lpc_fallback_and_explicit_board_priority(tmp_path):
    endpoint = '/dev/serial/by-id/usb-Klipper_lpc1769'
    text = generate_config(_parsed(), _user(mcu_path=endpoint), output_path=str(tmp_path/'printer.cfg'), verbose=False)['content']
    assert _read_pin_config(text)[0]['mcu']['restart_method'] == 'command'
    assert _read_pin_config(render(tmp_path, 'cheetah', mcu_path=endpoint))[0]['mcu']['restart_method'] == 'cheetah'
