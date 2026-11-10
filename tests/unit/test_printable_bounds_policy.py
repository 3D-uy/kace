"""Printable origins are explicit decisions, not inferred rail translations."""
import copy
import json

import pytest

from core.capabilities import normalize_and_validate_configuration
from core.exceptions import GenerationError
from core.firmware_workflow import persistable_wizard_data, restore_wizard_data
from core.generator import generate_config
from core.motion_model import PrinterMotionSpace
from core.profile_values import mark_user_override
from tests.unit.test_generator import _parsed, _user
from tests.unit.test_profile_editor_navigation import editor


def _ambiguous(axis="x"):
    return _user(**{
        f"{axis}_size": "220", f"{axis}_position_min": "-10",
        f"{axis}_position_max": "210", f"{axis}_position_endstop": "-10",
    })


@pytest.mark.parametrize("axis", ["x", "y"])
def test_model_and_normalizer_require_explicit_origin_instead_of_shifting(axis):
    data = _ambiguous(axis)
    before = copy.deepcopy(data)
    for operation, error in (
        (PrinterMotionSpace, ValueError),
        (normalize_and_validate_configuration, GenerationError),
    ):
        with pytest.raises(error, match=f"explicit.*printable_{axis}_min.*printable_{axis}_max"):
            operation(copy.deepcopy(data))
    assert data == before


@pytest.mark.parametrize("axis", ["x", "y"])
def test_explicit_shifted_bed_agrees_on_center_and_probe_coordinates(axis):
    data = _ambiguous(axis)
    data.update({f"printable_{axis}_min": "-10", f"printable_{axis}_max": "210"})
    normalize_and_validate_configuration(data)
    space = PrinterMotionSpace(data)

    assert space.printable_bed_area()[axis] == (-10, 210)
    assert data[f"printable_center_{axis}"] == "100"
    assert space.starter_macro_positions()["center"][("x", "y").index(axis)] == 100
    assert space.safe_z_home_position()[("x", "y").index(axis)] == 100


def test_default_trace_survives_real_checkpoint_serialization_and_remains_implicit():
    data = _user(x_size="220", x_position_max="220")
    normalize_and_validate_configuration(data)
    trace = copy.deepcopy(data["_printable_bounds_defaults"])
    assert trace["printable_x_min"] == "0"
    assert trace["printable_x_max"] == "220"
    saved = json.loads(json.dumps(persistable_wizard_data(data)))
    restored = restore_wizard_data(saved)
    normalize_and_validate_configuration(restored)
    assert restored == data
    assert restored["_printable_bounds_defaults"] == trace

    restored.update(x_position_min="-10", x_position_max="210", x_position_endstop="-10")
    before = copy.deepcopy(restored)
    with pytest.raises(ValueError, match="explicit"):
        PrinterMotionSpace(restored)
    assert restored == before
    with pytest.raises(GenerationError, match="explicit"):
        normalize_and_validate_configuration(restored)
    assert restored["_printable_bounds_defaults"] == trace


def test_explicit_same_value_override_retires_its_default_trace():
    data = _user(x_size="220", x_position_max="220")
    normalize_and_validate_configuration(data)
    mark_user_override(data, "printable_x_min", "printable_x_max")
    normalize_and_validate_configuration(data)
    assert "printable_x_min" not in data["_printable_bounds_defaults"]
    assert "printable_x_max" not in data["_printable_bounds_defaults"]
    data.update(x_size="200")
    normalize_and_validate_configuration(data)
    assert data["printable_x_max"] == "220"
    assert PrinterMotionSpace(data).printable_bed_area()["x"] == (0, 220)


def test_changed_explicit_bound_is_not_replaced_by_a_previous_default():
    data = _user()
    normalize_and_validate_configuration(data)
    data["printable_x_max"] = "200"
    normalize_and_validate_configuration(data)
    assert data["printable_x_max"] == "200"
    assert "printable_x_max" not in data["_printable_bounds_defaults"]


