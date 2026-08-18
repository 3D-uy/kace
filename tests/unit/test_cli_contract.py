"""Regression checks for CLI switches documented to users."""

import unittest
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


class TestCliContract(unittest.TestCase):
    def test_real_build_flag_enables_real_build_environment(self):
        source = (ROOT / "kace.py").read_text(encoding="utf-8")
        self.assertIn('_ap.add_argument("--real-build"', source)
        self.assertIn('if _known.real_build:', source)
        self.assertIn('os.environ["KACE_REAL_BUILD"] = "1"', source)

    def test_normal_execution_rejects_unknown_arguments(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "kace.py"), "--not-a-kace-option", "--version"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("unrecognized arguments: --not-a-kace-option", result.stderr)

    def test_physical_board_contract_flag_is_explicit_and_not_auto_compatible(self):
        source = (ROOT / "kace.py").read_text(encoding="utf-8")
        self.assertIn('"--board-contract-sd-deploy"', source)
        self.assertIn('os.environ["KACE_BOARD_CONTRACT_SD_DEPLOY"] = "1"', source)
        result = subprocess.run(
            [
                sys.executable, str(ROOT / "kace.py"),
                "--auto", "--board-contract-sd-deploy",
            ],
            cwd=ROOT, capture_output=True, text=True, timeout=10, check=False,
        )
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertIn("cannot be combined with --auto", result.stderr)

    def test_cli_does_not_use_parse_known_args(self):
        source = (ROOT / "kace.py").read_text(encoding="utf-8")
        self.assertNotIn("parse_known_args", source)


if __name__ == "__main__":
    unittest.main()
