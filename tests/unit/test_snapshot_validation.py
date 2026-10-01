"""Golden files need an independent loader oracle, not only byte comparison."""

import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.regression import validate_snapshots as validation


class SnapshotValidationTests(unittest.TestCase):
    def test_invalid_missing_or_unavailable_validation_never_passes(self):
        for result, error in (({"valid": False, "reason": "pin required"}, None),
                              (None, None), ({"valid": "yes"}, None),
                              ({"valid": True}, "Docker unavailable")):
            with self.subTest(result=result, error=error), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "invalid-expected.txt").write_text("[fan]\n", encoding="utf-8")
                with patch.object(validation, "run_docker_validation", return_value=(
                    {"invalid-expected": result}, error
                )), contextlib.redirect_stdout(io.StringIO()):
                    report = validation.execute(root / "out", root)
                self.assertFalse(report["successful"])
                self.assertEqual(report["summary"]["PASS"], 0)

    def test_every_snapshot_is_copied_byte_for_byte_and_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contents = {"one-expected": b"# example\r\n", "two-expected": b"# another\n"}
            for name, data in contents.items():
                (root / (name + ".txt")).write_bytes(data)
            (root / "unrelated.txt").write_text("not a config snapshot", encoding="utf-8")
            with patch.object(validation, "run_docker_validation", return_value=(
                {name: {"valid": True} for name in contents}, None
            )) as loader, contextlib.redirect_stdout(io.StringIO()):
                report = validation.execute(root / "out", root)
            self.assertTrue(report["successful"])
            self.assertEqual(report["summary"]["PASS"], 2)
            artifact_dir, manifest_path = loader.call_args.args
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["klipper_ref"], validation.KLIPPER_REF)
            for case in manifest["cases"]:
                self.assertEqual((artifact_dir / case["config_path"]).read_bytes(), contents[case["id"]])
                self.assertEqual(case["source_sha256"], hashlib.sha256(contents[case["id"]]).hexdigest())

    def test_empty_fixture_collection_is_not_success(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(validation, "run_docker_validation") as loader, \
             contextlib.redirect_stdout(io.StringIO()):
            report = validation.execute(Path(directory) / "out", Path(directory))
        self.assertFalse(report["successful"])
        self.assertEqual(report["summary"]["total"], 0)
        loader.assert_not_called()
