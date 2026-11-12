"""Readable columns and restrained semantic colours without changing evidence."""
import copy
import os
from unittest.mock import patch

import pytest
from wcwidth import wcswidth

from core.firmware_wizard import _print_board_contract_firmware_review, run_firmware_wizard
from core.menu import _plain_label
from core.summary import print_summary
from core.terminal import RESET, SECTION, WARNING
from core.translations import get_lang, set_lang, t
from firmware.boards.runtime import resolve_firmware_authority


@pytest.fixture(autouse=True)
def restore_locale():
    previous = get_lang()
    yield
    set_lang(previous)


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
@pytest.mark.parametrize("columns", [80, 114, 160])
def test_firmware_columns_filename_help_and_panel_boundary(language, columns, capsys):
    set_lang(language)
    decision = resolve_firmware_authority("generic-bigtreetech-skr-v1.4.cfg", detected_mcu="lpc1769")
    with patch("shutil.get_terminal_size", return_value=os.terminal_size((columns, 29))):
        _print_board_contract_firmware_review(decision, detected_mcu="lpc1769")
    raw = capsys.readouterr().out.splitlines()
    lines = [_plain_label(line) for line in raw]
    bound = max(wcswidth(line) for line in lines if "─" in line)
    assert all(wcswidth(line) <= bound for line in lines)
    keys = ("builder.contract_board", "builder.hardware_variant", "builder.processor",
            "builder.comm_interface", "builder.artifact_filename", "builder.flash_method")
    fields = [next(line for line in lines if line.strip().startswith(t(key).rstrip(":"))) for key in keys]
    assert len({wcswidth(line[:line.index(":")]) for line in fields}) == 1
    assert fields[4].endswith(": firmware.bin")
    for key in keys:
        row = next(line for line in raw if t(key).rstrip(":") in line)
        assert SECTION not in row
        assert row.index(WARNING) > row.index(":")
        assert row.endswith(RESET)
        assert row.count(WARNING) == 1
    assert any(SECTION in line and t("builder.summary_title") in line for line in raw)
    # Ordinary instructions remain white even when wrapping over several lines.
    help_start = t("firmware.review.next").split()[0]
    help_line = next(line for line in raw if _plain_label(line).strip().startswith(help_start))
    assert SECTION not in help_line and WARNING not in help_line


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
@pytest.mark.parametrize("columns", [80, 114, 160])
def test_summary_groups_use_white_rows_and_one_panel_width(language, columns, capsys):
    set_lang(language)
    data = {"board": "generic-bigtreetech-skr-v1.4.cfg", "mcu_type": "lpc1769",
            "kinematics": "cartesian", "x_size": 300, "y_size": 300, "z_size": 350,
            "probe": "BLTouch", "probe_x_offset": -38, "probe_y_offset": 12,
            "driver_type": "TMC2209", "driver_mode": "UART", "macros_generated": True}
    before = copy.deepcopy(data)
    with patch("shutil.get_terminal_size", return_value=os.terminal_size((columns, 29))):
        print_summary(data)
    raw = capsys.readouterr().out.splitlines()
    lines = [_plain_label(line) for line in raw]
    bound = max(wcswidth(line) for line in lines if "═" in line)
    assert all(wcswidth(line) <= bound for line in lines)
    for key in ("summary.probe_group", "summary.motion_model", "summary.generated_files", "summary.next_steps"):
        index = next(index for index, line in enumerate(lines) if line.strip() == t(key))
        assert not lines[index - 1].strip()
        assert SECTION in raw[index] and "\033[1m" not in raw[index]
    for key in ("summary.board", "summary.mcu", "summary.driver_type", "summary.probe_offsets"):
        line = next(line for line in raw if t(key).rstrip(":") + ":" in line)
        assert SECTION not in line and WARNING not in line
    assert data == before


def test_contract_builder_owns_the_single_compilation_phase_message(capsys):
    def builder(*args):
        print("[fixture] Compilando firmware")
        raise RuntimeError("fixture stops before compiling")
    with patch("core.firmware_wizard.numbered_select", return_value="compile"), \
         patch("core.firmware_wizard.build_board_contract_runtime", side_effect=builder):
        run_firmware_wizard({"board": "generic-bigtreetech-skr-v1.4.cfg", "mcu_type": "lpc1769"})
    output = capsys.readouterr().out
    assert output.count("[fixture] Compilando firmware") == 1
    assert t("kace.compiling") not in output
