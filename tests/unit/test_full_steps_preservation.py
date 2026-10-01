"""Motor full steps must survive rendering without changing motion scale."""
import copy
import json

import pytest

from core.exceptions import GenerationError
from core.generator import generate_config
from core.profile_values import extract_profile_values, mark_profile_values, mark_user_override
from core.firmware_workflow import persistable_wizard_data
from core.scraper import parse_config, extract_profile_defaults
from tests.unit.test_generator import _parsed, _user

TARGETS = {"x": "stepper_x", "y": "stepper_y", "z": "stepper_z",
           "z1": "stepper_z1", "z2": "stepper_z2", "z3": "stepper_z3", "e": "extruder"}


def multi_board():
    parsed = _parsed()
    for i in range(1, 4):
        parsed[f"stepper_z{i}"] = {"step_pin": f"PF{i * 3}", "dir_pin": f"PF{i * 3 + 1}",
                                  "enable_pin": f"PF{i * 3 + 2}"}
    return parsed


def render(tmp_path, parsed, user=None):
    return generate_config(parsed, user or _user(z_motors="4"),
                           output_path=str(tmp_path / "printer.cfg"), verbose=False)


@pytest.mark.parametrize("target,section", TARGETS.items())
@pytest.mark.parametrize("full_steps", [200, 400, 48])
def test_each_motor_preserves_explicit_full_steps(tmp_path, target, section, full_steps):
    parsed = multi_board()
    parsed[section]["full_steps_per_rotation"] = str(full_steps)
    result = render(tmp_path, parsed)
    final = parse_config(result["content"])
    assert final[section]["full_steps_per_rotation"] == str(full_steps)
    assert result["value_provenance"][f"full_steps_per_rotation_{target}"] == "PROFILE"
    sidecar = json.loads((tmp_path / "printer.cfg.provenance.json").read_text())
    assert sidecar["values"][f"full_steps_per_rotation_{target}"] == "PROFILE"


def test_omission_preserves_klipper_default_without_snapshot_churn(tmp_path):
    result = render(tmp_path, multi_board())
    final = parse_config(result["content"])
    for target, section in TARGETS.items():
        assert "full_steps_per_rotation" not in final[section]
        assert result["value_provenance"][f"full_steps_per_rotation_{target}"] == "SAFE_DEFAULT"


def test_different_z_motors_and_omitted_secondary_do_not_inherit_primary(tmp_path):
    parsed = multi_board()
    for target, value in (("z", "400"), ("z1", "48"), ("z3", "200")):
        parsed[TARGETS[target]]["full_steps_per_rotation"] = value
    final = parse_config(render(tmp_path, parsed)["content"])
    assert [final[TARGETS[t]].get("full_steps_per_rotation", "200") for t in ("z", "z1", "z2", "z3")] == ["400", "48", "200", "200"]


def test_profile_authority_override_and_resume(tmp_path):
    board = multi_board()
    board["stepper_x"]["full_steps_per_rotation"] = "200"
    profile = copy.deepcopy(board)
    profile["stepper_x"]["full_steps_per_rotation"] = "400"
    user = _user(z_motors="4", _profile_parsed=profile)
    user.update(extract_profile_defaults(profile))
    mark_profile_values(user, profile)
    assert user["full_steps_per_rotation_x"] == "400"
    assert parse_config(render(tmp_path, board, user)["content"])["stepper_x"]["full_steps_per_rotation"] == "400"
    user["full_steps_per_rotation_x"] = "48"
    mark_user_override(user, "full_steps_per_rotation_x")
    restored = json.loads(json.dumps(persistable_wizard_data(user)))
    result = render(tmp_path, board, restored)
    assert parse_config(result["content"])["stepper_x"]["full_steps_per_rotation"] == "48"
    assert result["value_provenance"]["full_steps_per_rotation_x"] == "USER_OVERRIDE"
    assert board["stepper_x"]["full_steps_per_rotation"] == "200"
    assert profile["stepper_x"]["full_steps_per_rotation"] == "400"


@pytest.mark.parametrize("bad", ["0", "-4", "201", "400.0", "nan", "inf", "", None, True])
@pytest.mark.parametrize("source", ["profile", "override"])
def test_invalid_full_steps_fail_before_output_changes(tmp_path, bad, source):
    parsed = multi_board()
    user = _user(z_motors="4")
    if source == "profile":
        parsed["extruder"]["full_steps_per_rotation"] = bad
    else:
        user["full_steps_per_rotation_e"] = bad
        mark_user_override(user, "full_steps_per_rotation_e")
    output = tmp_path / "printer.cfg"
    output.write_text("unchanged")
    with pytest.raises(GenerationError, match="full_steps_per_rotation_e"):
        render(tmp_path, parsed, user)
    assert output.read_text() == "unchanged"
    assert not (tmp_path / "printer.cfg.provenance.json").exists()


def test_unused_z_motor_does_not_block_selected_configuration(tmp_path):
    parsed = multi_board()
    parsed["stepper_z3"]["full_steps_per_rotation"] = "bad-unused"
    result = render(tmp_path, parsed, _user(z_motors="1"))
    assert "[stepper_z3]" not in result["content"]
    assert "full_steps_per_rotation_z3" not in result["value_provenance"]


def test_unresolved_selected_step_count_cannot_fall_back(tmp_path):
    with pytest.raises(GenerationError, match="full_steps_per_rotation_x"):
        render(tmp_path, multi_board(), _user(z_motors="4",
            _value_provenance={"full_steps_per_rotation_x": "UNRESOLVED"}))


def test_source_extraction_preserves_blank_for_validation():
    assert extract_profile_values({"stepper_x": {"full_steps_per_rotation": ""}})["full_steps_per_rotation_x"] == ""


def test_generic_default_does_not_hide_profile_step_count(tmp_path):
    parsed = multi_board()
    parsed["stepper_x"]["full_steps_per_rotation"] = "400"
    user = _user(z_motors="4", full_steps_per_rotation_x="200",
                 _value_provenance={"full_steps_per_rotation_x": "SAFE_DEFAULT"})
    result = render(tmp_path, parsed, user)
    assert parse_config(result["content"])["stepper_x"]["full_steps_per_rotation"] == "400"
    assert result["value_provenance"]["full_steps_per_rotation_x"] == "PROFILE"


def test_explicit_override_can_replace_invalid_profile_value(tmp_path):
    parsed = multi_board()
    parsed["extruder"]["full_steps_per_rotation"] = "bad"
    user = _user(z_motors="4", full_steps_per_rotation_e="48")
    mark_user_override(user, "full_steps_per_rotation_e")
    result = render(tmp_path, parsed, user)
    assert parse_config(result["content"])["extruder"]["full_steps_per_rotation"] == "48"
