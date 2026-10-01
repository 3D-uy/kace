"""The Z mechanics choice must be explicit, staged and tied to its context."""
import copy
import json
from unittest.mock import patch

import pytest

from core.exceptions import GenerationError, WizardExit
from core.firmware_workflow import persistable_wizard_data
from core.scraper import parse_config
from core.wizard.steps import motion
from tests.unit.test_full_steps_preservation import multi_board, render
from tests.unit.test_generator import _user
from tests.unit.test_z_mechanics_preservation import mechanics


def data(count=2):
    board = multi_board()
    mechanics(board, "z", "40", "32", "80:16")
    board["stepper_z"]["full_steps_per_rotation"] = "400"
    return _user(z_motors=str(count), board_parsed=board)


def choose(user, modes, inputs=(), confirm=True):
    with patch.object(motion, "numbered_select", side_effect=modes), \
            patch.object(motion, "simple_input", side_effect=inputs), \
            patch.object(motion, "yes_no", return_value=confirm):
        return motion._step_z_mechanics(user)


@pytest.mark.parametrize("count", [2, 4])
def test_confirmed_same_assembly_copies_all_four_scale_values(tmp_path, count):
    user = data(count)
    assert choose(user, ["same"] * (count - 1)) == "done"
    result = render(tmp_path, user["board_parsed"], user)
    final = parse_config(result["content"])
    for index in range(1, count):
        values = final[f"stepper_z{index}"]
        assert [values[option] for option in ("rotation_distance", "microsteps", "gear_ratio", "full_steps_per_rotation")] == ["40", "32", "80:16", "400"]


def test_individual_values_are_not_replaced_by_the_primary(tmp_path):
    user = data()
    assert choose(user, ["individual"], ["8", "16", "2:1", "48"]) == "done"
    final = parse_config(render(tmp_path, user["board_parsed"], user)["content"])
    assert [final["stepper_z1"][o] for o in ("rotation_distance", "microsteps", "gear_ratio", "full_steps_per_rotation")] == ["8", "16", "2:1", "48"]


def test_individual_empty_reduction_is_explicitly_ungeared(tmp_path):
    user = data()
    assert choose(user, ["individual"], ["8", "16", "", "200"]) == "done"
    final = parse_config(render(tmp_path, user["board_parsed"], user)["content"])
    assert final["stepper_z1"]["gear_ratio"] == "1:1"


def test_keep_preserves_complete_independent_profile_and_provenance(tmp_path):
    user = data()
    mechanics(user["board_parsed"], "z1", "4", "16", "1:1")
    assert choose(user, ["keep"]) == "done"
    result = render(tmp_path, user["board_parsed"], user)
    assert result["value_provenance"]["rotation_distance_z1"] == "PROFILE"
    assert parse_config(result["content"])["stepper_z1"]["rotation_distance"] == "4"


@pytest.mark.parametrize("modes,confirm,expected", [(["same"], False, "__retry__"), (["__back__"], True, "__back__")])
def test_no_partial_commit_without_confirmation(modes, confirm, expected):
    user = data()
    before = copy.deepcopy(user)
    assert choose(user, modes, confirm=confirm) == expected
    assert user == before


def test_back_after_first_motor_discards_all_staged_choices():
    user = data(4)
    before = copy.deepcopy(user)
    assert choose(user, ["same", "__back__"]) == "__back__"
    assert user == before


def test_quit_discards_staged_choices():
    user = data()
    before = copy.deepcopy(user)
    with pytest.raises(WizardExit):
        choose(user, ["__quit__"])
    assert user == before


def test_resume_keeps_confirmation_and_rejects_changed_primary(tmp_path):
    user = data()
    choose(user, ["same"])
    restored = json.loads(json.dumps(persistable_wizard_data(user)))
    render(tmp_path, restored["board_parsed"], restored)
    restored["board_parsed"]["stepper_z"]["gear_ratio"] = "3:1"
    with pytest.raises(GenerationError, match="confirmation"):
        render(tmp_path, restored["board_parsed"], restored)
    assert choose(restored, ["same"]) == "done"
    final = parse_config(render(tmp_path, restored["board_parsed"], restored)["content"])
    assert final["stepper_z1"]["gear_ratio"] == "3:1"


@pytest.mark.parametrize("change", ["profile", "board", "count", "secondary", "choice"])
def test_changed_context_or_values_invalidates_confirmation(tmp_path, change):
    user = data()
    choose(user, ["same"])
    if change == "profile":
        user["printer_profile"] = "another-profile.cfg"
    elif change == "board":
        user["board"] = "another-board.cfg"
    elif change == "count":
        user["z_motors"] = "4"
    elif change == "secondary":
        user["board_parsed"]["stepper_z1"]["rotation_distance"] = "2"
    else:
        user["rotation_distance_z1"] = "12"
    with pytest.raises(GenerationError, match="confirmation"):
        render(tmp_path, user["board_parsed"], user)


