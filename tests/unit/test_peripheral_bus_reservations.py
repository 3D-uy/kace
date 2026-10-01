"""Reviewed peripherals reserve only their selected hardware bus and MCU."""
from unittest.mock import patch

import pytest

from core.bus_pins import hardware_bus_requests
from core.pin_validator import PinAliasError
from core.firmware_workflow import generation_pin_reservations
from core.deployer import _run_config_transaction
from core.generator import generate_config
from core.exceptions import GenerationError
from firmware.identity import FirmwareIdentityError
from core.workflow_outcome import WorkflowOutcome
from core.wizard.steps.sensors import make_pin_validator_with_collision_check
from tests.unit.test_firmware_bus_reservations import bus_artifact
from tests.unit.test_firmware_pin_reservations import resumed_user
from tests.unit.test_generator import _parsed, _user
from tests.unit.test_reserved_pin_review import PROBE, assert_untouched
from tests.unit.test_config_transaction import FakeTransport, GENERATED


SPI_CASES = [
    ("adxl345", {}, "cs_pin"), ("angle a", {}, "cs_pin"),
    ("ad5206 a", {}, "enable_pin"), ("dac084S085 a", {}, "enable_pin"),
    ("display", {"lcd_type": "uc1701"}, "cs_pin"),
    ("display secondary", {"lcd_type": "hd44780_spi"}, "latch_pin"),
    ("display", {"lcd_type": "aip31068_spi"}, "latch_pin"),
] + [("temperature_sensor t", {"sensor_type": sensor}, "sensor_pin")
     for sensor in ("MAX6675", "MAX31855", "MAX31856", "MAX31865")]
I2C_CASES = [(name, {}) for name in ("icm20948", "mpu9250", "mcp4018 a", "mcp4451 a",
    "mcp4728 a", "pca9533 a", "pca9632 a", "sx1509 a", "ads1x1x a")] + [
    ("temperature_sensor t", {"sensor_type": sensor}) for sensor in
    ("BME280", "AHT10", "AHT1X", "AHT2X", "AHT3X", "HTU21D", "SI7013", "SI7020", "SI7021", "SHT21", "SHT3X", "LM75")]


@pytest.mark.parametrize("section,options,pin_field", SPI_CASES)
def test_spi_dispatch_and_alternative_cs_fields(section, options, pin_field):
    sections = {section: {**options, pin_field: "toolhead:CS", "spi_bus": "spi2"},
                "board_pins tool": {"mcu": "toolhead", "aliases": "CS=PC8"}}
    assert hardware_bus_requests(sections) == {"toolhead": [("spi_bus", "spi2")]}


@pytest.mark.parametrize("section,options", I2C_CASES)
def test_i2c_default_and_selected_mcu(section, options):
    assert hardware_bus_requests({section: options}) == {"mcu": [("i2c_bus", None)]}
    assert hardware_bus_requests({section: {**options, "i2c_mcu": "toolhead", "i2c_bus": "i2c2"}}) == {
        "toolhead": [("i2c_bus", "i2c2")]}


@pytest.mark.parametrize("section,options", [("bmi160", {}), ("lis2dw", {}), ("lis3dh", {}),
    ("display", {"lcd_type": "ssd1306"}), ("display a", {"lcd_type": "sh1106"})])
def test_dual_devices_select_by_cs_presence(section, options):
    assert hardware_bus_requests({section: options}) == {"mcu": [("i2c_bus", None)]}
    assert hardware_bus_requests({section: {**options, "cs_pin": "toolhead:None", "i2c_mcu": "other"}}) == {
        "toolhead": [("spi_bus", None)]}


@pytest.mark.parametrize("section", ["extruder", "extruder1", "heater_bed", "heater_generic h",
    "temperature_sensor t", "temperature_fan f", "temperature_probe p"])
def test_sensor_factory_consumers(section):
    assert hardware_bus_requests({section: {"sensor_type": "MAX31865", "sensor_pin": "PC8"}}) == {
        "mcu": [("spi_bus", None)]}


def test_options_in_macros_or_unrelated_sections_do_not_activate_buses():
    assert hardware_bus_requests({"gcode_macro M": {"sensor_type": "BME280", "i2c_bus": "i2c1"},
        "extruder_stepper e": {"sensor_type": "MAX31865"},
        "display": {"lcd_type": "st7920", "spi_bus": "spi1"},
        "dotstar a": {"spi_bus": "spi1"},
        "temperature_sensor t": {"sensor_type": "Generic 3950", "spi_bus": "spi1"}}) == {}


def test_software_i2c_overrides_bus_and_checks_mcu_and_completeness():
    opts = {"sensor_type": "BME280", "i2c_bus": "ignored", "i2c_mcu": "toolhead",
            "i2c_software_scl_pin": "toolhead:PB8", "i2c_software_sda_pin": "toolhead:PB9"}
    assert hardware_bus_requests({"temperature_sensor t": opts}) == {}
    for changed in ({"i2c_software_sda_pin": ""}, {"i2c_software_sda_pin": "PB9"}, {"i2c_mcu": ""}):
        with pytest.raises(PinAliasError):
            hardware_bus_requests({"temperature_sensor t": {**opts, **changed}})


