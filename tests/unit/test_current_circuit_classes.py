"""Unsupported current-control circuits must never disappear from a board route."""
import json
from unittest.mock import Mock, patch

import pytest

from core.board_auxiliary import SOURCE_ACTIVITY, SOURCE_OPTIONS, selected_board_electrical_source
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.exceptions import GenerationError
from core.firmware_workflow import persistable_wizard_data
from core.generator import generate_config
from core.scraper import parse_config
from tests.unit.test_config_transaction import FakeTransport, GENERATED
from tests.unit.test_generator import _parsed, _user
from tests.unit.test_board_dependency_recovery import test_real_cli_resume_rechecks_saved_artifact_before_deployment as resume_scenario

CASES = [
    ('ad5206', '[ad5206 currents]\nenable_pin: PG1\nscale: 2\nchannel_1: 1\n'),
    ('dac084s085', '[dac084S085 currents]\nenable_pin: PG1\nscale: 2\nchannel_A: 1\n'),
    ('mcp4451', '[mcp4451 currents]\ni2c_address: 44\nscale: 2\nwiper_0: 1\n'),
    ('mcp4018', '[mcp4018 currents]\ni2c_software_scl_pin: PG1\ni2c_software_sda_pin: PG2\nscale: 2\nwiper: 1\n'),
    ('output_pin motor_current', '[output_pin motor_current]\npin: PG1\npwm: true\nhardware_pwm: true\ncycle_time: .0001\nscale: 2\nvalue: 1\n'),
]


@pytest.fixture(params=CASES, ids=lambda case: case[0])
def circuit(request):
    return request.param


@pytest.mark.parametrize('old_metadata', [False, True])
def test_standalone_selection_cannot_drop_required_current_circuit(circuit, old_metadata, tmp_path):
    reason, raw = circuit
    source = parse_config(raw, keep_comments=True)
    if old_metadata:
        source.pop(SOURCE_ACTIVITY)
        source.pop(SOURCE_OPTIONS)
    paths = [tmp_path/name for name in ('printer.cfg', 'printer.cfg.provenance.json', 'macros.cfg')]
    for path in paths:
        path.write_bytes(b'previous artifact')
    with pytest.raises(GenerationError, match=reason):
        generate_config({**_parsed(), **source}, _user(driver_mode='Standalone'),
                        output_path=str(paths[0]), include_macros=True, verbose=False)
    assert all(path.read_bytes() == b'previous artifact' for path in paths)


def test_proven_commented_example_does_not_enable_current_hardware(circuit, tmp_path):
    _, raw = circuit
    source = parse_config('\n'.join('#'+line for line in raw.splitlines()), keep_comments=True)
    result = generate_config({**_parsed(), **source}, _user(), output_path=str(tmp_path/'printer.cfg'), verbose=False)
    assert raw.splitlines()[0] not in result['content']


@pytest.mark.parametrize('copied_circuit', [False, True])
def test_json_recovery_and_copied_cfg_cannot_authorize_unsupported_circuit(circuit, copied_circuit, tmp_path):
    reason, raw = circuit
    saved = json.loads(json.dumps(persistable_wizard_data({'board':'selected.cfg', 'board_raw_config':raw})))
    source = selected_board_electrical_source({'workflow_checkpoint':{'wizard_data':saved}})
    content = GENERATED + (raw.encode() if copied_circuit else b'')
    transport, confirm = FakeTransport({'printer.cfg':content}), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, content, None, selected_board=source,
        confirm=confirm, activation='firmware', verify_existing_ready=True,
        snapshot_root=str(tmp_path/'snapshots')).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED and reason in result.detail
    confirm.assert_not_called()
    assert not transport.calls and transport.files == {'printer.cfg':content}
    assert not (tmp_path/'snapshots').exists()


@pytest.mark.parametrize('state', ['CONFIG_GENERATED', 'READY_TO_DEPLOY', 'DEPLOYING'])
def test_real_cli_resume_rechecks_each_current_class(circuit, state, tmp_path):
    reason, raw = circuit
    resume_scenario(state, raw, reason, tmp_path)


def test_live_export_and_integrated_firmware_reject_before_effects(circuit, tmp_path):
    from core.deployer import _run_config_transaction, _copy_artifacts, deploy_firmware_installation
    from core.workflow_outcome import WorkflowOutcome
    from core.moonraker_deployer import DeployState
    from tests.unit.test_deployer import FirmwareInstallationPreconditionTests
    reason, raw = circuit
    user = FirmwareInstallationPreconditionTests()._user()
    user.update(board='selected.cfg', board_raw_config=raw)
    transport = FakeTransport()
    with patch('core.deployer._generated_config_bytes', return_value=('unused', GENERATED, None)), \
         patch('core.config_transaction.configuration_transport', return_value=transport), \
         patch('core.deployer.shutil.copy2') as copy:
        live = _run_config_transaction(transport, user, 'none', generated=('unused', GENERATED, None))
        assert live.outcome == WorkflowOutcome.PRECONDITION_FAILED and reason in live.detail
        assert not _copy_artifacts(user, str(tmp_path), 'all')
        installed = deploy_firmware_installation(user)
        assert installed.state == DeployState.FAILED_PRECONDITION
    copy.assert_not_called()
    user['firmware_deployment_service'].execute.assert_not_called()
    assert not transport.calls


def test_foreign_profile_does_not_replace_selected_board_current_authority(circuit, tmp_path):
    _, raw = circuit
    result = generate_config(_parsed(), _user(_profile_parsed=parse_config(raw)),
                             output_path=str(tmp_path/'printer.cfg'), verbose=False)
    assert raw.splitlines()[0] not in result['content']
