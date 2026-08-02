# tests/unit/test_adr_validation.py
import os
import tempfile
import unittest
from core.generator import generate_config
from core.exceptions import GenerationError

_BASE_USER_DATA = {
    "mcu_path": "/dev/serial/by-id/usb-test-if00",
    "board": "test-board.cfg",
    "printer_profile": "test-board.cfg",
    "kinematics": "cartesian",
    "probe": "None",
    "driver_type": "None (Standard)",
    "driver_mode": "Standalone",
    "hotend_thermistor": "EPCOS 100K B57560G104F",
    "bed_thermistor": "EPCOS 100K B57560G104F",
    "web_interface": "None",
    "z_motors": "1",
    "motors": "4",
    "extruder": "1",
    "runout": "No",
    "language": "en"
}

_PARSED_COMPLETE = {
    "stepper_x": {
        "step_pin": "PA1",
        "dir_pin": "PA2",
        "enable_pin": "PA3",
        "endstop_pin": "PA4",
    },
    "stepper_y": {
        "step_pin": "PB1",
        "dir_pin": "PB2",
        "enable_pin": "PB3",
        "endstop_pin": "PB4",
    },
    "stepper_z": {
        "step_pin": "PC1",
        "dir_pin": "PC2",
        "enable_pin": "PC3",
        "endstop_pin": "PC4",
    },
    "extruder": {
        "step_pin": "PD1",
        "dir_pin": "PD2",
        "enable_pin": "PD3",
        "heater_pin": "PD4",
        "sensor_pin": "PD5",
    },
    "heater_bed": {
        "heater_pin": "PE1",
        "sensor_pin": "PE2",
    },
    "fan": {
        "pin": "PE3",
    }
}

class TestAdrValidation(unittest.TestCase):

    def test_valid_geometry_generation(self):
        """Test configuration generation succeeds with correct decoupled geometry."""
        user_data = dict(_BASE_USER_DATA)
        user_data.update({
            "x_size": "250",
            "y_size": "250",
            "z_size": "250",
            "x_position_min": "-10",
            "x_position_max": "260",
            "x_position_endstop": "-10",
            "y_position_min": "-15",
            "y_position_max": "255",
            "y_position_endstop": "-15",
            "z_position_min": "0",
            "z_position_max": "260",
            "z_position_endstop": "0",
            "printable_x_min": "0",
            "printable_x_max": "250",
            "printable_y_min": "0",
            "printable_y_max": "250",
            "printable_z_max": "250"
        })
        with tempfile.TemporaryDirectory() as tmpdir:
            output = generate_config(
                parsed_data=_PARSED_COMPLETE,
                user_data=user_data,
                output_path=os.path.join(tmpdir, "printer.cfg"),
            )
        self.assertTrue(len(output) > 0)

    def test_printable_width_exceeds_travel(self):
        """Test generation fails when printable width exceeds travel range."""
        user_data = dict(_BASE_USER_DATA)
        user_data.update({
            "x_size": "300",
            "y_size": "250",
            "z_size": "250",
            "x_position_min": "0",
            "x_position_max": "280",      # travel range = 280
            "printable_x_min": "0",
            "printable_x_max": "300"       # printable width = 300
        })
        with self.assertRaises(GenerationError) as context:
            generate_config(parsed_data=_PARSED_COMPLETE, user_data=user_data)
        self.assertIn("exceeds maximum X travel range", str(context.exception))

    def test_printable_depth_exceeds_travel(self):
        """Test generation fails when printable depth exceeds travel range."""
        user_data = dict(_BASE_USER_DATA)
        user_data.update({
            "x_size": "250",
            "y_size": "300",
            "z_size": "250",
            "y_position_min": "0",
            "y_position_max": "280",      # travel range = 280
            "printable_y_min": "0",
            "printable_y_max": "300"       # printable depth = 300
        })
        with self.assertRaises(GenerationError) as context:
            generate_config(parsed_data=_PARSED_COMPLETE, user_data=user_data)
        self.assertIn("exceeds maximum Y travel range", str(context.exception))

    def test_printable_height_exceeds_travel(self):
        """Test generation fails when printable height exceeds travel range."""
        user_data = dict(_BASE_USER_DATA)
        user_data.update({
            "x_size": "250",
            "y_size": "250",
            "z_size": "300",
            "z_position_min": "0",
            "z_position_max": "280",      # travel range = 280
            "printable_z_max": "300"       # printable height = 300
        })
        with self.assertRaises(GenerationError) as context:
            generate_config(parsed_data=_PARSED_COMPLETE, user_data=user_data)
        self.assertIn("exceeds maximum Z travel range", str(context.exception))

    def test_printable_boundary_outside_travel_limits(self):
        """Test generation fails when printable bounds are outside travel limits."""
        # 1. X min outside travel
        user_data = dict(_BASE_USER_DATA)
        user_data.update({
            "x_size": "250",
            "y_size": "250",
            "z_size": "250",
            "x_position_min": "10",       # travel min is 10
            "x_position_max": "260",       # travel max is 260 (range = 250)
            "x_position_endstop": "10",   # endstop matches min to prevent auto-adjustment
            "printable_x_min": "0",       # printable min starts at 0 (impossible)
            "printable_x_max": "250"
        })
        with self.assertRaises(GenerationError) as context:
            generate_config(parsed_data=_PARSED_COMPLETE, user_data=user_data)
        self.assertIn("is outside physical X travel limits", str(context.exception))

if __name__ == '__main__':
    unittest.main()