def test_peripheral_software_spi_uses_the_same_pin_contract():
    opts = {"cs_pin": "PC8", "spi_bus": "ignored", "spi_software_sclk_pin": "PC9",
            "spi_software_miso_pin": "PC10", "spi_software_mosi_pin": "PC11"}
    assert hardware_bus_requests({"adxl345": opts}) == {}


def peripheral_firmware(tmp_path):
    return bus_artifact(tmp_path, enums={"spi_bus": {"spi1": 0}, "i2c_bus": {"i2c1": 0, "i2c2": 1}},
        constants={"BUS_PINS_spi1": "PB8,PB10,PB11", "BUS_PINS_i2c1": "PB8,PB9",
                   "BUS_PINS_i2c2": "PB12,PB13"})


@pytest.mark.parametrize("resume", [False, True])
def test_i2c_reservations_bind_runtime_or_checkpoint_and_mcu(tmp_path, resume):
    built = peripheral_firmware(tmp_path)
    user = resumed_user(built) if resume else {"firmware_artifact": built}
    for chip, expected in [("mcu", {"PB8": "i2c1", "PB9": "i2c1"}), ("toolhead", {})]:
        config = f"[temperature_sensor t]\nsensor_type: BME280\ni2c_mcu: {chip}\n"
        assert generation_pin_reservations(user, config=config) == {"mcu": expected}


@pytest.mark.parametrize("extra,error", [
    ("[display]\nlcd_type: ssd1306\n", "reserved by firmware"),
    ("[display]\nlcd_type: ssd1306\ni2c_bus: i2c2\n", None),
    # K27's generator gate rejects this factory before the pin-reservation gate.
    # Keep the rejection, and a separate permitted renderer/MCU path below.
    ("[temperature_sensor t]\nsensor_type: BME280\ni2c_mcu: toolhead\n", "not supported for generated heaters"),
    ("[mcu toolhead]\nserial: /tmp/toolhead\n[display]\nlcd_type: ssd1306\ni2c_mcu: toolhead\n", None),
    ("[adxl345]\ncs_pin: PC8\n", "reserved by firmware"),
])
def test_final_render_is_checked_before_writing(tmp_path, extra, error):
    built = peripheral_firmware(tmp_path)
    output = tmp_path / "printer.cfg"
    output.write_text("previous", encoding="utf-8")
    parsed = _parsed(bltouch={"sensor_pin": "^PB8", "control_pin": "PB9"})
    user = _user(probe="BLTouch", firmware_artifact=built)
    # Inject only the renderer output to isolate its final validation boundary.
    with patch("core.generator._render_display_blocks", return_value="\n" + extra):
        if error:
            with pytest.raises(GenerationError, match=error):
                generate_config(parsed, user, str(output), verbose=False)
            assert output.read_text() == "previous"
            assert not (tmp_path / "printer.cfg.provenance.json").exists()
        else:
            generate_config(parsed, user, str(output), verbose=False)


def test_retained_nested_i2c_include_blocks_live_publication(tmp_path):
    built = peripheral_firmware(tmp_path)
    original = {"printer.cfg": GENERATED + b"[include user.cfg]\n", "user.cfg": b"[include sensor.cfg]\n",
                "sensor.cfg": b"[temperature_sensor t]\nsensor_type: BME280\n"}
    transport = FakeTransport(original)
    with patch("core.deployer._preflight_check", return_value=True), patch(
        "core.deployer._interactive_configuration_review", return_value=True):
        result = _run_config_transaction(transport, {"firmware_artifact": built}, "none",
                                         generated=(str(tmp_path / "source.cfg"), PROBE, None))
    assert result.outcome == WorkflowOutcome.PRECONDITION_FAILED
    assert "i2c1" in result.detail
    assert_untouched(transport, original)


def test_wizard_does_not_activate_unselected_peripheral_examples(tmp_path):
    built = peripheral_firmware(tmp_path)
    with patch("core.wizard.steps.sensors._get_parsed", return_value={
        "display": {"lcd_type": "ssd1306"}, "temperature_sensor t": {"sensor_type": "BME280"}}):
        assert make_pin_validator_with_collision_check({"firmware_artifact": built})("PB8") is True


def test_mixed_tmc_spi_and_i2c_cannot_hide_overlapping_reservations(tmp_path):
    built = peripheral_firmware(tmp_path)
    config = "[tmc2130 stepper_x]\ncs_pin: PC8\n[temperature_sensor t]\nsensor_type: BME280\n"
    with pytest.raises(FirmwareIdentityError, match="conflicting"):
        generation_pin_reservations({"firmware_artifact": built}, config=config)


def test_two_i2c_devices_share_the_same_selected_bus(tmp_path):
    built = peripheral_firmware(tmp_path)
    config = "[temperature_sensor t]\nsensor_type: BME280\n[display]\nlcd_type: ssd1306\n"
    assert generation_pin_reservations({"firmware_artifact": built}, config=config) == {
        "mcu": {"PB8": "i2c1", "PB9": "i2c1"}}
