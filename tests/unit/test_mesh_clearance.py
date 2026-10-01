"""Bed-mesh clearance must never be lowered by parsing or reconciliation."""
import copy
import json
from unittest.mock import Mock

import pytest

from core.bed_mesh import generate_bed_mesh_config
from core.configuration_review import validate_configuration_plan
from core.exceptions import GenerationError
from core.generator import generate_config
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.motion_model import PrinterMotionSpace
from core.pin_validator import _read_pin_config
from tests.unit.test_generator import _parsed, _user


VALID = ("10", "10.0", "10.5", "10.123456789012345", "1.05e1", "0", 10.5)
INVALID = ("", "bad", "nan", "NaN", "inf", "-inf", "1e999", None, True)


def generate(tmp_path, value="10.5", **user):
    parsed = _parsed(bltouch={"sensor_pin": "^PB8", "control_pin": "PB9"},
                     bed_mesh={"horizontal_move_z": value})
    return generate_config(parsed, _user(probe="BLTouch", **user),
                           output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]


@pytest.mark.parametrize("value", VALID)
@pytest.mark.parametrize("probe", ["BLTouch", "CR-Touch", "Inductive"])
def test_explicit_height_is_not_truncated_or_replaced(value, probe):
    user = {"x_size": "235", "y_size": "235", "probe": probe}
    parsed = {"bed_mesh": {"horizontal_move_z": value}}
    before = copy.deepcopy((user, parsed))
    result = generate_bed_mesh_config(PrinterMotionSpace(user), user, parsed)
    assert result["horizontal_move_z"] == str(value)
    assert (user, parsed) == before


@pytest.mark.parametrize("value", INVALID)
def test_invalid_explicit_values_fail_without_replacing_output(tmp_path, value):
    target = tmp_path / "printer.cfg"
    target.write_bytes(b"existing user configuration")
    with pytest.raises(GenerationError, match="horizontal_move_z"):
        generate(tmp_path, value)
    assert target.read_bytes() == b"existing user configuration"
    assert not (tmp_path / "printer.cfg.provenance.json").exists()


@pytest.mark.parametrize("value", VALID)
def test_generated_and_reconciled_height_is_preserved(tmp_path, value):
    content = generate(tmp_path, value)
    plan = build_managed_config_plan(content.encode(), None, {"printer.cfg": None})
    assert _read_pin_config(content)[0]["bed_mesh"]["horizontal_move_z"] == str(value)
    assert _read_pin_config(effective_hardware_text(plan))[0]["bed_mesh"]["horizontal_move_z"] == str(value)
    assert validate_configuration_plan(plan).valid


@pytest.mark.parametrize("source", ["root", "managed", "include"])
@pytest.mark.parametrize("generated,existing", [("5", "10.5"), ("10.5", "5")])
def test_existing_height_is_kept_and_second_plan_is_noop(tmp_path, source, generated, existing):
    content = generate(tmp_path, generated).encode()
    old = content.replace(f"horizontal_move_z: {generated}".encode(), f"horizontal_move_z: {existing}".encode())
    if source == "root":
        remote = {"printer.cfg": old}
    elif source == "managed":
        remote = {"printer.cfg": b"[mcu]\nserial: /tmp/klipper\n[include kace/generated-hardware.cfg]\n",
                  "kace/generated-hardware.cfg": old}
    else:
        remote = {"printer.cfg": content + b"\n[include user.cfg]\n",
                  "user.cfg": f"[bed_mesh]\nhorizontal_move_z: {existing}\n".encode()}
    plan = build_managed_config_plan(content, None, remote)
    assert _read_pin_config(effective_hardware_text(plan))[0]["bed_mesh"]["horizontal_move_z"] == existing
    remote.update({a.remote_name: a.content for a in plan.artifacts})
    assert not build_managed_config_plan(content, None, remote).changed_artifacts


def test_separate_profile_owns_height_and_switching_does_not_reuse_old_value(tmp_path):
    from core.firmware_workflow import persistable_wizard_data
    user = _user(probe="BLTouch", _profile_parsed={"bed_mesh": {"horizontal_move_z": "10.5"}})
    parsed = _parsed(bltouch={"sensor_pin": "^PB8", "control_pin": "PB9"}, bed_mesh={"horizontal_move_z": "2"})
    restored = json.loads(json.dumps(persistable_wizard_data(user)))
    first = generate_config(parsed, restored, output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]
    assert _read_pin_config(first)[0]["bed_mesh"]["horizontal_move_z"] == "10.5"
    restored["_profile_parsed"] = {}
    second = generate_config(parsed, restored, output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]
    assert _read_pin_config(second)[0]["bed_mesh"]["horizontal_move_z"] == "5"


