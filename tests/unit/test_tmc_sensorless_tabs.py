"""Sensorless dependencies must survive whitespace-separated TMC headers."""
from copy import deepcopy

import pytest

from core.exceptions import GenerationError
from core.tmc_sensorless import validate_tmc_virtual_endstops
from tests.unit.test_sensorless_homing_enforcement import _sensorless


@pytest.mark.parametrize("model", ("tmc2209", "tmc2130", "tmc5160"))
@pytest.mark.parametrize("separator", (" ", "\t"))
def test_sensorless_driver_is_recognized_without_mutation(model, separator):
    data = _sensorless(model)
    data[model + separator + "stepper_x"] = data.pop(model + " stepper_x")
    before = deepcopy(data)
    validate_tmc_virtual_endstops(data)
    assert data == before


@pytest.mark.parametrize("model", ("tmc2209", "tmc2130", "tmc5160"))
@pytest.mark.parametrize("separator", (" ", "\t"))
def test_missing_diag_rejected_on_named_driver(model, separator):
    data = _sensorless(model)
    driver = data.pop(model + " stepper_x")
    driver.pop("diag_pin" if model == "tmc2209" else "diag1_pin")
    data[model + separator + "stepper_x"] = driver
    with pytest.raises(GenerationError, match="requires DIAG"):
        validate_tmc_virtual_endstops(data)


@pytest.mark.parametrize("separator", (" ", "\t", "  "))
@pytest.mark.parametrize("kinematics,target", (("corexy", "stepper_y"),
                                               ("cartesian", "stepper_x1")))
def test_participating_motor_cannot_hide_hold_current(separator, kinematics, target):
    data = _sensorless(kinematics=kinematics)
    data[target] = {"endstop_pin": "PB3"}
    data["tmc2209" + separator + target] = {"hold_current": "0.4"}
    with pytest.raises(GenerationError, match="hold_current"):
        validate_tmc_virtual_endstops(data)


@pytest.mark.parametrize("separator", (" ", "\t"))
def test_other_cartesian_motor_remains_allowed(separator):
    data = _sensorless()
    data["tmc2209" + separator + "stepper_y"] = {"hold_current": "0.4"}
    data["stepper_y"] = {"endstop_pin": "PB3"}
    before = deepcopy(data)
    validate_tmc_virtual_endstops(data)
    assert data == before
