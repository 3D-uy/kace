"""Independent TMC2660 transport validation in effective configuration."""
from unittest.mock import Mock, patch

import pytest

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.exceptions import GenerationError
from core.generator import generate_config
from core.managed_config import build_managed_config_plan
from core.tmc_spi import spi_transport_owners, validate_spi_config
from tests.unit.test_config_transaction import FakeTransport, GENERATED
from tests.unit.test_generator import _parsed, _user
from tests.unit.test_tmc_chain_reservations import SOFTWARE
from tests.unit.test_tmc_spi_chain import config_text
from tests.unit.test_tmc_uart_review import remote_files


CASES = [
    ("default", {}, True),
    ("minimum-speed", {"spi_speed": "100000"}, True),
    ("explicit-speed", {"spi_speed": "4000000"}, True),
    ("slow", {"spi_speed": "99999"}, False),
    ("float", {"spi_speed": "100000.0"}, False),
    ("exponent", {"spi_speed": "1e6"}, False),
    ("negative", {"spi_speed": "-1"}, False),
    ("empty-speed", {"spi_speed": ""}, False),
    ("missing-cs", {"cs_pin": None}, False),
    ("empty-cs", {"cs_pin": ""}, False),
    ("inverted-cs", {"cs_pin": "!PC11"}, False),
    ("pullup-cs", {"cs_pin": "^PC11"}, False),
    ("unknown-mcu", {"cs_pin": "missing:PC11"}, False),
    ("no-cs", {"cs_pin": "None"}, True),
    ("chain-length", {"chain_length": "2"}, False),
    ("chain-position", {"chain_position": "1"}, False),
    ("chain-both", {"chain_length": "2", "chain_position": "1"}, False),
    ("software", SOFTWARE, True),
    ("missing-miso", {**SOFTWARE, "spi_software_miso_pin": None}, False),
    ("missing-mosi", {**SOFTWARE, "spi_software_mosi_pin": None}, False),
    ("orphan-miso", {"spi_software_miso_pin": "PB14"}, False),
    ("orphan-mosi", {"spi_software_mosi_pin": "PB15"}, False),
    ("unused-bus", {**SOFTWARE, "spi_bus": "spi1"}, False),
    ("cs-as-clock", {**SOFTWARE, "spi_software_sclk_pin": "PC11"}, False),
    ("same-signals", {**SOFTWARE, "spi_software_mosi_pin": "PB14"}, False),
    ("mixed-mcu", {**SOFTWARE, "spi_software_miso_pin": "tool:PB14"}, False),
]


def sections_for(options=None, companion=None, reverse=False):
    options = {"cs_pin": "PC11", "run_current": ".580", **(options or {})}
    sections = {"tmc2660 stepper_x": {k: v for k, v in options.items() if v is not None}}
    if companion:
        sections.update(companion)
    if reverse:
        sections = dict(reversed(list(sections.items())))
    sections["mcu tool"] = {"serial": "/dev/unused"}
    return sections


@pytest.mark.parametrize("name,options,accepted", CASES, ids=[case[0] for case in CASES])
def test_transport_contract(name, options, accepted):
    content = config_text(sections_for(options))
    if accepted:
        validate_spi_config(content)
    else:
        with pytest.raises(GenerationError, match="SPI"):
            validate_spi_config(content)


@pytest.mark.parametrize("model", ("tmc2130", "tmc5160", "tmc2660"))
@pytest.mark.parametrize("reverse", (False, True))
@pytest.mark.parametrize("shared_cs", (False, True))
def test_independent_transports(model, reverse, shared_cs):
    companion = {f"{model} stepper_y": {
        "cs_pin": "PC11" if shared_cs else "PC12", "run_current": ".580", **SOFTWARE}}
    sections = sections_for(SOFTWARE, companion, reverse)
    if shared_cs:
        with pytest.raises(GenerationError, match="SPI"):
            validate_spi_config(config_text(sections))
    else:
        validate_spi_config(config_text(sections))
        owners = spi_transport_owners(sections)
        assert owners == {name: name for name in sections if name.startswith("tmc")}


@pytest.mark.parametrize("noop", (False, True))
def test_invalid_included_transport_stops_before_write(tmp_path, noop):
    remote = remote_files(config_text(sections_for({"chain_length": "2", "sense_resistor": ".100"})))
    if noop:
        plan = build_managed_config_plan(GENERATED, None, remote)
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        assert not build_managed_config_plan(GENERATED, None, remote).changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, GENERATED, None, activation="none", confirm=confirm,
        snapshot_root=str(tmp_path / "snapshots"), verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "chain_length" in result.detail
    confirm.assert_not_called()
    assert transport.files == remote
    assert not any(call[0] in ("upload", "delete", "restart") for call in transport.calls)


def test_include_can_supply_transport():
    remote = remote_files(config_text(sections_for({"cs_pin": None, "sense_resistor": ".100"})) + "[include pins.cfg]\n")
    remote["pins.cfg"] = b"[tmc2660 stepper_x]\ncs_pin: PC11\n"
    result = validate_configuration_plan(build_managed_config_plan(GENERATED, None, remote))
    assert result.valid, result


def test_final_render_validates_tmc2660_before_write(tmp_path):
    from jinja2 import Template
    render = Template.render
    def inject(template, *args, **kwargs):
        return render(template, *args, **kwargs) + config_text(sections_for({"spi_speed": "1", "sense_resistor": ".100"}))
    output = tmp_path / "printer.cfg"
    with patch.object(Template, "render", inject), pytest.raises(GenerationError, match="spi_speed"):
        generate_config(_parsed(), _user(), output_path=str(output), verbose=False)
    assert not output.exists()
