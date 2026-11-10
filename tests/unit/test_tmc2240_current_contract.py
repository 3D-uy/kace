"""Preserved TMC2240 current is constrained by Rref, not generic TMC limits."""
import copy
import math

import pytest

from core.exceptions import GenerationError
from core.profile_values import validate_tmc_current_settings, resolve_tmc_sections
from tests.unit.test_generator import _user


def validate(options):
    validate_tmc_current_settings({"tmc2240 stepper_x": options})


@pytest.mark.parametrize("value", ["11999", "60001", "0", "nan", "inf", "", None])
def test_rref_is_finite_and_within_official_range(value):
    with pytest.raises(GenerationError, match="rref"):
        validate({"run_current": "0.3", "rref": value})


@pytest.mark.parametrize("option", ["run_current", "hold_current"])
@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "-inf", "", None, "2.2"])
def test_current_rejects_invalid_or_excess_value(option, value):
    with pytest.raises(GenerationError, match=option):
        validate({"run_current": "0.5", option: value})


def test_run_current_is_required():
    with pytest.raises(GenerationError, match="run_current"):
        validate({})


@pytest.mark.parametrize("rref", [12000., 24000., 60000.])
@pytest.mark.parametrize("option", ["run_current", "hold_current"])
def test_exact_current_ceiling_tracks_rref_without_rounding(rref, option):
    # Preserve the exact arithmetic order in the pinned TMC2240CurrentHelper.
    ceiling = (36000. / rref) / math.sqrt(2.)
    options = {"rref": str(rref), "run_current": ".1", option: repr(ceiling)}
    validate(options)
    with pytest.raises(GenerationError, match=option):
        validate({**options, option: repr(math.nextafter(ceiling, math.inf))})


@pytest.mark.parametrize("options", [
    {"run_current": "2.1"},
    {"run_current": ".4", "rref": "60000"},
    {"run_current": ".4", "hold_current": "2.1"},
    {"run_current": ".1", "rref": "24000", "hold_current": ".2"},
])
def test_compatible_values_and_omissions_are_not_rewritten(options):
    original = copy.deepcopy(options)
    validate(options)
    assert options == original


@pytest.mark.parametrize("mode", ["UART", "SPI"])
def test_validation_does_not_enable_guided_tmc2240_generation(mode):
    with pytest.raises(GenerationError, match="Unsupported TMC model"):
        resolve_tmc_sections({}, _user(driver_type="TMC2240", driver_mode=mode))
