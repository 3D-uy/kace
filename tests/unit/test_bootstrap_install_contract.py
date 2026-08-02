"""Regression tests for the immutable bootstrap/install.sh contract."""

from __future__ import annotations

import hashlib
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = ROOT / "scripts" / "bootstrap.sh"
INSTALLER = ROOT / "install.sh"


def _shell_assignment(script: str, name: str) -> str:
    match = re.search(rf'^{name}="([^"]+)"$', script, re.MULTILINE)
    if not match:
        raise AssertionError(f"Missing shell assignment for {name}")
    return match.group(1)


class TestBootstrapInstallContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = BOOTSTRAP.read_text(encoding="utf-8")
        cls.install_ref = _shell_assignment(cls.script, "KACE_INSTALL_REF")
        cls.install_sha256 = _shell_assignment(cls.script, "KACE_INSTALL_SHA256")
        cls.install_url = _shell_assignment(cls.script, "KACE_INSTALL_URL")

    def test_contract_uses_an_immutable_git_reference(self):
        self.assertRegex(self.install_ref, r"^[0-9a-f]{40}$")
        self.assertEqual(
            self.install_url,
            "https://raw.githubusercontent.com/3D-uy/KACE/${KACE_INSTALL_REF}/install.sh",
        )
        self.assertNotIn("/main/install.sh", self.script)

    def test_current_installer_matches_contract_hash(self):
        actual = hashlib.sha256(INSTALLER.read_bytes()).hexdigest()
        self.assertEqual(actual, self.install_sha256)

    def test_pinned_git_revision_matches_contract_hash(self):
        result = subprocess.run(
            ["git", "show", f"{self.install_ref}:install.sh"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        )
        actual = hashlib.sha256(result.stdout).hexdigest()
        self.assertEqual(actual, self.install_sha256)

    def test_failed_install_is_a_terminal_bootstrap_error(self):
        failure_block = self.script.split('if [ "$INSTALL_OK" -ne 1 ]; then', 1)[1]
        failure_block = failure_block.split("fi", 1)[0]
        self.assertIn("=== KACE_BOOTSTRAP_ERROR: KACE_INSTALL ===", failure_block)
        self.assertIn("exit 1", failure_block)

    def test_installed_repository_uses_same_pinned_revision(self):
        self.assertIn('KACE_SOURCE_REF="$KACE_INSTALL_REF"', self.script)
        self.assertIn("KACE_NO_LAUNCH=1", self.script)

    def test_bootstrap_does_not_disable_os_security_updates(self):
        self.assertNotIn("systemctl disable --now apt-daily", self.script)


if __name__ == "__main__":
    unittest.main()
