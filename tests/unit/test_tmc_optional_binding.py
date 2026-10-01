"""Optional TMC overrides must be reviewed against their current circuit."""
import copy
import json
from unittest.mock import patch

import pytest

from core.exceptions import GenerationError
from core.generator import generate_config
from core.profile_values import mark_user_override, resolve_generation_values
from core.firmware_workflow import persistable_wizard_data
from core.wizard.steps import hardware
from tests.unit.test_tmc_electrical_authority import inputs
from tests.unit.test_tmc_current_binding import mutate


def optional_user(option, model="tmc2209", target="x"):
    board, _, user, section = inputs(model, target)
    user["z_motors"] = "1" if target not in ("z1", "z2", "z3") else "4"
    user[f"{option}_{target}"] = "0.300" if option == "hold_current" else "0"
    mark_user_override(user, f"{option}_{target}")
    return board, user, section


@pytest.mark.parametrize("option", ["hold_current", "stealthchop_threshold"])
@pytest.mark.parametrize("change", ["board", "model", "mode", "socket", "resistor", "uart", "address", "step_pin", "mcu", "aliases", "profile", "source_mechanics", "user_mechanics"])
def test_stale_optional_override_is_unresolved(option, change):
    board, user, section = optional_user(option)
    mutate(board, user, section, change)
    values, provenance = resolve_generation_values(board, user)
    assert provenance[f"{option}_x"] == "UNRESOLVED"
    assert f"{option}_x" not in values


@pytest.mark.parametrize("option", ["hold_current", "stealthchop_threshold"])
@pytest.mark.parametrize("model", ["tmc2208", "tmc2209", "tmc2130", "tmc5160"])
@pytest.mark.parametrize("target", ["x", "y", "z", "z1", "z2", "z3", "e"])
def test_optional_evidence_survives_persistence(option, model, target):
    _, user, _ = optional_user(option, model, target)
    saved = json.loads(json.dumps(persistable_wizard_data(user)))
    key = f"{option}_{target}"
    assert saved["_tmc_current_confirmations"][key]["schema"] == 1
    assert resolve_generation_values(saved["board_parsed"], saved)[0][key] == user[key]


@pytest.mark.parametrize("option", ["hold_current", "stealthchop_threshold"])
def test_unbound_optional_value_blocks_generation(tmp_path, option):
    board, user, _ = optional_user(option)
    user.pop("_tmc_current_confirmations", None)
    with pytest.raises(GenerationError, match=option):
        generate_config(board, user, output_path=str(tmp_path / "p.cfg"), verbose=False)
    assert not (tmp_path / "p.cfg").exists()


@pytest.mark.parametrize("option", ["hold_current", "stealthchop_threshold"])
@pytest.mark.parametrize("board_option", [False, True])
def test_explicit_blank_restores_board_or_omission(option, board_option):
    board, user, section = optional_user(option)
    if not board_option:
        board[section].pop(option)
    user.pop("_tmc_current_confirmations", None)
    with patch.object(hardware, "simple_input", return_value=""), patch.object(hardware, "yes_no", return_value=True):
        assert hardware._step_tmc_currents(user) == "done"
    values, provenance = resolve_generation_values(user["board_parsed"], user)
    assert user["_value_provenance"].get(f"{option}_x") != "USER_OVERRIDE"
    if board_option:
        assert values[f"{option}_x"] == board[section][option]
    else:
        assert f"{option}_x" not in values
        assert provenance[f"{option}_x"] == "KLIPPER_DEFAULT"


@pytest.mark.parametrize("option,value", [("hold_current", "0.310"), ("stealthchop_threshold", "999999")])
def test_stale_optional_can_be_reentered(option, value):
    board, user, section = optional_user(option)
    mutate(board, user, section, "resistor")
    with patch.object(hardware, "simple_input", return_value=value), patch.object(hardware, "yes_no", return_value=True):
        assert hardware._step_tmc_currents(user) == "done"
    assert resolve_generation_values(user["board_parsed"], user)[0][f"{option}_x"] == value


