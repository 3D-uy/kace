"""Automatic BLTouch suggestions require a specific upstream board revision."""
from pathlib import Path
import re

import pytest

from core.scraper import get_bltouch_pins_for_board, parse_config

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/bltouch-catalog"
SUPPORTED = {
    "generic-bigtreetech-octopus-v1.1.cfg": ("PB7", "PB6"),
    "generic-bigtreetech-octopus-pro-v1.0.cfg": ("PB7", "PB6"),
    "generic-bigtreetech-octopus-pro-v1.1.cfg": ("PB7", "PB6"),
    "generic-bigtreetech-octopus-max-ez.cfg": ("^PB15", "PB14"),
}


@pytest.mark.parametrize("name,pair", SUPPORTED.items())
def test_exact_catalog_pair_matches_official_bltouch_example(name, pair):
    text = (FIXTURES / name).read_text(encoding="utf-8")
    # Independent extraction of the complete official commented example.
    block = re.search(r"(?m)^#\[bltouch\]\n((?:#[^\n]*\n)+)", text).group(1)
    expected = {key: re.search(rf"(?m)^#{key}:\s*(\S+)", block).group(1)
                for key in ("sensor_pin", "control_pin")}
    assert tuple(expected.values()) == pair
    assert get_bltouch_pins_for_board(name) == expected
    assert parse_config(text, name)["bltouch"] == expected


@pytest.mark.parametrize("name", [
    "generic-bigtreetech-skr-v1.4.cfg", "generic-bigtreetech-skr-v1.3.cfg",
    "generic-bigtreetech-skr-mini-e3-v2.0.cfg", "generic-bigtreetech-skr-mini-e3-v3.0.cfg",
    "generic-creality-v4.2.2.cfg", "generic-creality-v4.2.7.cfg",
    "generic-mks-robin-nano-v1.cfg", "generic-mks-robin-nano-v2.cfg",
    "generic-mks-robin-nano-v3.cfg", "generic-bigtreetech-skr-2.cfg",
    "generic-fysetc-spider.cfg", "generic-mks-sgen-l.cfg", "generic-mks-gen-l.cfg",
    "generic-bigtreetech-octopus-v2.0.cfg", "generic-bigtreetech-octopus-pro-v1.2.cfg",
    "copy-generic-bigtreetech-octopus-max-ez.cfg", "octopus",
])
def test_unverified_or_different_revision_requires_manual_mapping(name):
    assert get_bltouch_pins_for_board(name) == {}
    assert not parse_config("", name)["bltouch"]


@pytest.mark.parametrize("role,pin", [("sensor_pin", "PB7"), ("control_pin", "PB6")])
def test_conflicting_active_function_suppresses_entire_fallback_pair(role, pin):
    text = f"[extruder]\nheater_pin: !{pin}\n"
    assert not parse_config(text, "generic-bigtreetech-octopus-v1.1.cfg")["bltouch"]


def test_sensor_can_reuse_only_the_replaced_z_endstop():
    name = "generic-bigtreetech-octopus-v1.1.cfg"
    assert parse_config("[stepper_z]\nendstop_pin: ^PB7\n", name)["bltouch"]
    assert not parse_config("[stepper_y]\nendstop_pin: ^PB7\n", name)["bltouch"]
    assert not parse_config("[stepper_z]\nstep_pin: PB7\n", name)["bltouch"]
    assert not parse_config("[stepper_z]\nendstop_pin: PB6\n", name)["bltouch"]


def test_alias_collision_suppresses_fallback():
    text = "[board_pins]\naliases: HEATER=PB6\n[heater_bed]\nheater_pin: HEATER\n"
    assert not parse_config(text, "generic-bigtreetech-octopus-v1.1.cfg")["bltouch"]


def test_partial_user_mapping_is_not_completed_from_a_different_wiring_example():
    assert parse_config("[bltouch]\nsensor_pin: ^PA0\n",
                        "generic-bigtreetech-octopus-v1.1.cfg")["bltouch"] == {"sensor_pin": "^PA0"}


def test_explicit_source_mapping_is_preserved():
    assert parse_config("[bltouch]\nsensor_pin: ^PA0\ncontrol_pin: PA1\n",
                        "generic-bigtreetech-octopus-v1.1.cfg")["bltouch"] == {
                            "sensor_pin": "^PA0", "control_pin": "PA1"}


@pytest.mark.parametrize("name", [
    "generic-bigtreetech-skr-v1.3.cfg", "generic-bigtreetech-skr-2.cfg",
    "generic-mks-robin-nano-v3.cfg",
])
def test_removed_unsafe_mapping_cannot_generate_without_manual_pins(name, tmp_path):
    from core.exceptions import GenerationError
    from core.generator import generate_config
    from tests.unit.test_generator import _user

    parsed = parse_config((FIXTURES / name).read_text(encoding="utf-8"), name)
    output = tmp_path / "printer.cfg"
    with pytest.raises(GenerationError, match="unresolved TODO pins"):
        generate_config(parsed, _user(probe="BLTouch", x_size="200", y_size="200", z_size="200"),
                        output_path=str(output), verbose=False)
    assert not output.exists()


def test_secondary_mcu_allocation_does_not_suppress_primary_example():
    assert parse_config("[output_pin led]\npin: toolhead:PB6\n",
                        "generic-bigtreetech-octopus-v1.1.cfg")["bltouch"]["control_pin"] == "PB6"


def test_reserved_alias_target_suppresses_example():
    assert not parse_config("[board_pins]\naliases: PB6=<reserved>\n",
                            "generic-bigtreetech-octopus-v1.1.cfg")["bltouch"]
