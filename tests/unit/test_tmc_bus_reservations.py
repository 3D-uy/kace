"""TMC buses participate in probe generation and destination reservation gates."""
from unittest.mock import patch

import pytest

from core.bus_pins import tmc_bus_requests
from core.exceptions import GenerationError
from core.firmware_workflow import generation_pin_reservations
from core.generator import generate_config
from core.pin_validator import PinAliasError
from core.deployer import _run_config_transaction
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.managed_config import build_managed_config_plan
from core.workflow_outcome import WorkflowOutcome
from core.wizard.steps.sensors import make_pin_validator_with_collision_check
from tests.unit.test_firmware_bus_reservations import bus_artifact
from tests.unit.test_firmware_pin_reservations import resumed_user
from tests.unit.test_generator import _parsed, _user
from tests.unit.test_reserved_pin_review import PROBE, assert_untouched
from tests.unit.test_config_transaction import FakeTransport, GENERATED


def built_bus(tmp_path):
    return bus_artifact(tmp_path, enums={"spi_bus": {"spi1": 0, "spi2": 1}},
        constants={"BUS_PINS_spi1": "PB8,PB10,PB11", "BUS_PINS_spi2": "PB12,PB13,PB14"})


def driver(pin="PC8", **options):
    return {"cs_pin": pin, "run_current": "0.8", **options}


@pytest.mark.parametrize("model", ["tmc2130", "tmc2660", "tmc5160", "tmc2240"])
@pytest.mark.parametrize("chip", ["mcu", "toolhead"])
def test_defaults_and_cs_ownership(model, chip):
    assert tmc_bus_requests({f"{model} stepper_x": driver(f"{chip}:CS"),
        f"board_pins {chip}": {"mcu": chip, "aliases": "CS=PC8"}}) == {chip: [("spi_bus", None)]}


def test_tmc2240_uart_wins_and_unrelated_options_do_not_select_spi():
    assert tmc_bus_requests({"tmc2240 stepper_x": driver(uart_pin="PC9"),
        "tmc2209 stepper_y": {"uart_pin": "PC9", "spi_bus": "spi1"},
        "gcode_macro SOMETHING": {"spi_bus": "spi1"}}) == {}


def test_shared_hardware_bus_is_one_request():
    assert tmc_bus_requests({"tmc2130 stepper_x": driver(spi_bus="spi1"),
        "tmc5160 stepper_y": driver("PC9", spi_bus="spi1")}) == {"mcu": [("spi_bus", "spi1")]}


def test_software_spi_does_not_reserve_hardware_even_with_spi_bus_present():
    assert tmc_bus_requests({"tmc2130 stepper_x": driver(spi_bus="spi1",
        spi_software_sclk_pin="PC9", spi_software_miso_pin="PC10",
        spi_software_mosi_pin="PC11")}) == {}


@pytest.mark.parametrize("options", [
    {}, driver(spi_software_sclk_pin="PC9"),
    driver(spi_software_sclk_pin="PC9", spi_software_miso_pin="toolhead:PC10",
           spi_software_mosi_pin="PC11"),
])
def test_missing_cs_or_incomplete_cross_mcu_software_is_rejected(options):
    with pytest.raises(PinAliasError):
        tmc_bus_requests({"tmc2130 stepper_x": options})


@pytest.mark.parametrize("resume", [False, True])
def test_runtime_and_resume_use_final_bus_and_preserve_mcu_boundary(tmp_path, resume):
    built = built_bus(tmp_path)
    user = resumed_user(built) if resume else {"firmware_artifact": built}
    for chip, expected in [("mcu", {"PB8": "spi1", "PB10": "spi1", "PB11": "spi1"}),
                           ("toolhead", {})]:
        config = f"[tmc2130 stepper_x]\ncs_pin: {chip}:PC8\n"
        assert generation_pin_reservations(user, config=config) == {"mcu": expected}


@pytest.mark.parametrize("model", ["TMC2130", "TMC5160"])
def test_generation_rejects_implicit_default_bus_before_writes(tmp_path, model):
    built = built_bus(tmp_path)
    user = _user(probe="BLTouch", driver_type=model, driver_mode="SPI", firmware_artifact=built)
    parsed = _parsed(bltouch={"sensor_pin": "^PB8", "control_pin": "PB9"},
                     **{f"{model.lower()} stepper_x": driver()})
    output = tmp_path / "printer.cfg"
    output.write_text("previous", encoding="utf-8")
    with pytest.raises(GenerationError, match="reserved by firmware for spi1"):
        generate_config(parsed, user, str(output), verbose=False)
    assert output.read_text() == "previous"
    assert not (tmp_path / "printer.cfg.provenance.json").exists()


def test_generation_accepts_different_bus_and_commented_standalone(tmp_path):
    built = built_bus(tmp_path)
    for mode in ("SPI", "Standalone"):
        user = _user(probe="BLTouch", driver_type="TMC2130", driver_mode=mode, firmware_artifact=built)
        parsed = _parsed(bltouch={"sensor_pin": "^PB8", "control_pin": "PB9"},
                         **{"tmc2130 stepper_x": driver(spi_bus="spi2")})
        generate_config(parsed, user, str(tmp_path / f"{mode}.cfg"), verbose=False)


