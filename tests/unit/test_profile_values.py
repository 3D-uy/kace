import os
import tempfile
import unittest

from core.generator import generate_config
from core.exceptions import GenerationError
from core.profile_values import (
    ValueProvenance,
    extract_profile_values,
    mark_profile_values,
    mark_user_override,
)
from tests.unit.test_generator import _parsed, _user


class TestProfileValueResolution(unittest.TestCase):
    def _generate(self, parsed, user):
        with tempfile.NamedTemporaryFile(suffix=".cfg", delete=False) as output:
            path = output.name
        try:
            return generate_config(parsed, user, output_path=path)
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_profile_motion_heater_and_driver_values_survive_generation(self):
        parsed = _parsed(
            printer={
                "kinematics": "cartesian",
                "max_velocity": "420",
                "max_accel": "6200",
                "max_z_velocity": "18",
                "max_z_accel": "350",
            },
            stepper_x={
                **_parsed()["stepper_x"],
                "microsteps": "32",
                "rotation_distance": "39.75",
                "homing_speed": "75",
                "homing_positive_dir": "True",
                "position_min": "0",
                "position_max": "235",
                "position_endstop": "235",
            },
            extruder={
                **_parsed()["extruder"],
                "microsteps": "32",
                "rotation_distance": "22.678",
                "nozzle_diameter": "0.600",
                "filament_diameter": "2.850",
                "sensor_type": "Generic 3950",
                "control": "pid",
                "pid_kp": "30.1",
                "pid_ki": "2.2",
                "pid_kd": "101.3",
                "min_temp": "5",
                "max_temp": "285",
            },
            heater_bed={
                **_parsed()["heater_bed"],
                "sensor_type": "Generic 3950",
                "control": "pid",
                "pid_kp": "60.2",
                "pid_ki": "1.2",
                "pid_kd": "700.4",
                "min_temp": "2",
                "max_temp": "120",
            },
            **{
                "tmc2209 stepper_x": {
                    "uart_pin": "PA10",
                    "run_current": "0.91",
                    "hold_current": "0.31",
                    "stealthchop_threshold": "0",
                }
            },
        )
        user = _user(
            driver_type="TMC2209",
            driver_mode="UART",
            x_position_endstop="235",
            _profile_parsed=parsed,
        )
        user.update(extract_profile_values(parsed))
        mark_profile_values(user, parsed)

        result = self._generate(parsed, user)
        content = result["content"]
        self.assertIn("max_velocity: 420", content)
        self.assertIn("microsteps: 32", content)
        self.assertIn("rotation_distance: 39.75", content)
        self.assertIn("homing_positive_dir: True", content)
        self.assertIn("nozzle_diameter: 0.600", content)
        self.assertIn("filament_diameter: 2.850", content)
        self.assertIn("pid_Kp: 30.1", content)
        self.assertIn("run_current: 0.91", content)
        self.assertEqual(
            result["value_provenance"]["max_velocity"], ValueProvenance.PROFILE.value
        )
        self.assertIn("#   max_velocity=PROFILE", content)

    def test_user_override_wins_and_is_recorded(self):
        parsed = _parsed(printer={"kinematics": "cartesian", "max_velocity": "420"})
        user = _user(_profile_parsed=parsed)
        user.update(extract_profile_values(parsed))
        mark_profile_values(user, parsed)
        user["max_velocity"] = "275"
        mark_user_override(user, "max_velocity")

        result = self._generate(parsed, user)
        self.assertIn("max_velocity: 275", result["content"])
        self.assertEqual(
            result["value_provenance"]["max_velocity"], ValueProvenance.USER_OVERRIDE.value
        )

    def test_probe_z_minimum_uses_contextual_default_but_never_overrides_user(self):
        parsed = _parsed(bltouch={"sensor_pin": "^PB2", "control_pin": "PB3"})
        safe_default_user = _user(
            probe="BLTouch",
            z_position_min="0",
            _value_provenance={"z_position_min": ValueProvenance.SAFE_DEFAULT.value},
        )
        self.assertIn("position_min: -2", self._generate(parsed, safe_default_user)["content"])

        explicit_user = _user(probe="BLTouch", z_position_min="0")
        self.assertIn("position_min: 0", self._generate(parsed, explicit_user)["content"])

    def test_explicit_unresolved_safety_value_blocks_generation(self):
        user = _user(
            _value_provenance={"hotend_max_temp": ValueProvenance.UNRESOLVED.value}
        )
        with self.assertRaisesRegex(GenerationError, "hotend_max_temp"):
            self._generate(_parsed(), user)


if __name__ == "__main__":
    unittest.main()
