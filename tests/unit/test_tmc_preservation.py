"""Model-specific electrical contracts; loader coverage lives in regression validation."""
import configparser
from copy import deepcopy

import pytest

from core.exceptions import GenerationError, WizardExit
from core.generator import generate_config
from core.profile_values import resolve_generation_values, resolve_tmc_sections
from core.wizard.steps.hardware import _apply_z_tmc_mappings
from tests.unit.test_generator import _parsed, _user


def read_config(text):
    cfg = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=("#",))
    cfg.read_string(text)
    return cfg


@pytest.mark.parametrize("model,mode,options", [
    ("TMC2209", "UART", {"uart_pin": "PC11", "tx_pin": "PC10", "uart_address": "2", "sense_resistor": "0.150", "diag_pin": "^PC0", "driver_SGTHRS": "255", "interpolate": "False"}),
    ("TMC2208", "UART", {"uart_pin": "PC11", "select_pins": "!PD0, PD4", "sense_resistor": "0.150", "driver_PWM_OFS": "30"}),
    ("TMC2225", "UART", {"uart_pin": "PC11", "sense_resistor": "0.150"}),
    ("TMC2130", "SPI", {"cs_pin": "PD0", "spi_bus": "spi1", "spi_speed": "1000000", "diag1_pin": "^PC0", "driver_SGT": "-10", "chain_length": "2", "chain_position": "1", "sense_resistor": "0.150"}),
    ("TMC5160", "SPI", {"cs_pin": "PD0", "spi_software_sclk_pin": "PB3", "spi_software_mosi_pin": "PB5", "spi_software_miso_pin": "PB4", "sense_resistor": "0.075", "driver_TPFD": "4"}),
])
def test_preserves_electrical_options_per_selected_model(tmp_path, model, mode, options):
    parsed = _parsed()
    canonical = "tmc2208" if model == "TMC2225" else model.lower()
    section = canonical + " stepper_x"
    parsed[section] = {"run_current": "0.580", **options}
    before = deepcopy(parsed)
    out = tmp_path / "printer.cfg"
    generate_config(parsed, _user(driver_type=model, driver_mode=mode), output_path=str(out))
    generated = read_config(out.read_text(encoding="utf-8"))
    for key, value in options.items():
        assert generated[section][key] == value
    assert parsed == before


def test_all_seven_targets_keep_addresses_and_resistors(tmp_path):
    parsed = _parsed()
    targets = ("stepper_x", "stepper_y", "stepper_z", "extruder", "stepper_z1", "stepper_z2", "stepper_z3")
    for index, target in enumerate(targets):
        if target not in parsed:
            parsed[target] = dict(parsed["stepper_z"], step_pin=f"PF{index}", dir_pin=f"PG{index}", enable_pin=f"PH{index}")
        parsed[f"tmc2209 {target}"] = {"run_current": "0.580", "uart_pin": "PC11" if index < 4 else "PC12", "uart_address": str(index % 4), "sense_resistor": "0.150"}
    out = tmp_path / "printer.cfg"
    generate_config(parsed, _user(driver_type="TMC2209", driver_mode="UART", z_motors="4"), output_path=str(out))
    generated = read_config(out.read_text(encoding="utf-8"))
    for index, target in enumerate(targets):
        assert generated[f"tmc2209 {target}"]["uart_address"] == str(index % 4)
        assert generated[f"tmc2209 {target}"]["sense_resistor"] == "0.150"


@pytest.mark.parametrize("options,error", [
    ({"uart_pin": "PC11", "uart_address": "4"}, "out of range"),
    ({"uart_pin": "PC11", "uart_address": "NaN"}, "invalid uart_address"),
    ({"uart_pin": "PC11", "driver_SGT": "1"}, "unsupported options"),
    ({"uart_pin": "PC11", "cs_pin": "PA1"}, "unsupported options"),
    ({"uart_pin": ""}, "missing uart_pin"),
    ({"sense_resistor": "0.150"}, "missing uart_pin"),
])
def test_invalid_options_fail_before_writing(tmp_path, options, error):
    parsed = _parsed()
    parsed["tmc2209 stepper_x"] = {"run_current": "0.580", **options}
    out = tmp_path / "printer.cfg"
    with pytest.raises(GenerationError, match=error):
        generate_config(parsed, _user(driver_type="TMC2209", driver_mode="UART"), output_path=str(out))
    assert not out.exists()


