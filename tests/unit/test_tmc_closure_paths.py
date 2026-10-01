"""Final K04 routes: every generated target/model and original shared UART."""
from copy import deepcopy
from unittest.mock import Mock

import pytest

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.generator import generate_config
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.pin_validator import _read_pin_config
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_generator import _parsed, _user
from tests.unit.test_reserved_pin_review import assert_untouched
from tests.unit.test_tmc_chain_reservations import SOFTWARE

MODELS = ("tmc2208", "tmc2225", "tmc2209", "tmc2130", "tmc5160")
TARGETS = ("stepper_x", "stepper_y", "stepper_z", "stepper_z1", "stepper_z2", "stepper_z3", "extruder")


def matrix_inputs(model, target):
    parsed = _parsed()
    for index in range(1, 4):
        parsed[f"stepper_z{index}"] = dict(parsed["stepper_z"], step_pin=f"PF{index}", dir_pin=f"PG{index}", enable_pin=f"!PH{index}")
    canonical = "tmc2208" if model == "tmc2225" else model
    options = {"run_current": "0.580", "sense_resistor": "0.150", "interpolate": "False", "driver_toff": "3"}
    mode = "UART" if canonical in ("tmc2208", "tmc2209") else "SPI"
    if mode == "UART":
        options.update(uart_pin="PC11", tx_pin="PC10", uart_address="3" if model == "tmc2209" else "0")
        if model == "tmc2209":
            options.update(diag_pin="^PC6", driver_sgthrs="80")
    else:
        options.update(cs_pin="PC11", **SOFTWARE, spi_speed="1000000", driver_sgt="-10", diag1_pin="^!PC6")
    name = canonical + " " + target
    parsed[name] = options
    return parsed, _user(driver_type=model.upper(), driver_mode=mode, z_motors="4"), name


def original_inputs(sensorless=False):
    parsed = _parsed()
    for index, target in enumerate(("stepper_x", "stepper_y", "stepper_z", "extruder")):
        parsed["tmc2209 " + target] = {"uart_pin": "PC11", "tx_pin": "PC10", "uart_address": str(index),
            "run_current": "0.8"}
        if target != "extruder":
            parsed["tmc2209 " + target].update(sense_resistor="0.150", diag_pin="^PA1", driver_sgthrs="80")
    if sensorless:
        # Separate extension of the original fixture: distinct DIAG GPIO for
        # active X/Y endstops. The original reused PA1 only as inactive metadata.
        for axis, diag in (("x", "^PC6"), ("y", "^PC7")):
            parsed["tmc2209 stepper_" + axis]["diag_pin"] = diag
            parsed["stepper_" + axis].update(endstop_pin=f"tmc2209_stepper_{axis}:virtual_endstop", homing_retract_dist="0")
    return parsed, _user(driver_type="TMC2209", driver_mode="UART")


def generate(parsed, user, path):
    return generate_config(parsed, user, output_path=str(path), verbose=False)["content"]


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("target", TARGETS)
def test_every_emitted_target_retains_selected_options(tmp_path, model, target):
    parsed, user, section = matrix_inputs(model, target)
    expected = deepcopy(parsed[section])
    content = generate(parsed, user, tmp_path / "printer.cfg")
    assert _read_pin_config(content)[0][section] == expected
    plan = build_managed_config_plan(content.encode(), None, {})
    assert validate_configuration_plan(plan).valid
    assert _read_pin_config(effective_hardware_text(plan))[0][section] == expected


@pytest.mark.parametrize("sensorless", (False, True))
def test_original_shared_uart_survives_reconciliation_and_noop(tmp_path, sensorless):
    parsed, user = original_inputs(sensorless)
    expected = {name: deepcopy(options) for name, options in parsed.items() if name.startswith("tmc")}
    content = generate(parsed, user, tmp_path / "printer.cfg")
    plan = build_managed_config_plan(content.encode(), None, {"printer.cfg": content.encode()})
    assert validate_configuration_plan(plan).valid
    effective = _read_pin_config(effective_hardware_text(plan))[0]
    assert {name: effective[name] for name in expected} == expected
    remote = {a.remote_name: a.content for a in plan.artifacts}
    second = build_managed_config_plan(content.encode(), None, remote)
    assert not second.changed_artifacts
    assert validate_configuration_plan(second).valid


@pytest.mark.parametrize("field,value", (("uart_address", "0"), ("sense_resistor", "0"), ("diag_pin", "^PC6"), ("driver_sgthrs", "256")))
@pytest.mark.parametrize("noop", (False, True))
def test_corrupt_included_original_configuration_blocks_publication(tmp_path, field, value, noop):
    parsed, user = original_inputs(True)
    content = generate(parsed, user, tmp_path / "printer.cfg")
    remote = {"printer.cfg": content.encode() + b"\n[include tuning.cfg]\n",
        "tuning.cfg": f"[tmc2209 stepper_y]\n{field}: {value}\n".encode()}
    if noop:
        plan = build_managed_config_plan(content.encode(), None, remote)
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        assert not build_managed_config_plan(content.encode(), None, remote).changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, content.encode(), None, activation="none", confirm=confirm,
        snapshot_root=str(tmp_path / "snapshots"), verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    confirm.assert_not_called()
    assert_untouched(transport, remote)
