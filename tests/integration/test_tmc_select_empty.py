"""Explicit empty UART selectors survive generation and effective publication."""
import json
from unittest.mock import Mock

import pytest

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.exceptions import GenerationError
from core.generator import generate_config
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.pin_validator import _read_pin_config
from tests.integration.test_heater_options_contract import destination
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_effective_xy_geometry import _generate, _context, _assert_no_destination_mutations
from tests.unit.test_generator import _parsed, _user


MODELS = ('tmc2208', 'tmc2209', 'tmc2240')


def driver(model):
    return f'\n[{model} stepper_x]\nuart_pin: PG13\nrun_current: .4\n'.encode()


@pytest.mark.parametrize('model', ('tmc2208', 'tmc2209'))
@pytest.mark.parametrize('selector', [None, '', '   '])
def test_guided_generation_preserves_selector_presence_and_provenance(tmp_path, model, selector):
    name = model+' stepper_x'
    board = _parsed()
    board[name] = {'uart_pin': 'PG13', 'run_current': '.4'}
    if selector is not None:
        board[name]['select_pins'] = selector
    output = tmp_path/'printer.cfg'
    generate_config(board, _user(driver_type=model.upper(), driver_mode='UART', z_motors='1'),
                    output_path=str(output), verbose=False)
    fields = _read_pin_config(output.read_text(encoding='utf-8'))[0][name]
    trace = json.loads(output.with_suffix('.cfg.provenance.json').read_text(encoding='utf-8'))['sources']['tmc_options'][name]['options']
    if selector is None:
        assert 'select_pins' not in fields and 'select_pins' not in trace
    else:
        assert fields['select_pins'] == ''
        assert trace['select_pins']['value'] == ''
        assert trace['select_pins']['origin'] == 'SELECTED_BOARD'


@pytest.mark.parametrize('model', MODELS)
@pytest.mark.parametrize('source', ['root', 'include', 'save'])
@pytest.mark.parametrize('noop', [False, True])
def test_effective_empty_selector_can_publish_without_becoming_omitted(tmp_path, model, source, noop):
    base = _generate(tmp_path)
    context = _context(tmp_path, base)
    section = model+' stepper_x'
    remote = destination(base+driver(model), section, 'select_pins', '', source)
    plan = build_managed_config_plan(base, None, remote, geometry_context=context)
    if noop:
        remote.update({a.remote_name:a.content for a in plan.artifacts})
        plan = build_managed_config_plan(base, None, remote, geometry_context=context)
        assert not plan.changed_artifacts
    review = validate_configuration_plan(plan)
    assert review.valid, review.errors
    assert _read_pin_config(effective_hardware_text(plan))[0][section]['select_pins'] == ''
    transport = FakeTransport(remote)
    before = dict(transport.files)
    result = ConfigDeploymentTransaction(transport, base, None, geometry_context=context,
        activation='none', confirm=lambda _:True, output=lambda _:None, poll_interval=0,
        snapshot_root=str(tmp_path/'snapshots')).run()
    assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    if noop:
        _assert_no_destination_mutations(transport, before)
    effective = effective_hardware_text(build_managed_config_plan(base, None, transport.files, geometry_context=context))
    assert _read_pin_config(effective)[0][section]['select_pins'] == ''


@pytest.mark.parametrize('model', MODELS)
@pytest.mark.parametrize('source', ['root', 'include', 'save'])
@pytest.mark.parametrize('noop', [False, True])
def test_malformed_selector_list_still_blocks_before_confirmation_and_writes(tmp_path, model, source, noop):
    base = _generate(tmp_path)
    context = _context(tmp_path, base)
    section = model+' stepper_x'
    remote = destination(base+driver(model), section, 'select_pins', ',', source)
    plan = build_managed_config_plan(base, None, remote, geometry_context=context)
    if noop:
        remote.update({a.remote_name:a.content for a in plan.artifacts})
        plan = build_managed_config_plan(base, None, remote, geometry_context=context)
        assert not plan.changed_artifacts
    review = validate_configuration_plan(plan)
    assert not review.valid and any(e.code == 'tmc-uart-conflict' for e in review.errors)
    transport = FakeTransport(remote)
    before = dict(transport.files)
    confirm = Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, base, None, geometry_context=context,
        activation='none', confirm=confirm, output=lambda _:None, poll_interval=0,
        snapshot_root=str(tmp_path/'snapshots')).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    confirm.assert_not_called()
    _assert_no_destination_mutations(transport, before)


@pytest.mark.parametrize('model', ('tmc2208', 'tmc2209'))
def test_malformed_source_preserves_existing_cfg_and_sidecar(tmp_path, model):
    board = _parsed()
    board[model+' stepper_x'] = {'uart_pin': 'PG13', 'run_current': '.4', 'select_pins': ','}
    cfg, trace = tmp_path/'printer.cfg', tmp_path/'printer.cfg.provenance.json'
    cfg.write_bytes(b'existing cfg')
    trace.write_bytes(b'existing sidecar')
    with pytest.raises(GenerationError, match='select pin'):
        generate_config(board, _user(driver_type=model.upper(), driver_mode='UART', z_motors='1'),
                        output_path=str(cfg), verbose=False)
    assert cfg.read_bytes() == b'existing cfg' and trace.read_bytes() == b'existing sidecar'
