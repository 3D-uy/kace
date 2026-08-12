"""Regression checks for the public standalone installation command."""

from pathlib import Path
import hashlib
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]
IMMUTABLE_REF = "c9a2ee84f66b40acc5ee08f8d2529fa92815c5a4"
INSTALL_SHA256 = "f116b3475684f6f242b10c53fcc3f898a8ab7b6e4e7149892a3a0e932dc1d701"


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
