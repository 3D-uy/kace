"""Selected curve identity survives generation, provenance and managed review."""
import copy
import json

import pytest

from core.configuration_review import validate_configuration_plan
from core.exceptions import GenerationError
from core.generator import generate_config
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.scraper import parse_config
from tests.unit.test_generator import _parsed, _user
from tests.unit.test_thermistor_selection import BETA, OTHER, selection_inputs


def generate_and_check(tmp_path, board, user, expected):
    before = copy.deepcopy((board, user))
    path = tmp_path / "printer.cfg"
    result = generate_config(board, user, output_path=str(path), verbose=False)
    text = result["content"]
    assert (board, user) == before
    assert path.read_text(encoding="utf-8") == text
    parsed = parse_config(text)
    assert {k: v for k, v in parsed.items() if k.startswith("thermistor ")} == expected
    assert parsed["extruder"]["sensor_type"] == user["hotend_thermistor"]
    assert parsed["heater_bed"]["sensor_type"] == user["bed_thermistor"]
    for section in expected:
        assert text.index("[" + section + "]") < text.index("[extruder]")
    provenance = json.loads(path.with_name("printer.cfg.provenance.json").read_text(encoding="utf-8"))
    assert provenance["sources"]["custom_thermistors"] == expected
    plan = build_managed_config_plan(text.encode(), None, {"printer.cfg": text.encode()})
    review = validate_configuration_plan(plan)
    assert review.valid, review.errors
    effective = parse_config(effective_hardware_text(plan))
    assert {k: v for k, v in effective.items() if k.startswith("thermistor ")} == expected
    remote = {artifact.remote_name: artifact.content for artifact in plan.artifacts}
    assert not build_managed_config_plan(text.encode(), None, remote).changed_artifacts
    return text


@pytest.mark.parametrize("source", ["board", "profile", "resume"])
def test_two_case_distinct_heater_curves_keep_values_and_provenance(tmp_path, source):
    curves = {"thermistor Curve": BETA, "thermistor curve": OTHER}
    definitions, user = selection_inputs(source, curves,
                                         hotend_thermistor="Curve", bed_thermistor="curve")
    generate_and_check(tmp_path, {**_parsed(), **definitions}, user, curves)


@pytest.mark.parametrize("source", ["board", "profile", "resume"])
@pytest.mark.parametrize("name, expected", [("Curve", BETA), ("curve", OTHER)])
def test_only_referenced_case_is_generated(tmp_path, source, name, expected):
    definitions, user = selection_inputs(source, {
        "thermistor Curve": BETA, "thermistor curve": OTHER,
    }, hotend_thermistor=name)
    generate_and_check(tmp_path, {**_parsed(), **definitions}, user, {"thermistor " + name: expected})


@pytest.mark.parametrize("header", ["thermistor  My  Curve", "thermistor\tMy\tCurve"])
def test_spaced_factory_header_generates_the_referenced_name(tmp_path, header):
    generate_and_check(tmp_path, {**_parsed(), header: BETA},
                       _user(hotend_thermistor="My Curve"), {"thermistor My Curve": BETA})


@pytest.mark.parametrize("swapped", [False, True])
def test_source_order_does_not_override_exact_selection(tmp_path, swapped):
    first, second = {"thermistor Curve": BETA}, {"thermistor curve": OTHER}
    if swapped:
        first, second = second, first
    generate_and_check(tmp_path, {**_parsed(), **first}, _user(
        hotend_thermistor="Curve", bed_thermistor="curve", _profile_parsed=second,
    ), {"thermistor Curve": BETA, "thermistor curve": OTHER})


def test_invalid_unselected_curve_cannot_block_exact_selection(tmp_path):
    generate_and_check(tmp_path, {**_parsed(), "thermistor Curve": BETA,
                                 "thermistor curve": None},
                       _user(hotend_thermistor="Curve"), {"thermistor Curve": BETA})


@pytest.mark.parametrize("source", ["board", "profile", "resume"])
def test_legacy_folded_selection_keeps_generated_identity(tmp_path, source):
    definitions, user = selection_inputs(source, {"thermistor curve": BETA},
                                         hotend_thermistor="Curve")
    generate_and_check(tmp_path, {**_parsed(), **definitions}, user, {"thermistor Curve": BETA})


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("kind", ["exact-conflict", "legacy-conflict", "invalid-exact"])
def test_selected_definition_error_precedes_cfg_and_provenance_writes(tmp_path, existing, kind):
    path = tmp_path / "printer.cfg"
    sidecar = tmp_path / "printer.cfg.provenance.json"
    if existing:
        path.write_bytes(b"existing cfg\n")
        sidecar.write_bytes(b"existing provenance\n")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    name = "curve" if kind == "legacy-conflict" else "Curve"
    board = {**_parsed(), "thermistor " + name: BETA}
    user = _user(hotend_thermistor="Curve")
    if kind == "invalid-exact":
        board["thermistor Curve"] = {**BETA, "beta": "0"}
        board["thermistor curve"] = BETA
        reason = "beta"
    else:
        user["_profile_parsed"] = {"thermistor " + name: OTHER}
        reason = "conflicting custom thermistor"
    original = copy.deepcopy((board, user))
    with pytest.raises(GenerationError, match=reason):
        generate_config(board, user, output_path=str(path), verbose=False)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before
    assert (board, user) == original
