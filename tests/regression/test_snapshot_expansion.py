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


# ── Mock raw configs ───────────────────────────────────────────────────────────
# Each string represents a minimal but realistic Klipper config for its target
# board — enough to exercise parse_config + extract_profile_defaults + Jinja2
# template rendering for snapshot comparison.

MOCK_CREALITY_422 = """
[stepper_x]
step_pin: PC2
dir_pin: PB9
enable_pin: !PC3
microsteps: 16
rotation_distance: 40
endstop_pin: ^PA5
position_endstop: 0
position_max: 235
homing_speed: 50

[stepper_y]
step_pin: PB8
dir_pin: PB7
enable_pin: !PC3
microsteps: 16
rotation_distance: 40
endstop_pin: ^PA6
position_endstop: 0
position_max: 235
homing_speed: 50

[stepper_z]
step_pin: PB6
dir_pin: PB5
enable_pin: !PC3
microsteps: 16
rotation_distance: 8
endstop_pin: ^PA7
position_endstop: 0.0
position_max: 250

[extruder]
step_pin: PB4
dir_pin: PB3
enable_pin: !PC3
microsteps: 16
rotation_distance: 33.500
nozzle_diameter: 0.400
filament_diameter: 1.750
heater_pin: PA1
sensor_type: EPCOS 100K B57560G104F
sensor_pin: PC5
control: pid
pid_Kp: 21.527
pid_Ki: 1.063
pid_Kd: 108.982
min_temp: 0
max_temp: 250

[heater_bed]
heater_pin: PA2
sensor_type: EPCOS 100K B57560G104F
sensor_pin: PC4
control: pid
pid_Kp: 54.027
pid_Ki: 0.770
pid_Kd: 948.182
min_temp: 0
max_temp: 130

[mcu]
serial: /dev/serial/by-id/usb-Klipper_stm32f103xe_mock-if00

[printer]
kinematics: cartesian
max_velocity: 300
max_accel: 500
max_z_velocity: 5
max_z_accel: 100
"""

MOCK_CREALITY_427 = MOCK_CREALITY_422  # Same pinout, different filename

MOCK_OCTOPUS = """
[stepper_x]
step_pin: PF13
dir_pin: PF12
enable_pin: !PF14
microsteps: 16
rotation_distance: 40
endstop_pin: PG6
position_endstop: 0
position_max: 350
homing_speed: 50

[stepper_y]
step_pin: PG0
dir_pin: PG1
enable_pin: !PF15
microsteps: 16
rotation_distance: 40
endstop_pin: PG9
position_endstop: 0
position_max: 350
homing_speed: 50

[stepper_z]
step_pin: PF11
dir_pin: PG3
enable_pin: !PG5
microsteps: 16
rotation_distance: 8
endstop_pin: PG10
position_endstop: 0.0
position_max: 400

[extruder]
step_pin: PE2
dir_pin: PE3
enable_pin: !PD4
microsteps: 16
rotation_distance: 22.6789511
nozzle_diameter: 0.400
filament_diameter: 1.750
heater_pin: PA2
sensor_type: Generic 3950
sensor_pin: PF4
control: pid
pid_Kp: 26.213
pid_Ki: 1.304
pid_Kd: 131.721
min_temp: 0
max_temp: 300

[heater_bed]
heater_pin: PA3
sensor_type: Generic 3950
sensor_pin: PF3
control: pid
pid_Kp: 54.027
pid_Ki: 0.770
pid_Kd: 948.182
min_temp: 0
max_temp: 130

[mcu]
serial: /dev/serial/by-id/usb-Klipper_stm32f446xx_mock-if00

[printer]
kinematics: cartesian
max_velocity: 500
max_accel: 3000
max_z_velocity: 15
max_z_accel: 300
"""

