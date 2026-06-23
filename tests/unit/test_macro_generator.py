import os
import tempfile
import shutil
import unittest
from core.macro_generator import generate_starter_macros

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

if __name__ == "__main__":
    unittest.main()
