import unittest
from core.validators import validate_klipper_pin, questionary_pin_validator, questionary_numeric_validator, questionary_pos_numeric_validator

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
            "toolhead::gpio5", "toolhead: gpio5", "toolhead:gpio5:gpio6"
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

        invalid_nums = ["abc", "12a", "--5", "2.3.4", "back-arrow"]
        for n in invalid_nums:
            with self.subTest(val=n):
                self.assertNotEqual(questionary_numeric_validator(n), True)

    def test_pos_numeric_validator(self):
        valid_pos = ["0.1", "235", "100.2", "<", "back", "volver", ""]
        for n in valid_pos:
            with self.subTest(val=n):
                self.assertTrue(questionary_pos_numeric_validator(n))

        invalid_pos = ["0", "-5.5", "-0.1", "abc", "12a", "2.3.4"]
        for n in invalid_pos:
            with self.subTest(val=n):
                self.assertNotEqual(questionary_pos_numeric_validator(n), True)

if __name__ == "__main__":
    unittest.main()