@pytest.mark.parametrize("value", ["-0.01", "251"])
def test_height_outside_generated_z_or_probe_limits_is_rejected(tmp_path, value):
    with pytest.raises(GenerationError, match="horizontal_move_z"):
        generate(tmp_path, value)
    assert not (tmp_path / "printer.cfg").exists()


@pytest.mark.parametrize("value,offset,valid", [("10.5", "10.5", True), ("10.5", "10.6", False),
                                               ("-0.5", "-1", True)])
def test_custom_probe_height_uses_actual_offset(tmp_path, value, offset, valid):
    from core.custom_probe import parse_custom_probe_config
    user = _user(probe="Custom Probe", z_position_min="-2", custom_probe=parse_custom_probe_config(
        f"[probe]\npin: ^PB8\nx_offset: 0\ny_offset: 0\nz_offset: {offset}\n"))
    board = _parsed(bed_mesh={"horizontal_move_z": value})
    if not valid:
        with pytest.raises(GenerationError, match="z_offset"):
            generate_config(board, user, output_path=str(tmp_path / "printer.cfg"), verbose=False)
    else:
        content = generate_config(board, user, output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]
        assert _read_pin_config(content)[0]["bed_mesh"]["horizontal_move_z"] == value


@pytest.mark.parametrize("noop", [False, True])
@pytest.mark.parametrize("override", [
    "[bed_mesh]\nhorizontal_move_z: nan\n", "[bed_mesh]\nhorizontal_move_z: bad\n",
    "[bed_mesh]\nhorizontal_move_z: 251\n", "[bltouch]\nz_offset: 11\n",
    "[stepper_z]\nposition_max: 10\n"])
def test_invalid_effective_include_blocks_transaction(tmp_path, noop, override):
    from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
    from tests.unit.test_config_transaction import FakeTransport
    content = generate(tmp_path).encode()
    remote = {"printer.cfg": content + b"\n[include user.cfg]\n",
              "user.cfg": b"[include nested.cfg]\n", "nested.cfg": override.encode()}
    if noop:
        plan = build_managed_config_plan(content, None, remote)
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        assert not build_managed_config_plan(content, None, remote).changed_artifacts
    transport = FakeTransport(remote)
    before, confirm = dict(transport.files), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, content, None, activation="none", confirm=confirm,
        output=lambda _: None, snapshot_root=str(tmp_path / "snapshots"), poll_interval=0).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "horizontal_move_z" in result.detail
    confirm.assert_not_called()
    assert transport.files == before
    assert not any(c[0] in ("upload", "delete", "restart", "restart_moonraker") for c in transport.calls)


def test_without_probe_does_not_generate_or_validate_unused_mesh():
    user = {"probe": "None"}
    assert generate_bed_mesh_config(PrinterMotionSpace(user), user,
                                    {"bed_mesh": {"horizontal_move_z": "bad"}}) == {}


def test_post_render_height_is_rechecked_before_writing(tmp_path, monkeypatch):
    import core.generator as generator
    original = generator._postprocess_generated_output
    monkeypatch.setattr(generator, "_postprocess_generated_output", lambda text:
        original(text).replace("horizontal_move_z: 10.5", "horizontal_move_z: nan"))
    with pytest.raises(GenerationError, match="horizontal_move_z"):
        generate(tmp_path)
    assert not (tmp_path / "printer.cfg").exists()


def test_saved_probe_calibration_is_checked_against_height(tmp_path):
    content = generate(tmp_path).encode()
    current = content.replace(b"z_offset: 0", b"#z_offset: 0") + (
        b"\n#*# <---------------------- SAVE_CONFIG ---------------------->\n"
        b"#*# [bltouch]\n#*# z_offset = 11\n")
    plan = build_managed_config_plan(content, None, {"printer.cfg": current})
    assert any(e.code == "mesh-clearance" and "z_offset" in e.message
               for e in validate_configuration_plan(plan).errors)


@pytest.mark.parametrize("height,minimum,maximum,offset,valid", [
    ("5", "0", "5", "0", True), ("5.01", "0", "5", "0", False),
    ("-1", "-1", "250", "-2", True), ("-1.01", "-1", "250", "-2", False),
    ("0", "0", "250", "0", True), ("-0.01", "-1", "250", "0", False),
])
def test_known_limits_are_inclusive_without_inventing_positive_only_rule(height, minimum, maximum, offset, valid):
    from core.bed_mesh import validate_mesh_clearance
    sections = {"bed_mesh": {"horizontal_move_z": height}, "probe": {"z_offset": offset},
                "stepper_z": {"position_min": minimum, "position_max": maximum}}
    if valid:
        validate_mesh_clearance(sections)
    else:
        with pytest.raises(GenerationError, match="horizontal_move_z"):
            validate_mesh_clearance(sections)
