"""Consumer-role failures reject effective configurations before writes."""
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


def section_text(kind):
    return f"\n[{kind} Audit]\npin: PG10\n" + (
        "sensor_type: Generic 3950\nsensor_pin: PG11\nmin_temp: 0\nmax_temp: 100\ncontrol: watermark\n"
        if kind == "temperature_fan" else "")


@pytest.mark.parametrize("kind,option,value", [
    ("controller_fan", "fan_speed", "1.1"),
    ("controller_fan", "idle_timeout", "1.5"),
    ("temperature_fan", "target_temp", "nan"),
    ("temperature_fan", "max_delta", "0"),
])
@pytest.mark.parametrize("source", ["root", "include", "save"])
@pytest.mark.parametrize("noop", [False, True])
def test_invalid_role_blocks_before_confirmation_and_publication(tmp_path, kind, option, value, source, noop):
    content = _generate(tmp_path); context = _context(tmp_path, content)
    remote = destination(content + section_text(kind).encode(), kind + " Audit", option, value, source)
    plan = build_managed_config_plan(content, None, remote, geometry_context=context)
    if noop:
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        plan = build_managed_config_plan(content, None, remote, geometry_context=context)
        assert not plan.changed_artifacts
    review = validate_configuration_plan(plan)
    assert not review.valid and any(e.code == "fan-consumers" for e in review.errors)
    transport = FakeTransport(remote); before = dict(transport.files); confirm = Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, content, None, geometry_context=context,
        activation="none", confirm=confirm, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path/"snapshots")).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    confirm.assert_not_called()
    _assert_no_destination_mutations(transport, before)


@pytest.mark.parametrize("kind,fields", [
    ("controller_fan", "idle_speed: inf\n"),
    ("temperature_fan", "max_speed: 0\n"),
    ("temperature_fan", "control: pid\npid_Kp: 1\npid_Ki: 0\n"),
])
def test_invalid_postrender_preserves_cfg_and_provenance(tmp_path, monkeypatch, kind, fields):
    import core.generator as generator
    original = generator._postprocess_generated_output
    monkeypatch.setattr(generator, "_postprocess_generated_output", lambda text:
        original(text) + section_text(kind) + fields)
    cfg, sidecar = tmp_path/"printer.cfg", tmp_path/"printer.cfg.provenance.json"
    cfg.write_bytes(b"existing cfg"); sidecar.write_bytes(b"existing provenance")
    with pytest.raises(GenerationError):
        _generate(tmp_path)
    assert cfg.read_bytes() == b"existing cfg"
    assert sidecar.read_bytes() == b"existing provenance"


@pytest.mark.parametrize("kind,fields", [
    ("controller_fan", "fan_speed: 0\nidle_speed: 0\nidle_timeout: 0\nheater:\nstepper:\n"),
    ("temperature_fan", "min_speed: .8\nmax_speed: .2\n"),
    ("temperature_fan", "min_temp: 50\n"),
    ("temperature_fan", "target_temp: 0\nmin_speed: 0\n"),
    ("temperature_fan", "control: pid\npid_kp: -1\npid_ki: 0\npid_kd: -1\n"),
])
def test_compatible_values_remain_exact_through_transaction(tmp_path, kind, fields):
    content = _generate(tmp_path); context = _context(tmp_path, content)
    remote = {"printer.cfg": content+b"\n[include user.cfg]\n",
              "user.cfg": (section_text(kind)+fields).encode()}
    transport = FakeTransport(remote)
    result = ConfigDeploymentTransaction(transport, content, None, geometry_context=context,
        activation="none", confirm=lambda _: True, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path/"snapshots")).run()
    assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    plan = build_managed_config_plan(content, None, transport.files, geometry_context=context)
    actual = _read_pin_config(effective_hardware_text(plan))[0][kind+" Audit"]
    for line in fields.strip().splitlines():
        key, value = line.split(":", 1)
        assert actual[key] == value.strip()
