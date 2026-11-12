"""Controller reference-list rejection occurs before confirmation and writes."""
from unittest.mock import Mock
import pytest

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.exceptions import GenerationError
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.pin_validator import _read_pin_config
from tests.integration.test_heater_options_contract import destination
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_effective_xy_geometry import _generate, _context, _assert_no_destination_mutations


SECTION = "controller_fan RefAudit"
EXTRA = f"\n[{SECTION}]\npin: PG10\n"


@pytest.mark.parametrize("option,value", [("heater","extruder,"),("stepper",",stepper_x")])
@pytest.mark.parametrize("source", ["root", "include", "save"])
@pytest.mark.parametrize("noop", [False, True])
def test_bad_list_blocks_effective_publication(tmp_path, option, value, source, noop):
    base = _generate(tmp_path); context = _context(tmp_path, base)
    remote = destination(base+EXTRA.encode(), SECTION, option, value, source)
    plan = build_managed_config_plan(base, None, remote, geometry_context=context)
    if noop:
        remote.update({a.remote_name:a.content for a in plan.artifacts})
        plan = build_managed_config_plan(base, None, remote, geometry_context=context)
        assert not plan.changed_artifacts
    review = validate_configuration_plan(plan)
    assert not review.valid and any(e.code == "controller-fan-references" for e in review.errors)
    transport = FakeTransport(remote); before = dict(transport.files); confirm = Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, base, None, geometry_context=context,
        activation="none", confirm=confirm, output=lambda _:None, poll_interval=0,
        snapshot_root=str(tmp_path/"snapshots")).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    confirm.assert_not_called()
    _assert_no_destination_mutations(transport,before)


@pytest.mark.parametrize("option", ["heater", "stepper"])
def test_bad_postrender_preserves_existing_cfg_and_provenance(tmp_path, monkeypatch, option):
    import core.generator as generator
    original = generator._postprocess_generated_output
    monkeypatch.setattr(generator, "_postprocess_generated_output", lambda text:
        original(text)+EXTRA+option+": ,\n")
    cfg,sidecar = tmp_path/"printer.cfg",tmp_path/"printer.cfg.provenance.json"
    cfg.write_bytes(b"existing cfg"); sidecar.write_bytes(b"existing provenance")
    with pytest.raises(GenerationError, match="empty reference"):
        _generate(tmp_path)
    assert cfg.read_bytes() == b"existing cfg" and sidecar.read_bytes() == b"existing provenance"


@pytest.mark.parametrize("source", ["root", "include", "save"])
def test_explicit_empty_binding_preserved_by_publication(tmp_path, source):
    base = _generate(tmp_path); context = _context(tmp_path, base)
    remote = destination(base+(EXTRA+"heater:\n").encode(), SECTION, "stepper", "", source)
    transport = FakeTransport(remote)
    result = ConfigDeploymentTransaction(transport, base, None, geometry_context=context,
        activation="none", confirm=lambda _:True, output=lambda _:None, poll_interval=0,
        snapshot_root=str(tmp_path/"snapshots")).run()
    assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    plan = build_managed_config_plan(base,None,transport.files,geometry_context=context)
    fields = _read_pin_config(effective_hardware_text(plan))[0][SECTION]
    assert fields["heater"] == fields["stepper"] == ""
