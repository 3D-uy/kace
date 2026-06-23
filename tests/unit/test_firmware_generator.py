# tests/unit/test_firmware_generator.py
#
# Unit tests for firmware/generator.py (generate_firmware_config) and
# firmware/validator.py (validate_config).
#
# Both modules work with real files on disk but require no external tools,
# no network, no questionary, and no subprocess calls — fully offline.
#
# firmware/builder.py is intentionally NOT tested here: it is an interactive
# orchestration shell with a while-True questionary loop and subprocess.run
# calls (make olddefconfig, make, etc.). Unit testing it would require mocking
# the entire build system for near-zero correctness gain.

import os
import tempfile
import unittest

from firmware.firmware_generator import generate_firmware_config
from firmware.validator import validate_config


# ── generate_firmware_config ──────────────────────────────────────────────────

class TestGenerateFirmwareConfig(unittest.TestCase):
    """Tests for firmware/generator.py — generates a Kconfig .config file."""

    def setUp(self):
        # Use a real temp directory as a fake klipper_path for each test.
        self._tmpdir = tempfile.TemporaryDirectory()
        self.klipper_path = self._tmpdir.name

    def tearDown(self):
        self._tmpdir.cleanup()

    def _config_path(self):
        return os.path.join(self.klipper_path, ".config")

    def _read_config(self):
        with open(self._config_path(), "r", encoding="utf-8") as f:
            return f.read()

    # ── Basic output ──────────────────────────────────────────────────────────

    def test_success_returns_true_and_message(self):
        """A valid config dict must return (True, <message>)."""
        cfg = {"CONFIG_MCU": '"stm32"', "CONFIG_USB": "y"}
        ok, msg = generate_firmware_config(cfg, self.klipper_path)
        self.assertTrue(ok)
        self.assertIsInstance(msg, str)

    def test_creates_dot_config_file(self):
        """The function must create a .config file inside klipper_path."""
        cfg = {"CONFIG_MCU": '"stm32"', "CONFIG_USB": "y"}
        generate_firmware_config(cfg, self.klipper_path)
        self.assertTrue(os.path.exists(self._config_path()))

    def test_config_keys_written_as_key_equals_value(self):
        """Every key in the dict must be written as KEY=value on its own line."""
        cfg = {
            "CONFIG_MCU": '"stm32"',
            "CONFIG_USB": "y",
            "CONFIG_FLASH_START": "0x8000",
        }
        generate_firmware_config(cfg, self.klipper_path)
        content = self._read_config()
        self.assertIn('CONFIG_MCU="stm32"', content)
        self.assertIn("CONFIG_USB=y", content)
        self.assertIn("CONFIG_FLASH_START=0x8000", content)

    def test_each_key_on_its_own_line(self):
        """Keys must not be concatenated — each on a separate newline."""
        cfg = {"A": "1", "B": "2", "C": "3"}
        generate_firmware_config(cfg, self.klipper_path)
        lines = self._read_config().splitlines()
        keys_found = [l.split("=")[0] for l in lines if "=" in l]
        self.assertIn("A", keys_found)
        self.assertIn("B", keys_found)
        self.assertIn("C", keys_found)

    def test_empty_dict_creates_empty_config(self):
        """An empty dict must create an empty (but existing) .config file."""
        ok, _ = generate_firmware_config({}, self.klipper_path)
        self.assertTrue(ok)
        self.assertEqual(self._read_config(), "")

    # ── Known MCU profiles ────────────────────────────────────────────────────

    def test_stm32f446_usb_profile(self):
        """STM32F446 USB profile keys must be written correctly."""
        cfg = {
            "CONFIG_MCU": '"stm32"',
            "CONFIG_MCU_STM32F446XX": "y",
            "CONFIG_FLASH_START": "0x8000",
            "CONFIG_USB": "y",
            "CONFIG_CLOCK_FREQ": "168000000",
        }
        generate_firmware_config(cfg, self.klipper_path)
        content = self._read_config()
        self.assertIn("CONFIG_MCU_STM32F446XX=y", content)
        self.assertIn("CONFIG_USB=y", content)
        self.assertNotIn("CONFIG_SERIAL=y", content)

    def test_rp2040_usb_no_flash_offset(self):
        """RP2040 must not have a CONFIG_FLASH_START key."""
        cfg = {"CONFIG_MCU": '"rp2040"', "CONFIG_USB": "y"}
        generate_firmware_config(cfg, self.klipper_path)
        content = self._read_config()
        self.assertNotIn("CONFIG_FLASH_START", content)

    def test_lpc1769_uart_profile(self):
        """LPC1769 UART profile must include flash offset and serial flag."""
        cfg = {
            "CONFIG_MCU": '"lpc176x"',
            "CONFIG_FLASH_START": "0x4000",
            "CONFIG_SERIAL": "y",
            "CONFIG_CLOCK_FREQ": "120000000",
        }
        generate_firmware_config(cfg, self.klipper_path)
        content = self._read_config()
        self.assertIn("CONFIG_FLASH_START=0x4000", content)
        self.assertIn("CONFIG_SERIAL=y", content)

    # ── Missing klipper path ──────────────────────────────────────────────────

    def test_nonexistent_klipper_path_returns_false(self):
        """If klipper_path does not exist, must return (False, <error>)."""
        ok, msg = generate_firmware_config(
            {"CONFIG_MCU": '"stm32"'}, "/nonexistent/path/to/klipper"
        )
        self.assertFalse(ok)
        self.assertIn("not found", msg.lower())

    def test_error_message_contains_path(self):
        """The error message must contain the offending path for debuggability."""
        ok, msg = generate_firmware_config({}, "/no/such/directory")
        self.assertFalse(ok)
        self.assertIn("/no/such/directory", msg)


