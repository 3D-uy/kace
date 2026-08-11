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
        venv_index = self.script.index('python3 -m venv "$STAGING_DIR/venv"')
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

    def test_pinned_source_revision_is_verified_after_checkout(self):
        self.assertIn("KACE_EXPECTED_COMMIT", self.script)
        self.assertIn("FETCH_HEAD^{commit}", self.script)
        self.assertRegex(
            self.script,
            r'ACTUAL_COMMIT=.*rev-parse --verify HEAD',
        )
        self.assertIn('"$ACTUAL_COMMIT" != "$EXPECTED_COMMIT"', self.script)

    def test_install_does_not_mutate_hostname_resolution(self):
        self.assertNotIn("tee -a /etc/hosts", self.script)
        self.assertNotIn("Attempting to add", self.script)

    def test_dependencies_are_built_in_a_fresh_staging_environment(self):
        self.assertIn("STAGING_DIR", self.script)
        self.assertIn('python3 -m venv "$STAGING_DIR/venv"', self.script)
        self.assertNotIn("pip\" install --upgrade pip", self.script)
        self.assertIn('--require-hashes -r "$STAGING_DIR/requirements.txt"', self.script)
        self.assertIn('KACE_VENV_FROM="$STAGING_DIR"', self.script)
        self.assertIn('data.replace(source, target)', self.script)

    def test_runtime_publication_has_rollback_and_preserves_generated_state(self):
        self.assertIn("_RUNTIME_PATHS", self.script)
        self.assertIn("rollback_publication", self.script)
        self.assertIn("flock -n 9", self.script)
        self.assertIn('PUBLISHED_COMMIT=$(git -C "$INSTALL_DIR" rev-parse --verify HEAD)', self.script)
        self.assertIn("Published virtual environment failed its import preflight", self.script)
        self.assertNotIn('checkout -f FETCH_HEAD', self.script)

    def test_global_wrapper_is_published_atomically(self):
        self.assertRegex(self.script, r'mktemp .*KACE_BIN')
        self.assertRegex(self.script, r'mv .*KACE_BIN')
        self.assertNotIn('sudo tee "$KACE_BIN"', self.script)

    def test_unattended_install_can_finish_without_launching_wizard(self):
        guard_index = self.script.index('${KACE_NO_LAUNCH:-0}')
        tty_index = self.script.index('exec < /dev/tty')
        self.assertLess(guard_index, tty_index)
        unattended_block = self.script[guard_index:tty_index]
        self.assertIn("exit 0", unattended_block)


if __name__ == "__main__":
    unittest.main()
