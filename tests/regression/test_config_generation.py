import unittest
import os
from tests.kace_test_case import KaceTestCase
from core.scraper import parse_config, extract_profile_defaults

try:
    import jinja2  # noqa: F401
    _JINJA2_AVAILABLE = True
except ImportError:
    _JINJA2_AVAILABLE = False

if _JINJA2_AVAILABLE:
    from core.generator import generate_config
else:
    generate_config = None

_skip_no_jinja2 = unittest.skipUnless(
    _JINJA2_AVAILABLE,
    "jinja2 not installed — regression tests run in Docker only",
)

# Mock Klipper config representing generic-bigtreetech-skr-v1.4.cfg
MOCK_SKR14_RAW_CONFIG = """
# This file contains common pin mappings for the BIGTREETECH SKR V1.4
# board. To use this config, the firmware should be compiled for the
# LPC1768 or LPC1769(Turbo).

[stepper_x]
step_pin: P2.2
dir_pin: !P2.6
enable_pin: !P2.1
microsteps: 16
rotation_distance: 40
endstop_pin: P1.29
position_endstop: 0
position_max: 235
homing_speed: 50

[stepper_y]
step_pin: P0.19
dir_pin: !P0.20
enable_pin: !P2.8
microsteps: 16
rotation_distance: 40
endstop_pin: P1.28
position_endstop: 0
position_max: 235
homing_speed: 50

[stepper_z]
step_pin: P0.22
dir_pin: P2.11
enable_pin: !P0.21
microsteps: 16
rotation_distance: 8
endstop_pin: P1.27
position_endstop: 0.0
position_max: 300

[extruder]
step_pin: P2.13
dir_pin: !P0.11
enable_pin: !P2.12
microsteps: 16
rotation_distance: 33.500
nozzle_diameter: 0.400
filament_diameter: 1.750
heater_pin: P2.7
sensor_type: EPCOS 100K B57560G104F
sensor_pin: P0.24
control: pid
pid_Kp: 22.2
pid_Ki: 1.08
pid_Kd: 114
min_temp: 0
max_temp: 260

[heater_bed]
heater_pin: P2.5
sensor_type: EPCOS 100K B57560G104F
sensor_pin: P0.25
control: pid
pid_Kp: 54.027
pid_Ki: 0.770
pid_Kd: 948.182
min_temp: 0
max_temp: 130

[mcu]
serial: /dev/serial/by-id/usb-Klipper_Klipper_firmware_12345-if00

[printer]
kinematics: cartesian
max_velocity: 400
max_accel: 500
max_z_velocity: 10
max_z_accel: 100
"""

