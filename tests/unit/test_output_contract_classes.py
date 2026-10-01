"""Electrical output composition by behavior, without profile-name fixtures."""
import json
from unittest.mock import Mock

import pytest

from core.board_auxiliary import selected_board_electrical_source, validate_board_electrical_artifact
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.exceptions import GenerationError
from core.firmware_workflow import persistable_wizard_data
from core.generator import generate_config
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.scraper import parse_config
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_generator import _parsed, _user

STATIC = '[static_digital_output rails]\npins: !PG1, PG2\n'
DIGITAL = '[output_pin machine_enable]\npin: !PG3\nvalue: 1\nshutdown_value: 1\n'
CASES = [('static', STATIC, 'static_digital_output rails', ('pins: PG1, PG2', 'pins: !PG1, PG4')),
         ('digital', DIGITAL, 'output_pin machine_enable', ('shutdown_value: 0', 'value: 0')),
         ('combined', STATIC + DIGITAL, 'output_pin machine_enable', ('pin: PG2', 'pwm: true'))]


@pytest.fixture(params=CASES, ids=lambda case: case[0])
def circuit(request, tmp_path):
    name, raw, section, mutations = request.param
    selected = parse_config(raw, keep_comments=True)
    board = {**_parsed(), **selected}
    user = _user(_profile_parsed=parse_config('[output_pin machine_enable]\npin: PG9\nvalue: 0\n'))
    content = generate_config(board, user, output_path=str(tmp_path/'printer.cfg'), verbose=False)['content']
    return raw, selected, content, section, mutations


def test_class_survives_json_recovery_and_two_publications(circuit, tmp_path):
    raw, selected, content, _, _ = circuit
    user = {'board':'selected.cfg', 'board_raw_config':raw, 'board_parsed':selected}
    saved = json.loads(json.dumps(persistable_wizard_data(user)))
    recovered = selected_board_electrical_source({'workflow_checkpoint':{'wizard_data':saved}})
    transport = FakeTransport()
    for _ in range(2):
        result = ConfigDeploymentTransaction(transport, content.encode(), None, selected_board=recovered,
            activation='none', snapshot_root=str(tmp_path/'snapshots')).run()
        assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION, result.detail
        plan = build_managed_config_plan(content.encode(), None, transport.files)
        assert not plan.changed_artifacts
        validate_board_electrical_artifact(recovered, effective_hardware_text(plan))


def test_alias_equivalence_does_not_erase_mcu_or_polarity(circuit):
    _, selected, content, _, _ = circuit
    pin = 'PG1' if 'static_digital_output rails' in selected else 'PG3'
    equivalent = content.replace(pin, 'SIGNAL') + f'\n[board_pins]\naliases: SIGNAL={pin}\n'
    validate_board_electrical_artifact(selected, equivalent)
    for wrong in (content.replace('!'+pin, pin),
                  content.replace('!'+pin, '!aux:'+pin) + '\n[mcu aux]\nserial: /tmp/aux\n'):
        with pytest.raises(GenerationError, match='missing or changed'):
            validate_board_electrical_artifact(selected, wrong)


@pytest.mark.parametrize('mutation', [0, 1])
@pytest.mark.parametrize('noop', [False, True])
def test_effective_role_or_level_mutation_stops_before_confirmation(circuit, tmp_path, mutation, noop):
    _, selected, content, section, mutations = circuit
    remote = {'printer.cfg':content.encode()+b'\n[include user.cfg]\n',
              'user.cfg':f'[{section}]\n{mutations[mutation]}\n'.encode()}
    if noop:
        remote.update({a.remote_name:a.content for a in build_managed_config_plan(content.encode(), None, remote).artifacts})
        assert not build_managed_config_plan(content.encode(), None, remote).changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, content.encode(), None, selected_board=selected,
        activation='firmware', confirm=confirm, snapshot_root=str(tmp_path/'snapshots'),
        verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED, result.detail
    confirm.assert_not_called()
    assert transport.files == remote and all(call[0]=='read' for call in transport.calls)
