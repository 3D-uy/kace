"""Selected-source G28 procedures cannot silently become ordinary homing."""
import json
from unittest.mock import Mock

import pytest

from core.board_auxiliary import selected_board_electrical_source, validate_board_electrical_artifact
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.exceptions import GenerationError
from core.firmware_workflow import persistable_wizard_data
from core.generator import generate_config
from core.managed_config import build_managed_config_plan
from core.scraper import parse_config
from tests.unit.test_config_transaction import FakeTransport, GENERATED
from tests.unit.test_generator import _parsed, _user


PROCEDURES = {
    'sensorless_current': '[homing_override]\ngcode:\n    SET_TMC_CURRENT STEPPER=stepper_x CURRENT=0.5\n    G28\n',
    'axis_order': '[homing_override]\ngcode:\n    G28 Z\n    G28 X Y\n',
    'probe_preparation': '[homing_override]\naxes: z\nset_position_z: 0\ngcode:\n    G1 Z5\n    G28\n',
    'virtual_z_reset': '[homing_override]\naxes: z\nset_position_z: 0\ngcode:\n    G92 Z0\n',
}


@pytest.mark.parametrize('procedure', PROCEDURES.values(), ids=PROCEDURES.keys())
@pytest.mark.parametrize('origin', ['board', 'profile'])
def test_source_homing_blocks_before_generation_writes(tmp_path, procedure, origin):
    board, user = _parsed(), _user()
    source = parse_config(procedure, keep_comments=True)
    if origin == 'board':
        board.update(source)
    else:
        user.update(_profile_parsed=source, raw_config=procedure, profile_loaded=True)
    target = tmp_path/'printer.cfg'
    target.write_text('unchanged')
    with pytest.raises(GenerationError, match='homing_override'):
        generate_config(board, user, output_path=str(target), verbose=False)
    assert target.read_text() == 'unchanged'
    assert not (tmp_path/'printer.cfg.provenance.json').exists()


@pytest.mark.parametrize('procedure', PROCEDURES.values(), ids=PROCEDURES.keys())
@pytest.mark.parametrize('noop', [False, True])
def test_saved_artifact_cannot_bypass_source_procedure(tmp_path, procedure, noop):
    source = parse_config(procedure)
    remote = {'printer.cfg': GENERATED}
    if noop:
        remote.update({a.remote_name: a.content for a in build_managed_config_plan(GENERATED, None, remote).artifacts})
        assert not build_managed_config_plan(GENERATED, None, remote).changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, GENERATED, None, selected_board=source,
        activation='none', confirm=confirm, verify_existing_ready=noop,
        snapshot_root=str(tmp_path/'snapshots')).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert 'homing_override' in result.detail
    confirm.assert_not_called()
    assert transport.files == remote and all(c[0] == 'read' for c in transport.calls)


@pytest.mark.parametrize('origin', ['board', 'profile'])
@pytest.mark.parametrize('raw', [False, True])
def test_json_recovery_retains_homing_boundary(origin, raw):
    text = PROCEDURES['axis_order']
    data = {'board': 'selected.cfg', 'board_parsed': _parsed()}
    key, raw_key = ('board_parsed', 'board_raw_config') if origin == 'board' else ('_profile_parsed', 'raw_config')
    data[key] = parse_config(text)
    if raw:
        data[raw_key] = text
    saved = json.loads(json.dumps(persistable_wizard_data(data)))
    with pytest.raises(GenerationError, match='homing_override'):
        selected_board_electrical_source({'workflow_checkpoint': {'wizard_data': saved}})


@pytest.mark.parametrize('keep_comments', [False, True])
def test_commented_example_does_not_become_requirement(tmp_path, keep_comments):
    text = '#[homing_override]\n#gcode:\n#    G28 Z\n'
    board = _parsed()
    board.update(parse_config(text, keep_comments=keep_comments))
    result = generate_config(board, _user(), output_path=str(tmp_path/'printer.cfg'), verbose=False)
    assert '[homing_override]' not in result['content']
    validate_board_electrical_artifact(parse_config(text, keep_comments=keep_comments), GENERATED)


@pytest.mark.parametrize('origin', ['board', 'profile'])
def test_old_commented_discovery_requires_raw_source_to_recover(origin):
    parsed_key, raw_key = ('board_parsed', 'board_raw_config') if origin == 'board' else ('_profile_parsed', 'raw_config')
    data = {'board': 'selected.cfg', 'board_parsed': _parsed(), parsed_key: {'homing_override': {'gcode': ''}}}
    with pytest.raises(GenerationError, match='homing_override'):
        selected_board_electrical_source(data)
    data[raw_key] = '#[homing_override]\n#gcode:\n#    G28\n'
    source = selected_board_electrical_source(data)
    validate_board_electrical_artifact(source, GENERATED)


@pytest.mark.parametrize('override', [{'profile_loaded': False}, {'_profile_parsed': {}, 'raw_config': ''}])
def test_live_flags_cannot_erase_saved_homing_dependency(override):
    saved = {'board': 'selected.cfg', 'board_parsed': _parsed(),
             '_profile_parsed': parse_config(PROCEDURES['axis_order'])}
    with pytest.raises(GenerationError, match='homing_override'):
        selected_board_electrical_source({**override, 'workflow_checkpoint': {'wizard_data': saved}})


def test_matching_user_include_does_not_certify_source_homing():
    text = PROCEDURES['axis_order']
    with pytest.raises(GenerationError, match='homing_override'):
        validate_board_electrical_artifact(parse_config(text), GENERATED.decode()+'\n'+text)


def test_print_strategy_is_not_part_of_this_boundary(tmp_path):
    board = _parsed()
    board.update(parse_config('[gcode_macro PRINT_START]\ngcode:\n    G28\n'))
    text = generate_config(board, _user(), output_path=str(tmp_path/'printer.cfg'), verbose=False)['content']
    assert '[gcode_macro PRINT_START]' not in text
    # Source-agnostic manual APIs retain existing review responsibilities.
    assert selected_board_electrical_source({}) is None


def test_raw_active_source_cannot_be_hidden_by_an_empty_parsed_map(tmp_path):
    user = _user(raw_config=PROCEDURES['axis_order'], _profile_parsed={})
    with pytest.raises(GenerationError, match='homing_override'):
        generate_config(_parsed(), user, output_path=str(tmp_path/'printer.cfg'), verbose=False)


@pytest.mark.parametrize('noop', [False, True])
def test_effective_safe_z_home_and_override_conflict_before_write(tmp_path, noop):
    generated = GENERATED + b'\n[safe_z_home]\nhome_xy_position: 100, 100\n'
    remote = {'printer.cfg': generated+b'\n[include user.cfg]\n',
              'user.cfg': b'[include homing.cfg]\n',
              'homing.cfg': PROCEDURES['axis_order'].encode()}
    if noop:
        remote.update({a.remote_name: a.content for a in build_managed_config_plan(generated, None, remote).artifacts})
        assert not build_managed_config_plan(generated, None, remote).changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, generated, None, activation='none', confirm=confirm,
        verify_existing_ready=noop, snapshot_root=str(tmp_path/'snapshots')).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert 'homing_override' in result.detail and 'safe_z_home' in result.detail
    confirm.assert_not_called()
    assert transport.files == remote and all(c[0] == 'read' for c in transport.calls)
