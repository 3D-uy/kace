"""The selected watermark controller owns a positive, finite deadband."""
import copy

import pytest

from core.exceptions import GenerationError
from core.heater_options import validate_heater_options


HEATERS = ["extruder", "extruder1", "heater_bed", "heater_generic chamber"]


@pytest.mark.parametrize("section", HEATERS)
@pytest.mark.parametrize("value", ["0", "-0.25", "nan", "inf", "-inf", "bad", ""])
def test_active_watermark_rejects_invalid_delta(section, value):
    # > 0 follows the pinned controller; finiteness is KACE's own policy.
    with pytest.raises(GenerationError, match="max_delta"):
        validate_heater_options({section: {"control": "watermark", "max_delta": value}})


@pytest.mark.parametrize("section", HEATERS)
@pytest.mark.parametrize("value", [None, "0.000001", "2", " 2.75 ", "1000000"])
def test_positive_delta_and_omitted_default_preserved(section, value):
    fields = {"control": "watermark"}
    if value is not None:
        fields["max_delta"] = value
    sections = {section: fields}
    original = copy.deepcopy(sections)
    validate_heater_options(sections)
    assert sections == original


@pytest.mark.parametrize("control", [None, "pid", "custom_controller"])
def test_inactive_delta_does_not_invent_watermark_activation(control):
    # Required controller/unused option checks have separate owners.
    fields = {"max_delta": "nan"}
    if control is not None:
        fields["control"] = control
    validate_heater_options({"heater_bed": fields})


def test_other_sensor_registries_are_outside_heater_delta_contract():
    validate_heater_options({
        "temperature_fan chamber": {"control": "watermark", "max_delta": "nan"},
        "temperature_sensor room": {"control": "watermark", "max_delta": "0"},
    })
