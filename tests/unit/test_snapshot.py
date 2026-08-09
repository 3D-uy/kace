# tests/unit/test_snapshot.py
import unittest
from unittest.mock import patch, MagicMock
import os
import sys
import json
import tempfile

# Ensure root is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from core.snapshot import capture_snapshot, create_snapshot, restore_snapshot, DeploymentSnapshot


class TestSnapshot(unittest.TestCase):

    def test_strict_snapshot_persists_hashes_and_confirmed_absence(self):
        with tempfile.TemporaryDirectory() as root:
            snap = create_snapshot(
                {"printer.cfg": b"original", "kace/new.cfg": None},
                persist_root=root,
            )
            with open(os.path.join(snap.storage_path, "snapshot.json"), encoding="utf-8") as source:
                manifest = json.load(source)
        self.assertEqual(manifest["schema"], "kace-config-snapshot/v1")
        self.assertEqual(
            manifest["sha256"]["printer.cfg"],
            "0682c5f2076f099c34cfdd15a9e063849ed437a49677e6fcc5b4198c76575be5",
        )
        self.assertEqual(manifest["missing_files"], ["kace/new.cfg"])

    def test_strict_snapshot_rejects_path_like_transaction_id(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                create_snapshot({"printer.cfg": b"x"}, deployment_id="../escape", persist_root=root)

    @patch('core.snapshot.download_printer_cfg')
    def test_capture_snapshot_success(self, mock_download):
        def side_effect(host, port, filename, api_key=None):
            if filename == "printer.cfg":
                return True, b"[mcu]\nserial: /dev/ttyUSB0"
            elif filename == "macros.cfg":
                return True, b"[gcode_macro TEST]\ngcode: M105"
            return False, "Not found"

        mock_download.side_effect = side_effect

        snap = capture_snapshot(
            "192.168.1.100", 7125,
            ["printer.cfg", "macros.cfg", "absent.cfg"],
            manifest_mcus=("mcu",),
            board="btt-skr-v1.4",
            kace_version="v0.9.3.4"
        )

        self.assertIsNotNone(snap)
        self.assertEqual(snap.board, "btt-skr-v1.4")
        self.assertEqual(snap.kace_version, "v0.9.3.4")
        self.assertEqual(snap.mcus, ("mcu",))
        self.assertIn("printer.cfg", snap.config_files)
        self.assertIn("macros.cfg", snap.config_files)
        self.assertNotIn("absent.cfg", snap.config_files)

    @patch('core.snapshot.download_printer_cfg')
    def test_capture_snapshot_total_failure_returns_none(self, mock_download):
        mock_download.return_value = (False, "Connection refused")

        snap = capture_snapshot(
            "192.168.1.100", 7125,
            ["printer.cfg", "macros.cfg"],
        )

        self.assertIsNone(snap)

    @patch('core.snapshot.download_printer_cfg')
    def test_capture_snapshot_network_exception_handled(self, mock_download):
        mock_download.side_effect = ConnectionError("Network unreachable")

        snap = capture_snapshot(
            "192.168.1.100", 7125,
            ["printer.cfg"],
        )

        self.assertIsNone(snap)

    @patch('core.snapshot.restart_firmware')
    @patch('core.snapshot.upload_printer_cfg')
    def test_restore_snapshot_upload_order_and_restart(self, mock_upload, mock_restart):
        mock_upload.return_value = (True, "OK")
        mock_restart.return_value = (True, "OK")

        snap = DeploymentSnapshot(
            deployment_id="test-id",
            timestamp="2026-07-23T00:00:00Z",
            board="test-board",
            kace_version="v0.9.3.4",
            firmware_fingerprint="",
            mcus=("mcu",),
            dev_deploy=False,
            config_files={
                "printer.cfg": b"printer content",
                "macros.cfg": b"macros content",
                "includes/bed.cfg": b"bed content"
            }
        )

        failed = restore_snapshot(snap, "192.168.1.100", 7125, issue_restart=True)

        self.assertEqual(failed, [])
        self.assertTrue(mock_restart.called)
        
        # Verify upload order: printer.cfg MUST be uploaded last
        uploaded_filenames = [call.kwargs.get('filename') or call.args[3] for call in mock_upload.call_args_list]
        self.assertEqual(uploaded_filenames[-1], "printer.cfg")

    @patch('core.snapshot.restart_firmware')
    @patch('core.snapshot.upload_printer_cfg')
    def test_restore_snapshot_partial_failure(self, mock_upload, mock_restart):
        def side_effect(host, port, filepath, filename=None, api_key=None):
            if filename == "macros.cfg":
                return False, "Permission denied"
            return True, "OK"

        mock_upload.side_effect = side_effect

        snap = DeploymentSnapshot(
            deployment_id="test-id",
            timestamp="2026-07-23T00:00:00Z",
            board="test-board",
            kace_version="v0.9.3.4",
            firmware_fingerprint="",
            mcus=("mcu",),
            dev_deploy=False,
            config_files={
                "printer.cfg": b"printer content",
                "macros.cfg": b"macros content",
            }
        )

        failed = restore_snapshot(snap, "192.168.1.100", 7125, issue_restart=False)

        self.assertEqual(failed, ["macros.cfg"])
        self.assertFalse(mock_restart.called)


if __name__ == "__main__":
    unittest.main()
