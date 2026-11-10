"""Known MCU PWM rejects incompatible effective values before publication."""
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


@pytest.mark.parametrize("source", ["root", "include", "save"])
@pytest.mark.parametrize("noop", [False, True])
def test_software_fan_shutdown_rejects_before_confirmation_and_writes(tmp_path, source, noop):
    content = _generate(tmp_path); context = _context(tmp_path, content)
    remote = destination(content, "fan", "shutdown_speed", ".5", source)
    plan = build_managed_config_plan(content, None, remote, geometry_context=context)
    if noop:
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        plan = build_managed_config_plan(content, None, remote, geometry_context=context)
        assert not plan.changed_artifacts
    review = validate_configuration_plan(plan)
    assert not review.valid and any("shutdown" in error.message for error in review.errors)
    transport = FakeTransport(remote); before = dict(transport.files); confirm = Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, content, None, geometry_context=context,
        activation="none", confirm=confirm, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path/"snapshots")).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    confirm.assert_not_called()
    _assert_no_destination_mutations(transport, before)


@pytest.mark.parametrize("override", [
    "[fan]\nshutdown_speed: .5\n",
    "[heater_fan Aux]\npin: PG10\nmax_power: .5\n",
    "[output_pin led]\npin: PG10\npwm: true\nscale: 255\nshutdown_value: 127.5\n",
    "[output_pin led]\npin: PG10\npwm: true\ncycle_time: 3.01\n",
])
def test_postrender_pwm_defect_leaves_existing_cfg_and_provenance_intact(tmp_path, monkeypatch, override):
    import core.generator as generator
    original = generator._postprocess_generated_output
    monkeypatch.setattr(generator, "_postprocess_generated_output", lambda text: original(text)+"\n"+override)
    target, sidecar = tmp_path/"printer.cfg", tmp_path/"printer.cfg.provenance.json"
    target.write_bytes(b"existing cfg"); sidecar.write_bytes(b"existing provenance")
    with pytest.raises(GenerationError):
        _generate(tmp_path)
    assert target.read_bytes() == b"existing cfg"
    assert sidecar.read_bytes() == b"existing provenance"


@pytest.mark.parametrize("kind,extra", [
    ("heater_fan Aux", "max_power: .5\n"),
    ("controller_fan Aux", "shutdown_speed: .5\n"),
    ("fan_generic Aux", "shutdown_speed: .5\n"),
    ("temperature_fan Aux", "sensor_type: Generic 3950\nsensor_pin: PG11\ncontrol: watermark\nmin_temp: 0\nmax_temp: 100\nmax_power: .5\n"),
    ("output_pin Aux", "pwm: true\nscale: 255\nshutdown_value: 127.5\n"),
])
def test_preserved_consumer_uses_its_mcu_provider_contract(tmp_path, kind, extra):
    content = _generate(tmp_path); context = _context(tmp_path, content)
    remote = {"printer.cfg": content+b"\n[include user.cfg]\n", "user.cfg": b"[include nested.cfg]\n",
        "nested.cfg": (f"[{kind}]\npin: PG10\n"+extra).encode()}
    plan = build_managed_config_plan(content, None, remote, geometry_context=context)
    review = validate_configuration_plan(plan)
    assert not review.valid and any("shutdown" in error.message for error in review.errors)
    transport = FakeTransport(remote); before = dict(transport.files); confirm = Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, content, None, geometry_context=context,
        activation="none", confirm=confirm, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path/"snapshots")).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    confirm.assert_not_called()
    _assert_no_destination_mutations(transport, before)


@pytest.mark.parametrize("source", ["root", "include", "save"])
def test_compatible_binary_shutdown_is_preserved_on_publish(tmp_path, source):
    content = _generate(tmp_path); context = _context(tmp_path, content)
    transport = FakeTransport(destination(content, "fan", "shutdown_speed", "1", source))
    result = ConfigDeploymentTransaction(transport, content, None, geometry_context=context,
        activation="none", confirm=lambda _: True, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path/"snapshots")).run()
    assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    plan = build_managed_config_plan(content, None, transport.files, geometry_context=context)
    assert _read_pin_config(effective_hardware_text(plan))[0]["fan"]["shutdown_speed"] == "1"
