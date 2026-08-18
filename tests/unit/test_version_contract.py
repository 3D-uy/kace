import io
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from core.banner import print_kace_banner
from core.loader import read_version, set_bypass_cache


ROOT = Path(__file__).resolve().parents[2]


class TestKaceVersionContract(unittest.TestCase):
    def setUp(self):
        set_bypass_cache(True)

    def tearDown(self):
        set_bypass_cache(False)

    def test_version_file_matches_current_changelog_release(self):
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        current = re.search(
            r"^## \[([0-9]+(?:\.[0-9]+){2,3})\]",
            changelog,
            re.MULTILINE,
        )

        self.assertRegex(
            version,
            r"^[0-9]+(?:\.[0-9]+){2,3}(?:[.-][0-9A-Za-z.-]+)?$",
        )
        self.assertIsNotNone(current)
        self.assertEqual(version, current.group(1))
        self.assertEqual(read_version(), f"v{version}")

    def test_banner_reads_version_instead_of_accepting_an_override(self):
        output = io.StringIO()
        with patch("core.banner.read_version", return_value="v9.8.7") as version, \
             patch("core.banner.os.system"), \
             patch("sys.stdout", output):
            print_kace_banner("KACE test")

        version.assert_called_once_with()
        self.assertIn("v9.8.7", output.getvalue())
        with self.assertRaises(TypeError):
            print_kace_banner("KACE test", "v1.2.3")

    def test_cli_version_is_derived_from_version_file(self):
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        result = subprocess.run(
            [sys.executable, str(ROOT / "kace.py"), "--version"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), f"KACE v{version}")

    def test_runtime_consumers_do_not_embed_a_release_version(self):
        for relative in (
            "kace.py",
            "core/banner.py",
            "core/dashboard.py",
            "install.sh",
            "scripts/bootstrap.sh",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotRegex(
                source,
                r"(?<![A-Za-z0-9])v?0\.9\.3\.\d+(?![A-Za-z0-9])",
                relative,
            )


if __name__ == "__main__":
    unittest.main()