def test_wizard_uses_selected_model_and_active_z_count(tmp_path):
    built = built_bus(tmp_path)
    user = {"firmware_artifact": built, "driver_type": "TMC2130", "driver_mode": "SPI", "z_motors": 1}
    parsed = {"tmc2130 stepper_x": driver(spi_bus="spi2"),
              "tmc5160 stepper_x": driver(spi_bus="spi1"),
              "tmc2130 stepper_z1": driver("PC9", spi_bus="spi1")}
    with patch("core.wizard.steps.sensors._get_parsed", return_value=parsed):
        validator = make_pin_validator_with_collision_check(user)
        assert validator("PB8") is True
        assert "reserved by firmware for spi2" in validator("PB14")


@pytest.mark.parametrize("pin,bus,expected", [("PC8", "spi1", False),
    ("PC8", "spi2", True), ("toolhead:PC8", "spi1", True)])
def test_live_adapter_checks_bus_from_retained_nested_include(tmp_path, pin, bus, expected):
    built = built_bus(tmp_path)
    files = {"printer.cfg": GENERATED + b"[include user.cfg]\n",
             "user.cfg": b"[include driver.cfg]\n",
             "driver.cfg": f"[tmc2130 stepper_x]\ncs_pin: {pin}\nrun_current: 0.580\nspi_bus: {bus}\n".encode()}
    if pin.startswith("toolhead:"):
        files["driver.cfg"] = b"[mcu toolhead]\nserial: /dev/toolhead\n" + files["driver.cfg"]
    if pin.startswith("toolhead:"):
        files["driver.cfg"] += b"[mcu toolhead]\nserial: /dev/serial/by-id/toolhead\n"
    transport = FakeTransport(files)
    original = dict(transport.files)
    with patch("core.deployer._preflight_check", return_value=True), patch(
        "core.deployer._interactive_configuration_review", return_value=True):
        result = _run_config_transaction(transport, {"firmware_artifact": built}, "none",
                                         generated=(str(tmp_path / "source.cfg"), PROBE, None))
    if expected:
        assert result.outcome == WorkflowOutcome.DEPLOYED_PENDING_ACTIVATION
    else:
        assert result.outcome == WorkflowOutcome.PRECONDITION_FAILED
        assert "spi1" in result.detail
        assert_untouched(transport, original)


def test_later_include_override_is_resolved_before_selecting_bus(tmp_path):
    built = built_bus(tmp_path)
    remote = {"printer.cfg": GENERATED + b"[include driver.cfg]\n[include override.cfg]\n",
              "driver.cfg": b"[tmc2130 stepper_x]\ncs_pin: PC8\nrun_current: 0.580\nspi_bus: spi1\n",
              "override.cfg": b"[tmc2130 stepper_x]\nspi_bus: spi2\n"}
    plan = build_managed_config_plan(PROBE, None, remote)
    result = validate_configuration_plan(plan, firmware_reservation_reader=lambda hardware:
        generation_pin_reservations({"firmware_artifact": built}, config=hardware))
    assert result.valid, result.errors


@pytest.mark.parametrize("resume", [False, True])
def test_noop_cannot_bypass_default_bus_conflict(tmp_path, resume):
    built = built_bus(tmp_path)
    user = resumed_user(built) if resume else {"firmware_artifact": built}
    generated = PROBE + b"[tmc2130 stepper_x]\ncs_pin: PC8\nrun_current: 0.580\n"
    plan = build_managed_config_plan(generated, None, {})
    original = {item.remote_name: item.content for item in plan.artifacts}
    assert not build_managed_config_plan(generated, None, original).changed_artifacts
    transport = FakeTransport(original)
    result = ConfigDeploymentTransaction(transport, generated, None, activation="none",
        snapshot_root=str(tmp_path / "snapshots"), confirm=lambda _: True, verify_existing_ready=True,
        firmware_reservation_reader=lambda hardware:
            generation_pin_reservations(user, config=hardware)).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "spi1" in result.detail
    assert_untouched(transport, original)


def test_firmware_changed_during_confirmation_blocks_bus_publication(tmp_path):
    built = built_bus(tmp_path)
    generated = PROBE + b"[tmc2130 stepper_x]\ncs_pin: PC8\nrun_current: 0.580\nspi_bus: spi2\n"
    transport = FakeTransport({"printer.cfg": GENERATED})
    original = dict(transport.files)
    confirmations = []
    def confirm(_):
        confirmations.append(True)
        with open(built.path, "ab") as stream:
            stream.write(b"changed")
        return True
    result = ConfigDeploymentTransaction(transport, generated, None, activation="none",
        snapshot_root=str(tmp_path / "snapshots"), confirm=confirm,
        firmware_reservation_reader=lambda hardware:
            generation_pin_reservations({"firmware_artifact": built}, config=hardware)).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert confirmations == [True]
    assert_untouched(transport, original)
