"""Configured eddy scan clearance must cover the pinned Z approach."""
import pytest

from core.bed_mesh import validate_mesh_clearance
from core.exceptions import GenerationError


def sections(height="5", maximum="300", provider="probe_eddy_current sensor"):
    result = {"bed_mesh": {}, "stepper_z": {"position_min": "0", "position_max": maximum}}
    if height is not None:
        result["bed_mesh"]["horizontal_move_z"] = height
    if provider:
        result[provider] = {"z_offset": "0"} if provider in ("probe", "bltouch") else {}
    return result


@pytest.mark.parametrize("height,maximum", [("300", "300"), ("299.500001", "300"), ("5", "5"), (None, "5")])
def test_eddy_approach_above_maximum_is_rejected(height, maximum):
    with pytest.raises(GenerationError, match="rapid_scan"):
        validate_mesh_clearance(sections(height, maximum))


@pytest.mark.parametrize("height,maximum", [("299.5", "300"), ("299.499999", "300"),
                                           ("0", ".5"), ("5", "5.5"), (None, "5.5")])
def test_eddy_approach_at_or_below_maximum_is_accepted(height, maximum):
    validate_mesh_clearance(sections(height, maximum))


@pytest.mark.parametrize("provider", ["probe", "bltouch", None])
def test_non_eddy_providers_do_not_inherit_rapid_scan_extra_height(provider):
    validate_mesh_clearance(sections("300", "300", provider))


@pytest.mark.parametrize("height", ["nan", "inf", "-inf", "bad", True, ""])
def test_nonfinite_or_malformed_height_still_rejects(height):
    with pytest.raises(GenerationError, match="finite"):
        validate_mesh_clearance(sections(height))


def test_explicit_none_still_rejects():
    cfg = sections()
    cfg["bed_mesh"]["horizontal_move_z"] = None
    with pytest.raises(GenerationError, match="finite"):
        validate_mesh_clearance(cfg)


@pytest.mark.parametrize("field,value", [("position_max", "nan"), ("position_min", "-inf")])
def test_nonfinite_limits_still_reject(field, value):
    cfg = sections()
    cfg["stepper_z"][field] = value
    with pytest.raises(GenerationError, match="finite"):
        validate_mesh_clearance(cfg)


def test_eddy_height_must_still_be_above_declared_minimum():
    cfg = sections("-.1", "300")
    with pytest.raises(GenerationError, match="position_min"):
        validate_mesh_clearance(cfg)


def test_fragments_without_known_z_maximum_keep_their_previous_scope():
    cfg = sections("300")
    del cfg["stepper_z"]["position_max"]
    validate_mesh_clearance(cfg)
    del cfg["stepper_z"]
    validate_mesh_clearance(cfg)


def test_no_mesh_does_not_add_hypothetical_scan_constraint():
    cfg = sections("300", "300")
    del cfg["bed_mesh"]
    validate_mesh_clearance(cfg)
