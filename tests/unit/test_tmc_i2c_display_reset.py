"""Optional I2C display reset uses its bus MCU and exclusive pin identity."""
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
from tests.unit.test_tmc_spi_signals import signal_sections
from tests.unit.test_tmc_spi_chain import config_text
from tests.unit.test_tmc_uart_review import remote_files


CASES = [
    ("omitted", {}, True), ("free", {"reset_pin": "PC8"}, True),
    ("signal", {"reset_pin": "PB14"}, False), ("cs", {"reset_pin": "PC11"}, False),
    ("fan", {"reset_pin": "PC5"}, False), ("inverted", {"reset_pin": "!PC8"}, False),
    ("pullup", {"reset_pin": "^PC8"}, False),
    ("wrong-mcu", {"reset_pin": "tool:PC8"}, False),
    ("secondary", {"i2c_mcu": "tool", "reset_pin": "tool:PB14"}, True),
    ("secondary-wrong", {"i2c_mcu": "tool", "reset_pin": "PC8"}, False),
]
SOFTWARE = {"i2c_software_scl_pin": "PC6", "i2c_software_sda_pin": "PC7"}


def display_sections(options, lcd="ssd1306", model="tmc2130"):
    sections = signal_sections(model=model)
    sections.update({"display": {"lcd_type": lcd, **{key: value for key, value in options.items() if value is not None}}, "fan": {"pin": "PC5"},
                     "mcu tool": {"serial": "/dev/tool"}})
    return sections


@pytest.mark.parametrize("model", ("tmc2130", "tmc5160"))
@pytest.mark.parametrize("lcd", ("ssd1306", "sh1106"))
@pytest.mark.parametrize("name,options,valid", CASES)
def test_i2c_reset_identity(model, lcd, name, options, valid):
    text = config_text(display_sections(options, lcd, model))
    if valid:
        validate_spi_config(text)
    else:
        with pytest.raises(GenerationError, match="SPI"):
            validate_spi_config(text)


SOFTWARE_CASES = [
    ("free", {"reset_pin": "PC8"}, True),
    ("scl-reset", {"reset_pin": "PC6"}, False), ("sda-reset", {"reset_pin": "PC7"}, False),
    ("scl-tmc", {"reset_pin": "PC8", "i2c_software_scl_pin": "PB14"}, False),
    ("sda-tmc", {"reset_pin": "PC8", "i2c_software_sda_pin": "PC11"}, False),
    ("same-signals", {"reset_pin": "PC8", "i2c_software_sda_pin": "PC6"}, False),
    ("wrong-sda-mcu", {"reset_pin": "PC8", "i2c_software_sda_pin": "tool:PC7"}, False),
    ("missing-sda", {"reset_pin": "PC8", "i2c_software_sda_pin": None}, False),
    ("orphan-sda", {"reset_pin": "PC8", "i2c_software_scl_pin": None}, False),
    ("unused-hardware-bus", {"reset_pin": "PC8", "i2c_bus": "i2c1"}, False),
]


@pytest.mark.parametrize("name,options,valid", SOFTWARE_CASES)
def test_software_i2c_reset_collisions(name, options, valid):
    text = config_text(display_sections({**SOFTWARE, **options}))
    if valid:
        validate_spi_config(text)
    else:
        with pytest.raises(GenerationError, match="SPI"):
            validate_spi_config(text)


@pytest.mark.parametrize("target,valid", (("PC8", True), ("PB14", False)))
def test_reset_alias(target, valid):
    sections = display_sections({"reset_pin": "RST"})
    sections["board_pins names"] = {"aliases": f"RST={target}"}
    if valid:
        validate_spi_config(config_text(sections))
    else:
        with pytest.raises(GenerationError, match="SPI"):
            validate_spi_config(config_text(sections))


@pytest.mark.parametrize("noop", (False, True))
def test_included_reset_conflict_blocks_writes(tmp_path, noop):
    remote = remote_files(config_text(display_sections({"reset_pin": "PB14"})))
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
def test_include_override_is_effective(pin, valid):
    remote = remote_files(config_text(display_sections({"reset_pin": "PB14"})) + "[include reset.cfg]\n")
    remote["reset.cfg"] = f"[display]\nreset_pin: {pin}\n".encode()
    result = validate_configuration_plan(build_managed_config_plan(GENERATED, None, remote))
    assert result.valid == valid, result


def test_final_render_rejects_reset_on_spi(tmp_path):
    from jinja2 import Template
    render = Template.render
    def inject(template, *args, **kwargs):
        return render(template, *args, **kwargs) + config_text(display_sections({"reset_pin": "PB14"}))
    output = tmp_path / "printer.cfg"
    with patch.object(Template, "render", inject), pytest.raises(GenerationError, match="SPI"):
        generate_config(_parsed(), _user(), output_path=str(output), verbose=False)
    assert not output.exists()
