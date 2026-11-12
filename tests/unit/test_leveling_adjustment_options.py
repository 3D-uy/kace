"""Configured retry/adjustment contracts, separate from command overrides."""
import copy

import pytest

from core.exceptions import GenerationError
from core import leveling


SECTIONS = ("z_tilt", "quad_gantry_level")


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("value", ["-1", "1.5", "nan", "inf", "bad", "", None, True])
def test_retries_requires_nonnegative_integer(section, value):
    with pytest.raises(GenerationError, match="retries"):
        leveling.validate_leveling_adjustment_options({section: {"retries": value}})


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "-inf", "", None, True])
def test_explicit_retry_tolerance_requires_positive_finite_value(section, value):
    with pytest.raises(GenerationError, match="retry_tolerance"):
        leveling.validate_leveling_adjustment_options({section: {"retry_tolerance": value}})


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "-inf", "", None, True])
def test_explicit_qgl_max_adjust_requires_positive_finite_value(value):
    with pytest.raises(GenerationError, match="max_adjust"):
        leveling.validate_leveling_adjustment_options({"quad_gantry_level": {"max_adjust": value}})


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("options", [
    {}, {"retries": "0"}, {"retries": "31", "retry_tolerance": "1.01"},
    {"retries": "+005", "retry_tolerance": ".00001"},
])
def test_defaults_and_compatible_cfg_values_are_not_command_limited_or_rewritten(section, options):
    sections = {section: options.copy()}
    if section == "quad_gantry_level":
        sections[section]["max_adjust"] = ".00001"
    original = copy.deepcopy(sections)
    leveling.validate_leveling_adjustment_options(sections)
    assert sections == original


def test_omitted_defaults_and_other_sections_are_not_invented_or_reinterpreted():
    sections = {"quad_gantry_level": {}, "z_tilt": {},
                "gcode_macro LEVEL": {"gcode": "Z_TILT_ADJUST RETRIES=31 RETRY_TOLERANCE=0"},
                "unrelated": {"max_adjust": "nan", "retries": "-1"}}
    original = copy.deepcopy(sections)
    leveling.validate_leveling_adjustment_options(sections)
    assert sections == original
