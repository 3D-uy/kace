"""Effective sensor PWM limits reject before confirmation, file writes or no-op."""
from unittest.mock import Mock
import pytest

from core.configuration_review import validate_configuration_plan
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.pin_validator import _read_pin_config
from core.exceptions import GenerationError
from tests.integration.test_heater_options_contract import destination
from tests.unit.test_effective_xy_geometry import _generate, _context, _assert_no_destination_mutations
from tests.unit.test_config_transaction import FakeTransport


@pytest.mark.parametrize("section", ["extruder", "heater_bed"])
@pytest.mark.parametrize("source", ["root", "include", "save"])
@pytest.mark.parametrize("noop", [False, True])
def test_sensor_pwm_above_limit_never_reaches_confirmation_or_writes(tmp_path, section, source, noop):
    content = _generate(tmp_path); context = _context(tmp_path, content)
    remote = destination(content, section, "pwm_cycle_time", ".301", source)
    plan = build_managed_config_plan(content, None, remote, geometry_context=context)
    if noop:
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        plan = build_managed_config_plan(content, None, remote, geometry_context=context)
        assert not plan.changed_artifacts
    review = validate_configuration_plan(plan)
    assert not review.valid and any(e.code == "heater-options" and "pwm_cycle_time" in e.message for e in review.errors)
    transport = FakeTransport(remote); before = dict(transport.files); confirm = Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, content, None, geometry_context=context,
        activation="none", confirm=confirm, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path/"snapshots")).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    confirm.assert_not_called()
    _assert_no_destination_mutations(transport, before)


@pytest.mark.parametrize("section", ["extruder", "heater_bed"])
def test_generated_invalid_pwm_preserves_cfg_and_sidecar(tmp_path, monkeypatch, section):
    import core.generator as generator
    original = generator._postprocess_generated_output
    monkeypatch.setattr(generator, "_postprocess_generated_output",
        lambda text: original(text)+f"\n[{section}]\npwm_cycle_time: .301\n")
    target, sidecar = tmp_path/"printer.cfg", tmp_path/"printer.cfg.provenance.json"
    target.write_bytes(b"existing cfg"); sidecar.write_bytes(b"existing provenance")
    with pytest.raises(GenerationError, match="pwm_cycle_time"):
        _generate(tmp_path)
    assert target.read_bytes() == b"existing cfg"
    assert sidecar.read_bytes() == b"existing provenance"


@pytest.mark.parametrize("source", ["root", "include", "save"])
def test_exact_sensor_limit_is_deployed_and_preserved(tmp_path, source):
    content = _generate(tmp_path); context = _context(tmp_path, content)
    transport = FakeTransport(destination(content, "heater_bed", "pwm_cycle_time", ".300", source))
    result = ConfigDeploymentTransaction(transport, content, None, geometry_context=context,
        activation="none", confirm=lambda _: True, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path/"snapshots")).run()
    assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    plan = build_managed_config_plan(content, None, transport.files, geometry_context=context)
    assert _read_pin_config(effective_hardware_text(plan))[0]["heater_bed"]["pwm_cycle_time"] == ".300"


@pytest.mark.parametrize("kind,curve", [
    ("thermistor", "temperature1: 25\nresistance1: 100000\nbeta: 3950\n"),
    ("adc_temperature", "temperature1: 0\nvoltage1: 0\ntemperature2: 300\nvoltage2: 3\n"),
])
@pytest.mark.parametrize("pwm,valid", [(".300", True), (".301", False)])
def test_custom_sensor_name_remains_case_sensitive_through_effective_review(tmp_path, kind, curve, pwm, valid):
    content = _generate(tmp_path); context = _context(tmp_path, content)
    override = (f"[{kind} Audit Custom]\n{curve}\n[heater_generic chamber]\n"
        "heater_pin: PG10\nsensor_type: Audit Custom\nsensor_pin: PG11\n"
        f"control: watermark\nmin_temp: 0\nmax_temp: 250\npwm_cycle_time: {pwm}\n").encode()
    remote = {"printer.cfg": content+b"\n[include user.cfg]\n",
        "user.cfg": b"[include nested.cfg]\n", "nested.cfg": override}
    plan = build_managed_config_plan(content, None, remote, geometry_context=context)
    review = validate_configuration_plan(plan)
    assert review.valid == valid, review.errors
    transport = FakeTransport(remote); before = dict(transport.files); confirm = Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, content, None, geometry_context=context,
        activation="none", confirm=confirm, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path/"snapshots")).run()
    if valid:
        assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    else:
        assert any(e.code == "heater-options" for e in review.errors)
        assert result.state == ConfigTransactionState.PRECONDITION_FAILED
        confirm.assert_not_called()
        _assert_no_destination_mutations(transport, before)
