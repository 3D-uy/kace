"""Distinct raw resistances can collapse after floating-point logarithms."""
import copy
import itertools
import math

import pytest

from core.exceptions import GenerationError
from core.thermistor import selected_custom_thermistors, validate_custom_thermistors


COLLAPSED = ("100000", "100001", "100000.00000000001")
TEMPERATURES = ("25", "100", "200")


def curve(resistances=COLLAPSED, temperatures=TEMPERATURES):
    return {f"{field}{index}": value
            for index, pair in enumerate(zip(temperatures, resistances), 1)
            for field, value in zip(("temperature", "resistance"), pair)}


@pytest.mark.parametrize("resistances", list(itertools.permutations(COLLAPSED)))
@pytest.mark.parametrize("temperatures", list(itertools.permutations(TEMPERATURES)))
def test_collapsed_logs_report_generation_error_in_every_sample_order(resistances, temperatures):
    assert len({float(value) for value in resistances}) == 3
    assert len({math.log(float(value)) for value in resistances}) == 2
    with pytest.raises(GenerationError, match="singular"):
        validate_custom_thermistors({"thermistor Collapsed": curve(resistances, temperatures)})


@pytest.mark.parametrize("definition", [
    curve(("140000", "593", "189"), ("20", "195", "255")),
    # Numerically distinct nearby logs must not acquire an arbitrary minimum gap.
    curve(("100000", "100000.001", "100000.002")),
    {"temperature1": "25", "resistance1": "100000.00000000001", "beta": "3950"},
])
def test_nonsingular_and_beta_definitions_are_preserved(definition):
    sections = {"thermistor Compatible": definition}
    original = copy.deepcopy(sections)
    validate_custom_thermistors(sections)
    assert sections == original


@pytest.mark.parametrize("source", ["board", "profile"])
def test_selected_curve_propagates_structured_rejection_without_mutation(source):
    board = {"thermistor Collapsed": curve()} if source == "board" else {}
    user = {"hotend_thermistor": "Collapsed", "bed_thermistor": "Generic 3950"}
    if source == "profile":
        user["_profile_parsed"] = {"thermistor Collapsed": curve()}
    original = copy.deepcopy((board, user))
    with pytest.raises(GenerationError, match="singular"):
        selected_custom_thermistors(board, user)
    assert (board, user) == original
