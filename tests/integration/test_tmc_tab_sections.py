"""Effective TMC current bounds apply before simulated publication."""
from unittest.mock import Mock
import pytest
from core.configuration_review import validate_configuration_plan
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.pin_validator import _read_pin_config
from tests.integration.test_heater_options_contract import destination
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_effective_xy_geometry import _generate, _context, _assert_no_destination_mutations


@pytest.mark.parametrize('separator', [' ', '\t'])
@pytest.mark.parametrize('source', ['root', 'include', 'save'])
@pytest.mark.parametrize('noop', [False, True])
@pytest.mark.parametrize('value,valid', [('-1', False), ('0.580', True)])
def test_current_review_and_transaction(tmp_path, separator, source, noop, value, valid):
    base = _generate(tmp_path)
    ctx = _context(tmp_path, base)
    section = 'tmc2209' + separator + 'stepper_x'
    driver = f'\n[{section}]\nuart_pin: PG13\n'.encode()
    remote = destination(base + driver, section, 'run_current', value, source)
    plan = build_managed_config_plan(base, None, remote, geometry_context=ctx)
    if noop:
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        plan = build_managed_config_plan(base, None, remote, geometry_context=ctx)
        assert not plan.changed_artifacts
    assert _read_pin_config(effective_hardware_text(plan))[0][section]['run_current'] == value
    review = validate_configuration_plan(plan)
    assert review.valid == valid, review.errors
    transport = FakeTransport(remote)
    before = dict(transport.files)
    confirm = Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, base, None, geometry_context=ctx,
        activation='none', confirm=confirm, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path/'snapshots')).run()
    if valid:
        assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
        assert confirm.call_count == 1
        if noop:
            _assert_no_destination_mutations(transport, before)
    else:
        assert result.state == ConfigTransactionState.PRECONDITION_FAILED
        confirm.assert_not_called()
        _assert_no_destination_mutations(transport, before)
