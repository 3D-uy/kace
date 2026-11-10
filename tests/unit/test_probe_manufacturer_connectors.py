"""Supplemental connector evidence never replaces effective pin allocation."""
import copy
import os
from unittest.mock import patch

import pytest

from core.loader import load_boards_yaml
from core.scraper import parse_config
from core.translations import get_lang, set_lang
from core.wizard.steps import sensors
from core.wizard.runner import _BACK
from tests.unit.test_tmc_socket import FIXTURES, SKR
from tests.unit.test_firmware_pin_reservations import artifact


def context(mcu="lpc1769"):
    board = parse_config((FIXTURES / SKR).read_text(encoding="utf-8"), SKR, keep_comments=True)
    return dict(board=SKR, board_parsed=board, _board_parsed_for=SKR, mcu_type=mcu,
                driver_type="TMC2209", driver_mode="UART", z_motors="1")


def candidates(user):
    with patch.object(sensors, "_get_parsed", return_value=user["board_parsed"]):
        return sensors._get_probe_input_candidates(user)


@pytest.mark.parametrize("mcu", ["lpc1768", "lpc1769"])
def test_exact_skr_variants_offer_probe_connector_and_z_stop_without_invented_signal_flags(mcu):
    user = context(mcu)
    before = copy.deepcopy(user)
    choices = candidates(user)
    assert [item["pin"] for item in choices] == ["P0.10", "P1.27"]
    assert choices[0]["source"] == "manufacturer"
    assert choices[1]["source"] == "z_endstop"
    assert all(not item["pullup"] and not item["inverted"] for item in choices)
    assert "b238aa402753e81d551b7d34a181a262a138ae9e" in choices[0]["source_url"]
    assert user == before


@pytest.mark.parametrize("board,mcu", [
    ("generic-bigtreetech-skr-v1.3.cfg", "lpc1768"),
    ("custom-skr-v1.4.cfg", "lpc1769"),
    (SKR, ""), (SKR, "lpc176x"), (SKR, "stm32f103"),
])
def test_family_name_or_unknown_variant_cannot_authorize_connector(board, mcu):
    user = context(mcu)
    user.update(board=board, _board_parsed_for=board)
    assert not any(item["source"] == "manufacturer" for item in candidates(user))


@pytest.mark.parametrize("section,fields", [
    ("output_pin accessory", {"pin": "P0.10"}),
    ("stepper_z1", {"step_pin": "P0.10"}),
    ("output_pin accessory", {"pin": "!PROBE_ALIAS"}),
    ("mpu9250", {"i2c_software_sda_pin": "P0.10", "i2c_software_scl_pin": "P0.11"}),
    ("mpu9250", {"i2c_bus": "i2c2"}),
    ("temperature_sensor ambient", {"sensor_type": "BME280", "i2c_bus": "i2c2"}),
])
def test_known_consumer_or_selected_i2c2_prevents_connector_suggestion(section, fields):
    user = context()
    user["board_parsed"][section] = fields
    user["board_parsed"]["board_pins extra"] = {"aliases": "PROBE_ALIAS=P0.10"}
    assert "P0.10" not in [item["pin"] for item in candidates(user)]


@pytest.mark.parametrize("options", [{"i2c_bus": "i2c1"}, {"i2c_bus": "i2c2", "i2c_mcu": "toolhead"}])
def test_other_bus_or_other_mcu_does_not_hide_primary_probe(options):
    user = context()
    user["board_parsed"]["mpu9250"] = options
    assert "P0.10" in [item["pin"] for item in candidates(user)]


def test_bound_firmware_reservation_filters_manufacturer_connector(tmp_path):
    user = context()
    user["firmware_artifact"] = artifact(tmp_path, {"RESERVE_PINS_test": "P0.10"})
    assert "P0.10" not in [item["pin"] for item in candidates(user)]
    assert "P1.27" in [item["pin"] for item in candidates(user)]


def test_declared_probe_keeps_its_signal_settings_without_duplicate_manufacturer_choice():
    user = context()
    user["board_parsed"]["probe"] = {"pin": "^!P0.10"}
    choices = candidates(user)
    assert [item["pin"] for item in choices].count("P0.10") == 1
    assert choices[0]["source"] == "probe"
    assert choices[0]["pullup"] and choices[0]["inverted"]


def test_declared_probe_on_connector_does_not_bypass_selected_i2c2_conflict():
    user = context()
    user["board_parsed"]["probe"] = {"pin": "^P0.10"}
    user["board_parsed"]["mpu9250"] = {"i2c_bus": "i2c2"}
    assert "P0.10" not in [item["pin"] for item in candidates(user)]


@pytest.mark.parametrize("new_consumer", [
    {"output_pin accessory": {"pin": "P0.10"}},
    {"mpu9250": {"i2c_bus": "i2c2"}},
])
def test_allocation_changes_during_menu_cannot_commit_stale_connector(new_consumer):
    user = context()
    user.update(custom_probe_pin="P1.27", custom_probe_pullup=True)

    def select(*args, **kwargs):
        assert "P0.10" in [choice["value"] for choice in kwargs["choices"]]
        user["board_parsed"].update(new_consumer)
        return "P0.10"

    with patch.object(sensors, "_get_parsed", return_value=user["board_parsed"]), patch.object(
            sensors, "autocomplete_select", side_effect=select):
        assert sensors._step_custom_probe_pin(user) == "__retry__"
    assert user["custom_probe_pin"] == "P1.27"
    assert user["custom_probe_pullup"] is True


def test_connector_cannot_be_redirected_through_a_physical_pin_alias():
    user = context()
    user["board_parsed"]["board_pins override"] = {"aliases": "P0.10=P0.9"}
    assert not any(item["source"] == "manufacturer" for item in candidates(user))


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
@pytest.mark.parametrize("columns", [40, 80])
def test_selection_attributes_source_and_back_preserves_existing_input(language, columns, capsys):
    original = get_lang()
    try:
        set_lang(language)
        user = context()
        user.update(custom_probe_pin="P1.27", custom_probe_pullup=True)
        before = copy.deepcopy(user)
        with patch.object(sensors, "_get_parsed", return_value=user["board_parsed"]), patch.object(
                sensors, "autocomplete_select", return_value=_BACK), patch(
                "core.menu.shutil.get_terminal_size", return_value=os.terminal_size((columns, 24))):
            assert sensors._step_custom_probe_pin(user) == _BACK
        output = capsys.readouterr().out
        assert "BIGTREETECH" in output and "Klipper" in output
        assert "https://" not in output
        assert all(len(line) <= columns for line in output.splitlines())
        assert "wizard.probe_signal." not in output
        provenance = next(item for item in candidates(user) if item["source"] == "manufacturer")
        assert "github.com/bigtreetech/" in provenance["source_url"]
        assert user == before
    finally:
        set_lang(original)


def test_supplemental_sources_are_pinned_and_separate_from_klipper_example():
    entry = load_boards_yaml()["probe_connector_mappings"][SKR]["connectors"][0]
    for key in ("manufacturer_source", "turbo_source", "schematic_source"):
        assert entry[key].startswith("https://github.com/bigtreetech/BIGTREETECH-SKR-V1.3/blob/b238aa402753e81d551b7d34a181a262a138ae9e/")
    assert entry["bus_source"].startswith("https://github.com/Klipper3d/klipper/blob/fe4eb8650bd7de4c2100a14eaf09b0965c430e29/")
    official = (FIXTURES / SKR).read_text(encoding="utf-8")
    assert "P0.10" not in official
    assert "endstop_pin: !P1.27" in official
