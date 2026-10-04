"""A saved motor current is valid only for its reviewed hardware context."""
import copy
import json
from unittest.mock import patch

import pytest

from core.exceptions import GenerationError
from core.firmware_workflow import persistable_wizard_data
from core.generator import generate_config
from core.profile_values import mark_user_override, resolve_generation_values
from core.wizard.steps import hardware
from tests.unit.test_tmc_electrical_authority import inputs


def bound_user(model="tmc2209", target="x"):
    board, _, user, section = inputs(model, target)
    user["z_motors"] = "1" if target not in ("z1", "z2", "z3") else "4"
    user[f"run_current_{target}"] = "0.730"
    mark_user_override(user, f"run_current_{target}")
    return board, user, section


def mutate(board, user, section, change):
    if change == "board":
        user["board"] = "other.cfg"
    elif change == "model":
        user["driver_type"] = "TMC2208"
        board["tmc2208 stepper_x"] = board.pop(section)
    elif change == "mode":
        user["driver_mode"] = "SPI"
    elif change == "socket":
        user["z_socket_assignments"] = {"stepper_x": "extruder1"}
    elif change == "resistor":
        board[section]["sense_resistor"] = "0.110"
    elif change == "uart":
        board[section]["uart_pin"] = "PC10"
    elif change == "address":
        board[section]["uart_address"] = "1"
    elif change == "step_pin":
        board["stepper_x"]["step_pin"] = "PA3"
    elif change == "mcu":
        board["mcu"] = {"serial": "/dev/other"}
    elif change == "aliases":
        board["board_pins"] = {"aliases": "RX=PC10"}
    elif change == "profile":
        user["printer_profile"] = "other-printer.cfg"
    elif change == "source_mechanics":
        user["_profile_parsed"]["stepper_x"]["full_steps_per_rotation"] = "400"
    elif change == "user_mechanics":
        user["full_steps_per_rotation_x"] = "400"
        mark_user_override(user, "full_steps_per_rotation_x")
    elif change == "value":
        user["run_current_x"] = "0.910"


@pytest.mark.parametrize("change", ["board", "model", "mode", "socket", "resistor", "uart", "address",
                                    "step_pin", "mcu", "aliases", "profile", "source_mechanics", "user_mechanics", "value"])
def test_context_change_invalidates_current(change):
    board, user, section = bound_user()
    mutate(board, user, section, change)
    values, provenance = resolve_generation_values(board, user)
    assert provenance["run_current_x"] == "UNRESOLVED"
    assert "run_current_x" not in values


@pytest.mark.parametrize("model", ["tmc2208", "tmc2209", "tmc2130", "tmc5160"])
@pytest.mark.parametrize("target", ["x", "y", "z", "z1", "z2", "z3", "e"])
def test_all_targets_preserve_bound_current_after_json_roundtrip(model, target):
    _, user, _ = bound_user(model, target)
    saved = json.loads(json.dumps(persistable_wizard_data(user)))
    values, provenance = resolve_generation_values(saved["board_parsed"], saved)
    assert values[f"run_current_{target}"] == "0.730"
    assert provenance[f"run_current_{target}"] == "USER_OVERRIDE"
    assert saved["_tmc_current_confirmations"][f"run_current_{target}"]["schema"] == 1


@pytest.mark.parametrize("receipt", [None, {}, "broken", {"run_current_x": {"schema": 999}}])
def test_absent_or_invalid_binding_fails_before_writing(tmp_path, receipt):
    board, user, _ = bound_user()
    user["_tmc_current_confirmations"] = receipt
    with pytest.raises(GenerationError, match="run_current_x"):
        generate_config(board, user, output_path=str(tmp_path / "p.cfg"), verbose=False)
    assert not (tmp_path / "p.cfg").exists()


def test_auto_cannot_reuse_stale_current(monkeypatch):
    board, user, section = bound_user()
    mutate(board, user, section, "resistor")
    before = copy.deepcopy(user)
    monkeypatch.setenv("KACE_AUTO", "1")
    with patch.object(hardware, "simple_input") as prompt:
        with pytest.raises(GenerationError, match="run_current_x"):
            hardware._step_tmc_currents(user)
    prompt.assert_not_called()
    assert user == before


