"""Preserve the pinned distinction between omitted and empty heater lists."""
import pytest
from core.exceptions import GenerationError
from core.hotend_fan import validate_heater_fan_options
from core.managed_config import _section_options
from tests.unit.test_hotend_fan_options import board, render, SOURCE


@pytest.mark.parametrize("value", ["", "   ", "# no heaters", "; no heaters", "\n    # no heaters"])
def test_explicit_empty_list_needs_no_heater_object(value):
    validate_heater_fan_options(f"[heater_fan Audit]\npin: PG10\nheater: {value}\n")


@pytest.mark.parametrize("value", [",", "extruder,", ",extruder", "extruder,,heater_bed", "missing"])
def test_nonempty_invalid_list_remains_rejected(value):
    with pytest.raises(GenerationError, match="heater references"):
        validate_heater_fan_options(
            f"[extruder]\n[heater_bed]\n[heater_fan Audit]\npin: PG10\nheater: {value}\n")


def test_omitted_list_still_requires_default_extruder():
    with pytest.raises(GenerationError, match="extruder"):
        validate_heater_fan_options("[heater_fan Audit]\npin: PG10\n")
    validate_heater_fan_options("[extruder]\n[heater_fan Audit]\npin: PG10\n")


def test_selected_source_preserves_explicit_empty_through_generation(tmp_path):
    parsed, _ = board({"pin": "PC7", "heater": "", "fan_speed": "0"})
    content = render(tmp_path, parsed, fan_hotend_pin="PC7")
    fields = _section_options(content)[SOURCE]
    assert fields["heater"] == ""
    assert fields["fan_speed"] == "0"
