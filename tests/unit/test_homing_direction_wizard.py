"""Homing intent must remain reviewable without changing motor electrical direction."""

import copy
from unittest.mock import patch

import pytest

from core.exceptions import GenerationError, WizardExit
from core.menu import parse_choices
from core.translations import get_lang, set_lang
from core.wizard.runner import _BACK, _QUIT
from core.wizard.steps import motion


def travel(**changes):
    data = {f"{axis}_{field}": value for axis in ("x", "y", "z")
            for field, value in (("position_min", "0"), ("position_max", "320"),
                                 ("position_endstop", "0"))}
    data.update(changes)
    return data


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
def test_normal_flow_offers_three_localized_modes_and_shows_positive_inference(language):
    old_language = get_lang()
    set_lang(language)
    data = travel(x_position_endstop="320", dir_pin_x="!P2.6")
    menus = []
    def select(prompt, choices, default, **kwargs):
        menus.append((prompt, choices, default))
        return "auto"
    try:
        with patch.dict("os.environ", {"KACE_AUTO": "0"}), patch.object(motion, "numbered_select", side_effect=select):
            assert motion._step_homing_directions(data) == "done"
        assert len(menus) == 3
        for prompt, choices, default in menus:
            assert "wizard." not in prompt
            assert [choice["value"] for choice in choices[:3]] == ["auto", "False", "True"]
            assert default == 0
            assert all("wizard." not in choice["name"] for choice in choices[:3])
        assert "+X" in menus[0][1][0]["name"]
        assert data["homing_positive_dir_x"] == "True"
        assert data["homing_positive_dir_y"] == "False"
        assert data["_value_provenance"]["homing_positive_dir_x"] == "INFERRED"
        assert data["dir_pin_x"] == "!P2.6"
    finally:
        set_lang(old_language)


@pytest.mark.parametrize("choice,expected", [("False", "False"), ("True", "True")])
def test_explicit_choices_are_user_overrides(choice, expected):
    data = travel()
    with patch.dict("os.environ", {"KACE_AUTO": "0"}), patch.object(
            motion, "numbered_select", side_effect=[choice, "auto", "auto"]):
        assert motion._step_homing_directions(data) == "done"
    assert data["homing_positive_dir_x"] == expected
    assert data["_value_provenance"]["homing_positive_dir_x"] == "USER_OVERRIDE"


def test_imported_explicit_choice_is_default_and_keeps_profile_provenance():
    data = travel(homing_positive_dir_x="True", _value_provenance={"homing_positive_dir_x": "PROFILE"})
    menus = []
    def accept_default(prompt, choices, default, **kwargs):
        menus.append(default)
        return choices[default]["value"]
    with patch.dict("os.environ", {"KACE_AUTO": "0"}), patch.object(motion, "numbered_select", side_effect=accept_default):
        assert motion._step_homing_directions(data) == "done"
    assert menus == [2, 0, 0]
    assert data["homing_positive_dir_x"] == "True"
    assert data["_value_provenance"]["homing_positive_dir_x"] == "PROFILE"


def test_auto_recomputes_old_inference_from_edited_geometry():
    data = travel(x_position_endstop="320", homing_positive_dir_x="False",
                  _value_provenance={"homing_positive_dir_x": "INFERRED"})
    with patch.dict("os.environ", {"KACE_AUTO": "1"}), patch.object(motion, "numbered_select") as select:
        assert motion._step_homing_directions(data) == "done"
    select.assert_not_called()
    assert data["homing_positive_dir_x"] == "True"
    assert data["_value_provenance"]["homing_positive_dir_x"] == "INFERRED"


def test_ambiguous_auto_cannot_guess_and_requires_explicit_choice(capsys):
    data = travel(x_position_endstop="160")
    with patch.dict("os.environ", {"KACE_AUTO": "0"}), patch.object(
            motion, "numbered_select", side_effect=["auto", "True", "auto", "auto"]) as select:
        assert motion._step_homing_directions(data) == "done"
    assert select.call_count == 4
    assert select.call_args_list[0].kwargs["require_explicit"] is True
    assert "cannot infer" in capsys.readouterr().out
    assert data["homing_positive_dir_x"] == "True"
    assert data["_value_provenance"]["homing_positive_dir_x"] == "USER_OVERRIDE"


