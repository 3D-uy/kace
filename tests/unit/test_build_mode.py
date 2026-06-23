"""
tests/unit/test_build_mode.py
==============================
Unit tests for firmware.build_mode — mock build detection, banners, and size gate.
"""

import os
import tempfile
import unittest
from unittest.mock import patch


class TestIsMockBuild(unittest.TestCase):
    """Tests for is_mock_build() detection logic."""

    def test_mock_build_detected_when_marker_present(self):
        """is_mock_build() returns True when the make file contains the marker."""
        from firmware.build_mode import is_mock_build
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as fh:
            fh.write("#!/bin/bash\n# Mock make script\necho Mock make invoked\n")
            mock_path = fh.name
        try:
            with patch("firmware.build_mode._MOCK_MAKE_PATH", mock_path):
                self.assertTrue(is_mock_build())
        finally:
            os.unlink(mock_path)

    def test_mock_build_false_when_no_marker(self):
        """is_mock_build() returns False when the make file doesn't contain the marker."""
        from firmware.build_mode import is_mock_build
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as fh:
            fh.write("#!/bin/bash\n# Real GNU make wrapper\nmake \"$@\"\n")
            real_path = fh.name
        try:
            with patch("firmware.build_mode._MOCK_MAKE_PATH", real_path):
                self.assertFalse(is_mock_build())
        finally:
            os.unlink(real_path)

    def test_mock_build_false_when_file_missing(self):
        """is_mock_build() returns False when /usr/local/bin/make doesn't exist."""
        from firmware.build_mode import is_mock_build
        with patch("firmware.build_mode._MOCK_MAKE_PATH", "/nonexistent/path/to/make"):
            self.assertFalse(is_mock_build())


class TestFirmwareMinimumSize(unittest.TestCase):
    """Tests for the FIRMWARE_MINIMUM_SIZE_BYTES centralized constant."""

    def test_minimum_size_constant_is_10kb(self):
        """The centralized threshold must be exactly 10 240 bytes (10 KB)."""
        from firmware.build_mode import FIRMWARE_MINIMUM_SIZE_BYTES
        self.assertEqual(FIRMWARE_MINIMUM_SIZE_BYTES, 10 * 1024)

    def test_minimum_size_below_real_minimum(self):
        """10 KB threshold must be well below the minimum real Klipper size (~30 KB for AVR)."""
        from firmware.build_mode import FIRMWARE_MINIMUM_SIZE_BYTES
        SMALLEST_REAL_KLIPPER_BYTES = 30 * 1024
        self.assertLess(FIRMWARE_MINIMUM_SIZE_BYTES, SMALLEST_REAL_KLIPPER_BYTES)

    def test_minimum_size_above_mock_output(self):
        """10 KB threshold must be above the mock make output size (12 bytes)."""
        from firmware.build_mode import FIRMWARE_MINIMUM_SIZE_BYTES
        MOCK_OUTPUT_BYTES = len(b"MOCK BINARY\n")  # 12 bytes
        self.assertGreater(FIRMWARE_MINIMUM_SIZE_BYTES, MOCK_OUTPUT_BYTES)


class TestHumanSize(unittest.TestCase):
    """Tests for the _human_size() formatting helper."""

    def test_bytes_format(self):
        from firmware.build_mode import _human_size
        self.assertEqual(_human_size(12), "12 bytes")
        self.assertEqual(_human_size(1023), "1023 bytes")

    def test_kb_format(self):
        from firmware.build_mode import _human_size
        self.assertIn("KB", _human_size(10 * 1024))
        self.assertIn("10.0", _human_size(10 * 1024))

    def test_mb_format(self):
        from firmware.build_mode import _human_size
        self.assertIn("MB", _human_size(2 * 1024 * 1024))

    def test_boundary_1024(self):
        """Exactly 1024 bytes should format as KB."""
        from firmware.build_mode import _human_size
        self.assertIn("KB", _human_size(1024))


class TestPrinters(unittest.TestCase):
    """Smoke tests to ensure printer functions don't raise exceptions."""

    def test_print_build_mode_banner_mock_no_crash(self):
        """print_build_mode_banner() in mock context must not raise."""
        from firmware.build_mode import print_build_mode_banner
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as fh:
            fh.write("#!/bin/bash\n# Mock make script\n")
            mock_path = fh.name
        try:
            with patch("firmware.build_mode._MOCK_MAKE_PATH", mock_path):
                print_build_mode_banner()
        finally:
            os.unlink(mock_path)

    def test_print_build_mode_banner_real_no_crash(self):
        """print_build_mode_banner() with no mock active must not raise."""
        from firmware.build_mode import print_build_mode_banner
        with patch("firmware.build_mode._MOCK_MAKE_PATH", "/nonexistent/make"):
            print_build_mode_banner()

    def test_print_mock_warning_silent_when_no_mock(self):
        """print_mock_warning() should not print anything when no mock is active."""
        import io
        from firmware.build_mode import print_mock_warning
        with patch("firmware.build_mode._MOCK_MAKE_PATH", "/nonexistent/make"), \
             patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            print_mock_warning()
            self.assertEqual(mock_stdout.getvalue(), "")

    def test_print_size_warning_no_crash(self):
        """print_size_warning() must not raise for any valid byte count."""
        from firmware.build_mode import print_size_warning
        for size in (0, 12, 512, 10 * 1024 - 1):
            with self.subTest(size=size):
                print_size_warning("/tmp/klipper.bin", size)


if __name__ == "__main__":
    unittest.main()
