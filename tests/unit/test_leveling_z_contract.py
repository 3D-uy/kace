"""Declared Z motion for active z_tilt/QGL, without physical clearance claims."""
import copy

import pytest

from core.exceptions import GenerationError
from core.leveling import validate_leveling_clearance


SECTIONS = ("z_tilt", "quad_gantry_level")


def config(section, height="5", speed="50", minimum="0", maximum="250", provider="bltouch"):
    data = {section: {"horizontal_move_z": height, "speed": speed},
            "stepper_z": {"position_min": minimum, "position_max": maximum}}
    if provider:
        data[provider] = {"z_offset": "0"} if provider in ("probe", "bltouch") else {}
    return data


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("height", ["nan", "inf", "-inf", "bad", "", None, True])
def test_invalid_height_rejected(section, height):
    with pytest.raises(GenerationError, match="horizontal_move_z"):
        validate_leveling_clearance(config(section, height=height))


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("speed", ["0", "-1", "nan", "inf", "bad", "", None, True])
def test_invalid_speed_rejected(section, speed):
    with pytest.raises(GenerationError, match="speed"):
        validate_leveling_clearance(config(section, speed=speed))


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("height", ["0", ".01", "249.999", "250"])
def test_finite_height_inside_inclusive_range_preserved(section, height):
    cfg = config(section, height=height, speed=".001")
    before = copy.deepcopy(cfg)
    validate_leveling_clearance(cfg)
    assert cfg == before


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("height", ["-.001", "250.001"])
def test_height_outside_declared_range_rejected(section, height):
    with pytest.raises(GenerationError, match="position_(min|max)"):
        validate_leveling_clearance(config(section, height=height, provider=None))


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("provider", ["probe", "bltouch"])
def test_known_standard_probe_offset_is_lower_bound(section, provider):
    cfg = config(section, height="1", provider=provider)
    cfg[provider]["z_offset"] = "2"
    with pytest.raises(GenerationError, match="z_offset"):
        validate_leveling_clearance(cfg)
    cfg[section]["horizontal_move_z"] = "2"
    validate_leveling_clearance(cfg)


@pytest.mark.parametrize("section", SECTIONS)
def test_eddy_zero_offset_does_not_add_rapid_scan_half_millimetre(section):
    cfg = config(section, height="250", provider="probe_eddy_current sensor")
    validate_leveling_clearance(cfg)
    cfg["stepper_z"]["position_min"] = "-2"
    cfg[section]["horizontal_move_z"] = "-.1"
    with pytest.raises(GenerationError):
        validate_leveling_clearance(cfg)
    cfg[section]["horizontal_move_z"] = "0"
    validate_leveling_clearance(cfg)


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("key", ["position_min", "position_max"])
def test_known_limits_must_be_finite(section, key):
    cfg = config(section)
    cfg["stepper_z"][key] = "nan"
    with pytest.raises(GenerationError, match="finite"):
        validate_leveling_clearance(cfg)


@pytest.mark.parametrize("section", SECTIONS)
def test_default_height_five_respects_known_range(section):
    cfg = {section: {}, "stepper_z": {"position_max": "4"}}
    with pytest.raises(GenerationError, match="position_max"):
        validate_leveling_clearance(cfg)
    cfg["stepper_z"]["position_max"] = "5"
    validate_leveling_clearance(cfg)


@pytest.mark.parametrize("section", SECTIONS)
def test_fragments_do_not_invent_unknown_z_maximum_or_bounds(section):
    validate_leveling_clearance({section: {"horizontal_move_z": "1000"},
                                "stepper_z": {"position_min": "0"}})
    validate_leveling_clearance({section: {"horizontal_move_z": "-3"}})
    validate_leveling_clearance({section: {"horizontal_move_z": "-.1"},
                                "stepper_z": {"position_min": "-2", "position_max": "250"}})


def test_only_active_leveling_sections_are_in_scope():
    validate_leveling_clearance({"bed_mesh": {"horizontal_move_z": "nan"},
                                "stepper_z": {"position_max": "nan"}})
    validate_leveling_clearance({"#z_tilt": {"horizontal_move_z": "nan"}})
