"""Heater options from effective hardware must reject before publication."""
from unittest.mock import Mock
import re
import pytest
from core.configuration_review import validate_configuration_plan
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.pin_validator import _read_pin_config
from core.exceptions import GenerationError
from tests.unit.test_effective_xy_geometry import _generate, _context, _assert_no_destination_mutations
from tests.unit.test_config_transaction import FakeTransport


def destination(content, section, option, value, source):
    if source == "save":
        if option.startswith("pid_"):
            # SAVE_CONFIG comments the corresponding active calibration.
            # Leaving an active duplicate would keep that explicit override.
            head, tail = content.decode().split(f"[{section}]", 1)
            tail = re.sub(rf"(?mi)^{option}\s*:.*$", "# saved calibration", tail, count=1)
            content = (head+f"[{section}]"+tail).encode()
        return {"printer.cfg": content + (
            "\n#*# <---------------------- SAVE_CONFIG ---------------------->\n"
            "#*# DO NOT EDIT THIS BLOCK OR BELOW. The contents are auto-generated.\n#*#\n"
            f"#*# [{section}]\n#*# {option} = {value}\n").encode()}
    override = f"[{section}]\n{option}: {value}\n".encode()
    if source == "include":
        return {"printer.cfg": content+b"\n[include user.cfg]\n", "user.cfg": b"[include nested.cfg]\n", "nested.cfg": override}
    return {"printer.cfg": content+b"\n"+override}


@pytest.mark.parametrize("section,value", [("heater_bed", "0"), ("extruder", "nan")])
@pytest.mark.parametrize("source", ["root", "include", "save"])
@pytest.mark.parametrize("noop", [False, True])
def test_invalid_power_blocks_before_confirmation_and_writes(tmp_path, section, value, source, noop):
    content = _generate(tmp_path); context = _context(tmp_path, content)
    remote = destination(content, section, "max_power", value, source)
    plan = build_managed_config_plan(content, None, remote, geometry_context=context)
    if noop:
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        plan = build_managed_config_plan(content, None, remote, geometry_context=context)
        assert not plan.changed_artifacts
    assert _read_pin_config(effective_hardware_text(plan))[0][section]["max_power"] == value
    review = validate_configuration_plan(plan)
    assert not review.valid and any(e.code == "heater-options" for e in review.errors)
    transport = FakeTransport(remote); before = dict(transport.files); confirm = Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, content, None, geometry_context=context,
        activation="none", confirm=confirm, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path/"snapshots")).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    confirm.assert_not_called()
    _assert_no_destination_mutations(transport, before)


@pytest.mark.parametrize("section,option,value", [
    ("heater_bed", "min_temp", "-274"), ("heater_bed", "max_temp", "0"),
    ("heater_bed", "smooth_time", "0"), ("heater_bed", "pwm_cycle_time", "0"),
    ("extruder", "max_power", "1.01"), ("extruder", "pid_kp", "nan"),
])
def test_postrender_invalid_heater_options_leave_existing_artifacts_intact(tmp_path, monkeypatch, section, option, value):
    import core.generator as generator
    original = generator._postprocess_generated_output
    monkeypatch.setattr(generator, "_postprocess_generated_output",
        lambda text: original(text)+f"\n[{section}]\n{option}: {value}\n")
    target, sidecar = tmp_path/"printer.cfg", tmp_path/"printer.cfg.provenance.json"
    target.write_bytes(b"existing cfg");sidecar.write_bytes(b"existing sidecar")
    with pytest.raises(GenerationError, match=option):
        _generate(tmp_path)
    assert target.read_bytes() == b"existing cfg"
    assert sidecar.read_bytes() == b"existing sidecar"


@pytest.mark.parametrize("source", ["root", "include", "save"])
def test_finite_negative_pid_remains_compatible_and_preserved(tmp_path, source):
    content = _generate(tmp_path);context = _context(tmp_path, content)
    remote = destination(content, "heater_bed", "pid_ki", "-1", source)
    transport = FakeTransport(remote)
    result = ConfigDeploymentTransaction(transport, content, None, geometry_context=context,
        activation="none", confirm=lambda _: True, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path/"snapshots")).run()
    assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    actual = effective_hardware_text(build_managed_config_plan(content, None, transport.files, geometry_context=context))
    assert _read_pin_config(actual)[0]["heater_bed"]["pid_ki"] == "-1"