MOCK_SKR_PICO_RP2040 = """
[stepper_x]
step_pin: gpio11
dir_pin: !gpio10
enable_pin: !gpio12
microsteps: 16
rotation_distance: 40
endstop_pin: ^gpio4
position_endstop: 0
position_max: 235
homing_speed: 50

[stepper_y]
step_pin: gpio6
dir_pin: !gpio5
enable_pin: !gpio7
microsteps: 16
rotation_distance: 40
endstop_pin: ^gpio3
position_endstop: 0
position_max: 235
homing_speed: 50

[stepper_z]
step_pin: gpio19
dir_pin: !gpio28
enable_pin: !gpio2
microsteps: 16
rotation_distance: 8
endstop_pin: ^gpio25
position_endstop: 0.0
position_max: 300

[extruder]
step_pin: gpio14
dir_pin: !gpio13
enable_pin: !gpio15
microsteps: 16
rotation_distance: 33.500
nozzle_diameter: 0.400
filament_diameter: 1.750
heater_pin: gpio23
sensor_type: EPCOS 100K B57560G104F
sensor_pin: gpio26
control: pid
pid_Kp: 21.527
pid_Ki: 1.063
pid_Kd: 108.982
min_temp: 0
max_temp: 260

[heater_bed]
heater_pin: gpio21
sensor_type: EPCOS 100K B57560G104F
sensor_pin: gpio27
control: pid
pid_Kp: 54.027
pid_Ki: 0.770
pid_Kd: 948.182
min_temp: 0
max_temp: 130

[mcu]
serial: /dev/serial/by-id/usb-Klipper_rp2040_mock-if00

[printer]
kinematics: cartesian
max_velocity: 300
max_accel: 3000
max_z_velocity: 5
max_z_accel: 100
"""

MOCK_SKR_V13_LPC176X = """
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
serial: /dev/serial/by-id/usb-Klipper_lpc1768_mock-if00

[printer]
kinematics: cartesian
max_velocity: 400
max_accel: 500
max_z_velocity: 10
max_z_accel: 100
"""

MOCK_SKR_MINI_E3_SENSORLESS = """
[stepper_x]
step_pin: PB13
dir_pin: !PB12
enable_pin: !PB14
microsteps: 16
rotation_distance: 40
endstop_pin: tmc2209_stepper_x:virtual_endstop
position_endstop: 0
position_max: 235
homing_speed: 50
homing_retract_dist: 0

[tmc2209 stepper_x]
uart_pin: PC11
tx_pin: PC10
uart_address: 0
run_current: 0.580
diag_pin: ^PC0
driver_SGTHRS: 255

[stepper_y]
step_pin: PB10
dir_pin: !PB2
enable_pin: !PB11
microsteps: 16
rotation_distance: 40
endstop_pin: tmc2209_stepper_y:virtual_endstop
position_endstop: 0
position_max: 235
homing_speed: 50
homing_retract_dist: 0

[tmc2209 stepper_y]
uart_pin: PC11
tx_pin: PC10
uart_address: 2
run_current: 0.580
diag_pin: ^PC1
driver_SGTHRS: 255

[stepper_z]
step_pin: PB0
dir_pin: PC5
enable_pin: !PB1
microsteps: 16
rotation_distance: 8
endstop_pin: ^PC2
position_endstop: 0.0
position_max: 250

[extruder]
step_pin: PB3
dir_pin: !PB4
enable_pin: !PD2
microsteps: 16
rotation_distance: 33.500
nozzle_diameter: 0.400
filament_diameter: 1.750
heater_pin: PC8
sensor_type: EPCOS 100K B57560G104F
sensor_pin: PA0
control: pid
pid_Kp: 21.527
pid_Ki: 1.063
pid_Kd: 108.982
min_temp: 0
max_temp: 250

[heater_bed]
heater_pin: PC9
sensor_type: EPCOS 100K B57560G104F
sensor_pin: PC3
control: pid
pid_Kp: 54.027
pid_Ki: 0.770
pid_Kd: 948.182
min_temp: 0
max_temp: 130

[mcu]
serial: /dev/serial/by-id/usb-Klipper_stm32f103xe_mock-if00

[printer]
kinematics: cartesian
max_velocity: 300
max_accel: 3000
max_z_velocity: 5
max_z_accel: 100
"""


