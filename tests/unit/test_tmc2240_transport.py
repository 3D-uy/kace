"""Actual preserved TMC2240 transport interactions; no guided model support."""
from unittest.mock import Mock, patch

import pytest

from core.bus_pins import tmc_bus_requests
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.exceptions import GenerationError
from core.firmware_workflow import generation_pin_reservations
from core.generator import generate_config
from core.managed_config import build_managed_config_plan
from core.profile_values import resolve_tmc_sections
from tests.unit.test_config_transaction import FakeTransport, GENERATED
from tests.unit.test_generator import _parsed, _user
from tests.unit.test_reserved_pin_review import assert_untouched
from tests.unit.test_tmc_bus_reservations import built_bus
from tests.unit.test_tmc_chain_reservations import chain
from tests.unit.test_tmc_spi_chain import CASES as SPI_CASES, case_sections, config_text
from tests.unit.test_tmc_spi_signals import CASES as SIGNAL_CASES, signal_sections
from tests.unit.test_tmc_uart_review import remote_files


UART_CASES = [
    ("default", {}, {}, True),
    ("maximum-address", {"uart_address": "7"}, {}, True),
    ("negative-address", {"uart_address": "-1"}, {}, False),
    ("excess-address", {"uart_address": "8"}, {}, False),
    ("float-address", {"uart_address": "1.0"}, {}, False),
    ("empty-rx", {"uart_pin": ""}, {}, False),
    ("inverted-rx", {"uart_pin": "!PC11"}, {}, False),
    ("pulled-rx", {"uart_pin": "^PC11"}, {}, True),
    ("separate-tx", {"tx_pin": "PC12"}, {}, True),
    ("unknown-mcu", {"uart_pin": "unknown:PC11"}, {}, False),
    ("cross-mcu-tx", {"tx_pin": "tool:PC12"}, {"mcu tool": {"serial": "/dev/tool"}}, False),
    ("mixed-unique", {"uart_address": "7"}, {"tmc2209 stepper_y": {"uart_pin": "PC11", "uart_address": "1", "run_current": ".580"}}, True),
    ("mixed-duplicate", {"uart_address": "1"}, {"tmc2209 stepper_y": {"uart_pin": "PC11", "uart_address": "1", "run_current": ".580"}}, False),
    ("fan-conflict", {}, {"fan": {"pin": "PC11"}}, False),
    ("unused-cs", {"cs_pin": "PC12"}, {}, False),
    ("unused-spi-bus", {"spi_bus": "spi1"}, {}, False),
    ("unused-chain", {"chain_length": "2", "chain_position": "1"}, {}, False),
]


def uart_sections(changes=None, extra=None):
    return {**(extra or {}), "tmc2240 stepper_x": {"uart_pin": "PC11", "run_current": ".580", **(changes or {})}}


@pytest.mark.parametrize("name,changes,valid", SPI_CASES)
def test_effective_spi_chain(name, changes, valid):
    plan = build_managed_config_plan(GENERATED, None, remote_files(config_text(case_sections(changes, "tmc2240"))))
    assert validate_configuration_plan(plan).valid == valid


@pytest.mark.parametrize("name,changes,valid", SIGNAL_CASES)
def test_effective_spi_signals(name, changes, valid):
    from core.tmc_spi import validate_spi_config
    text = config_text(signal_sections(changes, "tmc2240"))
    if valid:
        validate_spi_config(text)
    else:
        with pytest.raises(GenerationError):
            validate_spi_config(text)


@pytest.mark.parametrize("name,changes,extra,valid", UART_CASES)
def test_effective_uart(name, changes, extra, valid):
    plan = build_managed_config_plan(GENERATED, None, remote_files(config_text(uart_sections(changes, extra))))
    assert validate_configuration_plan(plan).valid == valid


@pytest.mark.parametrize("model", ("tmc2240", "tmc2130", "tmc5160"))
@pytest.mark.parametrize("mode", ("software", "spi2", None))
@pytest.mark.parametrize("reverse", (False, True))
def test_shared_owner_projection(model, mode, reverse):
    sections = mixed_chain(model, mode, reverse)
    expected = {} if mode == "software" else {"mcu": [("spi_bus", mode)]}
    assert tmc_bus_requests(sections) == expected


def mixed_chain(model, mode, reverse):
    sections = chain("tmc2240", mode)
    options = sections.pop("tmc2240 stepper_y")
    sections[f"{model} stepper_y"] = options
    if reverse:
        first = sections.pop("tmc2240 stepper_x")
        # Keep the selected transport on the new owner, not its follower.
        for key in list(first):
            if key.startswith("spi_"):
                options[key] = first.pop(key)
        sections["tmc2240 stepper_x"] = first
    return sections


@pytest.mark.parametrize("mode", ("software", "spi2"))
def test_exact_firmware_reservations_have_no_follower_bus(tmp_path, mode):
    artifact = built_bus(tmp_path)
    expected = {} if mode == "software" else {"PB12": "spi2", "PB13": "spi2", "PB14": "spi2"}
    assert generation_pin_reservations({"firmware_artifact": artifact}, config=config_text(chain("tmc2240", mode))) == {"mcu": expected}


@pytest.mark.parametrize("field,value", (("tx_pin", "PC12"), ("uart_address", "1"), ("select_pins", "PC10"), ("spi_speed", "99999")))
def test_spi_rejects_unused_uart_or_invalid_speed(field, value):
    sections = {"tmc2240 stepper_x": {"cs_pin": "PC11", "run_current": ".580", field: value}}
    plan = build_managed_config_plan(GENERATED, None, remote_files(config_text(sections)))
    assert not validate_configuration_plan(plan).valid


@pytest.mark.parametrize("noop", (False, True))
@pytest.mark.parametrize("kind", ("spi", "uart"))
def test_invalid_transport_blocks_before_publication(tmp_path, noop, kind):
    sections = (case_sections({"second": {"chain_position": "1"}}, "tmc2240") if kind == "spi"
                else uart_sections({"uart_address": "8"}))
    remote = remote_files(config_text(sections))
    if noop:
        plan = build_managed_config_plan(GENERATED, None, remote)
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        assert not build_managed_config_plan(GENERATED, None, remote).changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, GENERATED, None, activation="none", confirm=confirm,
        snapshot_root=str(tmp_path / "snapshots"), verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    confirm.assert_not_called()
    assert_untouched(transport, remote)


@pytest.mark.parametrize("kind", ("spi", "uart"))
def test_render_checks_external_transport(tmp_path, kind):
    from jinja2 import Template
    render = Template.render
    sections = (case_sections({"second": {"chain_position": "1"}}, "tmc2240") if kind == "spi"
                else uart_sections({"uart_address": "8"}))
    def inject(template, *args, **kwargs):
        return render(template, *args, **kwargs) + config_text(sections)
    output = tmp_path / "printer.cfg"
    with patch.object(Template, "render", inject), pytest.raises(GenerationError):
        generate_config(_parsed(), _user(), output_path=str(output), verbose=False)
    assert not output.exists()


def test_not_added_to_guided_generation():
    with pytest.raises(GenerationError, match="Unsupported TMC model"):
        resolve_tmc_sections({}, _user(driver_type="TMC2240", driver_mode="SPI"))
