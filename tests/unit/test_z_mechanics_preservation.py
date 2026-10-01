"""Additional Z motors keep their own transmission, never a guessed ratio."""
import json

import pytest

from core.exceptions import GenerationError
from core.firmware_workflow import persistable_wizard_data
from core.profile_values import mark_user_override
from core.scraper import parse_config
from tests.unit.test_full_steps_preservation import multi_board, render
from tests.unit.test_generator import _user


def mechanics(board, target, rotation="40", microsteps="16", gear="80:16"):
    board[f"stepper_{target}"].update(rotation_distance=rotation, microsteps=microsteps, gear_ratio=gear)


@pytest.mark.parametrize("count", [2, 4])
def test_identical_declared_z_transmissions_are_preserved(tmp_path, count):
    board = multi_board()
    for index in range(count):
        mechanics(board, "z" + (str(index) if index else ""))
    result = render(tmp_path, board, _user(z_motors=str(count)))
    final = parse_config(result["content"])
    for index in range(count):
        target = "z" + (str(index) if index else "")
        section = final[f"stepper_{target}"]
        assert (section["rotation_distance"], section["microsteps"], section["gear_ratio"]) == ("40", "16", "80:16")
        assert result["value_provenance"][f"gear_ratio_{target}"] == "PROFILE"


def test_independent_transmissions_and_ungeared_secondary(tmp_path):
    board = multi_board()
    mechanics(board, "z", "40", "16", "5:1")
    mechanics(board, "z1", "8", "32", "2:1")
    mechanics(board, "z2", "12", "64", "3:1, 2:1")
    mechanics(board, "z3", "4", "16", "1:1")
    board["stepper_z3"].pop("gear_ratio")
    final = parse_config(render(tmp_path, board)["content"])
    assert (final["stepper_z1"]["rotation_distance"], final["stepper_z1"]["microsteps"], final["stepper_z1"]["gear_ratio"]) == ("8", "32", "2:1")
    assert final["stepper_z2"]["gear_ratio"] == "3:1, 2:1"
    assert final["stepper_z2"]["microsteps"] == "64"
    assert final["stepper_z3"]["rotation_distance"] == "4"
    assert "gear_ratio" not in final["stepper_z3"]


def test_explicit_per_motor_choices_survive_resume(tmp_path):
    board = multi_board()
    mechanics(board, "z")
    user = _user(z_motors="4")
    for index in (1, 2, 3):
        for option, value in (("rotation_distance", "40"), ("microsteps", "16"), ("gear_ratio", "80:16")):
            key = f"{option}_z{index}"
            user[key] = value
            mark_user_override(user, key)
    restored = json.loads(json.dumps(persistable_wizard_data(user)))
    result = render(tmp_path, board, restored)
    final = parse_config(result["content"])
    assert final["stepper_z3"]["gear_ratio"] == "80:16"
    assert result["value_provenance"]["gear_ratio_z3"] == "USER_OVERRIDE"


@pytest.mark.parametrize("option,value", [("gear_ratio", "5:1"), ("rotation_distance", "40"), ("microsteps", "32")])
def test_missing_secondary_mechanics_cannot_silently_change_scale(tmp_path, option, value):
    board = multi_board()
    board["stepper_z"][option] = value
    with pytest.raises(GenerationError, match=f"{option}_z1"):
        render(tmp_path, board, _user(z_motors="2"))
    assert not (tmp_path / "printer.cfg").exists()


@pytest.mark.parametrize("option,value", [
    ("gear_ratio", "5"), ("gear_ratio", "5:0"), ("gear_ratio", "0:1"),
    ("gear_ratio", "-5:1"), ("gear_ratio", "nan:1"), ("gear_ratio", "inf:1"),
    ("gear_ratio", "2:1, bad"), ("rotation_distance", ""), ("rotation_distance", "nan"),
    ("rotation_distance", "0"), ("microsteps", ""), ("microsteps", "16.5"),
])
def test_invalid_secondary_values_fail_before_writing(tmp_path, option, value):
    board = multi_board()
    mechanics(board, "z1")
    board["stepper_z1"][option] = value
    (tmp_path / "printer.cfg").write_text("previous")
    with pytest.raises(GenerationError, match=f"{option}_z1"):
        render(tmp_path, board, _user(z_motors="2"))
    assert (tmp_path / "printer.cfg").read_text() == "previous"
    assert not (tmp_path / "printer.cfg.provenance.json").exists()


def test_inactive_secondary_values_do_not_block(tmp_path):
    board = multi_board()
    mechanics(board, "z3", "bad", "bad", "bad")
    result = render(tmp_path, board, _user(z_motors="1"))
    assert "[stepper_z3]" not in result["content"]


def test_empty_gear_ratio_is_upstream_ungeared_case(tmp_path):
    board = multi_board()
    mechanics(board, "z1", "8", "16", "")
    final = parse_config(render(tmp_path, board, _user(z_motors="2"))["content"])
    assert "gear_ratio" not in final["stepper_z1"]


@pytest.mark.parametrize("count", ["0", "-1", "5", "1000000000"])
def test_only_supported_z_motors_are_resolved(tmp_path, count):
    with pytest.raises(GenerationError, match="z_motors"):
        render(tmp_path, multi_board(), _user(z_motors=count))


def test_selected_profile_owns_secondary_mechanics_and_override_wins(tmp_path):
    board = multi_board()
    profile = multi_board()
    mechanics(board, "z1", "8", "16", "2:1")
    mechanics(profile, "z1", "20", "32", "5:1")
    user = _user(z_motors="2", _profile_parsed=profile)
    result = render(tmp_path, board, user)
    assert parse_config(result["content"])["stepper_z1"]["gear_ratio"] == "5:1"
    user["gear_ratio_z1"] = "1:1"
    mark_user_override(user, "gear_ratio_z1")
    result = render(tmp_path, board, user)
    assert parse_config(result["content"])["stepper_z1"]["gear_ratio"] == "1:1"
    assert board["stepper_z1"]["gear_ratio"] == "2:1"
