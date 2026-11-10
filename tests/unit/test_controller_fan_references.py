"""Malformed controller lists fail without pretending to resolve the registry."""
import pytest

from core.controller_fan_references import validate_controller_fan_references
from core.exceptions import GenerationError
from core.pin_validator import _read_pin_config


@pytest.mark.parametrize("option", ["heater", "stepper"])
@pytest.mark.parametrize("value", [",", ",extruder", "extruder,", "extruder,,Other", "extruder,\n  , Other"])
def test_empty_tokens_are_invalid(option, value):
    sections = _read_pin_config(f"[controller_fan Case]\n{option}: {value}\n")[0]
    with pytest.raises(GenerationError, match=option):
        validate_controller_fan_references(sections)


@pytest.mark.parametrize("fields", [
    "", "heater:\nstepper:\n", "heater: # empty\nstepper: ; empty\n",
    "heater: extruder\n", "stepper: stepper_x, stepper_z1\n",
    "stepper: manual_stepper Lift, extruder_stepper Feeder\n",
    "heater: Chamber, extruder\nstepper: stepper_x,\n  stepper_y\n",
    "heater: Missing\nstepper: External motor\n", "heater: Extruder\n"
])
def test_names_defaults_and_empty_lists_are_not_rewritten(fields):
    sections = _read_pin_config("[controller_fan Case]\n"+fields)[0]
    before = {k:dict(v) for k,v in sections.items()}
    validate_controller_fan_references(sections)
    assert sections == before


@pytest.mark.parametrize("section", ["heater_fan Other", "fan_generic Other", "Controller_fan Other", "controller_fanatic Other"])
def test_other_consumers_are_outside_this_gate(section):
    validate_controller_fan_references({section:{"heater":","}})
