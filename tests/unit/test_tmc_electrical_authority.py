"""TMC electrical values must follow the selected circuit, not foreign profiles."""
import copy
import json

import pytest

from core.profile_values import extract_profile_values, mark_profile_values, mark_user_override, resolve_generation_values
from core.generator import generate_config
from tests.unit.test_generator import _parsed, _user


def inputs(model="tmc2209", target="x"):
    section = f"{model} " + ("extruder" if target == "e" else f"stepper_{target}")
    board = _parsed()
    board[section] = {"uart_pin" if model in ("tmc2208", "tmc2209") else "cs_pin": "PC11",
                      "run_current": "0.580", "hold_current": "0.250", "stealthchop_threshold": "0",
                      "sense_resistor": "0.150"}
    profile = copy.deepcopy(board)
    profile[section].update(run_current="1.200", hold_current="0.600", stealthchop_threshold="999999", sense_resistor="0.075")
    user = _user(board="selected.cfg", printer_profile="foreign.cfg", board_parsed=board,
                 _profile_parsed=profile, driver_type=model.upper(),
                 driver_mode="UART" if model in ("tmc2208", "tmc2209") else "SPI", z_motors="4")
    user.update(extract_profile_values(profile))
    mark_profile_values(user, profile)
    return board, profile, user, section


@pytest.mark.parametrize("model", ["tmc2208", "tmc2209", "tmc2130", "tmc5160"])
@pytest.mark.parametrize("target", ["x", "y", "z", "z1", "z2", "z3", "e"])
def test_selected_board_owns_electrical_values_for_every_target(model, target):
    board, _, user, _ = inputs(model, target)
    values, _ = resolve_generation_values(board, user)
    assert [values[f"{option}_{target}"] for option in ("run_current", "hold_current", "stealthchop_threshold")] == ["0.580", "0.250", "0"]


def test_unmarked_profile_values_do_not_override_selected_board():
    board, _, user, _ = inputs()
    user.pop("_value_provenance")
    assert resolve_generation_values(board, user)[0]["run_current_x"] == "0.580"


def test_inferred_current_does_not_override_board_circuit():
    board, _, user, _ = inputs()
    user["_value_provenance"]["run_current_x"] = "INFERRED"
    assert resolve_generation_values(board, user)[0]["run_current_x"] == "0.580"


def test_reassigned_socket_is_recorded_with_its_electrical_values(tmp_path):
    from tests.unit.test_full_steps_preservation import multi_board
    board, _, user, section = inputs(target="z1")
    board.update(multi_board())
    user["z_motors"] = "2"
    user["z_socket_assignments"] = {"stepper_z1": "extruder1"}
    output = tmp_path / "printer.cfg"
    generate_config(board, user, output_path=str(output), verbose=False)
    trace = json.loads(output.with_suffix(".cfg.provenance.json").read_text())["sources"]["tmc_options"][section]
    assert trace["socket"] == "extruder1"


def test_foreign_profile_cannot_fill_missing_board_current(tmp_path):
    from core.exceptions import GenerationError
    board, _, user, section = inputs()
    user["z_motors"] = "1"
    del board[section]["run_current"]
    output = tmp_path / "printer.cfg"
    with pytest.raises(GenerationError, match="run_current_x"):
        generate_config(board, user, output_path=str(output), verbose=False)
    assert not output.exists()


@pytest.mark.parametrize("standalone", [False, True])
def test_inactive_tmc_values_cannot_block_generation(tmp_path, standalone):
    board, _, user, section = inputs(target="z3")
    user["z_motors"] = "1"
    del board[section]
    if standalone:
        user["driver_mode"] = "Standalone"
    output = tmp_path / "printer.cfg"
    generate_config(board, user, output_path=str(output), verbose=False)
    assert "[tmc2209 stepper_z3]" not in output.read_text(encoding="utf-8")


def test_explicit_override_wins_without_changing_board_resistance(tmp_path):
    board, _, user, section = inputs()
    user["z_motors"] = "1"
    user["run_current_x"] = "0.700"
    mark_user_override(user, "run_current_x")
    output = tmp_path / "printer.cfg"
    generate_config(board, user, output_path=str(output), verbose=False)
    trace = json.loads(output.with_suffix(".cfg.provenance.json").read_text())["sources"]["tmc_options"][section]
    assert trace["options"]["run_current"] == {"value": "0.700", "origin": "USER_OVERRIDE", "input_value": "0.700"}
    assert trace["options"]["sense_resistor"] == {"value": "0.150", "origin": "SELECTED_BOARD", "input_value": "0.150"}
    assert trace["board"] == "selected.cfg"


def test_source_trace_records_board_values_and_rechecks_after_resume(tmp_path):
    from core.firmware_workflow import persistable_wizard_data
    board, _, user, section = inputs()
    user["z_motors"] = "1"
    user = json.loads(json.dumps(persistable_wizard_data(user)))
    user["board_parsed"][section]["run_current"] = "0.620"
    output = tmp_path / "printer.cfg"
    generate_config(user["board_parsed"], user, output_path=str(output), verbose=False)
    trace = json.loads(output.with_suffix(".cfg.provenance.json").read_text())["sources"]["tmc_options"][section]
    assert trace["options"]["run_current"]["origin"] == "SELECTED_BOARD"
    assert trace["options"]["run_current"]["value"] == "0.620"
    assert trace["socket"] == "stepper_x"


def test_trace_does_not_invent_an_omitted_sense_resistor(tmp_path):
    board = _parsed()
    board["tmc2209 stepper_x"] = {"uart_pin": "PC11", "run_current": "0.580"}
    output = tmp_path / "printer.cfg"
    generate_config(board, _user(driver_type="TMC2209", driver_mode="UART"), output_path=str(output), verbose=False)
    trace = json.loads(output.with_suffix(".cfg.provenance.json").read_text())["sources"]["tmc_options"]["tmc2209 stepper_x"]
    assert trace["options"]["run_current"]["origin"] == "SELECTED_BOARD"
    assert "sense_resistor" not in trace["options"]
