"""Unit tests for core/moonraker.py — Moonraker HTTP API client.

All tests are fully offline: urllib.request.urlopen is patched via
unittest.mock so no real network calls are made. Follows the same
zero-dependency test pattern used throughout the KACE test suite.
"""

import io
import json
import unittest
from unittest.mock import MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from core.moonraker import (
    DEFAULT_PORT,
    _base_url,
    check_moonraker,
    upload_printer_cfg,
    restart_firmware,
    restart_klipper_service,
)


# ── Helpers ──────────────────────────────────────────────────────

def _fake_response(body: dict, status: int = 200):
    """Return a mock urllib response that reads a JSON body."""
    raw = json.dumps(body).encode()
    resp = MagicMock()
    resp.read.return_value = raw
    resp.status = status
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _http_error(code: int, reason: str = "Error", body: dict = None):
    """Return an urllib.error.HTTPError with an optional JSON body."""
    import urllib.error
    body_bytes = json.dumps(body or {}).encode()
    err = urllib.error.HTTPError(
        url="http://fake",
        code=code,
        msg=reason,
        hdrs={},
        fp=io.BytesIO(body_bytes),
    )
    return err


# ── _base_url ─────────────────────────────────────────────────────

class TestBaseUrl(unittest.TestCase):

    def test_adds_http_scheme(self):
        self.assertEqual(_base_url("192.168.1.1", 7125), "http://192.168.1.1:7125")

    def test_preserves_existing_scheme(self):
        self.assertEqual(_base_url("http://mypi.local", 7125), "http://mypi.local:7125")

    def test_strips_trailing_slash(self):
        self.assertEqual(_base_url("192.168.1.1/", 7125), "http://192.168.1.1:7125")


# ── check_moonraker ───────────────────────────────────────────────

class TestCheckMoonraker(unittest.TestCase):

    @patch("urllib.request.urlopen")
    def test_success_returns_version(self, mock_urlopen):
        """A valid /server/info response should return (True, version)."""
        mock_urlopen.return_value = _fake_response(
            {"result": {"moonraker_version": "v0.9.1"}}
        )
        ok, info = check_moonraker("192.168.1.100", 7125)
        self.assertTrue(ok)
        self.assertIn("v0.9.1", info)

    @patch("urllib.request.urlopen")
    def test_url_error_returns_false(self, mock_urlopen):
        """A connection error should return (False, error_message)."""
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        ok, info = check_moonraker("192.168.1.100", 7125)
        self.assertFalse(ok)
        self.assertIn("Connection", info)

    @patch("urllib.request.urlopen")
    def test_http_error_returns_false(self, mock_urlopen):
        """An HTTP error should return (False, error_message)."""
        mock_urlopen.side_effect = _http_error(403, "Forbidden")
        ok, info = check_moonraker("192.168.1.100", 7125)
        self.assertFalse(ok)
        self.assertIn("403", info)

    @patch("urllib.request.urlopen")
    def test_timeout_returns_false(self, mock_urlopen):
        """A timeout should return (False, error_message) without raising."""
        import socket
        mock_urlopen.side_effect = TimeoutError("timed out")
        ok, info = check_moonraker("192.168.1.100", 7125)
        self.assertFalse(ok)

    @patch("urllib.request.urlopen")
    def test_calls_correct_endpoint(self, mock_urlopen):
        """check_moonraker must request /server/info."""
        mock_urlopen.return_value = _fake_response({"result": {"moonraker_version": "0.1"}})
        check_moonraker("mypi", 7125)
        called_url = mock_urlopen.call_args[0][0]
        # called_url may be a Request object
        url_str = called_url.full_url if hasattr(called_url, "full_url") else str(called_url)
        self.assertIn("/server/info", url_str)


# ── upload_printer_cfg ────────────────────────────────────────────