def test_explicit_physical_bed_can_extend_beyond_effective_travel_in_model():
    space = PrinterMotionSpace({
        "x_position_max": 50, "printable_x_min": 0, "printable_x_max": 235,
        "printable_y_min": 0, "printable_y_max": 235,
    })
    assert space.printable_bed_area()["x"] == (0, 235)
    assert space.validate_probeable_area()["x"] == (0, 50)


def test_generation_rejects_ambiguous_origin_without_overwriting_previous_artifacts(tmp_path):
    path = tmp_path / "printer.cfg"
    generate_config(_parsed(), _user(), output_path=str(path), verbose=False)
    sidecar = tmp_path / "printer.cfg.provenance.json"
    before = path.read_bytes(), sidecar.read_bytes()

    with pytest.raises(GenerationError, match="explicit.*printable_x_min.*printable_x_max"):
        generate_config(_parsed(), _ambiguous(), output_path=str(path), verbose=False)

    assert (path.read_bytes(), sidecar.read_bytes()) == before


def test_summary_reports_ambiguity_without_inventing_printable_coordinates(capsys):
    from core.summary import print_summary

    data = _ambiguous()
    before = copy.deepcopy(data)
    print_summary(data)
    output = capsys.readouterr().out
    assert "printable_x_min" in output and "printable_x_max" in output
    assert "X [-10, 210]" not in output
    assert data == before


def test_offset_preview_cannot_confirm_ambiguous_bed_and_back_preserves_input(monkeypatch, capsys):
    from core import probe_offset_visualizer as preview

    data = _ambiguous()
    data.update(probe="BLTouch", probe_x_offset="-9", probe_y_offset="1")
    before = copy.deepcopy(data)
    replies = iter(["0", "0"])
    monkeypatch.setattr(preview, "simple_input", lambda *args, **kwargs: next(replies))
    offered = []

    def choose(prompt, choices):
        offered.extend(item["value"] for item in choices)
        return "back"

    monkeypatch.setattr(preview, "numbered_select", choose)
    result = preview.run_probe_offset_step(data)

    assert result["probe_x_offset"] == "__back__"
    assert "yes" not in offered
    output = capsys.readouterr().out
    assert "printable_x_min" in output and "printable_x_max" in output
    assert data == before


def test_editor_rejects_ambiguous_materialized_defaults_then_discard_preserves_state(editor, capsys):
    data, defaults, parsed, run = editor
    before = copy.deepcopy((data, defaults, parsed))

    assert run(["x_position_min", "-10", "x_position_max", "225", "save", "back"]) == "back"

    output = capsys.readouterr().out
    assert "Configuration Validation Failed" in output
    assert "explicit printable_x_min and printable_x_max" in output
    assert (data, defaults, parsed) == before


def test_editor_keeps_an_explicit_shifted_bed_through_save_and_checkpoint(editor):
    data, defaults, parsed, run = editor
    data.update(x_size="220", x_position_min="-10", x_position_max="210",
                x_position_endstop="-10", printable_x_min="-10", printable_x_max="210")
    mark_user_override(data, "printable_x_min", "printable_x_max")

    assert run(["save"]) == "save"
    restored = restore_wizard_data(json.loads(json.dumps(persistable_wizard_data(data))))
    normalize_and_validate_configuration(restored)

    assert restored["printable_center_x"] == "100"
    assert PrinterMotionSpace(restored).printable_bed_area()["x"] == (-10, 210)
    assert defaults["printable_x_min"] == "-10"
    assert defaults["printable_x_max"] == "210"


def test_editor_explicit_volume_acceptance_retires_matching_materialized_defaults(editor):
    data, defaults, parsed, run = editor
    sizes = [data[f"{axis}_size"] for axis in ("x", "y", "z")]

    assert run(["volume", *sizes, "save"]) == "save"

    assert not data["_printable_bounds_defaults"]
    for axis in ("x", "y"):
        for bound in ("min", "max"):
            assert data["_value_provenance"][f"printable_{axis}_{bound}"] == "USER_OVERRIDE"
