"""Empty heater binding survives effective review and simulated publication."""
from unittest.mock import Mock
import pytest
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.managed_config import build_managed_config_plan, effective_hardware_text, _section_options
from tests.integration.test_heater_options_contract import destination
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_effective_xy_geometry import _generate, _context, _assert_no_destination_mutations

SECTION = "heater_fan EmptyAudit"


@pytest.mark.parametrize("source", ["root", "include", "save"])
@pytest.mark.parametrize("noop", [False, True])
def test_empty_binding_survives_effective_transaction(tmp_path, source, noop):
    base = _generate(tmp_path); context = _context(tmp_path, base)
    remote = destination(base + f"\n[{SECTION}]\npin: PG10\n".encode(), SECTION, "heater", "", source)
    plan = build_managed_config_plan(base, None, remote, geometry_context=context)
    if noop:
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        plan = build_managed_config_plan(base, None, remote, geometry_context=context)
        assert not plan.changed_artifacts
    assert validate_configuration_plan(plan).valid
    assert _section_options(effective_hardware_text(plan))[SECTION]["heater"] == ""
    transport = FakeTransport(remote)
    result = ConfigDeploymentTransaction(transport, base, None, geometry_context=context,
        activation="none", confirm=lambda _: True, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path/"snapshots")).run()
    assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    final = build_managed_config_plan(base, None, transport.files, geometry_context=context)
    assert _section_options(effective_hardware_text(final))[SECTION]["heater"] == ""


@pytest.mark.parametrize("source", ["root", "include", "save"])
def test_malformed_nonempty_list_blocks_before_confirmation(tmp_path, source):
    base = _generate(tmp_path); context = _context(tmp_path, base)
    remote = destination(base + f"\n[{SECTION}]\npin: PG10\n".encode(), SECTION, "heater", "extruder,", source)
    transport = FakeTransport(remote); before = dict(transport.files); confirm = Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, base, None, geometry_context=context,
        activation="none", confirm=confirm, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path/"snapshots")).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    confirm.assert_not_called()
    _assert_no_destination_mutations(transport, before)
