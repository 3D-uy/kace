import unittest
import io
from contextlib import redirect_stdout
from core.scraper import parse_config, extract_profile_defaults
from core.wizard import print_detected_profile_summary

class TestProfileSummary(unittest.TestCase):

    def test_complete_profile_summary_output(self):
        """Verify that print_detected_profile_summary prints a complete, formatted configuration summary with inline comments."""
        cfg_content = """
[printer]
kinematics: cartesian

[stepper_x]
step_pin: PC2
position_min: -10
position_max: 300
position_endstop: -5

[stepper_y]
step_pin: PC3
position_min: 0
position_max: 300
position_endstop: 0

[stepper_z]
step_pin: PC4
position_min: -2
position_max: 350
position_endstop: 0

[bltouch]
sensor_pin: ^PB1
control_pin: PB0
x_offset: -38
y_offset: 0
# z_offset is intentionally omitted to test "unknown" fallback

[tmc2209 stepper_x]
uart_pin: PC11
run_current: 0.580

[extruder]
step_pin: PB3
sensor_type: Generic 3950

[heater_bed]
heater_pin: PB4
sensor_type: Generic 3950

[st7920]
cs_pin: PB5
        """
        parsed = parse_config(cfg_content)
        defaults = extract_profile_defaults(parsed)
        
        f = io.StringIO()
        with redirect_stdout(f):
            print_detected_profile_summary(defaults, parsed)
            
        output = f.getvalue()
        
        # Verify cyan headers exist
        # Verify cyan headers exist
        self.assertIn("\033[96mMotion System\033[0m", output)
        self.assertIn("\033[96mBuild Volume\033[0m", output)
        self.assertIn("\033[96mThermistors\033[0m", output)
        self.assertNotIn("Probe", output)
        self.assertNotIn("Drivers", output)
        self.assertNotIn("Displays", output)
        
        # Verify dim comments style is used
        self.assertIn("\033[2m# ", output)
        
        # Verify labels, values, and comments are printed
        self.assertIn("Kinematics:", output)
        self.assertIn("cartesian", output)
        self.assertIn("printer kinematics model", output)
        
        self.assertIn("X position_min:", output)
        self.assertIn("-10", output)
        self.assertIn("minimum position travel in X", output)
        
        self.assertIn("Build volume:", output)
        self.assertIn("300 x 300 x 350", output)
        self.assertIn("printable bed travel envelope", output)
        
        self.assertIn("Hotend thermistor:", output)
        self.assertIn("Generic 3950", output)
        self.assertIn("hotend temperature sensor type", output)

    def test_partial_profile_summary_output(self):
        """Verify that print_detected_profile_summary omits missing sections and values."""
        cfg_content = """
[printer]
kinematics: corexy

[stepper_x]
step_pin: PC2
position_max: 200

[stepper_y]
step_pin: PC3
position_max: 200

[stepper_z]
step_pin: PC4
position_max: 200
        """
        parsed = parse_config(cfg_content)
        defaults = extract_profile_defaults(parsed)
        
        f = io.StringIO()
        with redirect_stdout(f):
            print_detected_profile_summary(defaults, parsed)
            
        output = f.getvalue()
        
        # Motion system and Build Volume should exist
        self.assertIn("Motion System", output)
        self.assertIn("Kinematics:", output)
        self.assertIn("corexy", output)
        self.assertIn("X position_max:", output)
        
        # Omitted fields should not be in the output
        self.assertNotIn("position_min", output)
        self.assertNotIn("position_endstop", output)
        
        self.assertIn("Build Volume", output)
        self.assertIn("Build volume:", output)
        self.assertIn("200 x 200 x 200", output)
        
        # Probe, Drivers, Thermistors, and Displays should be omitted completely
        self.assertNotIn("Probe", output)
        self.assertNotIn("Drivers", output)
        self.assertNotIn("Thermistors", output)
        self.assertNotIn("Displays", output)

if __name__ == '__main__':
    unittest.main()
