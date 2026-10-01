"""Preserve selected-board enable/power levels, including shutdown-high."""
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from core.board_auxiliary import selected_board_digital_outputs, selected_board_electrical_source
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.exceptions import GenerationError
from core.generator import generate_config
from core.managed_config import build_managed_config_plan
from core.pin_validator import _read_pin_config
from core.scraper import parse_config
from tests.unit.test_generator import _user, _parsed
from tests.unit.test_config_transaction import FakeTransport, GENERATED

CASES = {
    'generic-cramps.cfg': ('output_pin machine_enable', 'gpio1_17', '0'),
    'printer-creality-cr10-smart-pro-2022.cfg': ('output_pin power', 'PA0', '1'),
}
FIXTURES = Path(__file__).resolve().parents[1]/'fixtures/board-power-latches'


def board_case(profile):
    raw = (FIXTURES/profile).read_bytes().decode()
    board = parse_config(raw, profile, keep_comments=True)
    user = _user(board=profile, x_size='200', y_size='200', z_size='200',
                 probe='BLTouch' if 'cr10-' in profile else 'None')
    return raw, board, user


@pytest.fixture(params=CASES)
def profile(request):
    return request.param


def generated(tmp_path, profile):
    raw, board, user = board_case(profile)
    text = generate_config(board, user, output_path=str(tmp_path/'printer.cfg'), verbose=False)['content']
    return raw, board, text


def test_real_source_recovery_provenance_and_repeat_publication(tmp_path, profile):
    raw, board, text = generated(tmp_path, profile)
    section, pin, shutdown = CASES[profile]
    expected = {'pin': pin, 'value': '1', 'shutdown_value': shutdown}
    assert _read_pin_config(text)[0][section] == expected
    proof = json.loads((tmp_path/'printer.cfg.provenance.json').read_text())
    assert proof['sources']['auxiliary_digital_outputs'][section] == expected
    recovered = selected_board_electrical_source({'board': profile, 'board_raw_config': raw})
    dest = FakeTransport()
    for _ in range(2):
        result = ConfigDeploymentTransaction(dest, text.encode(), None, selected_board=recovered,
            activation='none', snapshot_root=str(tmp_path/'snapshots'), poll_interval=0).run()
        assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION, result.detail


@pytest.mark.parametrize('field,value', [('pin','!PG1'), ('value','0'), ('shutdown_value','opposite'), ('pwm','true')])
@pytest.mark.parametrize('noop', [False, True])
def test_effective_overrides_fail_before_confirmation_or_writes(tmp_path, profile, field, value, noop):
    _, board, text = generated(tmp_path, profile)
    section, _, shutdown = CASES[profile]
    if value == 'opposite': value = str(1-int(shutdown))
    remote = {'printer.cfg': text.encode()+b'\n[include user.cfg]\n',
              'user.cfg': f'[{section}]\n{field}: {value}\n'.encode()}
    if noop:
        remote.update({a.remote_name: a.content for a in build_managed_config_plan(text.encode(),None,remote).artifacts})
        assert not build_managed_config_plan(text.encode(),None,remote).changed_artifacts
    dest, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(dest, text.encode(), None, selected_board=board,
        confirm=confirm, activation='firmware', snapshot_root=str(tmp_path/'snapshots')).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert dest.files == remote and all(c[0] == 'read' for c in dest.calls)
    confirm.assert_not_called()


@pytest.mark.parametrize('mutation', ['missing_source', 'value', 'shutdown', 'pin', 'pwm'])
def test_invalid_source_preserves_existing_files(tmp_path, profile, mutation):
    _, board, user = board_case(profile)
    section = CASES[profile][0]
    if mutation == 'missing_source': board.pop('_auxiliary_electrical_activity')
    else:
        key,value = {'value': ('value','.5'), 'shutdown': ('shutdown_value','nan'),
                     'pin': ('pin','^PG1'), 'pwm': ('pwm','true')}[mutation]
        board[section][key] = value
        board['_auxiliary_electrical_active_options'][section] = list(board[section])
    paths = [tmp_path/p for p in ('printer.cfg','macros.cfg','printer.cfg.provenance.json')]
    for p in paths: p.write_bytes(b'existing')
    with pytest.raises(GenerationError):
        generate_config(board,user,output_path=str(paths[0]),include_macros=True,verbose=False)
    assert all(p.read_bytes() == b'existing' for p in paths)