def test_guided_review_replaces_stale_binding(tmp_path):
    board, user, section = bound_user()
    mutate(board, user, section, "resistor")
    with patch.object(hardware, "simple_input", return_value="0.610"), patch.object(hardware, "yes_no", return_value=True):
        assert hardware._step_tmc_currents(user) == "done"
    result = generate_config(user["board_parsed"], user, output_path=str(tmp_path / "p.cfg"), verbose=False)
    assert "run_current: 0.610" in result["content"]


def test_unrelated_display_change_does_not_invalidate_current():
    board, user, _ = bound_user()
    user["display"] = "Other display"
    assert resolve_generation_values(board, user)[0]["run_current_x"] == "0.730"


def test_legacy_unmarked_current_requires_review():
    board, user, _ = bound_user()
    user.pop("_value_provenance")
    user.pop("_profile_parsed")
    user.pop("_tmc_current_confirmations", None)
    assert resolve_generation_values(board, user)[1]["run_current_x"] == "UNRESOLVED"


def test_alias_receipt_is_a_snapshot_not_a_live_board_reference():
    board, _, user, _ = inputs()
    board["board_pins"] = {"aliases": "RX=PC11"}
    user["run_current_x"] = "0.730"
    mark_user_override(user, "run_current_x")
    receipt = copy.deepcopy(user["_tmc_current_confirmations"])
    board["board_pins"]["aliases"] = "RX=PC10"
    assert user["_tmc_current_confirmations"] == receipt
    assert resolve_generation_values(board, user)[1]["run_current_x"] == "UNRESOLVED"


@pytest.mark.parametrize("confirm", [False, True])
def test_stale_binding_is_replaced_only_after_acceptance(confirm):
    board, user, section = bound_user()
    mutate(board, user, section, "resistor")
    before = copy.deepcopy(user)
    with patch.object(hardware, "simple_input", return_value="0.610"), patch.object(hardware, "yes_no", return_value=confirm):
        outcome = hardware._step_tmc_currents(user)
    if confirm:
        assert outcome == "done"
        assert resolve_generation_values(user["board_parsed"], user)[0]["run_current_x"] == "0.610"
    else:
        assert outcome == "__retry__"
        assert user == before


def test_current_confirmation_follows_guided_z_mechanics(tmp_path):
    from core.wizard.steps import motion
    from tests.unit.test_z_mechanics_wizard import data
    user = data()
    user.update(driver_type="TMC2209", driver_mode="UART")
    user["board_parsed"]["tmc2209 stepper_z1"] = {"uart_pin": "PC11"}
    with patch.object(motion, "numbered_select", side_effect=["same", "confirm"]), patch.object(motion, "yes_no", return_value=True):
        assert motion._step_z_mechanics(user) == "done"
    with patch.object(hardware, "simple_input", return_value="0.610"), patch.object(hardware, "yes_no", return_value=True):
        assert hardware._step_tmc_currents(user) == "done"
    result = generate_config(user["board_parsed"], user, output_path=str(tmp_path / "p.cfg"), verbose=False)
    assert result["value_provenance"]["run_current_z1"] == "USER_OVERRIDE"


def test_inactive_motor_binding_does_not_block_selected_motors():
    board, user, _ = bound_user(target="z3")
    user["z_motors"] = "1"
    assert "run_current_z3" not in resolve_generation_values(board, user)[1]


def test_board_current_does_not_need_user_confirmation():
    board, _, user, _ = inputs()
    user["_tmc_current_confirmations"] = "broken"
    assert resolve_generation_values(board, user)[0]["run_current_x"] == "0.580"


def test_durable_checkpoint_preserves_binding_but_not_its_validity_after_change(tmp_path):
    from core.firmware_workflow import create_checkpoint, write_checkpoint, load_checkpoint
    from core.profile_values import HARDWARE_SOURCE_POLICY
    from tests.unit.test_firmware_workflow import identity_reader
    _, user, _ = bound_user()
    user.update(mcu_type="stm32f103", hardware_source_policy=HARDWARE_SOURCE_POLICY)
    path = tmp_path / "workflow.json"
    checkpoint = create_checkpoint(user, identity_reader=identity_reader())
    write_checkpoint(checkpoint, str(path))
    resumed = load_checkpoint(str(path))["wizard_data"]
    assert resolve_generation_values(resumed["board_parsed"], resumed)[0]["run_current_x"] == "0.730"
    resumed["board_parsed"]["tmc2209 stepper_x"]["sense_resistor"] = "0.110"
    assert resolve_generation_values(resumed["board_parsed"], resumed)[1]["run_current_x"] == "UNRESOLVED"
