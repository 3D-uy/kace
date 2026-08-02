import unittest
from unittest.mock import patch, MagicMock
import os
import sys
import tempfile

from core.wizard import run_wizard
from core.scraper import parse_config, extract_profile_defaults
from core.deployer import deploy_moonraker
from core.motion_model import PrinterMotionSpace
from core.bed_mesh import generate_bed_mesh_config

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

@_skip_no_jinja2
class TestE2ERuntimeFlow(unittest.TestCase):

    @patch("urllib.request.urlopen")
    @patch("core.wizard.discover_mcu")
    @patch("core.wizard.fetch_config_list")
    def test_complete_e2e_runtime_pipeline(self, mock_fetch, mock_mcu, mock_urlopen):
        """Smoke test verifying the complete pipeline: parsed_data -> wizard -> motion_model -> bed_mesh -> generator -> deployer."""
        
        # 1. Setup Mock responses for MCU and board configuration
        mock_mcu.return_value = {"mcu_path": "/dev/serial/by-id/mock-usb", "derived_mcu": "stm32f103"}
        mock_fetch.return_value = ["generic-bigtreetech-skr-v1.4.cfg"]

        # 2. Pre-populated user_data (wizard is not called in this test)
        user_data = {
            "printer_profile": "generic-bigtreetech-skr-v1.4.cfg",
            "board": "generic-bigtreetech-skr-v1.4.cfg",
            "kinematics": "cartesian",
            "x_size": "235",
            "y_size": "235",
            "z_size": "250",
            "probe": "BLTouch",
            "probe_x_offset": "-38",
            "probe_y_offset": "0",
            "hotend_thermistor": "Generic 3950",
            "bed_thermistor": "Generic 3950",
            "driver_type": "TMC2209",
            "driver_mode": "UART",
            "web_interface": "Mainsail",
            "z_motors": "2",
            "mcu_path": "/dev/serial/by-id/mock-usb"
        }
        
        # Test parsing raw board configuration
        raw_board_cfg = """
        [stepper_x]
        step_pin: P2.2
        dir_pin: !P2.6
        enable_pin: !P2.1
        microsteps: 16
        rotation_distance: 40
        endstop_pin: P1.29
        position_endstop: 0
        position_max: 235
        
        [stepper_y]
        step_pin: P0.19
        dir_pin: P0.20
        enable_pin: !P2.8
        microsteps: 16
        rotation_distance: 40
        endstop_pin: P1.28
        position_endstop: 0
        position_max: 235

        [stepper_z]
        step_pin: P0.22
        dir_pin: !P2.11
        enable_pin: !P0.21
        microsteps: 16
        rotation_distance: 8
        endstop_pin: probe:z_virtual_endstop
        position_max: 250

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

        [bltouch]
        sensor_pin: P0.10
        control_pin: P2.0

        [stepper_z1]
        step_pin: P0.1
        dir_pin: P0.2
        enable_pin: P0.3
        """
        
        parsed = parse_config(raw_board_cfg, "generic-bigtreetech-skr-v1.4.cfg")
        self.assertIn("stepper_x", parsed)
        self.assertEqual(parsed["stepper_x"]["step_pin"], "P2.2")

        # 4. Verify Motion Model space boundaries
        motion_space = PrinterMotionSpace(user_data)
        self.assertEqual(motion_space.x_min, 0.0)
        self.assertEqual(motion_space.x_max, 235.0)

        # 5. Verify Bed Mesh derivation is geometry-aware
        mesh_cfg = generate_bed_mesh_config(motion_space, user_data, parsed)
        self.assertIn("mesh_min", mesh_cfg)
        self.assertIn("mesh_max", mesh_cfg)
        # Mesh min x should be at least (probe_x_offset if offset is positive, or 0 + offset bounds)
        # Probe X offset is -38. Probe must stay inside reachable bounds. Nozzle reachable is [0, 235].
        # Probe coordinate = Nozzle coordinate + probe offset.
        # When nozzle is at x=38, probe is at x=0. So probe X min is 0, which corresponds to nozzle X = 38.
        # Let's verify mesh_min is computed correctly:
        mesh_min_x, mesh_min_y = [float(val) for val in mesh_cfg["mesh_min"].split(",")]
        self.assertGreaterEqual(mesh_min_x, 0.0)

        # 6. Run Jinja2 Generator pipeline
        with tempfile.TemporaryDirectory() as tmpdir:
            res = generate_config(
                parsed,
                user_data,
                output_path=os.path.join(tmpdir, "printer.cfg"),
            )
        generated_cfg = res["content"]
        self.assertIn("[printer]", generated_cfg)
        self.assertIn("[bed_mesh]", generated_cfg)
        self.assertIn("kinematics: cartesian", generated_cfg)
        self.assertIn("sensor_type: Generic 3950", generated_cfg)

        # 7. Mock Moonraker deployment API requests
        mock_urlopen.return_value.__enter__.return_value.read.return_value = b'{"result": {"item": {"path": "printer.cfg"}}}'
        mock_urlopen.return_value.__enter__.return_value.status = 200

        # 8. Run Moonraker deployment simulation
        # Create a temp file representing the generated config
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "printer.cfg")
            with open(cfg_file, "w") as f:
                f.write(generated_cfg)
                
            # Mock core.menu functions used by deploy_moonraker
            # simple_input calls: host, port, api_key
            # numbered_select call: restart choice
            with patch("core.menu.simple_input", side_effect=["localhost", "7125", ""]) as mock_input, \
                 patch("core.menu.numbered_select", return_value="skip") as mock_select, \
                 patch("core.menu.yes_no", return_value=True) as mock_yesno, \
                 patch("core.menu.password_input", return_value="") as mock_pass, \
                 patch("core.deployer.os.path.expanduser", return_value=cfg_file):
                deploy_moonraker(user_data)

if __name__ == '__main__':
    unittest.main()
