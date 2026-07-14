"""
tests/unit/test_snapshot.py
Unit tests for core/snapshot.py — DeploymentSnapshot dataclass and
capture_snapshot / restore_snapshot helpers.

All tests are fully offline: urllib.request.urlopen and upload_printer_cfg
are patched so no real network calls are made.
"""

import os
import sys
import unittest
from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from core.snapshot import DeploymentSnapshot, capture_snapshot, restore_snapshot


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_snapshot(**overrides) -> DeploymentSnapshot:
    """Build a minimal valid snapshot for use in restore tests."""
    defaults = dict(
        deployment_id="test-id",
        timestamp="2026-01-01T00:00:00+00:00",
        board="btt_octopus",
        kace_version="1.0.0",
        firmware_fingerprint="mcu=kace-abc123",
        mcus=("mcu",),
        dev_deploy=False,
        config_files={
            "macros.cfg": b"# macros\n",
            "printer.cfg": b"[printer]\n",
        },
    )
    defaults.update(overrides)
    return DeploymentSnapshot(**defaults)


def _fake_download_ok(host, port, filename, api_key=None):
    """Simulate a successful download_printer_cfg call."""
    return True, f"# content of {filename}".encode()


def _fake_download_fail(host, port, filename, api_key=None):
    """Simulate a failing download_printer_cfg call."""
    return False, b"connection error"


# ── DeploymentSnapshot dataclass ─────────────────────────────────────────────

class TestDeploymentSnapshot(unittest.TestCase):

    def test_snapshot_is_immutable(self):
        """frozen=True must prevent mutation of any field."""
        snap = _make_snapshot()
        with self.assertRaises(FrozenInstanceError):
            snap.board = "new_board"  # type: ignore[misc]

    def test_snapshot_config_files_defaults_empty(self):
        """A snapshot created without config_files should have an empty dict."""
        snap = DeploymentSnapshot(
            deployment_id="x",
            timestamp="t",
            board="b",
            kace_version="k",
            firmware_fingerprint="",
            mcus=(),
            dev_deploy=False,
        )
        self.assertEqual(snap.config_files, {})

    def test_snapshot_mcus_stored_as_tuple(self):
        """mcus must be stored as a tuple, not a list (frozen dataclass requirement)."""
        snap = _make_snapshot(mcus=("mcu", "mcu toolboard"))
        self.assertIsInstance(snap.mcus, tuple)
        self.assertEqual(len(snap.mcus), 2)


# ── capture_snapshot ─────────────────────────────────────────────────────────

class TestCaptureSnapshot(unittest.TestCase):

    @patch("core.snapshot.download_printer_cfg", side_effect=_fake_download_ok)
    def test_capture_populates_all_fields(self, _mock):
        """A successful capture populates all fields and downloads files."""
        snap = capture_snapshot(
            "mypi", 7125, ["printer.cfg", "macros.cfg"],
            manifest_mcus=("mcu",),
            dev_deploy=True,
            board="btt_octopus",
            kace_version="2.0",
            firmware_fingerprint="mcu=kace-abc",
        )
        self.assertIsNotNone(snap)
        self.assertEqual(snap.board, "btt_octopus")
        self.assertEqual(snap.kace_version, "2.0")
        self.assertEqual(snap.firmware_fingerprint, "mcu=kace-abc")
        self.assertEqual(snap.mcus, ("mcu",))
        self.assertTrue(snap.dev_deploy)
        self.assertIn("printer.cfg", snap.config_files)
        self.assertIn("macros.cfg", snap.config_files)
        # UUID was generated
        self.assertEqual(len(snap.deployment_id), 36)
        # Timestamp is ISO-8601 string
        self.assertIn("T", snap.timestamp)

    @patch("core.snapshot.download_printer_cfg", side_effect=_fake_download_fail)
    def test_capture_returns_none_when_all_downloads_fail(self, _mock):
        """Returns None when every download attempt fails (Moonraker unreachable)."""
        snap = capture_snapshot("mypi", 7125, ["printer.cfg"])
        self.assertIsNone(snap)

    @patch("core.snapshot.download_printer_cfg")
    def test_capture_skips_missing_files(self, mock_dl):
        """Files that return ok=False are absent from config_files but others succeed."""
        def side_effect(host, port, filename, api_key=None):
            if filename == "printer.cfg":
                return True, b"[printer]\n"
            return False, b"not found"  # macros.cfg missing

        mock_dl.side_effect = side_effect
        snap = capture_snapshot("mypi", 7125, ["printer.cfg", "macros.cfg"])
        self.assertIsNotNone(snap)
        self.assertIn("printer.cfg", snap.config_files)
        self.assertNotIn("macros.cfg", snap.config_files)

    def test_capture_returns_empty_snapshot_when_no_files_requested(self):
        """Passing an empty filenames list returns a valid snapshot with no files."""
        snap = capture_snapshot("mypi", 7125, [])
        self.assertIsNotNone(snap)
        self.assertEqual(snap.config_files, {})

    @patch("core.snapshot.download_printer_cfg", side_effect=_fake_download_ok)
    def test_capture_fingerprint_recorded(self, _mock):
        """firmware_fingerprint passed to capture is stored verbatim on the snapshot."""
        fp = "mcu=kace-xyz789; mcu toolboard=kace-abc123"
        snap = capture_snapshot("mypi", 7125, ["printer.cfg"], firmware_fingerprint=fp)
        self.assertEqual(snap.firmware_fingerprint, fp)


