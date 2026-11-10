"""FHW-01: active native sensorless homing must keep its operating contract."""
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from core.config_geometry import load_geometry_context
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.exceptions import GenerationError
from core.firmware_workflow import persistable_wizard_data, restore_wizard_data
from core.generator import generate_config
from core.managed_config import build_managed_config_plan
from core.tmc_sensorless import validate_tmc_virtual_endstops
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_reserved_pin_review import assert_untouched
from tests.unit.test_tmc_closure_paths import original_inputs
from tests.unit.test_tmc_sensorless import sections


MODELS = ("tmc2209", "tmc2130", "tmc5160")
INVALID = ("retract", "omitted-retract", "hold", "both")


def _sensorless(model="tmc2209", *, kinematics="cartesian"):
    data = sections(model)
    data["printer"] = {"kinematics": kinematics}
    data["stepper_x"]["homing_retract_dist"] = "0"
    return data


def _invalidate(data, case, model="tmc2209"):
    if case in ("retract", "both"):
        data["stepper_x"]["homing_retract_dist"] = "5"
    elif case == "omitted-retract":
        data["stepper_x"].pop("homing_retract_dist", None)
    if case in ("hold", "both"):
        data[f"{model} stepper_x"]["hold_current"] = "0.4"


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("case", INVALID)
def test_native_sensorless_rejects_retract_default_and_hold_current(model, case):
    data = _sensorless(model)
    _invalidate(data, case, model)
    before = deepcopy(data)
    with pytest.raises(GenerationError, match="homing_retract_dist|hold_current"):
        validate_tmc_virtual_endstops(data)
    assert data == before


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("physical", (False, True))
def test_valid_sensorless_and_unrelated_physical_homing_remain_unchanged(model, physical):
    data = _sensorless(model)
    if physical:
        data["stepper_x"].update(endstop_pin="PB2", homing_retract_dist="5")
        data[f"{model} stepper_x"]["hold_current"] = "0.4"
    # A separate cartesian rail is not implicated by X sensorless homing.
    data[f"{model} stepper_y"] = {"hold_current": "0.4"}
    data["stepper_y"] = {"endstop_pin": "PB3", "homing_retract_dist": "5"}
    before = deepcopy(data)
    validate_tmc_virtual_endstops(data)
    assert data == before


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("active_axis", ("x", "y"))
def test_corexy_sensorless_rejects_hold_on_other_motor_with_physical_endstop(model, active_axis):
    data = _sensorless(model, kinematics="corexy")
    other = "y" if active_axis == "x" else "x"
    if active_axis == "y":
        data["stepper_y"] = data.pop("stepper_x")
        data["stepper_y"]["endstop_pin"] = f"{model}_stepper_y:virtual_endstop"
        data[f"{model} stepper_y"] = data.pop(f"{model} stepper_x")
    data[f"{model} stepper_{other}"] = {"hold_current": "0.4"}
    data[f"stepper_{other}"] = {"endstop_pin": "PB3", "homing_retract_dist": "5"}
    with pytest.raises(GenerationError, match="hold_current"):
        validate_tmc_virtual_endstops(data)


@pytest.mark.parametrize("model", MODELS)
def test_valid_corexy_and_alias_on_secondary_mcu_keep_existing_diag_contract(model):
    data = _sensorless(model, kinematics="corexy")
    option = "diag_pin" if model == "tmc2209" else "diag1_pin"
    data[f"{model} stepper_x"][option] = "^tool:STOP"
    data.update({
        "mcu tool": {"serial": "/dev/tool"},
        "board_pins tool": {"mcu": "tool", "aliases": "STOP=PC6"},
        f"{model} stepper_y": {"run_current": "0.8"},
        "stepper_y": {"endstop_pin": "PB3", "homing_retract_dist": "5"},
    })
    before = deepcopy(data)
    validate_tmc_virtual_endstops(data)
    assert data == before


def test_secondary_sensorless_endstop_uses_primary_rail_retract_setting():
    data = _sensorless()
    data["stepper_x1"] = {"endstop_pin": data["stepper_x"]["endstop_pin"]}
    data["stepper_x"].update(endstop_pin="PB3", homing_retract_dist="5")
    with pytest.raises(GenerationError, match="homing_retract_dist"):
        validate_tmc_virtual_endstops(data)


