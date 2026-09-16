import re
import unittest
from pathlib import Path
from unittest.mock import patch

from firmware.boards.upstream import load_klipper_source_contract
from tests.klipper_contract import KLIPPER_REF, KLIPPER_REPO_URL
from tests.regression import test_mcu_builds as mcu_builds


ROOT = Path(__file__).resolve().parents[2]


class KlipperSweepContractTests(unittest.TestCase):
    def test_all_sweep_entrypoints_share_one_immutable_klipper_ref(self):
        contract = load_klipper_source_contract()
        self.assertRegex(KLIPPER_REF, r"^[0-9a-f]{40}$")
        self.assertEqual(contract.validated_commit, KLIPPER_REF)
        self.assertEqual(contract.repository, KLIPPER_REPO_URL)

        for relative_path in (
            "tests/matrix/run_matrix.py",
            "tests/sweep/klipper_sweep.py",
            "tests/sweep/full_sweep_runner.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn("from tests.klipper_contract import", source, relative_path)
            self.assertNotRegex(source, r'fetch[^\n]+(?:master|main)', relative_path)
            self.assertNotRegex(source, r'checkout[^\n]+(?:master|main)', relative_path)

    def test_bootstrap_uses_the_board_contract_revision(self):
        source = (ROOT / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")
        contract = load_klipper_source_contract()
        self.assertEqual(
            re.search(r'^KLIPPER_REF="([^"]+)"$', source, re.MULTILINE).group(1),
            contract.validated_commit,
        )
        self.assertEqual(
            re.search(r'^KLIPPER_REPOSITORY="([^"]+)"$', source, re.MULTILINE).group(1),
            contract.repository,
        )

    @patch.object(mcu_builds.subprocess, "run")
    def test_legacy_build_fixture_fetches_and_verifies_contract_commit(self, run):
        run.return_value.stdout = KLIPPER_REF + "\n"
        try:
            mcu_builds.TestMCUBuilds.setUpClass()
            commands = [call.args[0] for call in run.call_args_list]
            self.assertIn(["git", "fetch", "--depth=1", "origin", KLIPPER_REF], commands)
            self.assertIn(["git", "checkout", "--detach", KLIPPER_REF], commands)
            self.assertIn(["git", "rev-parse", "HEAD"], commands)
            self.assertNotIn("clone", [arg for command in commands for arg in command])
        finally:
            mcu_builds.TestMCUBuilds.doClassCleanups()

    @patch.object(mcu_builds.subprocess, "run")
    def test_legacy_build_fixture_rejects_another_revision(self, run):
        run.return_value.stdout = "0" * 40 + "\n"
        try:
            with self.assertRaisesRegex(RuntimeError, "Klipper checkout mismatch"):
                mcu_builds.TestMCUBuilds.setUpClass()
        finally:
            mcu_builds.TestMCUBuilds.doClassCleanups()

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
