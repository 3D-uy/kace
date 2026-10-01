"""Declared SPI auxiliary pins cannot collide with transport or GPIO roles."""
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
from tests.unit.test_tmc_spi_peripherals import peripheral_sections
from tests.unit.test_tmc_spi_chain import config_text
from tests.unit.test_tmc_uart_review import remote_files


AUXILIARIES = [
    ("display", {"lcd_type": lcd}, field) for lcd, fields in
    (("uc1701", ("a0_pin", "rst_pin")), ("ssd1306", ("dc_pin", "reset_pin")),
     ("sh1106", ("dc_pin", "reset_pin"))) for field in fields
] + [
    (section, {"sensor_type": sensor}, "data_ready_pin")
    for section in ("load_cell", "load_cell_probe")
    for sensor in ("ads1220", "ads131m02", "ads131m04")
]
PIN_CASES = [("PC8", True), ("PB14", False), ("PC11", False), ("PC12", False),
             ("PC5", False), ("tool:PC8", False), ("!PC8", False), ("^PC8", False)]


def auxiliary_sections(section, options, field, pin, model="tmc2130"):
    sections = peripheral_sections(section, options, model=model)
    if section == "display":
        sections[section]["a0_pin" if options["lcd_type"] == "uc1701" else "dc_pin"] = "PC7"
    sections[section][field] = pin
    sections["fan"] = {"pin": "PC5"}
    sections["mcu tool"] = {"serial": "/dev/tool"}
    return sections


@pytest.mark.parametrize("model", ("tmc2130", "tmc5160"))
@pytest.mark.parametrize("section,options,field", AUXILIARIES)
@pytest.mark.parametrize("pin,valid", PIN_CASES)
def test_auxiliary_pin_contract(model, section, options, field, pin, valid):
    text = config_text(auxiliary_sections(section, options, field, pin, model))
    if valid:
        validate_spi_config(text)
    else:
        with pytest.raises(GenerationError, match="SPI"):
            validate_spi_config(text)


@pytest.mark.parametrize("target,valid", (("PC8", True), ("PB14", False)))
def test_auxiliary_aliases(target, valid):
    sections = auxiliary_sections("display", {"lcd_type": "uc1701"}, "a0_pin", "DC")
    sections["board_pins names"] = {"aliases": f"DC={target}"}
    if valid:
        validate_spi_config(config_text(sections))
    else:
        with pytest.raises(GenerationError, match="SPI"):
            validate_spi_config(config_text(sections))


def test_display_reset_and_dc_are_exclusive():
    sections = auxiliary_sections("display", {"lcd_type": "uc1701"}, "rst_pin", "PC7")
    with pytest.raises(GenerationError, match="SPI"):
        validate_spi_config(config_text(sections))


def test_undeclared_required_auxiliary_is_rejected():
    sections = peripheral_sections("display", {"lcd_type": "uc1701"})
    del sections["display"]["a0_pin"]
    with pytest.raises(GenerationError, match="a0_pin"):
        validate_spi_config(config_text(sections))


def test_inactive_field_does_not_claim_a_pin():
    sections = peripheral_sections("adxl345", {"dc_pin": "PB14"})
    validate_spi_config(config_text(sections))


@pytest.mark.parametrize("noop", (False, True))
def test_included_auxiliary_collision_blocks_before_writes(tmp_path, noop):
    sections = auxiliary_sections("display", {"lcd_type": "uc1701"}, "a0_pin", "PB14")
    remote = remote_files(config_text(sections))
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


@pytest.mark.parametrize("pin,valid", (("PB14", False), ("PC8", True)))
def test_effective_auxiliary_override(pin, valid):
    remote = remote_files(config_text(auxiliary_sections("display", {"lcd_type": "uc1701"}, "a0_pin", "PB14"))
                          + "[include override.cfg]\n")
    remote["override.cfg"] = f"[display]\na0_pin: {pin}\n".encode()
    result = validate_configuration_plan(build_managed_config_plan(GENERATED, None, remote))
    assert result.valid == valid, result


@pytest.mark.parametrize("valid", (False, True))
def test_final_render_handles_auxiliary_pin(tmp_path, valid):
    from jinja2 import Template
    render = Template.render
    def inject(template, *args, **kwargs):
        return render(template, *args, **kwargs) + config_text(auxiliary_sections(
            "display", {"lcd_type": "uc1701"}, "a0_pin", "PC8" if valid else "PB14"))
    output = tmp_path / "printer.cfg"
    with patch.object(Template, "render", inject):
        if valid:
            generate_config(_parsed(), _user(), output_path=str(output), verbose=False)
        else:
            with pytest.raises(GenerationError, match="SPI"):
                generate_config(_parsed(), _user(), output_path=str(output), verbose=False)
            assert not output.exists()
