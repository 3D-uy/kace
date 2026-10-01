"""Selected hardware must survive an unrelated printer profile, even on one MCU."""

import copy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from core.generator import generate_config
from core.exceptions import GenerationError
from core.profile_values import mark_profile_values, mark_user_override
from core.scraper import parse_config
from core.wizard import run_wizard
from tests.unit.test_generator import _user


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/board-profile-authority"
BOARD = "generic-bigtreetech-skr-mini-e3-v2.0.cfg"
PROFILES = (
    "printer-creality-cr6se-2020.cfg",
    "printer-creality-cr6se-2021.cfg",
    "printer-creality-ender3-v2-2020.cfg",
    "printer-creality-ender3-v2-neo-2022.cfg",
)


def load_config(name):
    return parse_config((FIXTURES / name).read_text(encoding="utf-8"), name)


def finish_wizard(data):
    # Exercise the real finalization; no network, discovery or interactive UI.
    with patch("core.wizard.fetch_config_list", return_value=[BOARD, *PROFILES]), \
         patch("core.wizard.discover_mcu", return_value={}), \
         patch("core.wizard.WizardRunner.run", return_value=data):
        return run_wizard()


@pytest.mark.parametrize("profile_name", (*PROFILES, "generic-creality-v4.2.7.cfg"))
def test_other_stm32_board_never_overwrites_selected_hardware(profile_name):
    board = load_config(BOARD)
    profile = load_config(profile_name)
    expected = copy.deepcopy(board)
    result = finish_wizard({"board": BOARD, "printer_profile": profile_name,
                            "board_parsed": board, "_profile_parsed": profile})
    assert result["board_parsed"] == expected
    # Literal upstream checks, independent from production source selection.
    assert board["stepper_x"]["step_pin"] == "PB13"
    assert board["extruder"]["heater_pin"] == "PC8"
    assert board["tmc2209 stepper_x"]["uart_address"] == "0"


@pytest.mark.parametrize("identity", ["same", "different", "missing"])
def test_profile_cannot_restore_old_pins_or_inject_circuits(identity):
    board = load_config(BOARD)
    profile = copy.deepcopy(board)
    profile["board_pins extra"] = {"aliases": "EXP1_1=PA0"}
    profile["mcu other"] = {"serial": "/dev/other"}
    profile["static_digital_output power"] = {"pins": "!PA1"}
    profile["tmc2209 stepper_x"].update(sense_resistor="0.500", uart_address="3")
    # An already selected hardware override must survive even an exact stock ID.
    board["stepper_x"]["dir_pin"] = "PB12"
    expected = copy.deepcopy(board)
    names = {"board": BOARD, "printer_profile": BOARD if identity == "same" else PROFILES[0]}
    if identity == "missing":
        names = {}
    result = finish_wizard({**names, "board_parsed": board, "_profile_parsed": profile})
    assert result["board_parsed"] == expected


@pytest.mark.parametrize("profile_name", PROFILES)
def test_generation_keeps_board_pins_and_profile_geometry(tmp_path, profile_name):
    board = load_config(BOARD)
    profile = load_config(profile_name)
    user = _user(board=BOARD, printer_profile=profile_name, board_parsed=board,
                 _profile_parsed=profile, driver_type="TMC2209", driver_mode="UART",
                 fan_hotend_pin="none")
    mark_profile_values(user, profile)
    user = finish_wizard(user)
    target = tmp_path / "printer.cfg"
    result = generate_config(user["board_parsed"], user, output_path=str(target), verbose=False)
    rendered = parse_config(result["content"], "printer.cfg")
    for section in ("stepper_x", "stepper_y", "stepper_z", "extruder", "heater_bed"):
        for key, value in load_config(BOARD)[section].items():
            if key.endswith("_pin"):
                assert rendered[section][key] == value
    assert rendered["stepper_x"]["position_max"] == profile["stepper_x"]["position_max"]
    assert rendered["extruder"]["rotation_distance"] == profile["extruder"]["rotation_distance"]
    assert rendered["extruder"]["sensor_type"] == profile["extruder"]["sensor_type"]
    assert rendered["tmc2209 stepper_x"]["uart_address"] == "0"


def test_manifest_records_sources_and_explicit_choices(tmp_path):
    board = load_config(BOARD)
    profile = load_config(PROFILES[0])
    user = _user(board=BOARD, printer_profile=PROFILES[0], board_parsed=board,
                 _profile_parsed=profile, x_position_max="240", driver_type="TMC2209",
                 driver_mode="UART", fan_part_cooling_pin="PC6", fan_hotend_pin="none")
    mark_profile_values(user, profile)
    mark_user_override(user, "x_position_max")
    target = tmp_path / "printer.cfg"
    result = generate_config(board, finish_wizard(user), output_path=str(target), verbose=False)
    manifest = json.loads(Path(str(target) + ".provenance.json").read_text())
    assert manifest["sources"]["board"] == BOARD
    assert manifest["sources"]["printer_profile"] == PROFILES[0]
    assert manifest["sources"]["hardware_options"]["extruder"]["heater_pin"] == "PC8"
    assert manifest["sources"]["hardware_options"]["fan"]["pin"] == "PC6"
    assert manifest["sources"]["hardware_choices"]["fan_part_cooling_pin"] == "PC6"
    assert parse_config(result["content"])["heater_fan heatbreak_cooling_fan"]["pin"] == "PC7"
    assert manifest["values"]["x_position_max"] == "USER_OVERRIDE"
    assert manifest["resolved_values"]["x_position_max"] == "240"
    assert manifest["values"]["rotation_distance_e"] == "PROFILE"
    assert parse_config(result["content"], "printer.cfg")["stepper_x"]["position_max"] == "240"


