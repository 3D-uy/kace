"""Explicit XY bed bounds are an atomic profile edit, separate from travel."""
import copy

import pytest

from core.motion_model import PrinterMotionSpace
from core.menu import _plain_label
from core.generator import generate_config
from core.profile_values import mark_user_override
from core.translations import set_lang, t
from core.wizard.steps.motion import print_detected_profile_summary
from tests.unit.test_profile_editor_navigation import editor
from tests.unit.test_profile_editor_volume import profile_editor


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
def test_shifted_bed_editor_saves_explicit_bounds_without_changing_rails(editor, language, capsys):
    data, defaults, parsed, run = editor
    set_lang(language)
    data.update(x_size="220", x_position_min="-10", x_position_max="210", x_position_endstop="-10")
    rails = {key: value for key, value in data.items() if "_position_" in key}
    original_parsed = copy.deepcopy(parsed)

    assert run(["printable_bounds", "-10", "210", "0", "235", "save"]) == "save"

    assert {key: value for key, value in data.items() if "_position_" in key} == rails
    assert parsed == original_parsed
    assert data["printable_center_x"] == "100"
    assert PrinterMotionSpace(data).printable_bed_area()["x"] == (-10, 210)
    assert data["x_size"] == "220"
    assert defaults["printable_x_min"] == "-10"
    assert defaults["printable_x_max"] == "210"
    assert not data["_printable_bounds_defaults"]
    assert defaults["_printable_bounds_defaults"] == data["_printable_bounds_defaults"]
    for axis in ("x", "y"):
        for bound in ("min", "max"):
            assert data["_value_provenance"][f"printable_{axis}_{bound}"] == "USER_OVERRIDE"
    editor_output = " ".join(_plain_label(capsys.readouterr().out).split())
    assert t("profile.printable_bounds") in editor_output
    assert "220 x 220 mm" in editor_output
    print_detected_profile_summary(defaults, parsed, data)
    assert "X -10..210 mm / Y 0..235 mm" in " ".join(capsys.readouterr().out.split())


@pytest.mark.parametrize("cancel_at", [0, 1, 2, 3])
def test_back_from_any_bound_preserves_other_staged_edits(editor, cancel_at):
    data, defaults, parsed, run = editor
    old_bounds = {key: value for key, value in data.items() if key.startswith("printable_")}
    old_trace = copy.deepcopy(data["_printable_bounds_defaults"])

    assert run(["x_position_max", "400", "printable_bounds", *["20"] * cancel_at, "<", "save"]) == "save"

    assert data["x_position_max"] == "400"
    assert {key: value for key, value in data.items() if key.startswith("printable_")} == old_bounds
    assert data["_printable_bounds_defaults"] == old_trace


@pytest.mark.parametrize("bounds", [
    ["20", "10", "0", "235"],
    ["0", "235", "20", "20"],
    ["-1", "235", "0", "235"],
    ["0", "321", "0", "235"],
])
def test_invalid_bounds_do_not_replace_accepted_candidate(editor, bounds, capsys):
    data, defaults, parsed, run = editor
    before = copy.deepcopy(data)

    assert run(["printable_bounds", *bounds, "save"]) == "save"

    assert data == before
    assert t("profile.printable_bounds_invalid") in capsys.readouterr().out


def test_full_bound_edit_is_discarded_with_editor_back(editor):
    data, defaults, parsed, run = editor
    before = copy.deepcopy((data, defaults, parsed))

    assert run(["printable_bounds", "10", "200", "10", "200", "back"]) == "back"

    assert (data, defaults, parsed) == before


@pytest.mark.parametrize("invalid", ["nan", "inf", "-inf"])
def test_nonfinite_entry_cannot_replace_a_bound(editor, invalid):
    data, defaults, parsed, run = editor

    assert run(["printable_bounds", invalid, "0", "235", "0", "235", "save"]) == "save"

    assert data["printable_x_min"] == "0"
    assert data["printable_x_max"] == "235"
    assert data["_value_provenance"]["printable_x_min"] == "USER_OVERRIDE"


def test_shifted_editor_geometry_reaches_generation_with_original_profile_preserved(profile_editor, tmp_path):
    data, defaults, parsed, run = profile_editor
    original = copy.deepcopy(data["_profile_parsed"])
    data["x_size"] = "220"
    mark_user_override(data, "x_size")

    assert run([
        "x_position_min", "-10", "x_position_max", "210", "x_position_endstop", "-10",
        "printable_bounds", "-10", "210", "0", "235", "save",
    ]) == "save"
    generated = generate_config(
        data["board_parsed"], data, output_path=str(tmp_path / "printer.cfg"), verbose=False,
    )

    assert generated["motion_space"]["printable_bed_area"]["x"] == (-10, 210)
    assert data["printable_center_x"] == "100"
    assert data["_profile_parsed"] == original
