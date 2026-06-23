import unittest
import firmware.derivation as drv
import os
from firmware.derivation import _FW_DB_FALLBACK
from core.exceptions import DerivationAmbiguityError

class TestDerivation(unittest.TestCase):

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

    def test_ambiguity_errors(self):
        # 1. No MCU -> prompts for family
        with self.assertRaises(DerivationAmbiguityError) as ctx:
            drv.derive_config(None)
        self.assertEqual(ctx.exception.param, "mcu_family")
        self.assertIn("stm32", ctx.exception.options)

        # 2. Ambiguous bootloader offset (stm32 pattern has flash_start: None)
        with self.assertRaises(DerivationAmbiguityError) as ctx:
            drv.derive_config("stm32", hint="usb")
        self.assertEqual(ctx.exception.param, "bootloader_offset")
        self.assertIn("No bootloader (0x0)", ctx.exception.options)

        # 3. Missing communication interface
        with self.assertRaises(DerivationAmbiguityError) as ctx:
            drv.derive_config("stm32f446xx", hint=None)
        self.assertEqual(ctx.exception.param, "comm_interface")
        self.assertIn("USB", ctx.exception.options)

    def test_precedence_validator_shadowing(self):
        """Simulate a shadowed pattern and ensure the validator catches it."""
        import core.loader
        original_loader = core.loader.load_boards_yaml
        core.loader.load_boards_yaml = lambda: {
            "mcu_firmware": [
                {"pattern": "stm32f", "arch": "stm32"},
                {"pattern": "stm32f103", "arch": "stm32"}
            ]
        }

        logs = []
        import builtins
        original_print = builtins.print
        def mock_print(*args, **kwargs):
            logs.append(" ".join(map(str, args)))
        builtins.print = mock_print

        try:
            fallback = drv._load_firmware_db()
            self.assertEqual(fallback, _FW_DB_FALLBACK, "Validation failed to fall back on shadowed pattern")
            self.assertTrue(any("Invalid pattern precedence" in log for log in logs), "Missing warning log")
        finally:
            core.loader.load_boards_yaml = original_loader
            builtins.print = original_print

if __name__ == '__main__':
    unittest.main()