def test_new_profile_is_not_hidden_by_stale_copied_values(tmp_path):
    user = data()
    choose(user, ["same"])
    profile = copy.deepcopy(user["board_parsed"])
    mechanics(profile, "z1", "4", "16", "2:1")
    user["_profile_parsed"] = profile
    assert choose(user, ["keep"]) == "done"
    final = parse_config(render(tmp_path, user["board_parsed"], user)["content"])
    assert final["stepper_z1"]["rotation_distance"] == "4"


def test_auto_does_not_invent_a_confirmation(monkeypatch):
    user = data()
    monkeypatch.setenv("KACE_AUTO", "1")
    with pytest.raises(GenerationError):
        motion._step_z_mechanics(user)
    assert "_z_mechanics_confirmation" not in user


def test_single_z_has_no_prompt():
    user = data(1)
    with patch.object(motion, "numbered_select", side_effect=AssertionError("unexpected prompt")):
        assert motion._step_z_mechanics(user) == "__skip__"


@pytest.mark.parametrize("inputs", [["nan"], ["8", "0"], ["8", "16", "1:0"], ["8", "16", "1:1", "201"]])
def test_invalid_individual_input_does_not_commit(inputs):
    user = data()
    before = copy.deepcopy(user)
    assert choose(user, ["individual"], inputs) == "__retry__"
    assert user == before


def test_review_defaults_to_no_and_detects_changed_live_primary():
    user = data()
    def changed(*args, **kwargs):
        assert kwargs["default"] is False
        user["board_parsed"]["stepper_z"]["rotation_distance"] = "12"
        return True
    with patch.object(motion, "numbered_select", return_value="same"), \
            patch.object(motion, "yes_no", side_effect=changed):
        assert motion._step_z_mechanics(user) == "__retry__"
    assert user["board_parsed"]["stepper_z"]["rotation_distance"] == "12"
    assert "rotation_distance_z1" not in user
    assert "_z_mechanics_confirmation" not in user


def test_keep_after_copy_retains_ownership_for_later_profile_change(tmp_path):
    user = data()
    choose(user, ["same"])
    choose(user, ["keep"])
    mechanics(user["board_parsed"], "z1", "4", "16", "2:1")
    assert choose(user, ["keep"]) == "done"
    final = parse_config(render(tmp_path, user["board_parsed"], user)["content"])
    assert final["stepper_z1"]["rotation_distance"] == "4"


def test_switch_to_single_z_clears_copied_secondary_choices():
    user = data()
    choose(user, ["same"])
    user["z_motors"] = "1"
    assert motion._step_z_mechanics(user) == "__skip__"
    assert "rotation_distance_z1" not in user
    assert "_z_mechanics_confirmation" not in user
    user["z_motors"] = "2"
    with pytest.raises(GenerationError):
        motion.resolve_generation_values(user["board_parsed"], user)


@pytest.mark.parametrize("confirmed", [False, True])
def test_auto_accepts_complete_source_or_existing_valid_confirmation(monkeypatch, confirmed):
    user = data()
    if confirmed:
        choose(user, ["same"])
    else:
        mechanics(user["board_parsed"], "z1", "8", "16", "1:1")
    before = copy.deepcopy(user)
    monkeypatch.setenv("KACE_AUTO", "1")
    assert motion._step_z_mechanics(user) == "__skip__"
    assert user == before


def test_runner_back_from_probe_discards_confirmation_and_allows_new_choice():
    from core.wizard.runner import WizardRunner
    user = data()
    visits = []
    def probe(state):
        visits.append(state["rotation_distance_z1"])
        return "__back__" if len(visits) == 1 else "done"
    runner = WizardRunner({"z_mechanics": {"prompt": motion._step_z_mechanics},
                           "probe": {"prompt": probe}}, ["z_mechanics", "probe"], user)
    with patch.object(motion, "numbered_select", side_effect=["same", "individual"]), \
            patch.object(motion, "simple_input", side_effect=["8", "16", "2:1", "48"]), \
            patch.object(motion, "yes_no", return_value=True), \
            patch("core.wizard.ui._print_step_header"):
        final = runner.run("z_mechanics")
    assert visits == ["40", "8"]
    assert final["_z_mechanics_confirmation"]["values"]["full_steps_per_rotation_z1"] == "48"


def test_profile_and_custom_routes_pass_through_mechanics_before_probe():
    from core.wizard import run_wizard, WizardRunner
    captured = {}
    original = WizardRunner.__init__
    def capture(self, config, order, initial_data=None):
        captured.update(config=config, order=order)
        original(self, config, order, initial_data)
    with patch("core.wizard.WizardRunner.__init__", capture), \
            patch("core.wizard.discover_mcu", return_value={}), \
            patch("core.wizard.fetch_config_list", return_value=[]), \
            patch("core.wizard.WizardRunner.run", return_value={}):
        run_wizard()
    runner = WizardRunner(captured["config"], captured["order"])
    assert captured["config"]["profile_review"]["next"]("confirm", {}) == "homing_directions"
    assert runner.get_default_next("z_limits") == "homing_directions"
    assert runner.get_default_next("homing_directions") == "z_mechanics"
    assert runner.get_default_next("z_mechanics") == "tmc_currents"
    assert runner.get_default_next("tmc_currents") == "probe"
