"""Saved generated payloads cannot acquire authority by skipping generation."""
import copy
import hashlib
import os
from contextlib import ExitStack
from unittest.mock import Mock, patch

import pytest

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.managed_config import build_managed_config_plan
from tests.unit.test_config_transaction import GENERATED, FakeTransport
from tests.unit.test_display_publication import VALID, display


PANEL = display('st7920', VALID['st7920'])


@pytest.mark.parametrize('panel', [PANEL, display('ssd1306', {}, 'display secondary'),
                                 b'[st7920]\ncs_pin: PC1\n'])
@pytest.mark.parametrize('origin', ['hardware', 'macros'])
@pytest.mark.parametrize('noop', [False, True])
def test_generated_display_is_rejected_before_write_or_done(tmp_path, panel, origin, noop):
    hardware = GENERATED + panel if origin == 'hardware' else GENERATED
    macros = panel if origin == 'macros' else None
    files = {'printer.cfg': b'# manual destination\n'}
    if noop:
        files.update({a.remote_name: a.content for a in build_managed_config_plan(hardware, macros, files).artifacts})
    transport, review, events = FakeTransport(files), Mock(return_value=True), []
    result = ConfigDeploymentTransaction(transport, hardware, macros, activation='none',
        review=review, verify_existing_ready=noop, state_sink=lambda *event: events.append(event),
        snapshot_root=str(tmp_path/'snapshots')).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED, result
    assert 'display hardware' in result.detail
    assert transport.files == files
    assert not transport.calls
    review.assert_not_called()
    assert not any(state == 'DONE' for state, _ in events)


@pytest.mark.parametrize('kind', ['local', 'usb'])
@pytest.mark.parametrize('artifact_type', ['config', 'all'])
def test_export_does_not_copy_invalid_saved_config_or_companion_firmware(tmp_path, capsys, kind, artifact_type):
    from core import deployer
    dest = tmp_path/'export'; dest.mkdir()
    original = b'# existing destination\n'
    (dest/'printer.cfg').write_bytes(original)
    transport = FakeTransport({'printer.cfg': original})
    firmware = tmp_path/'firmware.bin'; firmware.write_bytes(b'firmware')
    with patch('core.deployer._generated_config_bytes', return_value=('unused', GENERATED+PANEL, None)), patch(
            'core.menu.simple_input', return_value=str(dest)), patch('core.menu.yes_no', return_value=True), patch(
            'core.config_transaction.LocalConfigTransport', return_value=transport):
        result = getattr(deployer, 'deploy_' + kind)({'firmware_path': str(firmware)}, artifact_type=artifact_type)
    assert not result.ok
    assert 'display hardware' in capsys.readouterr().out
    assert not transport.calls
    assert (dest/'printer.cfg').read_bytes() == original
    assert not (dest/'firmware.bin').exists()


@pytest.mark.parametrize('panel', [b'# [display]\n# lcd_type: st7920\n',
                                 b'[display_status]\n', b'[display_template title]\ntext: OK\n'])
def test_commented_and_software_only_generated_artifacts_still_publish(tmp_path, panel):
    transport = FakeTransport()
    result = ConfigDeploymentTransaction(transport, GENERATED+panel, None, activation='none',
        snapshot_root=str(tmp_path/'snapshots')).run()
    assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION, result


def test_live_helper_checks_supplied_payload_before_preflight(tmp_path):
    from core.deployer import _run_config_transaction
    transport = FakeTransport()
    with patch('core.deployer._preflight_check') as preflight:
        result = _run_config_transaction(transport, {'display_risk_accepted': True}, 'none',
                                        generated=('unused', GENERATED, PANEL))
    assert not result.ok
    assert 'display hardware' in result.detail
    assert not transport.calls
    preflight.assert_not_called()


def test_sftp_reader_rejection_is_reported_before_connecting():
    from core.deployer import deploy_config
    from core.exceptions import GenerationError
    with patch('core.deployer._generated_config_bytes', side_effect=GenerationError('display hardware unknown')), patch(
            'core.deployer._connect_ssh_client') as connect:
        result = deploy_config({'password': 'test'})
    assert not result.ok and 'display hardware' in result.detail
    connect.assert_not_called()


