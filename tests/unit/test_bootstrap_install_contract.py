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

    def test_external_dependencies_use_centralized_immutable_pins(self):
        pin_block = self.script.split("# BEGIN KACE_DEPENDENCY_PINS", 1)[1].split(
            "# END KACE_DEPENDENCY_PINS", 1
        )[0]
        expected_git_refs = {
            "KLIPPER_REF",
            "MOONRAKER_REF",
            "CROWSNEST_REF",
            "MAINSAIL_CONFIG_REF",
            "FLUIDD_CONFIG_REF",
            "KACE_INSTALL_REF",
        }
        expected_hashes = {
            "MAINSAIL_SHA256",
            "FLUIDD_SHA256",
            "MAINSAIL_CONFIG_SHA256",
            "FLUIDD_CONFIG_SHA256",
            "KACE_INSTALL_SHA256",
        }
        for name in expected_git_refs:
            self.assertRegex(_shell_assignment(pin_block, name), r"^[0-9a-f]{40}$")
        for name in expected_hashes:
            self.assertRegex(_shell_assignment(pin_block, name), r"^[0-9a-f]{64}$")

        self.assertIn('git -C "$staging" fetch --depth=1 origin "$expected_ref"', self.script)
        self.assertIn('git -C "$staging" checkout --detach "$expected_ref"', self.script)
        self.assertIn('git -C "$staging" rev-parse HEAD', self.script)
        self.assertIn("download_verified_file", self.script)
        self.assertIn("install_verified_dashboard", self.script)
        self.assertNotIn("git pull", self.script)
        self.assertNotRegex(
            self.script,
            r"(?:releases/latest|raw\.githubusercontent\.com/[^\n]+/(?:main|master)/)",
        )

    def test_worktree_installer_has_no_mutable_default(self):
        installer = INSTALLER.read_text(encoding="utf-8")
        self.assertIn('INSTALL_REF="${KACE_SOURCE_REF:-}"', installer)
        self.assertNotRegex(installer, r'KACE_SOURCE_REF:-(?:main|master)')

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
        self.assertIn('exit "$INSTALL_EXIT"', failure_block)
        for exit_code in (2, 10, 20, 30, 40):
            self.assertRegex(failure_block, rf"(?m)^\s*{exit_code}\)\s*$")

    def test_installed_repository_uses_same_pinned_revision_and_launches_wizard(self):
        self.assertIn('KACE_SOURCE_REF="$KACE_INSTALL_REF"', self.script)
        self.assertNotIn("KACE_NO_LAUNCH=1", self.script)
        installer_index = self.script.index('bash "$tmp_script"')
        finalization_index = self.script.index(
            'finalize_bootstrap_success "$MOONRAKER_CONFIG" "$BOOT_CFG"'
        )
        self.assertLess(installer_index, finalization_index)

    def test_bootstrap_does_not_disable_os_security_updates(self):
        self.assertNotIn("systemctl disable --now apt-daily", self.script)

    def test_bootstrap_does_not_trust_public_networks(self):
        authorization = self.script.split("[authorization]", 1)[1].split(
            "cors_domains:", 1
        )[0]
        self.assertNotIn("162.254.206.0/24", authorization)

    def test_core_service_startup_failures_are_terminal(self):
        self.assertNotIn("restart klipper   || true", self.script)
        self.assertNotIn("restart moonraker || true", self.script)
        self.assertIn("systemctl is-active --quiet klipper", self.script)
        self.assertIn("systemctl is-active --quiet moonraker", self.script)


if __name__ == "__main__":
    unittest.main()
