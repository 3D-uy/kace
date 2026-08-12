import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class KlipperSweepContractTests(unittest.TestCase):
    def test_all_sweep_entrypoints_share_one_immutable_klipper_ref(self):
        contract = (ROOT / "tests" / "klipper_contract.py").read_text(encoding="utf-8")
        self.assertRegex(contract, r'KLIPPER_REF\s*=\s*"[0-9a-f]{40}"')

        for relative_path in (
            "tests/matrix/run_matrix.py",
            "tests/sweep/klipper_sweep.py",
            "tests/sweep/full_sweep_runner.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn("from tests.klipper_contract import", source, relative_path)
            self.assertNotRegex(source, r'fetch[^\n]+(?:master|main)', relative_path)
            self.assertNotRegex(source, r'checkout[^\n]+(?:master|main)', relative_path)

    def test_sweep_clones_verify_the_checked_out_commit(self):
        for relative_path in (
            "tests/sweep/klipper_sweep.py",
            "tests/sweep/full_sweep_runner.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn('"rev-parse", "HEAD"', source, relative_path)
            self.assertIn("KLIPPER_REF", source, relative_path)

    def test_manual_workflow_can_explicitly_enable_the_full_sweep(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertRegex(
            workflow,
            r"workflow_dispatch:[\s\S]+?full_klipper_sweep:[\s\S]+?type:\s*boolean",
        )
        self.assertRegex(
            workflow,
            r"full-klipper-sweep:[\s\S]+?github\.event_name == 'workflow_dispatch'"
            r"[\s\S]+?inputs\.full_klipper_sweep",
        )


if __name__ == "__main__":
    unittest.main()
