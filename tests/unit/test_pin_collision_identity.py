"""Probe inputs own a pin in one MCU, with aliases resolved in that MCU."""
from unittest.mock import patch

import pytest

from core.wizard.steps.sensors import _get_unused_pins, make_pin_validator_with_collision_check


def validator(sections, mcu_type="rp2040"):
    with patch("core.wizard.steps.sensors._get_parsed", return_value=sections):
        return make_pin_validator_with_collision_check({"mcu_type": mcu_type})


@pytest.mark.parametrize("used,candidate,available", [
    ("gpio5", "toolhead:gpio5", True),
    ("toolhead:gpio5", "gpio5", True),
    ("toolhead:gpio5", "other:gpio5", True),
    ("toolhead:gpio5", "Toolhead:gpio5", True),
    ("gpio5", "gpio5", False),
    ("gpio5", "mcu:gpio5", False),
    ("mcu:gpio5", "gpio5", False),
    ("!toolhead:gpio5", "^toolhead:gpio5", False),
    ("!gpio5", "~!mcu:gpio5", False),
])
def test_mcu_identity_and_modifiers(used, candidate, available):
    check = validator({"fan": {"pin": used}})
    result = check(candidate)
    assert (result is True) == available
    if not available:
        assert candidate in result
        assert "fan (pin)" in result


@pytest.mark.parametrize("used,candidate,available", [
    ("gpio5", "HEADER", False),
    ("HEADER", "gpio5", False),
    ("HEADER", "CHAIN", False),
    ("toolhead:HEADER", "toolhead:gpio6", False),
    ("toolhead:CHAIN", "^toolhead:HEADER", False),
    ("HEADER", "toolhead:HEADER", True),
    ("toolhead:HEADER", "HEADER", True),
])
def test_named_alias_groups_and_chains_are_mcu_local(used, candidate, available):
    check = validator({
        "board_pins main": {"aliases": "HEADER=gpio5", "aliases_extra": "CHAIN=HEADER"},
        "board_pins tool": {"mcu": "toolhead", "aliases": "HEADER=gpio6, CHAIN=HEADER"},
        "fan": {"pin": used},
    })
    assert (check(candidate) is True) == available


@pytest.mark.parametrize("options", [
    {"aliases": "HEADER=gpio5"},
    {"aliases": "FIRST=gpio6", "aliases_extra": "HEADER=gpio5"},
])
def test_alias_definition_is_not_an_allocation(options):
    assert validator({"board_pins main": options})("HEADER") is True


@pytest.mark.parametrize("options", [
    {"aliases": "A=B,B=A"}, {"aliases": "A=gpio5,A=gpio6"},
    {"aliases": "A=!gpio5"},
])
def test_invalid_alias_table_fails_closed_but_navigation_still_works(options):
    check = validator({"board_pins main": options})
    assert check("gpio2") is not True
    assert check("<") is True


@pytest.mark.parametrize("token", ["GND", "CHAIN", "toolhead:GND"])
def test_reserved_alias_cannot_be_selected(token):
    check = validator({"board_pins headers": {
        "mcu": "mcu,toolhead", "aliases": "GND=<GND>,CHAIN=GND"}})
    assert "reserved" in check(token)


def test_non_pin_metadata_does_not_allocate_gpio():
    check = validator({"gcode_macro TEST": {"description": "gpio5", "gcode": "gpio6"},
                       "duplicate_pin_override": {"pins": "gpio7"}})
    assert all(check(pin) is True for pin in ("gpio5", "gpio6", "gpio7"))


@pytest.mark.parametrize("key", ["pins", "select_pins", "encoder_pins"])
def test_pin_lists_allocate_each_identity(key):
    check = validator({"peripheral": {key: "gpio5, !toolhead:gpio6"}})
    assert check("mcu:gpio5") is not True
    assert check("toolhead:gpio6") is not True
    assert check("gpio6") is True


def test_shared_enable_allocations_do_not_invalidate_unrelated_probe():
    check = validator({"stepper_x": {"enable_pin": "!gpio5"},
                       "stepper_y": {"enable_pin": "!gpio5"}})
    assert check("gpio6") is True
    # The new probe is not another stepper-enable consumer.
    assert check("gpio5") is not True


@pytest.mark.parametrize("token", ["toolhead:!gpio5", "!!gpio5", "!^gpio5", "^~gpio5"])
def test_modifier_placement_matches_klipper_input_grammar(token):
    assert validator({})(token) is not True


@pytest.mark.parametrize("token", ["^!toolhead:gpio5", "~gpio6", "!gpio5"])
def test_legal_input_modifiers(token):
    assert validator({})(token) is True


def test_explicit_primary_mcu_and_alias_do_not_bypass_architecture_check():
    check = validator({"board_pins": {"aliases": "WRONG=PA0"}})
    assert check("mcu:PA0") is not True
    assert check("WRONG") is not True
    # A secondary MCU may have another architecture; it is not guessed here.
    assert check("toolhead:PA0") is True


@pytest.mark.parametrize("used,available", [
    ("toolhead:gpio5", True), ("gpio5", False), ("mcu:gpio5", False),
])
def test_suggestions_preserve_primary_ownership_and_case(used, available):
    with patch("core.wizard.steps.sensors._get_parsed", return_value={
        "fan": {"pin": used},
        "board_pins": {"aliases": "INPUT=gpio5,SECOND=gpio6"},
    }):
        candidates = _get_unused_pins({"mcu_type": "rp2040"})
    assert (("INPUT", "gpio5") in candidates) == available
    assert ("SECOND", "gpio6") in candidates


def test_suggestions_resolve_named_alias_groups_without_cross_mcu_deduplication():
    sections = {
        "board_pins main": {"aliases": "HEADER=gpio5,OTHER=HEADER,GND=<GND>,RES=GND"},
        "board_pins tool": {"mcu": "toolhead", "aliases": "HEADER=gpio5",
                            "aliases_extra": "SECOND=gpio6"},
        "fan": {"pin": "^toolhead:SECOND"},
        "gcode_macro TEST": {"description": "gpio7"},
    }
    with patch("core.wizard.steps.sensors._get_parsed", return_value=sections):
        candidates = _get_unused_pins({"mcu_type": "rp2040"})
    assert ("HEADER", "gpio5") in candidates
    assert ("toolhead:HEADER", "toolhead:gpio5") in candidates
    # Metadata does not declare a board connector; no raw GPIO is invented.
    assert ("gpio7", "gpio7") not in candidates
    assert sum(pin == "gpio5" for _, pin in candidates) == 1
    assert all(pin not in ("<GND>", "toolhead:gpio6") for _, pin in candidates)


def test_invalid_aliases_produce_no_suggestions():
    with patch("core.wizard.steps.sensors._get_parsed", return_value={
        "board_pins": {"aliases": "A=B,B=A"}
    }):
        assert _get_unused_pins({"mcu_type": "rp2040"}) == []


def test_raw_config_path_resolves_namespaced_aliases():
    check = make_pin_validator_with_collision_check({
        "board": "custom", "printer_profile": "custom", "profile_loaded": True,
        "mcu_type": "rp2040", "raw_config": (
            "[board_pins tool]\nmcu: toolhead\naliases: HEADER=gpio5\n"
            "[fan]\npin: !toolhead:HEADER\n")})
    assert check("gpio5") is True
    assert check("toolhead:gpio5") is not True
