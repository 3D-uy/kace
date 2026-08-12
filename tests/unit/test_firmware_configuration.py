import unittest

from firmware.configuration import (
    BootloaderOffset,
    BootloaderOffsetKind,
    FirmwareConfigurationError,
    bootloader_offset_from_config,
    render_config_diff,
    validate_firmware_configuration,
    validate_processor_for_architecture,
)
from firmware.derivation import derive_config


class FirmwareConfigurationTests(unittest.TestCase):
    def test_typed_offset_rejects_internally_contradictory_values(self):
        with self.assertRaises(FirmwareConfigurationError):
            BootloaderOffset(BootloaderOffsetKind.ADDRESS, 0)
        with self.assertRaises(FirmwareConfigurationError):
            BootloaderOffset(BootloaderOffsetKind.NOT_APPLICABLE, 0)

    def test_zero_offset_is_typed_and_persisted_for_no_bootloader(self):
        config = derive_config(
            "stm32f103rc", hint="usb", flash_start=BootloaderOffset.no_bootloader()
        )
        offset = bootloader_offset_from_config(config, "stm32f103rc")

        self.assertEqual(offset.kind, BootloaderOffsetKind.NO_BOOTLOADER)
        self.assertEqual(config["CONFIG_FLASH_START"], "0x0")
        validate_firmware_configuration(config, processor="stm32f103rc")

    def test_lpc_no_bootloader_is_typed_and_validates_as_explicit_zero(self):
        config = derive_config(
            "lpc1769", hint="usb", flash_start=BootloaderOffset.no_bootloader()
        )

        self.assertEqual(config["CONFIG_FLASH_START"], "0x0")
        self.assertEqual(config["CONFIG_CLOCK_FREQ"], "120000000")
        validate_firmware_configuration(config, processor="lpc1769")

    def test_not_applicable_offset_remains_absent_for_rp2040(self):
        config = derive_config("rp2040", hint="usb")
        offset = bootloader_offset_from_config(config, "rp2040")

        self.assertEqual(offset.kind, BootloaderOffsetKind.NOT_APPLICABLE)
        self.assertNotIn("CONFIG_FLASH_START", config)
        validate_firmware_configuration(config, processor="rp2040")

    def test_offset_cannot_leak_into_architecture_where_it_is_not_applicable(self):
        with self.assertRaisesRegex(ValueError, "not applicable"):
            derive_config("rp2040", hint="usb", flash_start="0x8000")

    def test_processor_and_architecture_must_describe_same_target(self):
        config = derive_config("stm32f446xx", hint="usb")
        config["CONFIG_MCU"] = '"avr"'

        with self.assertRaisesRegex(FirmwareConfigurationError, "conflicts"):
            validate_firmware_configuration(config, processor="stm32f446xx")
        with self.assertRaisesRegex(FirmwareConfigurationError, "belongs to"):
            validate_processor_for_architecture("atmega2560", "stm32")

    def test_stale_dependent_flags_are_rejected_as_a_whole(self):
        config = derive_config("stm32f446xx", hint="usb")
        config["CONFIG_MACH_LPC176X"] = "y"
        config["CONFIG_CLOCK_FREQ"] = "120000000"

        with self.assertRaises(FirmwareConfigurationError) as raised:
            validate_firmware_configuration(config, processor="stm32f446xx")
        self.assertIn("CONFIG_CLOCK_FREQ", str(raised.exception))

    def test_processor_change_rederivation_discards_old_clock_offset_and_flags(self):
        before = derive_config("lpc1769", hint="usb")
        after = derive_config("stm32f446xx", hint="usb")

        validate_firmware_configuration(after, processor="stm32f446xx")
        self.assertNotIn("CONFIG_MACH_LPC176X", after)
        self.assertNotIn("CONFIG_MCU_LPC1769", after)
        self.assertNotIn("CONFIG_CLOCK_FREQ", after)
        self.assertEqual(after["CONFIG_FLASH_START"], "0x8000")
        diff = render_config_diff(before, after)
        self.assertIn("-CONFIG_CLOCK_FREQ=120000000", diff)
        self.assertIn("+CONFIG_MACH_STM32=y", diff)


if __name__ == "__main__":
    unittest.main()