@pytest.mark.parametrize("address", [None, "0"])
def test_shared_uart_rejects_implicit_or_explicit_duplicate_address(address):
    options = {"uart_pin": "PC11", "tx_pin": "PC10"}
    if address is not None:
        options["uart_address"] = address
    parsed = {f"tmc2209 stepper_{axis}": options.copy() for axis in ("x", "y")}
    with pytest.raises(GenerationError, match="shared UART"):
        resolve_tmc_sections(parsed, _user(driver_type="TMC2209", driver_mode="UART"))
    parsed["tmc2209 stepper_y"]["select_pins"] = "!PD0"
    parsed["tmc2209 stepper_x"]["select_pins"] = "PD0"
    assert len(resolve_tmc_sections(parsed, _user(driver_type="TMC2209", driver_mode="UART"))) == 2


def test_selected_model_never_uses_foreign_pins_or_currents():
    parsed = {"tmc2209 stepper_x": {"uart_pin": "PC11", "run_current": "0.8"}}
    user = {"driver_type": "TMC2130", "driver_mode": "SPI"}
    with pytest.raises(GenerationError, match="incompatible source driver"):
        resolve_tmc_sections(parsed, user)
    parsed["tmc2130 stepper_x"] = {"cs_pin": "PD0", "run_current": "0.5"}
    sections = resolve_tmc_sections(parsed, user)
    assert sections == {"tmc2130 stepper_x": parsed["tmc2130 stepper_x"]}
    values, provenance = resolve_generation_values(parsed, user)
    assert values["run_current_x"] == "0.5"
    assert provenance["run_current_x"] == "PROFILE"


@pytest.mark.parametrize("model,mode", [("TMC2209", "SPI"), ("TMC5160", "UART")])
def test_wrong_transport_is_rejected(model, mode):
    with pytest.raises(GenerationError, match="requires"):
        resolve_tmc_sections({}, _user(driver_type=model, driver_mode=mode))


def test_z_socket_preserves_complete_matching_section_and_rejects_other_model():
    options = {"uart_pin": "PD12", "uart_address": "3", "sense_resistor": "0.150", "diag_pin": "^PD13", "driver_sgthrs": "42"}
    user = {"driver_type": "TMC2209", "driver_mode": "UART", "z_motors": "2", "z_socket_assignments": {"stepper_z1": "extruder1"}, "board_parsed": {"tmc2209 extruder1": options.copy()}, "board_raw_config": "[tmc2209 extruder1]\nuart_pin: PD12\n"}
    _apply_z_tmc_mappings(user)
    assert user["board_parsed"] == {"tmc2209 stepper_z1": options}
    user["board_parsed"] = {"tmc2130 extruder1": {"cs_pin": "PD12"}}
    user["board_raw_config"] = "[tmc2130 extruder1]\ncs_pin: PD12\n"
    with pytest.raises(WizardExit):
        _apply_z_tmc_mappings(user)
    assert user["board_parsed"] == {"tmc2130 extruder1": {"cs_pin": "PD12"}}


def test_sensorless_retains_virtual_endstops_diag_address_and_zero_retract(tmp_path):
    from core.scraper import parse_config
    from tests.regression.test_snapshot_expansion import MOCK_SKR_MINI_E3_SENSORLESS, _make_user_data
    # Exercise the synthetic sensorless circuit without claiming the complete
    # official source. Its source-identity rejection and real-board cooling
    # coverage live in test_skr_v2_required_cooling.py.
    parsed = parse_config(MOCK_SKR_MINI_E3_SENSORLESS, "synthetic-skr-mini-e3-sensorless.cfg")
    user = _make_user_data(parsed, "test", "/dev/serial/by-id/test", drivers="TMC2209", driver_mode="UART")
    out = tmp_path / "printer.cfg"
    generate_config(parsed, user, output_path=str(out))
    generated = read_config(out.read_text(encoding="utf-8"))
    for axis, address, diag in (("x", "0", "^PC0"), ("y", "2", "^PC1")):
        assert generated[f"stepper_{axis}"]["endstop_pin"] == f"tmc2209_stepper_{axis}:virtual_endstop"
        assert generated[f"stepper_{axis}"]["homing_retract_dist"] == "0"
        tmc = generated[f"tmc2209 stepper_{axis}"]
        assert tmc["diag_pin"] == diag
        assert tmc["uart_address"] == address
        assert tmc["driver_sgthrs"] == "255"
