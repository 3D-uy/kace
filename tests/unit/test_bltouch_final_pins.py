"""Final BLTouch pin checks must run after rendering and reconciliation."""
import copy

import pytest

from core.exceptions import GenerationError
from core.generator import generate_config
from core.configuration_review import validate_configuration_plan
from core.managed_config import build_managed_config_plan
from core.firmware_workflow import persistable_wizard_data
from tests.unit.test_generator import _parsed, _user


@pytest.mark.parametrize("role,section,field", [
    ("sensor_pin", "stepper_y", "endstop_pin"),
    ("control_pin", "stepper_x", "endstop_pin"),
    ("control_pin", "extruder", "sensor_pin"),
    ("control_pin", "extruder", "enable_pin"),
    ("sensor_pin", "stepper_z", "step_pin"),
    ("control_pin", "heater_bed", "heater_pin"),
])
def test_final_conflict_preserves_existing_output(tmp_path, role, section, field):
    parsed = _parsed(bltouch={"sensor_pin": "^PB8", "control_pin": "PB9"})
    parsed["bltouch"][role] = parsed[section][field].lstrip("^~!")
    output = tmp_path / "printer.cfg"
    output.write_bytes(b"existing user configuration")
    before = copy.deepcopy(parsed)
    with pytest.raises(GenerationError, match="BLTouch"):
        generate_config(parsed, _user(probe="BLTouch"), output_path=str(output), verbose=False)
    assert output.read_bytes() == b"existing user configuration"
    assert not (tmp_path / "printer.cfg.provenance.json").exists()
    assert parsed == before


def test_sensor_can_reuse_z_input_after_rendering_replaces_it(tmp_path):
    parsed = _parsed(bltouch={"sensor_pin": "^PB8", "control_pin": "PB9"})
    parsed["stepper_z"]["endstop_pin"] = "^PB8"
    result = generate_config(parsed, _user(probe="BLTouch"), output_path=str(tmp_path / "printer.cfg"), verbose=False)
    assert "endstop_pin: probe:z_virtual_endstop" in result["content"]


@pytest.mark.parametrize("probe", ["BLTouch", "CR-Touch"])
def test_manual_and_persisted_choices_are_validated_after_overrides(tmp_path, probe):
    parsed = _parsed(bltouch={"sensor_pin": "^PB8", "control_pin": "PB9"})
    user = persistable_wizard_data(_user(probe=probe, bltouch_control_pin=parsed["extruder"]["sensor_pin"]))
    with pytest.raises(GenerationError, match="BLTouch"):
        generate_config(parsed, user, output_path=str(tmp_path / "printer.cfg"), verbose=False)
    assert not (tmp_path / "printer.cfg").exists()


def test_nonconflicting_manual_choice_is_rendered_without_mutating_source(tmp_path):
    parsed = _parsed(bltouch={"sensor_pin": "^PB8", "control_pin": "PB9"})
    before = copy.deepcopy(parsed)
    result = generate_config(parsed, _user(probe="BLTouch", bltouch_control_pin="PB10"),
                             output_path=str(tmp_path / "printer.cfg"), verbose=False)
    assert "control_pin: PB10" in result["content"]
    assert parsed == before


@pytest.mark.parametrize("pins,other", [
    ("sensor_pin: ^PB1\ncontrol_pin: PB1", ""),
    ("sensor_pin: ^SENSOR\ncontrol_pin: CONTROL", "[board_pins]\naliases: SENSOR=PB1,CONTROL=PB1"),
    ("sensor_pin: ^PB1\ncontrol_pin: CONTROL", "[board_pins]\naliases: CONTROL=<reserved>"),
    ("sensor_pin: ^PB1\ncontrol_pin: PB0", "[fan]\npin: !PB0"),
    ("sensor_pin: ^PB1\ncontrol_pin: PB0", "[stepper_z]\nendstop_pin: ^PB1"),
    ("sensor_pin: ^PB1\ncontrol_pin: PB0", "[multi_pin fans]\npins: PA0,PB0"),
    ("sensor_pin: ^PB1\ncontrol_pin: PB0", "[display]\nencoder_pins: ^PB0,^PA0"),
    ("sensor_pin: ^PB1\ncontrol_pin: PB0", "[duplicate_pin_override]\npins: PB0\n[fan]\npin: PB0"),
    ("sensor_pin: ^PB1\ncontrol_pin: ^PB0", ""),
    ("sensor_pin: toolhead:!PB1\ncontrol_pin: PB0", ""),
])
def test_reconciled_hardware_rejects_conflicts_and_invalid_modifiers(pins, other):
    content = f"[bltouch]\n{pins}\n{other}\n".encode()
    plan = build_managed_config_plan(content, None, {"printer.cfg": None, "moonraker.conf": None})
    result = validate_configuration_plan(plan)
    assert any(error.code == "bltouch-pin-conflict" for error in result.errors)


@pytest.mark.parametrize("other", [
    "[fan]\npin: toolhead:PB0",
    "[gcode_macro TEST]\ngcode:\n    M118 PB0\ndescription: PB1",
    "#[fan]\n#pin: PB0",
    "[stepper_x]\nenable_pin: !PA0\n[stepper_y]\nenable_pin: !PA0",
])
def test_unrelated_metadata_comments_and_shared_enables_are_not_conflicts(other):
    content = f"[bltouch]\nsensor_pin: ^PB1\ncontrol_pin: PB0\n{other}\n".encode()
    plan = build_managed_config_plan(content, None, {"printer.cfg": None, "moonraker.conf": None})
    assert not any(error.code == "bltouch-pin-conflict" for error in validate_configuration_plan(plan).errors)


def test_existing_include_conflict_blocks_transaction_before_upload(tmp_path):
    from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
    from tests.unit.test_config_transaction import FakeTransport, GENERATED

    generated = GENERATED + b"[stepper_z]\nendstop_pin: probe:z_virtual_endstop\n[bltouch]\nsensor_pin: ^PB8\ncontrol_pin: PB9\n"
    transport = FakeTransport({"printer.cfg": GENERATED + b"[include user.cfg]\n",
                               "user.cfg": b"[fan]\npin: !PB9\n"})
    original = dict(transport.files)
    result = ConfigDeploymentTransaction(
        transport, generated, None, activation="firmware", confirm=lambda _: True,
        output=lambda _: None, snapshot_root=str(tmp_path), poll_interval=0,
    ).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "BLTouch" in result.detail
    assert transport.files == original
    assert not any(call[0] in ("upload", "delete", "restart", "restart_moonraker")
                   for call in transport.calls)


def test_later_include_override_is_validated_in_effective_order():
    generated = b"[bltouch]\nsensor_pin: ^PB8\ncontrol_pin: PB9\n"
    current = {"printer.cfg": b"[mcu]\nserial: /tmp/test\n[include user.cfg]\n",
               "user.cfg": b"[bltouch]\ncontrol_pin: PA0\n[heater_bed]\nheater_pin: PA0\n"}
    plan = build_managed_config_plan(generated, None, current)
    assert any(error.code == "bltouch-pin-conflict" for error in validate_configuration_plan(plan).errors)
