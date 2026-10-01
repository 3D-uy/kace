"""Unsupported Replicape platform must not yield a publishable partial config."""
from unittest.mock import Mock
import pytest
from core.exceptions import GenerationError
from core.generator import generate_config
from core.scraper import parse_config
from core.board_auxiliary import require_supported_board_electrical_dependencies, selected_board_electrical_source
from core.configuration_review import validate_configuration_plan
from core.managed_config import build_managed_config_plan
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from tests.unit.test_generator import _parsed, _user
from tests.unit.test_config_transaction import FakeTransport


@pytest.mark.parametrize('source', ['active', 'legacy', 'recovered'])
def test_platform_source_cannot_generate_or_resume(source, tmp_path):
    raw = '[replicape]\nrevision: B3\nhost_mcu: host\n'
    parsed = parse_config(raw, 'platform.cfg') if source != 'legacy' else {'replicape': {'revision':'B3'}}
    if source == 'recovered':
        parsed = selected_board_electrical_source({'workflow_checkpoint': {'wizard_data':
            {'board':'platform.cfg','board_raw_config':raw}}})
    board = _parsed(**parsed)
    with pytest.raises(GenerationError, match='[Rr]eplicape'):
        generate_config(board, _user(), output_path=str(tmp_path/'printer.cfg'), verbose=False)
    assert list(tmp_path.iterdir()) == []


def test_commented_platform_example_does_not_enable_or_block_hardware(tmp_path):
    board = _parsed(**parse_config('#[replicape]\n#revision: B3\n'))
    generate_config(board, _user(), output_path=str(tmp_path/'printer.cfg'), verbose=False)


@pytest.mark.parametrize('section,field,pin', [
    ('fan','pin','replicape:power_fan0'),
    ('stepper_x','enable_pin','replicape : stepper_x_enable'),
    ('heater_bed','heater_pin','!replicape:power_hotbed'),
])
def test_missing_platform_provider_blocks_generated_consumers(tmp_path, section, field, pin):
    board = _parsed()
    board[section][field] = pin
    path = tmp_path/'printer.cfg'
    path.write_bytes(b'previous')
    with pytest.raises(GenerationError, match='[Rr]eplicape'):
        generate_config(board, _user(), output_path=str(path), verbose=False)
    assert path.read_bytes() == b'previous'
    assert not (tmp_path/'printer.cfg.provenance.json').exists()


@pytest.mark.parametrize('payload', ['[fan]\npin: replicape:power_fan0\n',
                                    '[replicape]\nrevision: B3\nhost_mcu: host\n'])
@pytest.mark.parametrize('noop', [False, True])
def test_effective_platform_blocks_nested_publish_and_noop(tmp_path, payload, noop):
    text = generate_config(_parsed(), _user(), output_path=str(tmp_path/'base.cfg'), verbose=False)['content']
    remote = {'printer.cfg': (text+'\n[include user.cfg]\n').encode(),
              'user.cfg': b'[include platform.cfg]\n','platform.cfg':payload.encode()}
    plan = lambda: build_managed_config_plan(text.encode(), None, remote)
    if noop:
        remote.update({a.remote_name:a.content for a in plan().artifacts})
        assert not plan().changed_artifacts
    assert any(e.code == 'platform-dependency' for e in validate_configuration_plan(plan()).errors)
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, text.encode(), None,
        activation='none', confirm=confirm, verify_existing_ready=noop,
        snapshot_root=str(tmp_path/'snapshots'), poll_interval=0).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED, result
    confirm.assert_not_called()
    assert transport.files == remote
    assert not any(c[0] in ('upload','delete','restart','restart_moonraker') for c in transport.calls)


@pytest.mark.parametrize('fields', [
    {'pins':'PA1, !replicape : power_fan0'},
    {'select_pins':'PA1,replicape:stepper_x_enable'},
    {'encoder_pins':'PA1, replicape:servo0'},
])
def test_pin_lists_do_not_hide_missing_provider(fields):
    from core.board_auxiliary import validate_replicape_platform
    with pytest.raises(GenerationError, match='Replicape pin provider'):
        validate_replicape_platform({'resource test':fields})


def test_real_mcu_named_replicape_is_not_the_platform():
    from core.board_auxiliary import validate_replicape_platform
    validate_replicape_platform({'mcu replicape':{'serial':'/tmp/klipper_host_other'},
                                 'fan':{'pin':'replicape:gpio2'}})
    with pytest.raises(GenerationError, match='outside KACE installation support'):
        validate_replicape_platform({'mcu replicape':{},'replicape':{'revision':'B3'}})


def test_names_comments_and_macro_bodies_are_not_platform_consumers(tmp_path):
    from core.board_auxiliary import validate_replicape_platform
    validate_replicape_platform({'gcode_macro replicape':{'gcode':'RESPOND MSG="replicape:power_fan0"'}})
    text = generate_config(_parsed(), _user(), output_path=str(tmp_path/'printer.cfg'), verbose=False)['content']
    text += '\n#[replicape]\n#revision: B3\n#pin: replicape:power_fan0\n'
    result = validate_configuration_plan(build_managed_config_plan(text.encode(),None,{}))
    assert result.valid,result.errors


@pytest.mark.parametrize('source', [None, {}])
def test_old_artifact_cannot_bypass_platform_guard_without_source(source):
    from core.board_auxiliary import validate_board_electrical_artifact
    with pytest.raises(GenerationError, match='Replicape pin provider'):
        validate_board_electrical_artifact(source, b'[fan]\npin: replicape:power_fan0\n')