class TestUploadPrinterCfg(unittest.TestCase):

    def _write_tmp_cfg(self, tmp_dir, name="printer.cfg"):
        path = os.path.join(tmp_dir, name)
        with open(path, "w") as f:
            f.write("[printer]\nmax_velocity: 300\n")
        return path

    @patch("urllib.request.urlopen")
    def test_upload_success(self, mock_urlopen):
        """Successful upload should return (True, path)."""
        import tempfile
        mock_urlopen.return_value = _fake_response(
            {"result": {"item": {"path": "printer.cfg"}}}
        )
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._write_tmp_cfg(tmp)
            ok, result = upload_printer_cfg("mypi", 7125, cfg)
        self.assertTrue(ok)
        self.assertEqual(result, "printer.cfg")

    @patch("urllib.request.urlopen")
    def test_upload_explicit_filename(self, mock_urlopen):
        """Specifying an explicit filename should use it in the multipart header."""
        import tempfile
        mock_urlopen.return_value = _fake_response(
            {"result": {"item": {"path": "custom.cfg"}}}
        )
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._write_tmp_cfg(tmp, "printer.cfg")
            ok, result = upload_printer_cfg("mypi", 7125, cfg, filename="custom.cfg")
        self.assertTrue(ok)
        self.assertEqual(result, "custom.cfg")
        called_req = mock_urlopen.call_args[0][0]
        self.assertIn(b'filename="custom.cfg"', called_req.data)

    @patch("urllib.request.urlopen")
    def test_upload_default_basename(self, mock_urlopen):
        """Omitting filename should default to the file's basename (e.g. macros.cfg)."""
        import tempfile
        mock_urlopen.return_value = _fake_response(
            {"result": {"item": {"path": "macros.cfg"}}}
        )
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._write_tmp_cfg(tmp, "macros.cfg")
            ok, result = upload_printer_cfg("mypi", 7125, cfg)
        self.assertTrue(ok)
        self.assertEqual(result, "macros.cfg")
        called_req = mock_urlopen.call_args[0][0]
        self.assertIn(b'filename="macros.cfg"', called_req.data)

    @patch("urllib.request.urlopen")
    def test_upload_http_error_returns_false(self, mock_urlopen):
        """A 500 error during upload should return (False, error)."""
        import tempfile
        mock_urlopen.side_effect = _http_error(
            500, "Internal Server Error",
            body={"error": {"message": "disk full"}}
        )
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._write_tmp_cfg(tmp)
            ok, result = upload_printer_cfg("mypi", 7125, cfg)
        self.assertFalse(ok)

    def test_missing_file_returns_false(self):
        """A path that does not exist should return (False, ...) immediately."""
        ok, msg = upload_printer_cfg("mypi", 7125, "/nonexistent/printer.cfg")
        self.assertFalse(ok)
        self.assertIn("not found", msg)

    @patch("urllib.request.urlopen")
    def test_calls_upload_endpoint(self, mock_urlopen):
        """upload_printer_cfg must POST to /server/files/upload."""
        import tempfile
        mock_urlopen.return_value = _fake_response(
            {"result": {"item": {"path": "printer.cfg"}}}
        )
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._write_tmp_cfg(tmp)
            upload_printer_cfg("mypi", 7125, cfg)
        called_url = mock_urlopen.call_args[0][0]
        url_str = called_url.full_url if hasattr(called_url, "full_url") else str(called_url)
        self.assertIn("/server/files/upload", url_str)


# ── restart_firmware ──────────────────────────────────────────────

class TestRestartFirmware(unittest.TestCase):

    @patch("urllib.request.urlopen")
    def test_success(self, mock_urlopen):
        """A 200 response should return (True, message)."""
        mock_urlopen.return_value = _fake_response({"result": "ok"})
        ok, msg = restart_firmware("mypi", 7125)
        self.assertTrue(ok)

    @patch("urllib.request.urlopen")
    def test_http_error_returns_false(self, mock_urlopen):
        """An HTTP error should return (False, message)."""
        mock_urlopen.side_effect = _http_error(503, "Service Unavailable")
        ok, msg = restart_firmware("mypi", 7125)
        self.assertFalse(ok)
        self.assertIn("503", msg)

    @patch("urllib.request.urlopen")
    def test_calls_firmware_restart_endpoint(self, mock_urlopen):
        """restart_firmware must POST to /printer/firmware_restart."""
        mock_urlopen.return_value = _fake_response({"result": "ok"})
        restart_firmware("mypi", 7125)
        called_url = mock_urlopen.call_args[0][0]
        url_str = called_url.full_url if hasattr(called_url, "full_url") else str(called_url)
        self.assertIn("/printer/firmware_restart", url_str)


# ── restart_klipper_service ───────────────────────────────────────

class TestRestartKlipperService(unittest.TestCase):

    @patch("urllib.request.urlopen")
    def test_success(self, mock_urlopen):
        mock_urlopen.return_value = _fake_response({"result": "ok"})
        ok, msg = restart_klipper_service("mypi", 7125)
        self.assertTrue(ok)

    @patch("urllib.request.urlopen")
    def test_calls_machine_services_endpoint(self, mock_urlopen):
        """restart_klipper_service must POST to /machine/services/restart."""
        mock_urlopen.return_value = _fake_response({"result": "ok"})
        restart_klipper_service("mypi", 7125)
        called_url = mock_urlopen.call_args[0][0]
        url_str = called_url.full_url if hasattr(called_url, "full_url") else str(called_url)
        self.assertIn("/machine/services/restart", url_str)
        self.assertIn("klipper", url_str)


if __name__ == "__main__":
    unittest.main()
