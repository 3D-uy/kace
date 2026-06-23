# tests/unit/test_summary.py
#
# Unit tests for core/summary.py (print_summary).

import unittest
from unittest.mock import patch
import io
import sys

from core.summary import print_summary

class TestSummaryPrinter(unittest.TestCase):

    def test_print_summary_basic(self):
        """Verify summary printer outputs core information correctly."""
        user_data = {
            "printer_profile": "Ender 3",
            "board": "Creality v4.2.2",
            "mcu_type": "stm32f103",
            "kinematics": "cartesian",
            "x_size": 220.0,
            "y_size": 220.0,
            "z_size": 250.0,
            "probe": "None",
            "driver_type": "TMC2209",
            "driver_mode": "UART",
            "display_choice": "none",
            "web_interface": "Mainsail",
            "hotend_thermistor": "EPCOS 100K",
            "bed_thermistor": "EPCOS 100K",
            "macros_generated": True,
            "firmware_path": "/fake/kace/klipper.bin"
        }

        # Capture stdout
        captured = io.StringIO()
        sys.stdout = captured
        try:
            print_summary(user_data)
        finally:
            sys.stdout = sys.__stdout__

        output = captured.getvalue()
        self.assertIn("Ender 3", output)
        self.assertIn("Creality v4.2.2", output)
        self.assertIn("STM32F103", output)
        self.assertIn("cartesian", output)
        self.assertIn("220.0 × 220.0 × 250.0 mm", output)
        self.assertIn("klipper.bin", output)

    def test_print_summary_with_probe_offsets(self):
        """Verify summary printer displays probe offsets correctly."""
        user_data = {
            "printer_profile": "Ender 3",
            "board": "Creality v4.2.2",
            "mcu_type": "stm32f103",
            "kinematics": "cartesian",
            "x_size": 220.0,
            "y_size": 220.0,
            "z_size": 250.0,
            "probe": "BLTouch",
            "probe_x_offset": "-44.0",
            "probe_y_offset": "-9.0",
            "driver_type": "TMC2209",
            "display_choice": "none",
            "web_interface": "Mainsail",
            "hotend_thermistor": "EPCOS 100K",
            "bed_thermistor": "EPCOS 100K"
        }

        captured = io.StringIO()
        sys.stdout = captured
        try:
            print_summary(user_data)
        finally:
            sys.stdout = sys.__stdout__

        output = captured.getvalue()
        self.assertIn("BLTouch", output)
        self.assertIn("X = -44.0   Y = -9.0", output)

if __name__ == '__main__':
    unittest.main()
