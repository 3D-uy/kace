"""Preserved SX1509 incompatibilities reject before confirmation and writes."""
from unittest.mock import Mock
import pytest

from core.configuration_review import validate_configuration_plan
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.exceptions import GenerationError
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.pin_validator import _read_pin_config
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_effective_xy_geometry import _generate, _context, _assert_no_destination_mutations


PROVIDER = "[sx1509 Expander]\ni2c_address: 62\ni2c_bus: i2c1\n"
FAN = "[fan_generic Aux]\npin: sx1509_Expander:PIN_0\n"


@pytest.mark.parametrize("source", ["root", "include", "save"])
@pytest.mark.parametrize("noop", [False, True])
def test_missing_sx_hardware_mode_stops_before_confirmation_and_publication(tmp_path, source, noop):
    content = _generate(tmp_path); context = _context(tmp_path, content)
    extra = PROVIDER + FAN
    if source == "include":
        remote = {"printer.cfg": content+b"\n[include user.cfg]\n", "user.cfg": b"[include nested.cfg]\n",
            "nested.cfg": (extra+"hardware_pwm: false\n").encode()}
    elif source == "save":
        remote = {"printer.cfg": content+b"\n"+extra.encode()+(
            "\n#*# <---------------------- SAVE_CONFIG ---------------------->\n"
            "#*# DO NOT EDIT THIS BLOCK OR BELOW. The contents are auto-generated.\n#*#\n"
            "#*# [fan_generic Aux]\n#*# hardware_pwm = false\n").encode()}
    else:
        remote = {"printer.cfg": content+b"\n"+(extra+"hardware_pwm: false\n").encode()}
    plan = build_managed_config_plan(content, None, remote, geometry_context=context)
    if noop:
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        plan = build_managed_config_plan(content, None, remote, geometry_context=context)
        assert not plan.changed_artifacts
    review = validate_configuration_plan(plan)
    assert not review.valid and any(e.code == "sx1509-pwm" for e in review.errors)
    transport = FakeTransport(remote); before = dict(transport.files); confirm = Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, content, None, geometry_context=context,
        activation="none", confirm=confirm, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path/"snapshots")).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    confirm.assert_not_called()
    _assert_no_destination_mutations(transport, before)


@pytest.mark.parametrize("consumer", [
    FAN,
    "[heater_generic Aux]\nheater_pin: sx1509_Expander:PIN_0\nsensor_type: Generic 3950\nsensor_pin: PG11\ncontrol: watermark\nmin_temp: 0\nmax_temp: 250\n",
    "[output_pin Aux]\npin: sx1509_Expander:PIN_0\npwm: true\nhardware_pwm: true\ncycle_time: 3.001\n",
])
def test_sx_postrender_gate_preserves_existing_cfg_and_sidecar(tmp_path, monkeypatch, consumer):
    import core.generator as generator
    original = generator._postprocess_generated_output
    monkeypatch.setattr(generator, "_postprocess_generated_output", lambda text: original(text)+"\n"+PROVIDER+consumer)
    target, sidecar = tmp_path/"printer.cfg", tmp_path/"printer.cfg.provenance.json"
    target.write_bytes(b"existing cfg"); sidecar.write_bytes(b"existing provenance")
    with pytest.raises(GenerationError, match="SX1509|cycle_time"):
        _generate(tmp_path)
    assert target.read_bytes() == b"existing cfg"
    assert sidecar.read_bytes() == b"existing provenance"


def test_sx_hardware_fractional_shutdown_is_preserved_on_publish(tmp_path):
    content = _generate(tmp_path); context = _context(tmp_path, content)
    override = PROVIDER + FAN + "hardware_pwm: true\nshutdown_speed: .5\ncycle_time: 10\n"
    transport = FakeTransport({"printer.cfg": content+b"\n[include user.cfg]\n", "user.cfg": override.encode()})
    result = ConfigDeploymentTransaction(transport, content, None, geometry_context=context,
        activation="none", confirm=lambda _: True, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path/"snapshots")).run()
    assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    plan = build_managed_config_plan(content, None, transport.files, geometry_context=context)
    fields = _read_pin_config(effective_hardware_text(plan))[0]["fan_generic Aux"]
    assert fields["hardware_pwm"] == "true" and fields["shutdown_speed"] == ".5" and fields["cycle_time"] == "10"


@pytest.mark.parametrize("family,extra", [
    ("fan_generic Aux", ""),
    ("temperature_fan Aux", "sensor_type: Generic 3950\nsensor_pin: PG11\ncontrol: watermark\nmin_temp: 0\nmax_temp: 100\n"),
])
def test_saved_hardware_mode_keeps_the_exact_fan_instance_name(tmp_path, family, extra):
    content = _generate(tmp_path); context = _context(tmp_path, content)
    body = PROVIDER + f"[{family}]\npin: sx1509_Expander:PIN_0\n" + extra
    saved = ("\n#*# <---------------------- SAVE_CONFIG ---------------------->\n"
        "#*# DO NOT EDIT THIS BLOCK OR BELOW. The contents are auto-generated.\n#*#\n"
        f"#*# [{family}]\n#*# hardware_pwm = true\n").encode()
    remote = {"printer.cfg": content+b"\n"+body.encode()+saved}
    plan = build_managed_config_plan(content, None, remote, geometry_context=context)
    fields = _read_pin_config(effective_hardware_text(plan))[0]
    assert fields[family]["hardware_pwm"] == "true"
    assert family.casefold() not in fields
    review = validate_configuration_plan(plan)
    assert review.valid, review.errors