def test_secondary_sensorless_endstop_does_not_invent_an_independent_retract_default():
    data = _sensorless()
    data["stepper_x1"] = {"endstop_pin": data["stepper_x"]["endstop_pin"]}
    validate_tmc_virtual_endstops(data)


def test_directly_referenced_driver_cannot_hide_hold_current_on_another_rail():
    data = _sensorless()
    data["stepper_x"]["endstop_pin"] = "tmc2209_stepper_y:virtual_endstop"
    data["tmc2209 stepper_y"] = data.pop("tmc2209 stepper_x")
    data["tmc2209 stepper_y"]["hold_current"] = "0.4"
    with pytest.raises(GenerationError, match="hold_current"):
        validate_tmc_virtual_endstops(data)


@pytest.mark.parametrize("kinematics,target", [
    ("cartesian", "stepper_x1"), ("corexy", "stepper_y1"),
])
def test_additional_participating_motor_must_not_have_hold_current(kinematics, target):
    data = _sensorless(kinematics=kinematics)
    data[target] = {"step_pin": "PB4"}
    data[f"tmc2209 {target}"] = {"hold_current": "0.4"}
    with pytest.raises(GenerationError, match="hold_current"):
        validate_tmc_virtual_endstops(data)


def test_manual_stepper_does_not_inherit_printer_rail_retract_default():
    data = {
        "manual_stepper feeder": {"endstop_pin": "tmc2209_feeder:virtual_endstop"},
        "tmc2209 manual_stepper feeder": {"diag_pin": "^PC6", "run_current": "0.8"},
    }
    validate_tmc_virtual_endstops(data)


@pytest.mark.parametrize("case", INVALID)
@pytest.mark.parametrize("restore", (False, True))
def test_generation_and_restored_choices_reject_before_replacing_artifact(tmp_path, case, restore):
    parsed, user = original_inputs(True)
    _invalidate(parsed, case)
    user["board_parsed"] = parsed
    if restore:
        saved = json.loads(json.dumps(persistable_wizard_data(user)))
        before = deepcopy(saved)
        user = restore_wizard_data(saved)
        parsed = user["board_parsed"]
    output = tmp_path / "printer.cfg"
    output.write_bytes(b"# existing operator artifact\n")
    with pytest.raises(GenerationError, match="homing_retract_dist|hold_current"):
        generate_config(parsed, user, output_path=str(output), verbose=False)
    assert output.read_bytes() == b"# existing operator artifact\n"
    assert not (tmp_path / "printer.cfg.provenance.json").exists()
    if restore:
        assert saved == before


@pytest.mark.parametrize("case", ("retract", "hold", "both"))
@pytest.mark.parametrize("noop", (False, True))
def test_preserved_nested_sensorless_override_blocks_before_confirmation_and_writes(tmp_path, case, noop):
    parsed, user = original_inputs(True)
    path = tmp_path / "printer.cfg"
    generated = generate_config(parsed, user, output_path=str(path), verbose=False)["content"].encode()
    geometry = load_geometry_context(path, generated)
    override = ""
    if case in ("retract", "both"):
        override += "[stepper_x]\nhoming_retract_dist: 5\n"
    if case in ("hold", "both"):
        override += "[tmc2209 stepper_x]\nhold_current: 0.4\n"
    remote = {
        "printer.cfg": generated + b"\n[include user.cfg]\n",
        "user.cfg": b"[include tuning.cfg]\n",
        "tuning.cfg": override.encode(),
    }
    if noop:
        plan = build_managed_config_plan(generated, None, remote, geometry_context=geometry)
        remote.update({item.remote_name: item.content for item in plan.artifacts})
        assert not build_managed_config_plan(
            generated, None, remote, geometry_context=geometry).changed_artifacts
    original = deepcopy(remote)
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(
        transport, generated, None, geometry_context=geometry, activation="none",
        confirm=confirm, snapshot_root=str(tmp_path / "snapshots"), output=lambda _: None,
        verify_existing_ready=noop,
    ).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "homing_retract_dist" in result.detail or "hold_current" in result.detail
    confirm.assert_not_called()
    assert_untouched(transport, original)
