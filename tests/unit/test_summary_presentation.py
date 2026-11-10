"""Generated configuration retains its digest and does not claim installation success."""

import copy
import os
from unittest.mock import patch

import pytest
from wcwidth import wcswidth

from core.menu import _plain_label
from core.summary import print_summary
from core.translations import get_lang, set_lang, t


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
@pytest.mark.parametrize("columns", [60, 80, 120])
def test_generated_summary_wraps_digest_and_reports_pending_application(language, columns, capsys):
    previous = get_lang()
    state = {
        "printer_profile": "printer-example.cfg", "board": "generic-bigtreetech-skr-v1.4.cfg",
        "mcu_type": "lpc1769", "kinematics": "cartesian",
        "x_size": 300, "y_size": 300, "z_size": 350,
        "probe": "BLTouch", "probe_x_offset": -38, "probe_y_offset": 12,
        "driver_type": "TMC2209", "driver_mode": "UART", "web_interface": "Mainsail",
        "hotend_thermistor": "Generic 3950", "bed_thermistor": "Generic 3950",
    }
    before = copy.deepcopy(state)
    mesh = {"mesh_min": "20, 20", "mesh_max": "250, 250", "probe_count": "5, 5", "algorithm": "bicubic"}
    try:
        set_lang(language)
        with patch("shutil.get_terminal_size", return_value=os.terminal_size((columns, 24))), \
                patch("core.summary.generate_bed_mesh_config", return_value=mesh):
            print_summary(state, {"probe": {"pin": "PA1"}})
        text = _plain_label(capsys.readouterr().out)
        normalized = " ".join(text.split())
        assert all(wcswidth(line) <= columns for line in text.splitlines())
        for value in ("printer-example.cfg", "generic-bigtreetech-skr-v1.4.cfg", "LPC1769",
                      "300 × 300 × 350 mm", "Generic 3950", "bicubic", "~/kace/printer.cfg"):
            assert value in normalized
        for key in ("summary.generated_title", "summary.application_pending", "summary.motion_model",
                    "summary.generated_mesh", "summary.mesh_min", "summary.mesh_max",
                    "summary.probe_count", "summary.mesh_algorithm"):
            assert " ".join(t(key).split()) in normalized
        assert normalized.count(" ".join(t("summary.application_pending").split())) == 1
        assert t("summary.happy_printing") not in text
        assert "🎉" not in text and "✅" not in text
        assert state == before
    finally:
        set_lang(previous)