def test_reader_checks_actual_saved_bytes(tmp_path):
    from core.deployer import _generated_config_bytes
    from core.exceptions import GenerationError
    cfg = tmp_path/'printer.cfg'; cfg.write_bytes(GENERATED+PANEL)
    with patch('core.deployer.os.path.expanduser', return_value=str(cfg)):
        with pytest.raises(GenerationError, match='display hardware'):
            _generated_config_bytes()
    assert cfg.read_bytes() == GENERATED+PANEL


@pytest.mark.parametrize('payload', [b'\xff', b'not a config header\n'])
def test_reader_reports_unreadable_saved_content_as_precondition(tmp_path, payload):
    from core.deployer import deploy_config
    cfg = tmp_path/'printer.cfg'; cfg.write_bytes(payload)
    with patch('core.deployer.os.path.expanduser', return_value=str(cfg)), patch(
            'core.deployer._connect_ssh_client') as connect:
        result = deploy_config({})
    assert not result.ok and 'cannot be read for display review' in result.detail
    connect.assert_not_called()


@pytest.mark.parametrize('state', ['CONFIG_GENERATED', 'READY_TO_DEPLOY', 'DEPLOYING'])
def test_real_cli_resume_rejects_saved_display_even_with_accepted_risk(tmp_path, state):
    import kace
    from core.firmware_workflow import (create_checkpoint, transition_checkpoint, write_checkpoint,
                                       load_checkpoint, FirmwareWorkflowState as State)
    from tests.regression.test_main_integration import _WIZARD_USER_DATA_WITH_PARSED
    user = {**copy.deepcopy(_WIZARD_USER_DATA_WITH_PARSED), 'mcu_type': 'lpc1769',
            'mcu_path': '/dev/serial/by-id/test', 'board_raw_config': GENERATED.decode(),
            'display_choice': 'recommended:display', 'display_compat_class': 'fully_compatible',
            'display_risk_accepted': True}
    firmware = tmp_path/'firmware.bin'; firmware.write_bytes(b'firmware')
    evidence = {'path': str(firmware), 'final_filename': 'firmware.bin',
        'sha256': hashlib.sha256(b'firmware').hexdigest(), 'size_bytes': 8, 'method': 'MANUAL',
        'strategy': 'SD_CARD', 'instructions': [], 'build': {'mcu': user['mcu_type']}}
    checkpoint = transition_checkpoint(create_checkpoint(user), State.ARTIFACT_READY, artifact=evidence)
    checkpoint = transition_checkpoint(checkpoint, State.VERIFYING_MCU)
    checkpoint = transition_checkpoint(checkpoint, State.MCU_VERIFIED,
        verified_serial_path=user['mcu_path'], flash_evidence_recorded_at=1)
    for next_state in (State.CONFIG_GENERATED, State.READY_TO_DEPLOY, State.DEPLOYING):
        checkpoint = transition_checkpoint(checkpoint, next_state)
        if next_state.value == state:
            break
    checkpoint_path = str(tmp_path/'workflow.json'); write_checkpoint(checkpoint, checkpoint_path)
    assert load_checkpoint(checkpoint_path, current_hardware={}, verify_artifact=True)['state'] == state
    cfg = tmp_path/'printer.cfg'; cfg.write_bytes(GENERATED+PANEL)
    expanduser = os.path.expanduser
    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, {'KACE_AUTO': '1', 'KACE_FIRMWARE_WORKFLOW_PATH': checkpoint_path}))
        stack.enter_context(patch('kace.os.path.expanduser', side_effect=lambda p:
            str(cfg) if p == '~/kace/printer.cfg' else expanduser(p)))
        stack.enter_context(patch('firmware.detector.discover_mcu_hardware', return_value={}))
        for name in ('print_kace_banner', 'print_summary', 'time.sleep'):
            stack.enter_context(patch('kace.' + name))
        generated = stack.enter_context(patch('kace.generate_config'))
        stack.enter_context(patch('kace.run_wizard', side_effect=AssertionError('Must resume checkpoint')))
        menu = stack.enter_context(patch('kace.numbered_select', return_value=None))
        deployment = stack.enter_context(patch('kace.deploy_moonraker'))
        terminal = stack.enter_context(patch('kace.print_workflow_result'))
        with pytest.raises(SystemExit) as outcome:
            kace.main()
    assert outcome.value.code != 0
    assert 'display hardware' in terminal.call_args.args[0].detail
    generated.assert_not_called(); menu.assert_not_called(); deployment.assert_not_called()
    assert cfg.read_bytes() == GENERATED+PANEL
    assert load_checkpoint(checkpoint_path)['state'] != 'COMPLETE'
