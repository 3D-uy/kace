"""Review and publication use exact TMC SAVE_CONFIG section identities."""
from unittest.mock import Mock
import pytest

from core.configuration_review import validate_configuration_plan
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.pin_validator import _read_pin_config
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_effective_xy_geometry import _assert_no_destination_mutations, _context, _generate
from tests.unit.test_saved_sensor_case import block, saved


@pytest.mark.parametrize('sep', [' ', '\t'])
@pytest.mark.parametrize('source', ['root', 'include'])
@pytest.mark.parametrize('noop', [False, True])
@pytest.mark.parametrize('address,valid', [('3', True), ('4', False)])
def test_saved_address_review_and_publication(tmp_path, sep, source, noop, address, valid):
    content = _generate(tmp_path)
    context = _context(tmp_path, content)
    section = f'tmc2209{sep}extruder_stepper Mix'
    active = block(section, {'uart_pin': 'PG10', 'run_current': '0.5'}).encode()
    autosave = saved(section, {'uart_address': address}).encode()
    if source == 'root':
        remote = {'printer.cfg': content + active + autosave}
    else:
        remote = {'printer.cfg': content + b'\n[include user.cfg]\n' + autosave,
                  'user.cfg': b'[include nested.cfg]\n', 'nested.cfg': active}
    plan = build_managed_config_plan(content, None, remote, geometry_context=context)
    if noop:
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        plan = build_managed_config_plan(content, None, remote, geometry_context=context)
        assert not plan.changed_artifacts
    assert _read_pin_config(effective_hardware_text(plan))[0][section]['uart_address'] == address
    review = validate_configuration_plan(plan)
    assert review.valid == valid, review.errors
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    before = dict(transport.files)
    result = ConfigDeploymentTransaction(transport, content, None, geometry_context=context,
        activation='none', confirm=confirm, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path/'snapshots')).run()
    if valid:
        assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
        assert confirm.call_count == 1
        assert transport.files['printer.cfg'].endswith(autosave)
        if source == 'include':
            assert transport.files['nested.cfg'] == remote['nested.cfg']
        if noop:
            _assert_no_destination_mutations(transport, before)
    else:
        assert result.state == ConfigTransactionState.PRECONDITION_FAILED
        confirm.assert_not_called()
        _assert_no_destination_mutations(transport, before)