# ── restore_snapshot ─────────────────────────────────────────────────────────

class TestRestoreSnapshot(unittest.TestCase):

    def _upload_call_order(self, mock_upload):
        """Extract the filename argument from each upload_printer_cfg call."""
        return [c.kwargs.get("filename") or os.path.basename(c.args[2])
                for c in mock_upload.call_args_list]

    @patch("core.snapshot.restart_firmware")
    @patch("core.snapshot.upload_printer_cfg")
    def test_restore_uploads_printer_cfg_last(self, mock_upload, mock_restart):
        """printer.cfg must always be uploaded after all other files."""
        mock_upload.return_value = (True, "ok")
        snap = _make_snapshot(config_files={
            "macros.cfg": b"# macros\n",
            "motors.cfg": b"# motors\n",
            "printer.cfg": b"[printer]\n",
        })
        failed = restore_snapshot(snap, "mypi", 7125, issue_restart=False)
        self.assertEqual(failed, [])
        uploaded = [c.kwargs["filename"] for c in mock_upload.call_args_list]
        self.assertEqual(uploaded[-1], "printer.cfg")
        self.assertIn("macros.cfg", uploaded)
        self.assertIn("motors.cfg", uploaded)

    @patch("core.snapshot.restart_firmware")
    @patch("core.snapshot.upload_printer_cfg")
    def test_restore_returns_failed_list_on_upload_error(self, mock_upload, mock_restart):
        """Filenames that fail to upload are returned in the failed list."""
        def side_effect(host, port, tmp_path, filename=None, api_key=None):
            if filename == "macros.cfg":
                return False, "upload error"
            return True, "ok"

        mock_upload.side_effect = side_effect
        snap = _make_snapshot()
        failed = restore_snapshot(snap, "mypi", 7125, issue_restart=False)
        self.assertIn("macros.cfg", failed)
        self.assertNotIn("printer.cfg", failed)

    @patch("core.snapshot.restart_firmware")
    @patch("core.snapshot.upload_printer_cfg", return_value=(True, "ok"))
    def test_restore_issues_firmware_restart(self, mock_upload, mock_restart):
        """restart_firmware must be called once after all uploads when issue_restart=True."""
        snap = _make_snapshot()
        restore_snapshot(snap, "mypi", 7125, issue_restart=True)
        mock_restart.assert_called_once_with("mypi", 7125, api_key=None)

    @patch("core.snapshot.restart_firmware")
    @patch("core.snapshot.upload_printer_cfg", return_value=(True, "ok"))
    def test_restore_skips_restart_when_disabled(self, mock_upload, mock_restart):
        """restart_firmware must NOT be called when issue_restart=False."""
        snap = _make_snapshot()
        restore_snapshot(snap, "mypi", 7125, issue_restart=False)
        mock_restart.assert_not_called()

    @patch("core.snapshot.restart_firmware")
    @patch("core.snapshot.upload_printer_cfg", return_value=(True, "ok"))
    def test_restore_empty_snapshot_returns_no_failures(self, mock_upload, mock_restart):
        """A snapshot with no config_files produces an empty failed list."""
        snap = _make_snapshot(config_files={})
        failed = restore_snapshot(snap, "mypi", 7125, issue_restart=False)
        self.assertEqual(failed, [])
        mock_upload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
