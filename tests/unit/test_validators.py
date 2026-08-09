import unittest
from core.validators import (
    validate_klipper_pin,
    questionary_pin_validator,
    questionary_numeric_validator,
    questionary_pos_numeric_validator,
    questionary_thermistor_validator,
    questionary_arch_validator,
    questionary_processor_validator,
    questionary_hex_offset_validator,
)

class TestValidators(unittest.TestCase):

    def test_valid_pins(self):
        valid = [
            "PA1", "^PC14", "!PB6", "^!PB7", "PC14.2", "gpio22", "ar2", "~PC13", "!^~PE5", "!^PA0",
            "toolhead:gpio5", "!toolhead:gpio5", "toolhead:!gpio5", "^toolhead:gpio5", "can0:gpio4", "toolhead:PC14.2"
        ]
        for p in valid:
            with self.subTest(pin=p):
                self.assertTrue(validate_klipper_pin(p))
                self.assertEqual(questionary_pin_validator(p), True)

    def test_invalid_pins(self):
        invalid = [
            "", "   ", "PA1$", "P@1", "P A1", "PA-1", "PB6#", "!^", "~", "PA 0", "../bad",
            "toolhead::gpio5", "toolhead: gpio5", "toolhead:gpio5:gpio6", ".", "___"
        ]
        for p in invalid:
            with self.subTest(pin=p):
                self.assertFalse(validate_klipper_pin(p))
                self.assertNotEqual(questionary_pin_validator(p), True)

    def test_numeric_validator(self):
        valid_nums = ["0", "-5.5", "235", "100.2", "<", "back", "volver", ""]
        for n in valid_nums:
            with self.subTest(val=n):
                self.assertTrue(questionary_numeric_validator(n))

        invalid_nums = ["abc", "12a", "--5", "2.3.4", "back-arrow", "nan", "inf", "-inf"]
        for n in invalid_nums:
            with self.subTest(val=n):
                self.assertNotEqual(questionary_numeric_validator(n), True)

    def test_pos_numeric_validator(self):
        valid_pos = ["0.1", "235", "100.2", "<", "back", "volver", ""]
        for n in valid_pos:
            with self.subTest(val=n):
                self.assertTrue(questionary_pos_numeric_validator(n))

        invalid_pos = ["0", "-5.5", "-0.1", "abc", "12a", "2.3.4", "nan", "inf"]
        for n in invalid_pos:
            with self.subTest(val=n):
                self.assertNotEqual(questionary_pos_numeric_validator(n), True)

    def test_thermistor_validator(self):
        valid_thermistors = [
            "EPCOS 100K B57560G104F",
            "NTC 100K (generic)",
            "ATC Semitec 104GT-2",
            "Generic 3950",
            "<", "back", "volver"
        ]
        for t_name in valid_thermistors:
            with self.subTest(val=t_name):
                self.assertEqual(questionary_thermistor_validator(t_name), True)

        invalid_thermistors = [
            "EPCOS\n100K",
            "NTC\r100K",
            "bad\x00name",
            "line1\nline2\n",
            "thermistor\x07test", "", "   "
        ]
        for t_name in invalid_thermistors:
            with self.subTest(val=t_name):
                self.assertNotEqual(questionary_thermistor_validator(t_name), True)

    def test_arch_validator(self):
        valid_archs = [
            "stm32", "rp2040", "lpc176x", "avr", "linux",
            "<", "back", "volver", ""
        ]
        for a in valid_archs:
            with self.subTest(val=a):
                self.assertEqual(questionary_arch_validator(a), True)

        invalid_archs = [
            "stm32\n", "stm-32", "stm 32", "stm32; rm -rf /", "stm32$", "arch\r\n",
            "atsam", "stm32f4", "ARCH_1"
        ]
        for a in invalid_archs:
            with self.subTest(val=a):
                self.assertNotEqual(questionary_arch_validator(a), True)

    def test_processor_validator_uses_firmware_database(self):
        for processor in ("stm32f446", "lpc1769", "rp2040", "atmega2560"):
            with self.subTest(processor=processor):
                self.assertEqual(questionary_processor_validator(processor), True)
        for processor in ("", "unknown-chip", "stm 32"):
            with self.subTest(processor=processor):
                self.assertNotEqual(questionary_processor_validator(processor), True)

    def test_hex_offset_validator(self):
        valid_offsets = [
            "0x8000", "0x0", "0x2000", "0x4000", "0x7000", "0x10000", "0x20000", "0X8000",
            "<", "back", "volver", ""
        ]
        for o in valid_offsets:
            with self.subTest(val=o):
                self.assertEqual(questionary_hex_offset_validator(o), True)

        invalid_offsets = [
            "0x8000\n", "8000", "0x800g", "0x", "0x8000; rm", "0x8000\r"
        ]
        for o in invalid_offsets:
            with self.subTest(val=o):
                self.assertNotEqual(questionary_hex_offset_validator(o), True)

if __name__ == "__main__":
    unittest.main()
