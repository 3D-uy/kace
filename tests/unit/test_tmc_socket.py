"""Reviewed removable-driver buses must survive a different selected chip."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from core.exceptions import GenerationError, WizardExit
from core.generator import generate_config
from core.profile_values import mark_user_override, resolve_generation_values, resolve_tmc_sections
from core.scraper import parse_config
from core.tmc_socket import REVIEWED, SOURCE, selected_socket_sections
from core.wizard.steps.hardware import _apply_z_tmc_mappings, _step_tmc_currents
from tests.unit.test_generator import _user

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/tmc-sockets"
SKR = "generic-bigtreetech-skr-v1.4.cfg"
MODELS = ("TMC2208", "TMC2209", "TMC2225", "TMC2130", "TMC5160")


def inputs(name=SKR, model="TMC2209", socket="extruder1", raw=None):
    if raw is None:
        raw = (FIXTURES / name).read_text(encoding="utf-8")
    board = parse_config(raw, name, keep_comments=True)
    # Real socket assignment copies only motor pins, preserving Z mechanics.
    board["stepper_z1"] = {k: board[socket][k] for k in ("step_pin", "dir_pin", "enable_pin")}
    board.pop(socket)
    user = _user(board=name, printer_profile=name, board_parsed=board, board_raw_config=raw,
                 driver_type=model, driver_mode="SPI" if model in ("TMC2130", "TMC5160") else "UART",
                 z_motors="2", z_socket_assignments={"stepper_z1": socket}, fan_hotend_pin="none")
    # Fixture user explicitly confirms matching Z mechanics; SKR 2 uses 40 mm.
    for option, default in (("rotation_distance", "8"), ("microsteps", "16"), ("gear_ratio", "1:1")):
        key = option + "_z1"
        user[key] = board["stepper_z"].get(option, default)
        mark_user_override(user, key)
    return board, user


def confirm_currents(board, user):
    for target in ("x", "y", "z", "z1", "e"):
        key = "run_current_" + target
        user[key] = "0.580"
        mark_user_override(user, key)


@pytest.mark.parametrize("name", sorted(REVIEWED))
def test_catalog_matches_pinned_commented_examples(name):
    raw = (FIXTURES / name).read_text(encoding="utf-8")
    entry = REVIEWED[name]
    assert hashlib.sha256(raw.encode()).hexdigest() == entry["sha256"]
    active = parse_config(raw, name)
    full = parse_config(raw, name, keep_comments=True)
    for socket, item in entry["sockets"].items():
        assert item["motor_pins"] == {k: full[socket][k] for k in ("step_pin", "dir_pin", "enable_pin")}
        for transport in item["transports"].values():
            assert transport["section"] not in active
            assert transport["options"] == {k: full[transport["section"]][k] for k in transport["options"]}


@pytest.mark.parametrize("name", sorted(REVIEWED))
@pytest.mark.parametrize("model", MODELS)
def test_other_boards_and_drivers_map_primary_and_reused_sockets(name, model):
    board, user = inputs(name, model)
    _apply_z_tmc_mappings(user)
    sections = resolve_tmc_sections(board, user)
    canonical = "tmc2208" if model == "TMC2225" else model.lower()
    assert set(sections) == {canonical + " " + target for target in
                             ("stepper_x", "stepper_y", "stepper_z", "stepper_z1", "extruder")}
    entry = REVIEWED[name]
    for section, options in sections.items():
        target = section.split(" ", 1)[1]
        socket = user["z_socket_assignments"].get(target, target)
        transport = entry["sockets"][socket]["transports"][user["driver_mode"]]
        for key, value in transport["options"].items():
            assert options[key] == value
        if transport["section"].split()[0] != canonical:
            assert set(options) == set(transport["options"])
        else:
            original = parse_config(user["board_raw_config"], name, keep_comments=True)
            assert options == original[transport["section"]]
    before = deepcopy(board)
    _apply_z_tmc_mappings(user)
    assert board == before


def test_reported_case_requires_current_and_emits_correct_z1(tmp_path):
    board, user = inputs()
    _apply_z_tmc_mappings(user)
    assert board["tmc2209 stepper_z1"] == {"uart_pin": "P1.1"}
    values, owners = resolve_generation_values(board, user)
    assert all(owners["run_current_" + t] == "UNRESOLVED" for t in ("x", "y", "z", "z1", "e"))
    output = tmp_path / "printer.cfg"
    with pytest.raises(GenerationError, match="run_current"):
        generate_config(board, user, output_path=str(output), verbose=False)
    assert not output.exists()
    confirm_currents(board, user)
    before = deepcopy(board)
    generated = generate_config(board, user, output_path=str(output), verbose=False)
    actual = parse_config(generated["content"])
    assert actual["stepper_z1"]["step_pin"] == "P1.15"
    assert actual["stepper_z1"]["dir_pin"] == "P1.14"
    assert actual["stepper_z1"]["enable_pin"] == "!P1.16"
    assert actual["tmc2209 stepper_z1"]["uart_pin"] == "P1.1"
    assert actual["tmc2209 stepper_z1"]["run_current"] == "0.580"
    assert not any(s.startswith(("tmc2208 ", "tmc2130 ")) for s in actual)
    assert board == before
    trace = json.loads(Path(str(output) + ".provenance.json").read_text())["sources"]["tmc_options"]
    assert trace["tmc2209 stepper_z1"]["socket"] == "extruder1"
    assert trace["tmc2209 stepper_z1"]["options"]["run_current"]["origin"] == "USER_OVERRIDE"


def test_wizard_prompts_for_new_chip_current_transactionally():
    board, user = inputs()
    with patch("core.wizard.steps.hardware.simple_input", return_value="0.580") as prompt, \
         patch("core.wizard.steps.hardware.yes_no", return_value=True):
        assert _step_tmc_currents(user) == "done"
    assert prompt.call_count == 5
    assert resolve_generation_values(user["board_parsed"], user)[0]["run_current_z1"] == "0.580"


@pytest.mark.parametrize("change", ("hash", "identity", "motor_pin", "transport_pin", "extra_transport", "missing_source", "custom"))
def test_unreviewed_or_changed_wiring_cannot_borrow_a_chip_section(change):
    board, user = inputs()
    if change == "hash":
        board[SOURCE]["sha256"] = "invalid"
    elif change == "identity":
        user["board"] = "other.cfg"
    elif change == "motor_pin":
        board["stepper_z1"]["step_pin"] = "P0.0"
    elif change == "transport_pin":
        board["tmc2208 extruder1"]["uart_pin"] = "P0.0"
    elif change == "extra_transport":
        board["tmc2208 extruder1"]["tx_pin"] = "P0.0"
    elif change == "missing_source":
        board.pop(SOURCE)
    else:
        user["z_socket_assignments"]["stepper_z1"] = "custom"
    assert "tmc2209 stepper_z1" not in selected_socket_sections(board, user)
    if change != "custom":
        with pytest.raises(WizardExit):
            _apply_z_tmc_mappings(user)


def test_changed_raw_profile_is_not_reviewed_even_with_same_filename():
    raw = (FIXTURES / SKR).read_text(encoding="utf-8").replace("#uart_pin: P1.1\n", "#uart_pin: P0.0\n")
    board, user = inputs(raw=raw)
    assert "tmc2209 stepper_z1" not in selected_socket_sections(board, user)


def test_partial_selected_section_is_rejected_instead_of_repaired():
    board, user = inputs()
    board["tmc2209 stepper_x"] = {"run_current": "0.5"}
    with pytest.raises(GenerationError, match="missing uart_pin"):
        resolve_tmc_sections(board, user)


def test_driver_settings_are_not_imported_from_the_donor():
    board, user = inputs()
    board["tmc2208 extruder1"].update(sense_resistor="0.075", driver_toff="7", run_current="1.500")
    assert selected_socket_sections(board, user)["tmc2209 stepper_z1"] == {"uart_pin": "P1.1"}


def test_integrated_board_does_not_authorize_chip_replacement():
    name = "generic-bigtreetech-skr-mini-e3-v2.0.cfg"
    raw = (FIXTURES.parent / "board-profile-authority" / name).read_text(encoding="utf-8")
    board = parse_config(raw, name, keep_comments=True)
    user = _user(board=name, driver_type="TMC2208", driver_mode="UART")
    with pytest.raises(GenerationError, match="incompatible source driver"):
        resolve_tmc_sections(board, user)


def test_direct_generator_uses_same_resolution_without_mutating_inputs(tmp_path):
    board, user = inputs()
    confirm_currents(board, user)
    before = deepcopy(board)
    content = generate_config(board, user, output_path=str(tmp_path / "direct.cfg"), verbose=False)["content"]
    assert parse_config(content)["tmc2209 stepper_z1"]["uart_pin"] == "P1.1"
    assert board == before


@pytest.mark.parametrize("option", ("diag_pin", "diag0_pin", "diag1_pin"))
def test_only_commented_empty_diag_examples_are_omitted(option):
    model = "tmc2209" if option == "diag_pin" else "tmc2130"
    section = model + " stepper_x"
    pin = "uart_pin" if model == "tmc2209" else "cs_pin"
    raw = f"#[{section}]\n#{pin}: PA1\n#{option}:\n"
    assert option not in parse_config(raw, keep_comments=True)[section]
    active = parse_config(raw.replace("#", ""), keep_comments=True)
    assert active[section][option] == ""
    with pytest.raises(GenerationError, match="empty TMC option"):
        resolve_tmc_sections(active, _user(driver_type=model.upper(), driver_mode="UART" if model == "tmc2209" else "SPI"))


@pytest.mark.parametrize("name,model", [(n, m) for n in sorted(REVIEWED) for m in MODELS])
def test_full_generation_for_reviewed_board_driver_pairs(tmp_path, name, model):
    board, user = inputs(name, model)
    _apply_z_tmc_mappings(user)
    confirm_currents(board, user)
    content = generate_config(board, user, output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]
    actual = parse_config(content)
    canonical = "tmc2208" if model == "TMC2225" else model.lower()
    expected = resolve_tmc_sections(board, user)
    assert set(s for s in actual if s.startswith("tmc")) == set(expected)
    assert actual[canonical + " stepper_z1"]["run_current"] == "0.580"


def test_back_from_current_review_does_not_commit_socket_adaptation():
    board, user = inputs()
    before = deepcopy(user)
    with patch("core.wizard.steps.hardware.simple_input", return_value="__back__"):
        assert _step_tmc_currents(user) == "__back__"
    assert user == before


@pytest.mark.parametrize("model", MODELS)
def test_four_z_motors_keep_distinct_reused_sockets(tmp_path, model):
    board, user = inputs("generic-bigtreetech-octopus-v1.1.cfg", model)
    user["z_motors"] = "4"
    for index in (2, 3):
        target, socket = f"stepper_z{index}", f"extruder{index}"
        board[target] = {k: board[socket][k] for k in ("step_pin", "dir_pin", "enable_pin")}
        board.pop(socket)
        user["z_socket_assignments"][target] = socket
        for option in ("rotation_distance", "microsteps", "gear_ratio"):
            key = f"{option}_z{index}"
            user[key] = user[option + "_z1"]
            mark_user_override(user, key)
    _apply_z_tmc_mappings(user)
    for target in ("x", "y", "z", "z1", "z2", "z3", "e"):
        key = "run_current_" + target
        user[key] = "0.580"
        mark_user_override(user, key)
    content = generate_config(board, user, output_path=str(tmp_path / "four-z.cfg"), verbose=False)["content"]
    actual = parse_config(content)
    canonical = "tmc2208" if model == "TMC2225" else model.lower()
    pin_key = "cs_pin" if user["driver_mode"] == "SPI" else "uart_pin"
    assert [actual[f"{canonical} stepper_z{i}"][pin_key] for i in (1, 2, 3)] == ["PE4", "PE1", "PD3"]


def test_motor_direction_can_change_without_changing_socket_identity():
    board, user = inputs()
    board["stepper_z1"]["dir_pin"] = "!P1.14"
    assert selected_socket_sections(board, user)["tmc2209 stepper_z1"] == {"uart_pin": "P1.1"}
