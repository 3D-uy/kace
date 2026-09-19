"""Tests for the repository portability guard."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.check_portability import find_violations, scan_text


class TestPortabilityGuard(unittest.TestCase):
    def test_rejects_developer_profiles_and_workspaces(self):
        separator = chr(92)
        samples = (
            "C:" + separator + "Users" + separator + "fixture-user" + separator + "repo",
            "/" + "Users/fixture-user/repo",
            "/" + "home/fixture-user/repo",
            "D:" + separator + "fixture-workspace" + separator + "project",
            "C:" + separator * 2 + "Users" + separator * 2 + "fixture-user",
            "c:/" + "users/fixture-user/repo",
            "C." + "Users.fixture-user.repo",
            "D:" + "/fixture-workspace/project",
            separator + "home" + separator + "fixture-user" + separator + "repo",
            "/" + "home/user.name/repo",
            "/" + "Desktop/fixture.txt",
            "." + "Documents.fixture.txt",
        )
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertTrue(scan_text(sample))

    def test_allows_target_runtime_and_generic_paths(self):
        separator = chr(92)
        samples = (
            "/home/kace/printer_data/config",
            "/home/pi/klipper",
            "C:" + separator + "Downloads" + separator + "image.img",
            "/tmp/kace-download.part",
        )
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertEqual(scan_text(sample), [])

    def test_scans_all_tracked_locations_including_security_fixtures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / name for name in (
                "build/example.txt", "dist/example.txt",
                "tests/unit/test_precommit.py", "docs/example.md",
            )]
            for path in paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("D:" + "/fixture-workspace/file", encoding="utf-8")
            with patch("scripts.check_portability._tracked_files", return_value=paths):
                findings = find_violations(root)
            self.assertEqual(len(findings), len(paths))
            for path in paths:
                self.assertTrue(any(str(path.relative_to(root)) in line for line in findings))


if __name__ == "__main__":
    unittest.main()
