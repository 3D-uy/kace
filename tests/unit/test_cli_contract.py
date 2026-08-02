"""Regression checks for CLI switches documented to users."""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestCliContract(unittest.TestCase):
    def test_real_build_flag_enables_real_build_environment(self):
        source = (ROOT / "kace.py").read_text(encoding="utf-8")
        self.assertIn('_ap.add_argument("--real-build"', source)
        self.assertIn('if _known.real_build:', source)
        self.assertIn('os.environ["KACE_REAL_BUILD"] = "1"', source)


if __name__ == "__main__":
    unittest.main()