def _make_user_data(parsed, board_name, mcu_path, drivers="TMC2209", probe="None",
                    probe_x_offset="0", probe_y_offset="0"):
    defaults = extract_profile_defaults(parsed)
    ud = {
        "mcu_path":          mcu_path,
        "kinematics":        defaults["kinematics"],
        "x_size":            defaults.get("x_size", "235"),
        "y_size":            defaults.get("y_size", "235"),
        "z_size":            defaults.get("z_size", "250"),
        "stepper_drivers":   drivers,
        "hotend_thermistor": defaults["hotend_thermistor"],
        "bed_thermistor":    defaults["bed_thermistor"],
        "probe":             probe,
        "probe_x_offset":    probe_x_offset,
        "probe_y_offset":    probe_y_offset,
        "motors":            "4",
        "z_motors":          "1",
        "extruder":          "1",
        "runout":            "Yes",
        "language":          "en",
    }
    for axis in ["x", "y", "z"]:
        for key in ["position_min", "position_max", "position_endstop"]:
            full_key = f"{axis}_{key}"
            if full_key in defaults:
                ud[full_key] = defaults[full_key]
    return ud


@_skip_no_jinja2
class TestSnapshotExpansion(KaceTestCase):
    """Regression snapshots for 6 additional board families."""

    def _run_snapshot(self, snapshot_name, raw_cfg, board_filename,
                      mcu_path, drivers="TMC2209", probe="None"):
        parsed = parse_config(raw_cfg, board_filename)
        user_data = _make_user_data(parsed, board_filename, mcu_path,
                                    drivers=drivers, probe=probe)
        kace_dir   = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        output_file = os.path.join(kace_dir, "tests", "fixtures",
                                   f"{snapshot_name}.temp.cfg")
        try:
            generate_config(parsed, user_data, output_path=output_file)
            with open(output_file, "r", encoding="utf-8") as f:
                actual = f.read()
            self.assertSnapshot(snapshot_name, actual)
        finally:
            if os.path.exists(output_file):
                os.remove(output_file)

    # ── Individual board tests ─────────────────────────────────────────────────

    def test_creality_422_snapshot(self):
        """Regression snapshot for Creality v4.2.2 (STM32F103)."""
        self._run_snapshot(
            "creality-v4.2.2-expected",
            MOCK_CREALITY_422,
            "generic-creality-v4.2.2.cfg",
            "/dev/serial/by-id/usb-Klipper_stm32f103xe_mock-if00",
            probe="BLTouch",
        )

    def test_creality_427_snapshot(self):
        """Regression snapshot for Creality v4.2.7 (STM32F103)."""
        self._run_snapshot(
            "creality-v4.2.7-expected",
            MOCK_CREALITY_427,
            "generic-creality-v4.2.7.cfg",
            "/dev/serial/by-id/usb-Klipper_stm32f103xe_mock-if00",
            probe="BLTouch",
        )

    def test_octopus_snapshot(self):
        """Regression snapshot for Octopus v1.1 (STM32F446)."""
        self._run_snapshot(
            "octopus-v1.1-expected",
            MOCK_OCTOPUS,
            "generic-bigtreetech-octopus-v1.1.cfg",
            "/dev/serial/by-id/usb-Klipper_stm32f446xx_mock-if00",
        )

    def test_skr_pico_rp2040_snapshot(self):
        """Regression snapshot for SKR Pico (RP2040)."""
        self._run_snapshot(
            "skr-pico-rp2040-expected",
            MOCK_SKR_PICO_RP2040,
            "generic-bigtreetech-skr-pico.cfg",
            "/dev/serial/by-id/usb-Klipper_rp2040_mock-if00",
        )

    def test_skr_v13_lpc176x_snapshot(self):
        """Regression snapshot for SKR v1.3 (LPC1768)."""
        self._run_snapshot(
            "skr-v1.3-lpc176x-expected",
            MOCK_SKR_V13_LPC176X,
            "generic-bigtreetech-skr-v1.3.cfg",
            "/dev/serial/by-id/usb-Klipper_lpc1768_mock-if00",
        )

    def test_skr_mini_e3_sensorless_snapshot(self):
        """Regression snapshot for SKR Mini E3 with sensorless homing (STM32F103)."""
        self._run_snapshot(
            "skr-mini-e3-v2-sensorless-expected",
            MOCK_SKR_MINI_E3_SENSORLESS,
            "generic-bigtreetech-skr-mini-e3-v2.0.cfg",
            "/dev/serial/by-id/usb-Klipper_stm32f103xe_mock-if00",
        )


if __name__ == "__main__":
    unittest.main()
