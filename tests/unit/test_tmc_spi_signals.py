"""Explicit SPI signals follow upstream role sharing, never exclusive GPIO use."""
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
from tests.unit.test_tmc_chain_reservations import SOFTWARE
from tests.unit.test_tmc_spi_chain import case_sections, config_text
from tests.unit.test_tmc_uart_review import remote_files


CASES = [
    ("chain", {}, True),
    ("shared-signals", {"second": {"cs_pin": "PC12", **SOFTWARE}}, True),
    ("crossed-signals", {"second": {"cs_pin": "PC12", **SOFTWARE, "spi_software_mosi_pin": "PB14"}}, False),
    ("same-pin-two-roles", {"first": {"spi_software_mosi_pin": "PB14"}}, False),
    ("signal-on-cs", {"first": {"spi_software_sclk_pin": "PC11"}}, False),
    ("cs-on-other-signal", {"second": {"cs_pin": "PB14"}}, False),
    ("inverted-signal", {"first": {"spi_software_sclk_pin": "!PB13"}}, False),
    ("pullup-signal", {"first": {"spi_software_miso_pin": "^PB14"}}, False),
    ("missing-mosi", {"first": {"spi_software_mosi_pin": None}}, False),
    ("orphan-signal", {"first": {"spi_software_sclk_pin": None}}, False),
    ("unused-bus", {"first": {"spi_bus": "spi2"}}, False),
    ("unknown-mcu", {"first": {"spi_software_miso_pin": "tool:PB14"}}, False),
    ("different-mcu", {"first": {"spi_software_miso_pin": "tool:PB14"}, "extra": {"mcu tool": {"serial": "/dev/tool"}}}, False),
    ("same-alias", {"first": {"spi_software_miso_pin": "MISO"}, "second": {"cs_pin": "PC12", **SOFTWARE, "spi_software_miso_pin": "MISO"}, "extra": {"board_pins aliases": {"aliases": "MISO=PB14"}}}, True),
    ("different-alias", {"second": {"cs_pin": "PC12", **SOFTWARE, "spi_software_miso_pin": "MISO"}, "extra": {"board_pins aliases": {"aliases": "MISO=PB14"}}}, False),
    ("reserved-alias", {"first": {"spi_software_miso_pin": "MISO"}, "extra": {"board_pins aliases": {"aliases": "MISO=<reserved>"}}}, False),
    ("qualified-signal", {"first": {"spi_software_miso_pin": "mcu:PB14"}}, True),
    ("fan-conflict", {"extra": {"fan": {"pin": "!PB14"}}}, False),
    ("cs-output-conflict", {"extra": {"output_pin test": {"pin": "PC11"}}}, False),
    ("fan-other-mcu", {"extra": {"mcu tool": {"serial": "/dev/tool"}, "fan": {"pin": "tool:PB14"}}}, True),
    ("macro-text", {"extra": {"gcode_macro NOTE": {"gcode": "M118 pin=PB14"}}}, True),
]


def signal_sections(changes=None, model="tmc2130"):
    changes = changes or {}
    return case_sections({**changes, "first": {**SOFTWARE, **changes.get("first", {})}}, model)


@pytest.mark.parametrize("model", ("tmc2130", "tmc5160"))
@pytest.mark.parametrize("name,changes,valid", CASES, ids=[row[0] for row in CASES])
def test_explicit_signal_contract(model, name, changes, valid):
    text = config_text(signal_sections(changes, model))
    if valid:
        validate_spi_config(text)
    else:
        with pytest.raises(GenerationError, match="SPI"):
            validate_spi_config(text)


@pytest.mark.parametrize("section,field", [
    ("stepper_x", "step_pin"), ("stepper_z1", "dir_pin"), ("extruder", "enable_pin"),
    ("manual_stepper test", "endstop_pin"), ("extruder1", "heater_pin"),
    ("heater_bed", "sensor_pin"), ("heater_generic test", "heater_pin"),
    ("fan", "pin"), ("heater_fan test", "pin"), ("controller_fan test", "pin"),
    ("fan_generic test", "pin"), ("temperature_fan test", "pin"),
    ("fan_generic test", "enable_pin"), ("fan_generic test", "tachometer_pin"),
    ("output_pin test", "pin"), ("probe", "pin"), ("bltouch", "control_pin"),
])
def test_exclusive_consumers(section, field):
    text = config_text(signal_sections({"extra": {section: {field: "!PB14"}}}))
    with pytest.raises(GenerationError, match="SPI"):
        validate_spi_config(text)


@pytest.mark.parametrize("noop", (False, True))
def test_include_collision_blocks_before_confirmation(tmp_path, noop):
    remote = remote_files(config_text(signal_sections()) + "[include outputs.cfg]\n")
    remote["outputs.cfg"] = b"[output_pin test]\npin: PB14\n"
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


@pytest.mark.parametrize("pin,valid", (("PB14", False), ("PB7", True)))
def test_effective_include_override(pin, valid):
    remote = remote_files(config_text(signal_sections()) + "[output_pin test]\npin: PB14\n[include override.cfg]\n")
    remote["override.cfg"] = f"[output_pin test]\npin: {pin}\n".encode()
    result = validate_configuration_plan(build_managed_config_plan(GENERATED, None, remote))
    assert result.valid == valid, result


@pytest.mark.parametrize("model", ("tmc2130", "tmc5160"))
def test_real_generation_rejects_signal_on_existing_fan(tmp_path, model):
    board = _parsed(**signal_sections({"first": {"spi_software_miso_pin": "PC5"}}, model))
    output = tmp_path / "printer.cfg"
    with pytest.raises(GenerationError, match="SPI"):
        generate_config(board, _user(driver_type=model.upper(), driver_mode="SPI"), output_path=str(output), verbose=False)
    assert not output.exists()


def test_final_render_rejects_signal_collision(tmp_path):
    from jinja2 import Template
    render = Template.render
    def inject(template, *args, **kwargs):
        return render(template, *args, **kwargs) + config_text(signal_sections({"first": {"spi_software_miso_pin": "PC5"}}))
    output = tmp_path / "printer.cfg"
    with patch.object(Template, "render", inject), pytest.raises(GenerationError, match="SPI"):
        generate_config(_parsed(), _user(), output_path=str(output), verbose=False)
    assert not output.exists()
