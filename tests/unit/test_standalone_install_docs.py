"""Regression checks for the public standalone installation command."""

from pathlib import Path
import hashlib
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]
IMMUTABLE_REF = "cd12a469e5314a71da284f30fd80caaa1f0b7716"
INSTALL_SHA256 = "29b4a5124d36bcdef852f4d6e966db7bf73ba853920c080826da8251b6dde930"


class TestStandaloneInstallDocs(unittest.TestCase):
    def test_public_docs_never_execute_mutable_installer_content(self):
        for relative_path in (
            "README.md",
            "docs/es/README.md",
            "docs/pt/README.md",
            "install.sh",
        ):
            content = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotRegex(
                content,
                r"raw\.githubusercontent\.com/3D-uy/KACE/(?:main|master)/install\.sh",
                relative_path,
            )

    def test_quick_start_pins_and_verifies_installer_before_execution(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        quick_start = readme.split("## Quick start", 1)[1].split("## ", 1)[0]
        self.assertIn(IMMUTABLE_REF, quick_start)
        self.assertIn(INSTALL_SHA256, quick_start)
        self.assertIn("sha256sum -c -", quick_start)
        self.assertNotIn("bash <(curl", quick_start)
        self.assertLess(quick_start.index("sha256sum -c -"), quick_start.index('bash "$installer"'))

    def test_documented_hash_is_well_formed(self):
        self.assertRegex(IMMUTABLE_REF, r"^[0-9a-f]{40}$")
        self.assertRegex(INSTALL_SHA256, r"^[0-9a-f]{64}$")

    def test_documented_hash_matches_the_immutable_git_object(self):
        installer = subprocess.run(
            ["git", "show", f"{IMMUTABLE_REF}:install.sh"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        ).stdout
        self.assertEqual(hashlib.sha256(installer).hexdigest(), INSTALL_SHA256)


if __name__ == "__main__":
    unittest.main()
