"""The digest uses the generation probe contract and shared motion geometry."""

import copy
import os
from unittest.mock import patch

import pytest

from core.custom_probe import parse_custom_probe_config
from core.exceptions import GenerationError
from core.menu import _plain_label
from core.summary import print_summary
from core.translations import get_lang, set_lang, t


def _state(**changes):
    state = {
        "x_size": 300, "y_size": 300, "z_size": 350,
        "x_position_min": 0, "x_position_max": 300,
        "y_position_min": -8, "y_position_max": 300,
        "z_position_min": 0, "z_position_max": 350,
        "z_position_endstop": 0.5, "probe": "None",
    }
    state.update(changes)
    return state


def _render(state, capsys, parsed=None):
    with patch("shutil.get_terminal_size", return_value=os.terminal_size((120, 30))):
        print_summary(state, parsed)
    return " ".join(_plain_label(capsys.readouterr().out).split())


def test_printable_bounds_preserve_explicit_nonzero_origin(capsys):
    state = _state(printable_x_min=20, printable_x_max=280,
                   printable_y_min=15, printable_y_max=290)
    output = _render(state, capsys)
    assert f"{t('summary.printable_bed')} X [20, 280], Y [15, 290]" in output
    assert "X [0, 300], Y [-8, 300], Z [0, 350]" in output


@pytest.mark.parametrize("probe", ["None", "BLTouch", "CR-Touch", "Inductive"])
def test_homed_z_uses_probe_trigger_only_for_virtual_endstop(probe, capsys):
    state = _state(probe=probe)
    before = copy.deepcopy(state)
    output = _render(state, capsys)
    if probe == "None":
        assert "Z [0.5]" in output
        assert t("summary.probe_homed_z", offset="0") not in output
        assert t("summary.probeable_bed") not in output
    else:
        assert t("summary.probe_homed_z", offset="0") in output
        assert "Z [0.5]" not in output
    assert state == before


@pytest.mark.parametrize("offset", [0, 1.25])
@pytest.mark.parametrize("language", ["English", "Español", "Português"])
def test_raw_probe_offsets_feed_digest_mesh_and_virtual_z_without_mutation(offset, language, capsys):
    previous = get_lang()
    raw = f"# imported\r\n[probe]\r\npin: ^P0.10\r\nx_offset: -9\r\ny_offset: 1\r\nz_offset: {offset} # keep\r\n"
    state = _state(probe="Custom Probe", custom_probe=parse_custom_probe_config(raw))
    before = copy.deepcopy(state)
    try:
        set_lang(language)
        # Keep the real mesh calculator: missing legacy offsets must not turn
        # the custom raw -9/1 geometry into a zero-offset mesh.
        output = _render(state, capsys, {"probe": {"pin": "^P0.10"}})
        assert "X = -9.0 Y = +1.0" in output
        assert "X [0, 291], Y [0, 300]" in output
        assert t("summary.probe_homed_z", offset=f"{offset:g}") in output
        assert "Z [0.5]" not in output
        assert f"{t('summary.mesh_max')} 281.0, 290.0" in output
        assert state == before
        assert state["custom_probe"].config_text == raw
        assert "probe_x_offset" not in state and "probe_y_offset" not in state
    finally:
        set_lang(previous)


def test_absent_probe_never_calls_mesh_calculator(capsys):
    state = _state()
    state.pop("probe")
    with patch("core.summary.generate_bed_mesh_config") as calculate:
        _render(state, capsys, {"stepper_z": {"position_max": "350"}})
    calculate.assert_not_called()


def test_summary_rejects_legacy_offset_drift_without_changing_custom_block(capsys):
    state = _state(probe="Custom Probe", probe_x_offset=0,
                   custom_probe=parse_custom_probe_config(
                       "[probe]\npin: ^P0.10\nx_offset: -9\ny_offset: 1\nz_offset: 0\n"))
    before = copy.deepcopy(state)
    with pytest.raises(GenerationError, match="conflicts"):
        _render(state, capsys)
    assert state == before
