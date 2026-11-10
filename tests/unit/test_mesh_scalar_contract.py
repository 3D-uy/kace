"""Mesh scalar ownership, explicit values and finite-number boundaries."""
import copy

import pytest

from core.bed_mesh import generate_bed_mesh_config
from core.exceptions import GenerationError
from core.motion_model import PrinterMotionSpace


FIELDS = ("speed", "fade_start", "fade_end", "fade_target", "adaptive_margin")


def derive(mesh=None, **choices):
    user = {"x_size": "235", "y_size": "235", "probe": "BLTouch", **choices}
    return generate_bed_mesh_config(PrinterMotionSpace(user), user, {"bed_mesh": mesh or {}})


def test_selected_profile_owns_mesh_scalars_without_mutating_sources():
    board = {"speed": "99", "fade_start": "2", "fade_end": "8", "fade_target": "1", "adaptive_margin": "4"}
    profile = {"bed_mesh": {"speed": "77.125", "fade_start": "0", "fade_end": "0", "fade_target": "0", "adaptive_margin": "2.9"}}
    before = copy.deepcopy((board, profile))
    result = derive(board, _profile_parsed=profile)
    assert {k: result[k] for k in FIELDS} == profile["bed_mesh"]
    assert (board, profile) == before


def test_empty_selected_profile_does_not_fall_back_to_board_settings():
    result = derive({"speed": "99", "fade_end": "8", "adaptive_margin": "4"}, _profile_parsed={})
    assert result["speed"] == "120"
    assert result["fade_end"] == "10"
    assert "adaptive_margin" not in result


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "1e999", "bad", "", None, True])
def test_invalid_explicit_mesh_scalar_is_not_replaced_by_default(field, value):
    with pytest.raises(GenerationError, match=field):
        derive({field: value})


@pytest.mark.parametrize("field", ["fade_start", "fade_end", "fade_target", "adaptive_margin"])
@pytest.mark.parametrize("value", [0, "0", "0.0", "-0", "2.90123456789012345", "2.9e-1", "-0.5"])
def test_finite_explicit_values_preserve_text_and_zero(field, value):
    result = derive({field: value})
    assert result[field] == str(value)


@pytest.mark.parametrize("value", ["0", "-0.1", 0])
def test_speed_requires_positive_value(value):
    with pytest.raises(GenerationError, match="speed"):
        derive({"speed": value})


@pytest.mark.parametrize("value", ["12.123456789012345", "7.7e1", 77.125])
def test_speed_preserves_explicit_numeric_representation(value):
    assert derive({"speed": value})["speed"] == str(value)


@pytest.mark.parametrize("value", [2.9, "2.9", "2.90123456789012345", 0, "0", "-0.5"])
def test_adaptive_user_selection_preserves_decimals_and_zero(value):
    assert derive({"adaptive_margin": "8"}, adaptive_margin=value)["adaptive_margin"] == str(value)


def test_adaptive_flag_only_supplies_default_when_no_explicit_margin():
    assert derive(adaptive_mesh=True)["adaptive_margin"] == "5"
    assert derive({"adaptive_margin": "2.9"}, adaptive_mesh=True)["adaptive_margin"] == "2.9"


@pytest.mark.parametrize("value", ["nan", "inf", "bad", None, True])
def test_invalid_adaptive_override_does_not_fall_back(value):
    with pytest.raises(GenerationError, match="adaptive_margin"):
        derive({"adaptive_margin": "2.9"}, adaptive_margin=value)


def test_no_probe_does_not_validate_unused_mesh_options():
    assert derive({"speed": "nan"}, probe="None") == {}
