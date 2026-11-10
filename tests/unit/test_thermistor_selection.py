"""Select the referenced factory without conflating case-distinct curves."""
import copy
import json

import pytest

from core.exceptions import GenerationError
from core.firmware_workflow import persistable_wizard_data
from core.thermistor import selected_custom_thermistors
from tests.unit.test_generator import _user


BETA = {"temperature1": "25", "resistance1": "100000", "beta": "3950"}
OTHER = {"temperature1": "25", "resistance1": "110000", "beta": "4100"}


def selection_inputs(source, curves, **choices):
    board = copy.deepcopy(curves) if source == "board" else {}
    user = _user(**choices)
    if source != "board":
        user["_profile_parsed"] = copy.deepcopy(curves)
    if source == "resume":
        user = json.loads(json.dumps(persistable_wizard_data(user)))
    return board, user


@pytest.mark.parametrize("source", ["board", "profile", "resume"])
@pytest.mark.parametrize("name, expected", [("Curve", BETA), ("curve", OTHER)])
def test_exact_factory_selects_only_its_curve(source, name, expected):
    board, user = selection_inputs(source, {
        "thermistor Curve": BETA, "thermistor curve": OTHER,
    }, hotend_thermistor=name)
    before = copy.deepcopy((board, user))
    selected = selected_custom_thermistors(board, user)
    assert selected == {"thermistor " + name: expected}
    assert (board, user) == before
    selected["thermistor " + name]["beta"] = "9999"
    assert (board, user) == before


@pytest.mark.parametrize("source", ["board", "profile", "resume"])
def test_two_selected_names_remain_independent(source):
    curves = {"thermistor Curve": BETA, "thermistor curve": OTHER}
    board, user = selection_inputs(source, curves,
                                   hotend_thermistor="Curve", bed_thermistor="curve")
    assert selected_custom_thermistors(board, user) == curves


@pytest.mark.parametrize("swapped", [False, True])
def test_distinct_factories_across_sources_are_not_conflicts(swapped):
    first, second = {"thermistor Curve": BETA}, {"thermistor curve": OTHER}
    if swapped:
        first, second = second, first
    user = _user(hotend_thermistor="Curve", bed_thermistor="curve", _profile_parsed=second)
    assert selected_custom_thermistors(first, user) == {
        "thermistor Curve": BETA, "thermistor curve": OTHER,
    }


@pytest.mark.parametrize("swapped", [False, True])
def test_exact_factory_takes_priority_over_folded_legacy_candidate(swapped):
    # The mapping has no origin marker. Exact identity wins globally; this
    # does not certify whether the other mapping was folded historically.
    first, second = {"thermistor Curve": BETA}, {"thermistor curve": OTHER}
    if swapped:
        first, second = second, first
    assert selected_custom_thermistors(first, _user(
        hotend_thermistor="Curve", _profile_parsed=second)) == {"thermistor Curve": BETA}


@pytest.mark.parametrize("value", [None, [], {"broken": "value"}])
def test_invalid_case_distinct_unselected_curve_is_ignored(value):
    assert selected_custom_thermistors({
        "thermistor Curve": BETA, "thermistor curve": value,
    }, _user(hotend_thermistor="Curve")) == {"thermistor Curve": BETA}


@pytest.mark.parametrize("value", [None, [], {"beta": "0"}])
def test_invalid_exact_curve_does_not_fall_back_to_valid_other_case(value):
    with pytest.raises(GenerationError):
        selected_custom_thermistors({"thermistor Curve": value, "thermistor curve": BETA},
                                   _user(hotend_thermistor="Curve"))


@pytest.mark.parametrize("source", ["board", "profile", "resume"])
def test_legacy_folded_name_remains_supported_without_exact_candidate(source):
    board, user = selection_inputs(source, {"thermistor curve": BETA},
                                   hotend_thermistor="Curve")
    assert selected_custom_thermistors(board, user) == {"thermistor Curve": BETA}


@pytest.mark.parametrize("name", ["Curve", "curve"])
def test_identical_candidates_from_two_sources_emit_once(name):
    curve = {"thermistor " + name: BETA}
    assert selected_custom_thermistors(curve, _user(
        hotend_thermistor="Curve", bed_thermistor="Curve", _profile_parsed=curve,
    )) == {"thermistor Curve": BETA}


@pytest.mark.parametrize("name", ["Curve", "curve"])
def test_conflicting_candidates_in_selected_identity_group_are_rejected(name):
    with pytest.raises(GenerationError, match="conflicting custom thermistor"):
        selected_custom_thermistors({"thermistor " + name: BETA}, _user(
            hotend_thermistor="Curve", _profile_parsed={"thermistor " + name: OTHER},
        ))


@pytest.mark.parametrize("header", ["thermistor  My  Curve", "thermistor\tMy\tCurve"])
def test_factory_whitespace_normalization_matches_klipper(header):
    assert selected_custom_thermistors({header: BETA}, _user(
        hotend_thermistor="My Curve")) == {"thermistor My Curve": BETA}


def test_same_normalized_factory_with_conflicting_definitions_is_rejected():
    with pytest.raises(GenerationError, match="conflicting custom thermistor"):
        selected_custom_thermistors({"thermistor My Curve": BETA, "thermistor  My\tCurve": OTHER},
                                   _user(hotend_thermistor="My Curve"))


def test_builtin_or_unavailable_name_does_not_import_unselected_curve():
    assert selected_custom_thermistors({"thermistor Unselected": BETA}, _user()) == {}
