import unittest

from core.capabilities import (
    finite_number,
    supported_firmware_architectures,
    supported_kinematics,
    normalize_and_validate_configuration,
    validate_kinematics,
    validate_sensor_type,
)
from core.exceptions import GenerationError


class TestCapabilities(unittest.TestCase):
    def test_wizard_and_generator_kinematics_contract_excludes_delta(self):
        self.assertEqual(supported_kinematics(), ("cartesian", "corexy"))
        self.assertEqual(validate_kinematics(" CoreXY "), "corexy")
        with self.assertRaises(GenerationError):
            validate_kinematics("delta")

    def test_non_finite_and_out_of_range_values_are_rejected_with_field_name(self):
        for value in ("nan", "inf", "-inf"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(GenerationError, "x_size"):
                    finite_number("x_size", value, minimum=1, maximum=2000)
        with self.assertRaisesRegex(GenerationError, "probe_x_offset"):
            finite_number("probe_x_offset", "1001", minimum=-1000, maximum=1000)

    def test_sensor_type_must_be_nonempty(self):
        with self.assertRaisesRegex(GenerationError, "hotend_thermistor"):
            validate_sensor_type("hotend_thermistor", "  ")

    def test_homing_direction_accepts_only_klipper_booleans(self):
        data = {
            "kinematics": "cartesian",
            "probe": "None",
            "hotend_thermistor": "Generic 3950",
            "bed_thermistor": "Generic 3950",
            "homing_positive_dir_x": False,
        }
        normalize_and_validate_configuration(data)
        self.assertEqual(data["homing_positive_dir_x"], "False")

        data["homing_positive_dir_x"] = "towards-end"
        with self.assertRaisesRegex(GenerationError, "homing_positive_dir_x"):
            normalize_and_validate_configuration(data)

    def test_printable_z_must_be_above_mechanical_minimum(self):
        data = {
            "kinematics": "cartesian",
            "probe": "None",
            "hotend_thermistor": "Generic 3950",
            "bed_thermistor": "Generic 3950",
            "z_position_min": "100",
            "z_position_endstop": "100",
            "z_position_max": "250",
            "printable_z_max": "50",
        }
        with self.assertRaisesRegex(GenerationError, "printable_z_max"):
            normalize_and_validate_configuration(data)

    def test_firmware_architectures_come_from_derivation_database(self):
        architectures = supported_firmware_architectures()
        self.assertIn("stm32", architectures)
        self.assertIn("rp2040", architectures)
        self.assertNotIn("stm32f4", architectures)


if __name__ == "__main__":
    unittest.main()