@pytest.mark.parametrize("option", ["hold_current", "stealthchop_threshold"])
def test_declined_optional_reset_is_atomic(option):
    board, user, section = optional_user(option)
    mutate(board, user, section, "resistor")
    before = copy.deepcopy(user)
    with patch.object(hardware, "simple_input", return_value=""), patch.object(hardware, "yes_no", return_value=False):
        assert hardware._step_tmc_currents(user) == "__retry__"
    assert user == before


@pytest.mark.parametrize("option", ["hold_current", "stealthchop_threshold"])
def test_auto_never_accepts_stale_optional_value(monkeypatch, option):
    board, user, section = optional_user(option)
    mutate(board, user, section, "resistor")
    monkeypatch.setenv("KACE_AUTO", "1")
    with patch.object(hardware, "simple_input") as prompt:
        with pytest.raises(GenerationError, match=option):
            hardware._step_tmc_currents(user)
    prompt.assert_not_called()


@pytest.mark.parametrize("option,value", [("hold_current", "0"), ("hold_current", "2.001"),
                                         ("hold_current", "nan"), ("stealthchop_threshold", "-1"),
                                         ("stealthchop_threshold", "nan"), ("stealthchop_threshold", "inf")])
def test_invalid_numeric_optional_cannot_generate(tmp_path, option, value):
    board, user, _ = optional_user(option)
    user[f"{option}_x"] = value
    mark_user_override(user, f"{option}_x")
    with pytest.raises(GenerationError, match=option):
        generate_config(board, user, output_path=str(tmp_path / "p.cfg"), verbose=False)
    assert not (tmp_path / "p.cfg").exists()


def test_unresolved_board_value_cannot_be_restored_as_if_valid():
    board, user, section = optional_user("hold_current")
    board[section]["hold_current"] = "2.001"
    before = copy.deepcopy(user)
    with patch.object(hardware, "simple_input", return_value=""), patch.object(hardware, "yes_no") as confirm:
        assert hardware._step_tmc_currents(user) == "__retry__"
    confirm.assert_not_called()
    assert user == before


@pytest.mark.parametrize("option", ["hold_current", "stealthchop_threshold"])
def test_edited_optional_value_requires_new_evidence(option):
    board, user, _ = optional_user(option)
    user[f"{option}_x"] = "0.410" if option == "hold_current" else "25"
    assert resolve_generation_values(board, user)[1][f"{option}_x"] == "UNRESOLVED"


@pytest.mark.parametrize("option", ["hold_current", "stealthchop_threshold"])
def test_legacy_optional_without_provenance_requires_review(option):
    board, user, _ = optional_user(option)
    user.pop("_value_provenance")
    user.pop("_profile_parsed")
    user.pop("_tmc_current_confirmations")
    assert resolve_generation_values(board, user)[1][f"{option}_x"] == "UNRESOLVED"


def test_clearing_one_optional_does_not_change_other_confirmation():
    board, user, _ = optional_user("hold_current")
    user["stealthchop_threshold_x"] = "25"
    mark_user_override(user, "stealthchop_threshold_x")
    receipt = copy.deepcopy(user["_tmc_current_confirmations"]["stealthchop_threshold_x"])
    user["_tmc_current_confirmations"].pop("hold_current_x")
    with patch.object(hardware, "simple_input", return_value=""), patch.object(hardware, "yes_no", return_value=True):
        assert hardware._step_tmc_currents(user) == "done"
    assert user["_tmc_current_confirmations"]["stealthchop_threshold_x"] == receipt
    assert resolve_generation_values(user["board_parsed"], user)[0]["stealthchop_threshold_x"] == "25"


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
def test_optional_prompts_and_omission_summary_are_translated(language):
    from core.translations._strings import UI_STRINGS
    for key in ("hold_current", "stealthchop_threshold", "omitted"):
        assert UI_STRINGS["wizard.tmc_current." + key][language]
