"""Absent optional TMC settings must retain Klipper behavior."""
import json

import pytest

from core.generator import generate_config
from core.profile_values import mark_user_override
from core.pin_validator import _read_pin_config
from tests.unit.test_tmc_electrical_authority import inputs
from tests.unit.test_full_steps_preservation import multi_board


@pytest.mark.parametrize("model", ["tmc2208", "tmc2209", "tmc2130", "tmc5160"])
@pytest.mark.parametrize("target", ["x", "y", "z", "z1", "z2", "z3", "e"])
def test_missing_optional_values_are_omitted_for_every_target(tmp_path, model, target):
    board, _, user, section = inputs(model, target)
    board.update(multi_board())
    board[section].pop("hold_current")
    board[section].pop("stealthchop_threshold")
    path = tmp_path / "printer.cfg"
    result = generate_config(board, user, output_path=str(path), verbose=False)
    rendered, _ = _read_pin_config(result["content"])
    for option in ("hold_current", "stealthchop_threshold"):
        assert option not in rendered[section]
        assert result["value_provenance"][f"{option}_{target}"] == "KLIPPER_DEFAULT"
    source = json.loads(path.with_suffix(".cfg.provenance.json").read_text())["sources"]["tmc_options"][section]
    assert source["omitted_options"] == ["hold_current", "stealthchop_threshold"]


@pytest.mark.parametrize("owner", ["PROFILE", "USER_OVERRIDE", "SAFE_DEFAULT"])
def test_explicit_board_or_user_values_survive_but_old_defaults_do_not(tmp_path, owner):
    board, _, user, section = inputs()
    user["z_motors"] = "1"
    for option, value in (("hold_current", "0.300"), ("stealthchop_threshold", "0")):
        user[f"{option}_x"] = value
        user["_value_provenance"][f"{option}_x"] = owner
        if owner == "PROFILE":
            board[section][option] = value
        else:
            board[section].pop(option)
    if owner == "USER_OVERRIDE":
        mark_user_override(user, "hold_current_x", "stealthchop_threshold_x")
    rendered, _ = _read_pin_config(generate_config(board, user, output_path=str(tmp_path / "p.cfg"), verbose=False)["content"])
    if owner == "SAFE_DEFAULT":
        assert "hold_current" not in rendered[section]
        assert "stealthchop_threshold" not in rendered[section]
    else:
        assert rendered[section]["hold_current"] == "0.300"
        assert rendered[section]["stealthchop_threshold"] == "0"


@pytest.mark.parametrize("option", ["hold_current", "stealthchop_threshold"])
def test_empty_explicit_override_is_not_treated_as_absent(tmp_path, option):
    from core.exceptions import GenerationError
    board, _, user, _ = inputs()
    user["z_motors"] = "1"
    user[f"{option}_x"] = ""
    mark_user_override(user, f"{option}_x")
    with pytest.raises(GenerationError):
        generate_config(board, user, output_path=str(tmp_path / "p.cfg"), verbose=False)
