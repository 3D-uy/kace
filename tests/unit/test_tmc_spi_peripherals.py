"""TMC and reviewed peripheral SPI transports share roles, not chip selects."""
from unittest.mock import Mock, patch

import pytest

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.exceptions import GenerationError
from core.generator import generate_config
from core.managed_config import build_managed_config_plan
from core.tmc_spi import validate_spi_config
from tests.unit.test_config_transaction import FakeTransport, GENERATED
from tests.unit.test_generator import _parsed, _user
from tests.unit.test_peripheral_bus_reservations import SPI_CASES
from tests.unit.test_tmc_chain_reservations import SOFTWARE
from tests.unit.test_tmc_spi_signals import signal_sections
from tests.unit.test_tmc_spi_chain import config_text
from tests.unit.test_tmc_uart_review import remote_files


PERIPHERALS = SPI_CASES + [
    (name, {}, "cs_pin") for name in ("bmi160", "lis2dw", "lis3dh")
] + [
    ("display", {"lcd_type": lcd}, "cs_pin") for lcd in ("ssd1306", "sh1106")
] + [
    (name, {"sensor_type": sensor}, "cs_pin") for name in ("load_cell", "load_cell_probe")
    for sensor in ("ads1220", "ads131m02", "ads131m04")
] + [
    (name, {"sensor_type": "MAX31865"}, "sensor_pin") for name in
    ("extruder", "extruder1", "heater_bed", "heater_generic h", "temperature_fan f", "temperature_probe p")
]


def peripheral_sections(section="adxl345", options=None, pin_field="cs_pin", *, changes=None, model="tmc2130"):
    result = signal_sections(model=model)
    result[section] = {**(options or {}), pin_field: "PC12", **SOFTWARE}
    kind = section.split(" ", 1)[0]
    if kind == "display" and result[section].get("lcd_type") in ("uc1701", "ssd1306", "sh1106"):
        result[section]["a0_pin" if result[section]["lcd_type"] == "uc1701" else "dc_pin"] = "PC6"
    elif kind in ("load_cell", "load_cell_probe"):
        result[section]["data_ready_pin"] = "PC6"
    for key, value in (changes or {}).items():
        if value is None:
            result[section].pop(key, None)
        else:
            result[section][key] = value
    return result


@pytest.mark.parametrize("model", ("tmc2130", "tmc5160"))
@pytest.mark.parametrize("section,options,pin_field", PERIPHERALS)
@pytest.mark.parametrize("crossed", (False, True))
def test_reviewed_peripheral_sharing(model, section, options, pin_field, crossed):
    sections = peripheral_sections(section, options, pin_field, model=model,
        changes={"spi_software_mosi_pin": "PB14"} if crossed else {})
    if crossed:
        with pytest.raises(GenerationError, match="SPI"):
            validate_spi_config(config_text(sections))
    else:
        validate_spi_config(config_text(sections))


EDGE_CASES = [
    ("cs-on-tmc-cs", {"cs_pin": "PC11"}, False),
    ("cs-on-tmc-signal", {"cs_pin": "PB14"}, False),
    ("signal-on-tmc-cs", {"spi_software_miso_pin": "PC11"}, False),
    ("missing-mosi", {"spi_software_mosi_pin": None}, False),
    ("unused-bus", {"spi_bus": "spi2"}, False),
    ("orphan-software", {"spi_software_sclk_pin": None}, False),
    ("invalid-modifier", {"spi_software_miso_pin": "^PB14"}, False),
    ("other-mcu-signal", {"spi_software_miso_pin": "tool:PB14"}, False),
    ("no-cs", {"cs_pin": "None"}, True),
    ("invalid-no-cs", {"cs_pin": "!None"}, False),
    ("unknown-no-cs-mcu", {"cs_pin": "missing:None"}, False),
    ("hardware", {field: None for field in SOFTWARE}, True),
]


