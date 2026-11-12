"""Effective queued PWM contracts fail before confirmation or any writes."""
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


@pytest.mark.parametrize("kind", ["pwm_tool", "pwm_cycle_time"])
@pytest.mark.parametrize("source", ["root", "include", "save"])
@pytest.mark.parametrize("noop", [False, True])
def test_queued_shutdown_rejected_before_confirmation_or_publication(tmp_path, kind, source, noop):
    content = _generate(tmp_path); context = _context(tmp_path, content)
    # A pre-existing named consumer can be overridden through all three sources.
    active = content + f"\n[{kind} Audit]\npin: PG10\n".encode()
    remote = destination(active, kind + " Audit", "shutdown_value", ".5", source)
    plan = build_managed_config_plan(content, None, remote, geometry_context=context)
    if noop:
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        plan = build_managed_config_plan(content, None, remote, geometry_context=context)
        assert not plan.changed_artifacts
    review = validate_configuration_plan(plan)
    assert not review.valid and any(e.code == "pwm-output" for e in review.errors)
    transport = FakeTransport(remote); before = dict(transport.files); confirm = Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, content, None, geometry_context=context,
        activation="none", confirm=confirm, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path/"snapshots")).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    confirm.assert_not_called()
    _assert_no_destination_mutations(transport, before)


@pytest.mark.parametrize("kind,fields", [
    ("pwm_tool", "cycle_time: 3.001\n"),
    ("pwm_cycle_time", "shutdown_value: .5\n"),
    ("pwm_tool", "maximum_mcu_duration: 0\n"),
    ("pwm_tool", "maximum_mcu_duration: .5\nvalue: .5\n"),
    ("pwm_cycle_time", "scale: inf\n"),
])
def test_postrender_keeps_existing_artifacts_on_rejection(tmp_path, monkeypatch, kind, fields):
    import core.generator as generator
    original = generator._postprocess_generated_output
    monkeypatch.setattr(generator, "_postprocess_generated_output", lambda text:
        original(text)+f"\n[{kind} Audit]\npin: PG10\n"+fields)
    cfg, sidecar = tmp_path/"printer.cfg", tmp_path/"printer.cfg.provenance.json"
    cfg.write_bytes(b"existing cfg"); sidecar.write_bytes(b"existing provenance")
    with pytest.raises(GenerationError):
        _generate(tmp_path)
    assert cfg.read_bytes() == b"existing cfg"
    assert sidecar.read_bytes() == b"existing provenance"


@pytest.mark.parametrize("fields", ["value: .5\n", "maximum_mcu_duration: .5\n",
    "hardware_pwm: true\nvalue: .5\nshutdown_value: .5\nmaximum_mcu_duration: 3\n"])
def test_compatible_tool_defaults_and_equal_watchdog_are_preserved(tmp_path, fields):
    content = _generate(tmp_path); context = _context(tmp_path, content)
    remote = {"printer.cfg": content+b"\n[include user.cfg]\n",
        "user.cfg": ("[pwm_tool Audit]\npin: PG10\n"+fields).encode()}
    transport = FakeTransport(remote)
    result = ConfigDeploymentTransaction(transport, content, None, geometry_context=context,
        activation="none", confirm=lambda _: True, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path/"snapshots")).run()
    assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    plan = build_managed_config_plan(content, None, transport.files, geometry_context=context)
    actual = _read_pin_config(effective_hardware_text(plan))[0]["pwm_tool Audit"]
    for key, value in (line.split(": ") for line in fields.strip().splitlines()):
        assert actual[key] == value
