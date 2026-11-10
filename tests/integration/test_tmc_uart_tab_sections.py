"""Effective UART references are validated before any destination writes."""
from unittest.mock import Mock

import pytest
from core.configuration_review import validate_configuration_plan
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.managed_config import build_managed_config_plan
from tests.integration.test_heater_options_contract import destination
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_effective_xy_geometry import _generate, _context, _assert_no_destination_mutations


@pytest.mark.parametrize("separator", [" ", "\t"])
@pytest.mark.parametrize("source", ["root", "include", "save"])
@pytest.mark.parametrize("noop", [False, True])
@pytest.mark.parametrize("address,valid", [("0", True), ("3", True), ("4", False)])
def test_uart_address_before_publication(tmp_path, separator, source, noop, address, valid):
    base = _generate(tmp_path)
    context = _context(tmp_path, base)
    section = "tmc2209" + separator + "stepper_x"
    driver = f"\n[{section}]\nuart_pin: PG13\nrun_current: 0.580\n".encode()
    remote = destination(base + driver, section, "uart_address", address, source)
    plan = build_managed_config_plan(base, None, remote, geometry_context=context)
    if noop:
        remote.update({item.remote_name: item.content for item in plan.artifacts})
        plan = build_managed_config_plan(base, None, remote, geometry_context=context)
        assert not plan.changed_artifacts
    review = validate_configuration_plan(plan)
    assert review.valid == valid, review.errors
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    before = dict(transport.files)
    result = ConfigDeploymentTransaction(transport, base, None, geometry_context=context,
        activation="none", confirm=confirm, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path / "snapshots")).run()
    if valid:
        assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
        assert confirm.call_count == 1
        if noop:
            _assert_no_destination_mutations(transport, before)
    else:
        assert result.state == ConfigTransactionState.PRECONDITION_FAILED
        confirm.assert_not_called()
        _assert_no_destination_mutations(transport, before)
