"""CI must reject omitted, incomplete and failed real-build evidence."""
import hashlib
import io
import json
import os
from unittest.mock import patch
from pathlib import Path
import tempfile
import unittest

from docker.ci.run_real_builds import BuildEvidence, gate_passed, source_revision


class RealBuildGateTests(unittest.TestCase):
    def test_checkout_identity_survives_container_ownership_boundary(self):
        expected = source_revision()
        with patch.dict(os.environ, {"GIT_TEST_ASSUME_DIFFERENT_OWNER": "1"}):
            self.assertEqual(source_revision(), expected)

    def result(self, outcome="pass", count=7):
        class Sample(unittest.TestCase):
            def runTest(self):
                if outcome == "skip":
                    self.skipTest("toolchain missing")
                if outcome == "fail":
                    self.fail("compiler failed")
        return unittest.TextTestRunner(stream=io.StringIO()).run(
            unittest.TestSuite(Sample() for _ in range(count)))

    def test_complete_builds_pass_but_skips_fail(self):
        artifacts = [{}] * 12
        self.assertTrue(gate_passed(self.result(), artifacts))
        self.assertFalse(gate_passed(self.result("skip"), artifacts))
        self.assertFalse(gate_passed(self.result("fail"), artifacts))

    def test_missing_tests_or_artifacts_fail(self):
        self.assertFalse(gate_passed(self.result(count=6), [{}] * 12))
        self.assertFalse(gate_passed(self.result(), [{}] * 11))

    def test_evidence_survives_build_cleanup_with_exact_bytes(self):
        with tempfile.TemporaryDirectory() as retained:
            evidence = BuildEvidence(retained)
            with tempfile.TemporaryDirectory() as build:
                source = Path(build) / "klipper.bin"
                source.write_bytes(b"real-build-evidence")
                (Path(build) / "resolved.config").write_text("CONFIG_MACH_STM32=y")
                (Path(build) / "build-proof.json").write_text('{"build": "verified"}')
                evidence.retain(source, {"status": "success"}, "builder")
            record = evidence.artifacts[0]
            target = Path(retained) / record["file"]
            self.assertEqual(target.read_bytes(), b"real-build-evidence")
            self.assertEqual(record["sha256"], hashlib.sha256(target.read_bytes()).hexdigest())
            self.assertTrue((target.parent / "resolved.config").is_file())
            self.assertEqual(json.loads((target.parent / "build-proof.json").read_text()),
                             {"build": "verified"})