def test_reservations_collisions_and_missing_artifact_block(tmp_path, profile):
    _, board, text = generated(tmp_path, profile)
    section, pin, shutdown = CASES[profile]
    reservations = {'mcu': {pin: 'reserved bus'}}
    _, _, user = board_case(profile)
    with patch('core.firmware_workflow.generation_pin_reservations', return_value=reservations):
        with pytest.raises(GenerationError, match='reserved bus'):
            generate_config(board,user,output_path=str(tmp_path/'bad.cfg'),verbose=False)
    review = validate_configuration_plan(build_managed_config_plan(text.encode(),None,{}),
        selected_board=board, firmware_reservation_reader=lambda _: reservations)
    assert not review.valid and any('reserved bus' in e.message for e in review.errors)
    board[section]['pin'] = board['fan']['pin']
    with pytest.raises(GenerationError, match='conflicts'):
        generate_config(board,user,output_path=str(tmp_path/'bad.cfg'),verbose=False)
    _, board, _ = board_case(profile)
    block = f'[{section}]\npin: {pin}\nshutdown_value: {shutdown}\nvalue: 1\n'
    missing = text.replace(block,'').encode()
    assert missing != text.encode()
    dest = FakeTransport()
    result = ConfigDeploymentTransaction(dest,missing,None,selected_board=board,activation='firmware',
        snapshot_root=str(tmp_path/'snapshots')).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED and not dest.calls


def test_unselected_user_pwm_and_commented_source_remain_independent(profile):
    section = CASES[profile][0]
    source = parse_config(f'#[{section}]\n#pin: PG1\n#value: 1\n',keep_comments=True)
    assert selected_board_digital_outputs(source) == {}
    remote = {'printer.cfg': GENERATED+b'\n[include user.cfg]\n',
              'user.cfg': f'[{section}]\npin: PG1\npwm: true\ncycle_time: .001\n'.encode()}
    reader = Mock(side_effect=AssertionError('Unselected output must not request firmware evidence'))
    result = validate_configuration_plan(build_managed_config_plan(GENERATED,None,remote),
        selected_board=source,firmware_reservation_reader=reader)
    assert result.valid
    reader.assert_not_called()


def test_mechanical_profile_cannot_introduce_power(tmp_path, profile):
    _, board, _ = board_case(profile)
    text = generate_config(_parsed(),_user(_profile_parsed=board,x_size='200',y_size='200',z_size='200'),
        output_path=str(tmp_path/'printer.cfg'),verbose=False)['content']
    assert CASES[profile][0] not in _read_pin_config(text)[0]


def test_missing_latch_blocks_export_and_firmware(tmp_path, profile):
    from core.deployer import _copy_artifacts, deploy_firmware_installation
    from core.moonraker_deployer import DeployState
    from tests.unit.test_deployer import FirmwareInstallationPreconditionTests
    raw, _, text = generated(tmp_path, profile)
    section, pin, shutdown = CASES[profile]
    block = f'[{section}]\npin: {pin}\nshutdown_value: {shutdown}\nvalue: 1\n'
    missing = text.replace(block,'').encode()
    assert missing != text.encode()
    user = FirmwareInstallationPreconditionTests()._user()
    user.update(board=profile,board_raw_config=raw)
    with patch('core.deployer._generated_config_bytes',return_value=('unused',missing,None)), \
         patch('core.deployer.shutil.copy2') as copy:
        assert not _copy_artifacts(user,str(tmp_path),'all')
        assert deploy_firmware_installation(user).state == DeployState.FAILED_PRECONDITION
    copy.assert_not_called()
    user['firmware_deployment_service'].execute.assert_not_called()