# ── validate_config ───────────────────────────────────────────────────────────

class TestValidateFirmwareConfig(unittest.TestCase):
    """Tests for firmware/validator.py — validates a generated .config file."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.klipper_path = self._tmpdir.name
        self.config_path = os.path.join(self.klipper_path, ".config")

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write_config(self, content: str):
        with open(self.config_path, "w", encoding="utf-8") as f:
            f.write(content)

    # ── Happy path ────────────────────────────────────────────────────────────

    def test_valid_stm32_usb_config(self):
        """A complete STM32 USB config must pass validation."""
        self._write_config(
            'CONFIG_MCU="stm32"\n'
            "CONFIG_MCU_STM32F446XX=y\n"
            "CONFIG_FLASH_START=0x8000\n"
            "CONFIG_USB=y\n"
        )
        ok, msg = validate_config(self.klipper_path)
        self.assertTrue(ok, f"Expected validation to pass, got: {msg}")

    def test_valid_rp2040_usb_config(self):
        """RP2040 USB config with no flash offset must pass validation."""
        self._write_config('CONFIG_MCU="rp2040"\nCONFIG_USB=y\n')
        ok, msg = validate_config(self.klipper_path)
        self.assertTrue(ok, f"Expected validation to pass, got: {msg}")

    def test_valid_linux_process_config(self):
        """Linux process MCU (used for host-side Klipper) must pass validation
        even with no communication interface flag."""
        self._write_config('CONFIG_MCU="linux"\n')
        ok, msg = validate_config(self.klipper_path)
        self.assertTrue(ok, f"Expected validation to pass, got: {msg}")

    # ── Missing CONFIG_MCU ────────────────────────────────────────────────────

    def test_missing_mcu_architecture_fails(self):
        """CONFIG_MCU missing must return (False, ...) with a descriptive message."""
        self._write_config("CONFIG_USB=y\nCONFIG_FLASH_START=0x8000\n")
        ok, msg = validate_config(self.klipper_path)
        self.assertFalse(ok)
        self.assertIn("CONFIG_MCU", msg)

    # ── Missing flash offset for STM32 / LPC ─────────────────────────────────

    def test_stm32_missing_flash_offset_fails(self):
        """STM32 without CONFIG_FLASH_START must fail validation."""
        self._write_config('CONFIG_MCU="stm32"\nCONFIG_USB=y\n')
        ok, msg = validate_config(self.klipper_path)
        self.assertFalse(ok)
        self.assertIn("FLASH_START", msg)

    def test_lpc_missing_flash_offset_fails(self):
        """LPC176x without CONFIG_FLASH_START must fail validation."""
        self._write_config('CONFIG_MCU="lpc176x"\nCONFIG_SERIAL=y\n')
        ok, msg = validate_config(self.klipper_path)
        self.assertFalse(ok)
        self.assertIn("FLASH_START", msg)

    def test_rp2040_without_flash_offset_passes(self):
        """RP2040 must pass validation even without CONFIG_FLASH_START."""
        self._write_config('CONFIG_MCU="rp2040"\nCONFIG_USB=y\n')
        ok, msg = validate_config(self.klipper_path)
        self.assertTrue(ok)

    # ── Missing communication interface ──────────────────────────────────────

    def test_no_communication_interface_fails(self):
        """A non-Linux MCU with no USB/UART/CAN/SPI flag must fail validation."""
        self._write_config(
            'CONFIG_MCU="stm32"\nCONFIG_FLASH_START=0x8000\n'
        )
        ok, msg = validate_config(self.klipper_path)
        self.assertFalse(ok)
        # Must mention interface in error message
        msg_lower = msg.lower()
        self.assertTrue(
            any(w in msg_lower for w in ["usb", "uart", "can", "interface", "communication"]),
            f"Expected communication error, got: {msg}",
        )

    def test_uart_communication_accepted(self):
        """CONFIG_SERIAL=y (UART) must satisfy the communication requirement."""
        self._write_config(
            'CONFIG_MCU="stm32"\n'
            "CONFIG_FLASH_START=0x8000\n"
            "CONFIG_SERIAL=y\n"
        )
        ok, msg = validate_config(self.klipper_path)
        self.assertTrue(ok, f"Expected UART to pass validation, got: {msg}")

    def test_canbus_communication_accepted(self):
        """CONFIG_CANBUS=y must satisfy the communication requirement."""
        self._write_config(
            'CONFIG_MCU="stm32"\n'
            "CONFIG_FLASH_START=0x8000\n"
            "CONFIG_CANBUS=y\n"
        )
        ok, msg = validate_config(self.klipper_path)
        self.assertTrue(ok, f"Expected CAN to pass validation, got: {msg}")

    # ── Missing .config file ──────────────────────────────────────────────────

    def test_missing_config_file_returns_false(self):
        """If .config does not exist, must return (False, ...) without raising."""
        ok, msg = validate_config(self.klipper_path)
        self.assertFalse(ok)
        self.assertIn(".config", msg.lower())

    def test_return_type_is_tuple(self):
        """validate_config must always return a (bool, str) tuple."""
        result = validate_config(self.klipper_path)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], bool)
        self.assertIsInstance(result[1], str)


if __name__ == "__main__":
    unittest.main()