@_skip_no_jinja2
class TestConfigGeneration(KaceTestCase):

    def test_skr14_snapshot(self):
        """Regression test for generating a complete printer.cfg for an SKR v1.4."""
        
        # 1. Parse raw config
        parsed = parse_config(MOCK_SKR14_RAW_CONFIG, "generic-bigtreetech-skr-v1.4.cfg")
        defaults = extract_profile_defaults(parsed)

        # 2. Mock user wizard data
        user_data = {
            "mcu_path": "/dev/serial/by-id/usb-Klipper_lpc1769_mock-if00",
            "kinematics": defaults["kinematics"],
            "x_size": "235",
            "y_size": "235",
            "z_size": "250",
            "stepper_drivers": "TMC2209",
            "hotend_thermistor": defaults["hotend_thermistor"],
            "bed_thermistor": defaults["bed_thermistor"],
            "probe": "BLTouch",
            "motors": "4",
            "z_motors": "1",
            "extruder": "1",
            "runout": "Yes",
            "language": "en"
        }
        for axis in ["x", "y", "z"]:
            for key in ["position_min", "position_max", "position_endstop"]:
                full_key = f"{axis}_{key}"
                if full_key in defaults:
                    user_data[full_key] = defaults[full_key]

        # 3. Set up KACE env for templates
        kace_dir = os.path.join(os.path.dirname(__file__), "..", "..")
        kace_dir = os.path.abspath(kace_dir)
        
        # Temporary output path
        output_file = os.path.join(kace_dir, "tests", "fixtures", "printer.cfg.temp")

        # 4. Generate
        try:
            generate_config(parsed, user_data, output_path=output_file)
            
            # Read output
            with open(output_file, "r", encoding="utf-8") as f:
                actual_cfg = f.read()
                
            # 5. Snapshot Assertion
            self.assertSnapshot("skr-v1.4-expected", actual_cfg)
        finally:
            if os.path.exists(output_file):
                os.remove(output_file)

    def test_anet_a8_plus_profile_overrides_board_pins(self):
        """Verify that printer profile configuration overrides motherboard default pins."""
        mock_melzi_board = """
[stepper_x]
step_pin: PD7
dir_pin: PC5
enable_pin: !PD6
endstop_pin: ^!PC2
position_max: 200

[stepper_y]
step_pin: PC6
dir_pin: PC7
enable_pin: !PD6
endstop_pin: ^!PC3
position_max: 200

[stepper_z]
step_pin: PB3
dir_pin: !PB2
enable_pin: !PA5
endstop_pin: ^!PC4
position_max: 200

[extruder]
step_pin: PB1
dir_pin: PB0
enable_pin: !PD6
heater_pin: PD5
sensor_pin: PA7

[heater_bed]
heater_pin: PD2
sensor_pin: PA6
"""
        mock_anet_a8_plus_profile = """
[stepper_x]
step_pin: PD7
dir_pin: !PC5
enable_pin: !PD6
endstop_pin: ^!PC2
position_max: 300

[stepper_y]
step_pin: PC6
dir_pin: !PC7
enable_pin: !PD6
endstop_pin: ^!PC3
position_max: 300

[stepper_z]
step_pin: PB3
dir_pin: !PB2
enable_pin: !PA5
endstop_pin: ^!PC4
position_max: 350

[extruder]
step_pin: PB1
dir_pin: PB0
enable_pin: !PD6
heater_pin: PD5
sensor_pin: PA7

[heater_bed]
heater_pin: PD4
sensor_pin: PA6
"""
        # 1. Parse both
        board_parsed = parse_config(mock_melzi_board, "generic-melzi.cfg")
        profile_parsed = parse_config(mock_anet_a8_plus_profile, "printer-anet-a8-2019.cfg")
        
        # 2. Setup user_data
        user_data = {
            "mcu_path": "/dev/serial/by-id/usb-Klipper_atmega1284p_Melzi-if00",
            "kinematics": "cartesian",
            "x_size": "300",
            "y_size": "300",
            "z_size": "350",
            "stepper_drivers": "None (Standard)",
            "driver_type": "None (Standard)",
            "driver_mode": "Standalone",
            "hotend_thermistor": "Generic 3950",
            "bed_thermistor": "Generic 3950",
            "probe": "None",
            "motors": "4",
            "z_motors": "1",
            "extruder": "1",
            "runout": "No",
            "language": "en",
            "board": "generic-melzi.cfg",
            "printer_profile": "printer-anet-a8-2019.cfg"
        }
        
        # Merge profile pins into board config
        for section, section_data in profile_parsed.items():
            if section not in board_parsed:
                board_parsed[section] = {}
            for key, value in section_data.items():
                board_parsed[section][key] = value
                
        # 3. Generate config
        kace_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        output_file = os.path.join(kace_dir, "tests", "fixtures", "anet_a8_plus_temp.cfg")
        try:
            generate_config(board_parsed, user_data, output_path=output_file)
            
            # Read output
            with open(output_file, "r", encoding="utf-8") as f:
                content = f.read()
                
            # Verify pins are overridden
            self.assertIn("heater_pin: PD4", content)  # Overridden from profile!
            self.assertNotIn("heater_pin: PD2", content)  # Generic Melzi board pin is overridden!
            self.assertIn("dir_pin: !PC5", content)  # Overridden from profile!
            self.assertNotIn("dir_pin: PC5", content)  # Generic Melzi board pin is overridden!
        finally:
            if os.path.exists(output_file):
                os.remove(output_file)

if __name__ == '__main__':
    unittest.main()