def test_noninteractive_ambiguous_auto_rejects_without_partial_state():
    data = travel(y_position_endstop="160")
    before = copy.deepcopy(data)
    with patch.dict("os.environ", {"KACE_AUTO": "1"}), pytest.raises(GenerationError, match="homing_positive_dir_y"):
        motion._step_homing_directions(data)
    assert data == before


@pytest.mark.parametrize("cancel", [_BACK, _QUIT, None])
def test_back_or_exit_never_commits_partial_axis_choices(cancel):
    data = travel()
    before = copy.deepcopy(data)
    with patch.dict("os.environ", {"KACE_AUTO": "0"}), patch.object(
            motion, "numbered_select", side_effect=["True", cancel]):
        if cancel == _BACK:
            assert motion._step_homing_directions(data) == _BACK
        else:
            with pytest.raises(WizardExit):
                motion._step_homing_directions(data)
    assert data == before


@pytest.mark.parametrize("mode", ["auto", "False", "True"])
def test_profile_editor_stages_direction_and_auto_removes_imported_directive(mode):
    data = travel(x_position_endstop="320", homing_positive_dir_x="False",
                  _value_provenance={"homing_positive_dir_x": "PROFILE"})
    defaults = dict(data)
    parsed = {"stepper_x": {"homing_positive_dir": "False"}}
    with patch.object(motion, "_INTERACTIVE_MODE", False), patch.object(
            motion, "numbered_select", side_effect=["homing_positive_dir_x", mode, "save"]):
        assert motion._step_profile_editor_inner(defaults, parsed, data) == "save"
    assert data["homing_positive_dir_x"] == ("True" if mode == "auto" else mode)
    assert data["_value_provenance"]["homing_positive_dir_x"] == ("INFERRED" if mode == "auto" else "USER_OVERRIDE")
    if mode == "auto":
        assert "homing_positive_dir" not in parsed["stepper_x"]
        assert "homing_positive_dir_x" not in defaults
    else:
        assert parsed["stepper_x"]["homing_positive_dir"] == mode


def test_discard_profile_direction_edit_preserves_all_sources():
    data = travel(homing_positive_dir_x="False")
    defaults = dict(data)
    parsed = {"stepper_x": {"homing_positive_dir": "False"}}
    before = copy.deepcopy((data, defaults, parsed))
    with patch.object(motion, "_INTERACTIVE_MODE", False), patch.object(
            motion, "numbered_select", side_effect=["homing_positive_dir_x", "True", "back"]):
        assert motion._step_profile_editor_inner(defaults, parsed, data) == "back"
    assert (data, defaults, parsed) == before


def test_editor_shows_an_axis_direction_row_and_current_automatic_inference():
    data = travel(x_position_endstop="320")
    menus = []
    def select(prompt, choices, **kwargs):
        menus.append(parse_choices(choices)[1])
        return "back"
    with patch.object(motion, "_INTERACTIVE_MODE", False), patch.object(motion, "numbered_select", side_effect=select):
        assert motion._step_profile_editor_inner(dict(data), {}, data) == "back"
    rows = dict((value, title) for title, value in menus[0])
    assert "+X" in rows["homing_positive_dir_x"]
    assert "Automatic" in rows["homing_positive_dir_x"]
    assert "-Y" in rows["homing_positive_dir_y"]


def test_profile_summary_shows_homing_without_reversing_limits(capsys):
    data = travel(x_position_endstop="320")
    data["printer_profile"] = "Custom / Scratch Build"
    motion.print_detected_profile_summary(data, {}, data)
    output = capsys.readouterr().out
    assert "X homing:" in output
    assert "Automatic" in output
    assert "+X" in output
    assert "X position_min:" in output
    assert data["x_position_min"] == "0"
    assert data["x_position_max"] == "320"


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
@pytest.mark.parametrize("mode", ["auto", "True"])
def test_z_automatic_hint_explains_later_probe_selection(language, mode, capsys):
    from core.translations import t
    old_language = get_lang()
    set_lang(language)
    data = travel()
    if mode != "auto":
        data["homing_positive_dir_z"] = mode
    try:
        with patch.object(motion, "numbered_select", return_value=mode):
            assert motion._select_homing_direction(data, "z") == mode
        output = capsys.readouterr().out
        assert (t("wizard.homing.z_probe_hint") in output) is (mode == "auto")
        assert "wizard." not in output
    finally:
        set_lang(old_language)
