"""Generate, preserve and review mesh scalars before publication, without hardware."""
import json
import re
from unittest.mock import Mock

import pytest

from core.config_geometry import load_geometry_context
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.exceptions import GenerationError
from core.generator import generate_config
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.pin_validator import _read_pin_config
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_generator import _parsed, _user


FIELDS = ("speed", "fade_start", "fade_end", "fade_target", "adaptive_margin")


def generate(tmp_path, mesh=None, **choices):
    board = _parsed(bltouch={"sensor_pin": "^PB8", "control_pin": "PB9"}, bed_mesh=mesh or {})
    return generate_config(board, _user(probe="BLTouch", **choices),
                           output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"].encode()


def replace_mesh_options(text, options):
    match = re.search(rb"(?ms)^\[bed_mesh\]\n.*?(?=^\[|\Z)", text)
    assert match
    block = match[0]
    for key, value in options.items():
        replacement = f"{key}: {value}".encode()
        pattern = rb"(?m)^" + key.encode() + rb":.*$"
        if re.search(pattern, block):
            block = re.sub(pattern, replacement, block)
        else:
            block += b"\n" + replacement + b"\n"
    return text[:match.start()] + block + text[match.end():]


def test_checkpoint_profile_values_survive_generation_and_profile_switch(tmp_path):
    from core.firmware_workflow import persistable_wizard_data
    selected = {"speed": "77.125", "fade_start": "0", "fade_end": "0", "fade_target": "0", "adaptive_margin": "2.9"}
    restored = json.loads(json.dumps(persistable_wizard_data(_user(probe="BLTouch", _profile_parsed={"bed_mesh": selected}))))
    board = _parsed(bltouch={"sensor_pin": "^PB8", "control_pin": "PB9"}, bed_mesh={"speed": "99", "fade_end": "8"})
    text = generate_config(board, restored, output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]
    section = _read_pin_config(text)[0]["bed_mesh"]
    assert {k: section[k] for k in FIELDS} == selected
    restored["_profile_parsed"] = {}
    text = generate_config(board, restored, output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]
    section = _read_pin_config(text)[0]["bed_mesh"]
    assert section["speed"] == "120" and section["fade_end"] == "10"
    assert "adaptive_margin" not in section


@pytest.mark.parametrize("source", ["root", "managed", "include"])
def test_destination_tuning_is_preserved_and_second_plan_is_noop(tmp_path, source):
    content = generate(tmp_path, {"adaptive_margin": "5"})
    explicit = {"speed": "50.125", "fade_start": "0", "fade_end": "0", "fade_target": "0", "adaptive_margin": "2.9"}
    old = replace_mesh_options(content, explicit)
    if source == "root":
        remote = {"printer.cfg": old}
    elif source == "managed":
        remote = {"printer.cfg": b"[mcu]\nserial: /tmp/klipper\n[include kace/generated-hardware.cfg]\n",
                  "kace/generated-hardware.cfg": old}
    else:
        remote = {"printer.cfg": content + b"\n[include user.cfg]\n",
                  "user.cfg": ("[bed_mesh]\n" + "\n".join(f"{k}: {v}" for k, v in explicit.items()) + "\n").encode()}
    context = load_geometry_context(tmp_path / "printer.cfg", content)
    plan = build_managed_config_plan(content, None, remote, geometry_context=context)
    mesh = _read_pin_config(effective_hardware_text(plan))[0]["bed_mesh"]
    assert {k: mesh[k] for k in FIELDS} == explicit
    assert validate_configuration_plan(plan).valid
    remote.update({a.remote_name: a.content for a in plan.artifacts})
    assert not build_managed_config_plan(content, None, remote, geometry_context=context).changed_artifacts


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_nonfinite_generation_preserves_existing_output(tmp_path, field, value):
    path = tmp_path / "printer.cfg"
    path.write_bytes(b"existing configuration")
    with pytest.raises(GenerationError, match=field):
        generate(tmp_path, {field: value})
    assert path.read_bytes() == b"existing configuration"
    assert not (tmp_path / "printer.cfg.provenance.json").exists()


@pytest.mark.parametrize("field", FIELDS)
def test_postrender_nonfinite_scalar_is_rejected_before_write(tmp_path, monkeypatch, field):
    import core.generator as generator
    original = generator._postprocess_generated_output
    monkeypatch.setattr(generator, "_postprocess_generated_output", lambda text:
        replace_mesh_options(original(text).encode(), {field: "nan"}).decode())
    with pytest.raises(GenerationError, match=field):
        generate(tmp_path)
    assert not (tmp_path / "printer.cfg").exists()
    assert not (tmp_path / "printer.cfg.provenance.json").exists()


@pytest.mark.parametrize("source", ["include", "save"])
@pytest.mark.parametrize("noop", [False, True])
@pytest.mark.parametrize("field", FIELDS)
def test_nonfinite_effective_options_block_before_confirmation(tmp_path, source, noop, field):
    content = generate(tmp_path)
    if source == "include":
        remote = {"printer.cfg": content + b"\n[include user.cfg]\n", "user.cfg": b"[include nested.cfg]\n",
                  "nested.cfg": f"[bed_mesh]\n{field}: nan\n".encode()}
    else:
        match = re.search(rb"(?ms)^\[bed_mesh\]\n.*?(?=^\[|\Z)", content)
        assert match
        block = re.sub(rb"(?m)^" + field.encode() + rb":.*$", b"", match[0])
        active = content[:match.start()] + block + content[match.end():]
        remote = {"printer.cfg": active + (
            "\n#*# <---------------------- SAVE_CONFIG ---------------------->\n"
            "#*# DO NOT EDIT THIS BLOCK OR BELOW. The contents are auto-generated.\n#*#\n"
            f"#*# [bed_mesh]\n#*# {field} = nan\n").encode()}
    context = load_geometry_context(tmp_path / "printer.cfg", content)
    if noop:
        plan = build_managed_config_plan(content, None, remote, geometry_context=context)
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        assert not build_managed_config_plan(content, None, remote, geometry_context=context).changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    before = dict(transport.files)
    result = ConfigDeploymentTransaction(transport, content, None, activation="none", confirm=confirm,
        geometry_context=context, output=lambda _: None, snapshot_root=str(tmp_path / "snapshots"), poll_interval=0).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED and field in result.detail
    confirm.assert_not_called()
    assert transport.files == before
    assert not any(c[0] in ("upload", "delete", "restart", "restart_moonraker") for c in transport.calls)


@pytest.mark.parametrize("field", ["scan_overshoot", "split_delta_z", "move_check_distance"])
@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_preserved_extra_mesh_scalar_requires_finite_number(tmp_path, field, value):
    content = generate(tmp_path)
    context = load_geometry_context(tmp_path / "printer.cfg", content)
    remote = {"printer.cfg": content + b"\n[include tuning.cfg]\n",
              "tuning.cfg": f"[bed_mesh]\n{field}: {value}\n".encode()}
    validation = validate_configuration_plan(build_managed_config_plan(
        content, None, remote, geometry_context=context))
    assert not validation.valid
    assert any(field in error.message for error in validation.errors)
