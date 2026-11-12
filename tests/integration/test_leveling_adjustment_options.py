"""Effective leveling options must fail before approving or publishing files."""
from unittest.mock import Mock

import pytest

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.exceptions import GenerationError
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.pin_validator import _read_pin_config
from tests.integration.test_leveling_z_contract import generate, leveling_text
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_effective_xy_geometry import _assert_no_destination_mutations


def destination(content, section, option, value, source):
    base = leveling_text(section)
    if source == "save":
        return {"printer.cfg": content + b"\n" + base + (
            "\n#*# <---------------------- SAVE_CONFIG ---------------------->\n"
            "#*# DO NOT EDIT THIS BLOCK OR BELOW. The contents are auto-generated.\n#*#\n"
            f"#*# [{section}]\n#*# {option} = {value}\n").encode()}
    override = base + f"{option}: {value}\n".encode()
    if source == "include":
        return {"printer.cfg": content + b"\n[include user.cfg]\n",
                "user.cfg": b"[include nested.cfg]\n", "nested.cfg": override}
    return {"printer.cfg": content + b"\n" + override}


@pytest.mark.parametrize("section,option,value", [
    ("z_tilt", "retry_tolerance", "0"),
    ("quad_gantry_level", "max_adjust", "nan"),
])
@pytest.mark.parametrize("source", ["root", "include", "save"])
@pytest.mark.parametrize("noop", [False, True])
def test_invalid_adjustment_option_blocks_before_confirmation_and_writes(tmp_path, section, option, value, source, noop):
    content, context = generate(tmp_path, section)
    remote = destination(content, section, option, value, source)
    plan = build_managed_config_plan(content, None, remote, geometry_context=context)
    if noop:
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        plan = build_managed_config_plan(content, None, remote, geometry_context=context)
        assert not plan.changed_artifacts
    assert _read_pin_config(effective_hardware_text(plan))[0][section][option] == value
    validation = validate_configuration_plan(plan)
    assert not validation.valid
    assert all(e.code == "leveling-adjustment-options" for e in validation.errors)
    transport = FakeTransport(remote)
    before = dict(transport.files)
    confirm = Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, content, None, geometry_context=context,
        activation="none", confirm=confirm, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path / "snapshots")).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    confirm.assert_not_called()
    _assert_no_destination_mutations(transport, before)


@pytest.mark.parametrize("section", ["z_tilt", "quad_gantry_level"])
@pytest.mark.parametrize("option,value", [
    ("retries", "-1"), ("retries", "1.5"), ("retry_tolerance", "nan"),
])
def test_invalid_preserved_retry_values_are_rejected(tmp_path, section, option, value):
    content, context = generate(tmp_path, section)
    plan = build_managed_config_plan(content, None,
        destination(content, section, option, value, "include"), geometry_context=context)
    result = validate_configuration_plan(plan)
    assert not result.valid
    assert any(e.code == "leveling-adjustment-options" and option in e.message for e in result.errors)


@pytest.mark.parametrize("section", ["z_tilt", "quad_gantry_level"])
@pytest.mark.parametrize("source", ["root", "include", "save"])
def test_compatible_config_values_above_command_bounds_remain_publishable(tmp_path, section, source):
    content, context = generate(tmp_path, section)
    remote = destination(content, section, "retries", "31", source)
    # Separate preserved file exercises both CFG values without applying
    # command-only maxima (30 retries and tolerance 1) to configuration.
    remote["printer.cfg"] += b"\n[include tolerance.cfg]\n"
    remote["tolerance.cfg"] = f"[{section}]\nretry_tolerance: 1.01\n".encode()
    transport = FakeTransport(remote)
    result = ConfigDeploymentTransaction(transport, content, None, geometry_context=context,
        activation="none", confirm=Mock(return_value=True), output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path / "snapshots")).run()
    assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    actual = effective_hardware_text(build_managed_config_plan(content, None, transport.files, geometry_context=context))
    settings = _read_pin_config(actual)[0][section]
    assert settings["retries"] == "31"
    assert settings["retry_tolerance"] == "1.01"


@pytest.mark.parametrize("section,option,value", [
    ("z_tilt", "retries", "-1"), ("z_tilt", "retry_tolerance", "0"),
    ("quad_gantry_level", "max_adjust", "nan"),
])
def test_invalid_postrender_adjustment_options_leave_cfg_and_sidecar_intact(tmp_path, monkeypatch, section, option, value):
    import core.generator as generator
    original = generator._postprocess_generated_output
    override = leveling_text(section).decode() + f"{option}: {value}\n"
    monkeypatch.setattr(generator, "_postprocess_generated_output", lambda text: original(text) + "\n" + override)
    target, sidecar = tmp_path / "printer.cfg", tmp_path / "printer.cfg.provenance.json"
    target.write_bytes(b"existing cfg")
    sidecar.write_bytes(b"existing sidecar")
    with pytest.raises(GenerationError, match=option):
        generate(tmp_path, section)
    assert target.read_bytes() == b"existing cfg"
    assert sidecar.read_bytes() == b"existing sidecar"
