"""Effective autosave merging preserves exact custom sensor section names."""
import pytest

from core.managed_config import ManagedConfigPlan, _section_options, effective_hardware_text
from core.pin_validator import _read_pin_config
from core.scraper import parse_config


CURVES = {
    "thermistor": {"temperature1": "25", "resistance1": "100000", "beta": "3950"},
    "adc_temperature": {"temperature1": "25", "resistance1": "100000",
                        "temperature2": "150", "resistance2": "1641.9"},
}
SAVE_HEADER = (
    "\n#*# <---------------------- SAVE_CONFIG ---------------------->\n"
    "#*# DO NOT EDIT THIS BLOCK OR BELOW. The contents are auto-generated.\n#*#\n"
)


def block(section, fields):
    return f"\n[{section}]\n" + "".join(f"{key}: {value}\n" for key, value in fields.items())


def saved(section, fields):
    return SAVE_HEADER + "".join("#*# " + line + "\n" for line in block(section, fields).splitlines())


def effective(active, autosave, source="root"):
    files = {"printer.cfg": (active + autosave).encode()}
    if source == "include":
        files = {"printer.cfg": ("[include user.cfg]\n" + autosave).encode(),
                 "user.cfg": b"[include nested.cfg]\n", "nested.cfg": active.encode()}
    plan = ManagedConfigPlan(artifacts=(), source_files=tuple(files.items()))
    return _read_pin_config(effective_hardware_text(plan))[0]


@pytest.mark.parametrize("kind", CURVES)
@pytest.mark.parametrize("name", ["Curve", "curve"])
@pytest.mark.parametrize("source", ["root", "include"])
@pytest.mark.parametrize("entire_definition", [False, True])
def test_saved_fields_preserve_exact_section_identity(kind, name, source, entire_definition):
    section = f"{kind} {name}"
    fields = CURVES[kind]
    active_fields = {} if entire_definition else {k: v for k, v in fields.items() if k != "resistance1"}
    saved_fields = fields if entire_definition else {"resistance1": fields["resistance1"]}
    # A complete definition in SAVE_CONFIG is tested as merge data only;
    # whether it precedes a consumer remains a separate loading contract.
    active = "" if entire_definition else block(section, active_fields)
    assert effective(active, saved(section, saved_fields), source) == {section: fields}


@pytest.mark.parametrize("kind", CURVES)
@pytest.mark.parametrize("source", ["root", "include"])
def test_active_option_wins_only_for_the_same_exact_section(kind, source):
    section = f"{kind} Curve"
    fields = CURVES[kind]
    actual = effective(block(section, fields), saved(section, {"RESISTANCE1": "99999"}), source)
    assert actual == {section: fields}


@pytest.mark.parametrize("kind", CURVES)
@pytest.mark.parametrize("source", ["root", "include"])
def test_case_distinct_active_and_saved_sections_do_not_shadow_each_other(kind, source):
    lower, upper = f"{kind} curve", f"{kind} Curve"
    first = CURVES[kind]
    second = {**first, "resistance1": "110000"}
    actual = effective(block(lower, first), saved(upper, second), source)
    assert actual == {lower: first, upper: second}


@pytest.mark.parametrize("kind", CURVES)
def test_two_active_case_distinct_sections_receive_only_their_own_saved_field(kind):
    lower, upper = f"{kind} curve", f"{kind} Curve"
    first = CURVES[kind]
    partial = {k: v for k, v in first.items() if k != "resistance1"}
    actual = effective(block(lower, first) + block(upper, partial), saved(upper, {"resistance1": "110000"}))
    assert actual == {lower: first, upper: {**first, "resistance1": "110000"}}


@pytest.mark.parametrize("kind", CURVES)
@pytest.mark.parametrize("parse", [parse_config, _section_options], ids=["source", "planning"])
def test_source_and_planning_parsers_keep_distinct_curve_names(kind, parse):
    lower, upper = f"{kind} curve", f"{kind} Curve"
    first = CURVES[kind]
    second = {**first, "resistance1": "110000"}
    actual = parse(block(lower, first) + block(upper, second))
    assert actual[lower] == first
    assert actual[upper] == second
