# tests/unit/test_macro_generator.py
# Klipper source: https://www.klipper3d.org/Command_Templates.html
#
import os
import tempfile
import shutil
import unittest
from core.macro_generator import generate_starter_macros
from core.motion_model import PrinterMotionSpace

class TestMacroGenerator(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_generate_starter_macros(self):
        macros_path = generate_starter_macros(self.test_dir)
        self.assertTrue(os.path.exists(macros_path))
        self.assertEqual(os.path.basename(macros_path), "macros.cfg")

        with open(macros_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("[gcode_macro PID_HOTEND]", content)
        self.assertIn("[gcode_macro PID_BED]", content)
        self.assertIn("[gcode_macro HOME_AND_CENTER]", content)

    def test_small_bed_macros_use_reachable_geometry(self):
        space = PrinterMotionSpace({
            "x_size": "60", "y_size": "70", "z_size": "30",
            "x_position_max": "60", "y_position_max": "70", "z_position_max": "30",
        })
        macros_path = generate_starter_macros(self.test_dir, motion_space=space)
        with open(macros_path, "r", encoding="utf-8") as macros_file:
            content = macros_file.read()
        self.assertIn("G1 X30 Y35 Z6 F3000", content)
        self.assertIn("G1 X6 Y7 Z6 F3000", content)
        self.assertNotIn("X110 Y110 Z50", content)

    def test_macro_z_positions_respect_positive_minimum(self):
        space = PrinterMotionSpace({
            "x_size": "100", "y_size": "100", "z_size": "250",
            "x_position_max": "100", "y_position_max": "100",
            "z_position_min": "30", "z_position_max": "250",
            "printable_z_max": "200",
        })
        positions = space.starter_macro_positions()
        self.assertGreaterEqual(positions["center"][2], 30)
        self.assertGreaterEqual(positions["test"][2], 30)

    def test_pid_control_keeps_both_pid_macros(self):
        macros_path = generate_starter_macros(
            self.test_dir, hotend_control="pid", bed_control="pid"
        )
        with open(macros_path, "r", encoding="utf-8") as macros_file:
            content = macros_file.read()
        self.assertIn("[gcode_macro PID_HOTEND]", content)
        self.assertIn("[gcode_macro PID_BED]", content)

    def test_watermark_bed_omits_pid_bed_macro(self):
        macros_path = generate_starter_macros(self.test_dir, bed_control="watermark")
        with open(macros_path, "r", encoding="utf-8") as macros_file:
            content = macros_file.read()
        self.assertNotIn("[gcode_macro PID_BED]", content)

if __name__ == "__main__":
    unittest.main()