@pytest.mark.parametrize("name,changes,valid", EDGE_CASES)
def test_peripheral_signal_contract(name, changes, valid):
    sections = peripheral_sections(changes=changes)
    sections["mcu tool"] = {"serial": "/dev/tool"}
    if valid:
        validate_spi_config(config_text(sections))
    else:
        with pytest.raises(GenerationError, match="SPI"):
            validate_spi_config(config_text(sections))


@pytest.mark.parametrize("spelling,valid", (("PB14", False), ("MISO", True)))
def test_alias_spelling_between_peripheral_and_tmc(spelling, valid):
    sections = peripheral_sections(changes={"spi_software_miso_pin": spelling})
    sections["tmc2130 stepper_x"]["spi_software_miso_pin"] = "MISO"
    sections["board_pins names"] = {"aliases": "MISO=PB14"}
    if valid:
        validate_spi_config(config_text(sections))
    else:
        with pytest.raises(GenerationError, match="SPI"):
            validate_spi_config(config_text(sections))


def test_secondary_mcu_keeps_separate_identity():
    sections = peripheral_sections(changes={"cs_pin": "tool:PC11", **{field: "tool:" + value for field, value in SOFTWARE.items()}})
    sections["mcu tool"] = {"serial": "/dev/tool"}
    validate_spi_config(config_text(sections))


@pytest.mark.parametrize("section,options", [
    ("gcode_macro NOTE", {"gcode": "M118 ok"}),
    ("display", {"lcd_type": "st7920"}), ("display", {"lcd_type": "ssd1306"}),
    ("temperature_sensor t", {"sensor_type": "Generic 3950"}),
    ("load_cell", {"sensor_type": "hx711"}), ("bmi160", {}),
])
def test_unselected_spi_fields_do_not_create_transport(section, options):
    sections = signal_sections()
    sections[section] = {**options, **SOFTWARE, "spi_software_mosi_pin": "PB14"}
    validate_spi_config(config_text(sections))


@pytest.mark.parametrize("noop", (False, True))
def test_nested_peripheral_collision_blocks_before_writes(tmp_path, noop):
    sections = peripheral_sections(changes={"spi_software_mosi_pin": "PB14"})
    remote = remote_files(config_text(sections) + "[include extra.cfg]\n")
    remote["extra.cfg"] = b"# no override\n"
    if noop:
        plan = build_managed_config_plan(GENERATED, None, remote)
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        assert not build_managed_config_plan(GENERATED, None, remote).changed_artifacts
    transport = FakeTransport(remote)
    confirm = Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, GENERATED, None, activation="none", confirm=confirm,
        snapshot_root=str(tmp_path / "snapshots"), verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "SPI" in result.detail
    confirm.assert_not_called()
    assert transport.files == remote
    assert not any(call[0] in ("upload", "delete", "restart") for call in transport.calls)


@pytest.mark.parametrize("pin,valid", (("PB14", False), ("PB15", True)))
def test_effective_override_selects_peripheral_signal(pin, valid):
    remote = remote_files(config_text(peripheral_sections()) + "[include override.cfg]\n")
    remote["override.cfg"] = f"[adxl345]\nspi_software_mosi_pin: {pin}\n".encode()
    result = validate_configuration_plan(build_managed_config_plan(GENERATED, None, remote))
    assert result.valid == valid, result


@pytest.mark.parametrize("crossed", (False, True))
def test_final_generated_config_checks_peripheral(tmp_path, crossed):
    from jinja2 import Template
    render = Template.render
    def inject(template, *args, **kwargs):
        return render(template, *args, **kwargs) + config_text(peripheral_sections(
            changes={"spi_software_mosi_pin": "PB14"} if crossed else {}))
    output = tmp_path / "printer.cfg"
    with patch.object(Template, "render", inject):
        if crossed:
            with pytest.raises(GenerationError, match="SPI"):
                generate_config(_parsed(), _user(), output_path=str(output), verbose=False)
            assert not output.exists()
        else:
            generate_config(_parsed(), _user(), output_path=str(output), verbose=False)
            assert output.exists()
