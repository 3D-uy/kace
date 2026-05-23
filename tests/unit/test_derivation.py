import unittest
import firmware.derivation as drv
import firmware.prompts as prm
import builtins
import os
from firmware.derivation import _FW_DB_FALLBACK

class TestDerivation(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Mock interactive prompts to avoid blocking tests
        cls.orig_prompt_comm = drv.prompt_communication_interface
        cls.orig_prompt_boot = drv.prompt_bootloader_offset
        cls.orig_prompt_mcu = drv.prompt_mcu_family

        drv.prompt_communication_interface = lambda mcu: 'USB'
        drv.prompt_bootloader_offset = lambda mcu, opts: '0x8000'
        drv.prompt_mcu_family = lambda: 'stm32'

    @classmethod
    def tearDownClass(cls):
        drv.prompt_communication_interface = cls.orig_prompt_comm
        drv.prompt_bootloader_offset = cls.orig_prompt_boot
        drv.prompt_mcu_family = cls.orig_prompt_mcu

    def test_stm32f446xx(self):
        cfg = drv.derive_config('stm32f446xx', hint='usb')
        self.assertEqual(cfg['CONFIG_MCU'], '"stm32"')
        self.assertEqual(cfg['CONFIG_FLASH_START'], '0x8000')
        self.assertEqual(cfg['CONFIG_USB'], 'y')
        self.assertEqual(cfg['CONFIG_MCU_STM32F446XX'], 'y')

    def test_lpc1769(self):
        cfg = drv.derive_config('lpc1769', hint='usb')
        self.assertEqual(cfg['CONFIG_MCU'], '"lpc176x"')
        self.assertEqual(cfg['CONFIG_FLASH_START'], '0x4000')
        self.assertEqual(cfg['CONFIG_CLOCK_FREQ'], '120000000')

    def test_rp2040(self):
        cfg = drv.derive_config('rp2040', hint='usb')
        self.assertEqual(cfg['CONFIG_MCU'], '"rp2040"')
        self.assertNotIn('CONFIG_FLASH_START', cfg, "RP2040 should have no flash offset")

    def test_atmega2560(self):
        cfg = drv.derive_config('atmega2560', hint='uart')
        self.assertEqual(cfg['CONFIG_MCU'], '"avr"')
        self.assertEqual(cfg.get('CONFIG_MCU_ATMEGA2560'), 'y')

    def test_stm32f103_exact_match(self):
        cfg = drv.derive_config('stm32f103', hint='usb')
        self.assertEqual(cfg['CONFIG_FLASH_START'], '0x7000')

    def test_stm32f103rc_substring_match(self):
        # Should match stm32f103, not generic stm32f1
        cfg = drv.derive_config('stm32f103rc', hint='usb')
        self.assertEqual(cfg['CONFIG_FLASH_START'], '0x7000')

    def test_linux_early_return(self):
        cfg = drv.derive_config('linux', hint='usb')
        self.assertEqual(cfg['CONFIG_MCU'], '"linux"')
        self.assertNotIn('CONFIG_USB', cfg, "Linux should early-return before interface")

    def test_precedence_validator_shadowing(self):
        """Simulate a shadowed pattern and ensure the validator catches it."""
        bad_yaml = """
mcu_firmware:
  - pattern: "stm32f"
    arch: stm32
  - pattern: "stm32f103"  # Shadowed by stm32f above
    arch: stm32
"""
        bad_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'bad_boards_test.yaml')
        )
        with open(bad_path, "w") as f:
            f.write(bad_yaml)

        logs = []
        original_print = builtins.print
        def mock_print(*args, **kwargs):
            logs.append(" ".join(map(str, args)))
        builtins.print = mock_print

        original_path = drv.os.path.join
        drv.os.path.join = lambda *args: bad_path if "boards.yaml" in args[-1] else original_path(*args)

        try:
            fallback = drv._load_firmware_db()
            self.assertEqual(fallback, _FW_DB_FALLBACK, "Validation failed to fall back on shadowed pattern")
            self.assertTrue(any("Invalid pattern precedence" in log for log in logs), "Missing warning log")
        finally:
            drv.os.path.join = original_path
            builtins.print = original_print
            if os.path.exists(bad_path):
                os.remove(bad_path)

if __name__ == '__main__':
    unittest.main()
