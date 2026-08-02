"""Regression tests for files and prerequisites required by a minimal install."""

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "install.sh"
FIRMWARE_BUILDER = ROOT / "firmware" / "builder.py"


class TestInstallRuntimeContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = INSTALLER.read_text(encoding="utf-8")

    def test_installs_venv_package_before_creating_environment(self):
        dependency_index = self.script.index("python3-venv")
        venv_index = self.script.index('python3 -m venv "$INSTALL_DIR/venv"')
        self.assertLess(dependency_index, venv_index)

    def test_enforces_documented_minimum_python(self):
        self.assertIn("sys.version_info < (3, 11)", self.script)

    def test_sparse_checkout_contains_firmware_compiler_wrapper(self):
        wrapper_reference = re.search(
            r'"scripts"\s*,\s*"cc_wrapper\.py"',
            FIRMWARE_BUILDER.read_text(encoding="utf-8"),
            re.DOTALL,
        )
        self.assertIsNotNone(wrapper_reference)
        self.assertIn("/scripts/cc_wrapper.py", self.script)

    def test_source_revision_can_be_pinned_to_a_commit(self):
        self.assertIn('INSTALL_REF="${KACE_SOURCE_REF:-main}"', self.script)
        self.assertIn('fetch origin "$INSTALL_REF" --depth=1', self.script)
        self.assertNotIn('--branch "$INSTALL_REF"', self.script)


if __name__ == "__main__":
    unittest.main()
