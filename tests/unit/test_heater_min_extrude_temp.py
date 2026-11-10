"""Heater consumes explicit min_extrude_temp with inclusive temperature bounds."""
import copy

import pytest

from core.exceptions import GenerationError
from core.heater_options import validate_heater_options


HEATERS = ["extruder", "extruder1", "heater_bed", "heater_generic chamber"]


@pytest.mark.parametrize("section", HEATERS)
@pytest.mark.parametrize("value", ["-1", "151", "nan", "inf", "-inf", "bad", ""])
def test_invalid_explicit_threshold_rejected_for_each_heater(section, value):
    # The range is upstream's; finiteness is an additional KACE policy.
    with pytest.raises(GenerationError, match="min_extrude_temp"):
        validate_heater_options({section: {
            "min_temp": "0", "max_temp": "150", "min_extrude_temp": value,
        }})


@pytest.mark.parametrize("section", HEATERS)
@pytest.mark.parametrize("value", ["0", "150", "72.25"])
def test_inclusive_boundaries_zero_and_decimal_preserved(section, value):
    sections = {section: {
        "min_temp": "0", "max_temp": "150", "min_extrude_temp": value,
    }}
    original = copy.deepcopy(sections)
    validate_heater_options(sections)
    assert sections == original


@pytest.mark.parametrize("section", HEATERS)
def test_omitted_threshold_does_not_check_or_materialize_default(section):
    # Klipper's omitted 170 default is returned without checking these bounds.
    sections = {section: {"min_temp": "0", "max_temp": "150"}}
    original = copy.deepcopy(sections)
    validate_heater_options(sections)
    assert sections == original


@pytest.mark.parametrize("section", HEATERS)
def test_negative_threshold_inside_declared_range_is_not_arbitrarily_rejected(section):
    sections = {section: {
        "min_temp": "-10", "max_temp": "150", "min_extrude_temp": "-5",
    }}
    original = copy.deepcopy(sections)
    validate_heater_options(sections)
    assert sections == original


@pytest.mark.parametrize("fields", [
    {"min_extrude_temp": "-5"},
    {"min_temp": "-10", "min_extrude_temp": "0"},
    {"max_temp": "100", "min_extrude_temp": "-5"},
])
def test_fragments_do_not_acquire_unspecified_temperature_bounds(fields):
    original = copy.deepcopy(fields)
    validate_heater_options({"heater_generic chamber": fields})
    assert fields == original


def test_other_sensor_registries_remain_outside_heater_contract():
    validate_heater_options({
        "temperature_sensor room": {"min_extrude_temp": "nan"},
        "temperature_fan chamber": {"min_extrude_temp": "nan"},
    })