@pytest.mark.parametrize("name", [BOARD, "printer-creality-ender3-v2-2020.cfg"])
def test_exact_stock_selection_preserves_hardware_and_manual_direction(tmp_path, name):
    board = load_config(name)
    profile = copy.deepcopy(board)
    board["stepper_x"]["dir_pin"] = board["stepper_x"]["dir_pin"].lstrip("!")
    expected = copy.deepcopy(board)
    user = _user(board=name, printer_profile=name, board_parsed=board, _profile_parsed=profile)
    if name == BOARD:
        user.update(driver_type="TMC2209", driver_mode="UART")
    mark_profile_values(user, profile)
    user = finish_wizard(user)
    assert user["board_parsed"] == expected
    result = generate_config(board, user, output_path=str(tmp_path / "stock.cfg"), verbose=False)
    rendered = parse_config(result["content"], "stock.cfg")
    assert rendered["stepper_x"]["dir_pin"] == expected["stepper_x"]["dir_pin"]
    assert rendered["extruder"]["heater_pin"] == expected["extruder"]["heater_pin"]


def test_missing_hardware_is_not_filled_from_a_profile(tmp_path):
    user = _user(board_parsed={}, _profile_parsed=load_config(PROFILES[0]))
    result = finish_wizard(user)
    assert result["board_parsed"] == {}
    path = tmp_path / "missing.cfg"
    with pytest.raises(GenerationError, match=r"\[heater_bed\]: heater_pin is required") as error:
        generate_config({}, result, output_path=str(path), verbose=False)
    assert error.value.todos == [("heater_bed", "heater_pin")]
    assert not path.exists()
    assert not Path(str(path) + ".provenance.json").exists()


def test_z_socket_mapping_survives_final_profile_processing():
    from core.wizard.steps.hardware import _step_tmc_currents
    options = {"uart_pin": "PD12", "uart_address": "3", "sense_resistor": "0.150", "run_current": "0.580"}
    board = {"tmc2209 extruder1": options.copy(),
             "stepper_z1": {"step_pin": "PD1", "dir_pin": "PD2", "enable_pin": "!PD3"}}
    profile = {"tmc2209 stepper_z1": {"uart_pin": "PA1", "uart_address": "0"},
               "stepper_z1": {"step_pin": "PA2", "dir_pin": "PA3", "enable_pin": "!PA4"}}
    data = {"board": "selected.cfg", "printer_profile": "foreign.cfg",
                            "board_parsed": board, "_profile_parsed": profile,
                            "driver_type": "TMC2209", "driver_mode": "UART", "z_motors": "2",
                            "z_socket_assignments": {"stepper_z1": "extruder1"},
                            "board_raw_config": "[tmc2209 extruder1]\nuart_pin: PD12\n"}
    # Mapping now belongs to the guided current step, before finalization.
    assert _step_tmc_currents(data) == "done"
    result = finish_wizard(data)
    assert result["board_parsed"]["tmc2209 stepper_z1"] == options
    assert result["board_parsed"]["stepper_z1"]["step_pin"] == "PD1"
    assert "tmc2209 extruder1" not in result["board_parsed"]


@pytest.mark.parametrize("policy", [None, "mcu-family/v0", "selected-board/v999"])
def test_legacy_or_unknown_profile_checkpoint_is_rejected(policy):
    from core.firmware_workflow import CheckpointIncompatible, create_checkpoint, validate_checkpoint
    from tests.unit.test_firmware_workflow import base_user_data, identity_reader

    user = {**base_user_data(), "board": BOARD, "mcu_type": "stm32f103",
            "_profile_parsed": load_config(PROFILES[0]),
            "board_parsed": load_config(BOARD), "hardware_source_policy": policy}
    checkpoint = create_checkpoint(user, identity_reader=identity_reader())
    with pytest.raises(CheckpointIncompatible, match="mixed board pins"):
        validate_checkpoint(checkpoint)


def test_current_profile_checkpoint_and_legacy_scratch_remain_usable(tmp_path):
    from core.firmware_workflow import create_checkpoint, load_checkpoint, write_checkpoint
    from tests.unit.test_firmware_workflow import base_user_data, identity_reader

    cases = (base_user_data(), finish_wizard({**base_user_data(), "board": BOARD,
             "mcu_type": "stm32f103", "_profile_parsed": load_config(PROFILES[0]),
             "board_parsed": load_config(BOARD)}))
    for index, user in enumerate(cases):
        checkpoint = create_checkpoint(user, identity_reader=identity_reader())
        path = str(tmp_path / f"workflow-{index}.json")
        write_checkpoint(checkpoint, path=path)
        restored = load_checkpoint(path=path)
        assert restored["wizard_data"].get("board_parsed") == user.get("board_parsed")
