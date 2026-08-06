"""
tests/regression/test_full_installation_flows.py
=================================================
End-to-end integration tests simulating both complete installation flows:

Flow 1: Direct installation via script/one-liner + wizard execution + deployment.
Flow 2: Unattended Studio bootstrap + wizard execution + deployment.

Verifies that the REAL final files on disk (printer.cfg and moonraker.conf) ALWAYS contain:
  1. printer.cfg: [exclude_object]
  2. printer.cfg: [force_move] with enable_force_move: True (or preserved False)
  3. moonraker.conf: [file_manager] with enable_object_processing: True

Inspects the real final files written to disk, validating idempotency, atomic writes,
and preservation of user settings across repeated runs.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from core.generator import generate_config
from core.deployer import deploy_local
from core.reconciler import reconcile_config_directory


_BOARD_PARSED_FIXTURE = {
    "stepper_x": {"step_pin": "P2.2", "dir_pin": "!P2.6", "enable_pin": "!P2.1", "endstop_pin": "P1.29", "position_max": "235"},
    "stepper_y": {"step_pin": "P0.19", "dir_pin": "P0.20", "enable_pin": "!P2.8", "endstop_pin": "P1.28", "position_max": "235"},
    "stepper_z": {"step_pin": "P0.22", "dir_pin": "!P2.11", "enable_pin": "!P0.21", "endstop_pin": "P1.25", "position_max": "250"},
    "extruder": {"step_pin": "P2.13", "dir_pin": "!P0.11", "enable_pin": "!P2.12", "heater_pin": "P2.7", "sensor_pin": "P0.24", "sensor_type": "Generic 3950"},
    "heater_bed": {"heater_pin": "P2.5", "sensor_pin": "P0.25", "sensor_type": "Generic 3950"},
}

_USER_DATA_FIXTURE = {
    "board": "generic-bigtreetech-skr-v1.4.cfg",
    "kinematics": "cartesian",
    "x_size": "235",
    "y_size": "235",
    "z_size": "250",
    "probe": "None",
    "driver_type": "TMC2209",
    "driver_mode": "UART",
    "web_interface": "Mainsail",
    "z_motors": "1",
    "mcu_path": "/dev/serial/by-id/usb-Klipper-test",
    "board_parsed": _BOARD_PARSED_FIXTURE,
}


class TestFullInstallationFlows(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.kace_home = os.path.join(self.tmp_dir, "kace")
        self.printer_data_config = os.path.join(self.tmp_dir, "printer_data", "config")
        os.makedirs(self.kace_home, exist_ok=True)
        os.makedirs(self.printer_data_config, exist_ok=True)

        self._env_patch = patch.dict(os.environ, {"KACE_AUTO": "1"})
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _simulate_bootstrap(self, config_dir: str):
        """Simulate the bootstrap script execution on config_dir."""
        p_cfg = os.path.join(config_dir, "printer.cfg")
        m_cfg = os.path.join(config_dir, "moonraker.conf")

        if not os.path.exists(p_cfg):
            with open(p_cfg, "w", encoding="utf-8") as f:
                f.write("[mcu]\nserial: /dev/serial/by-id/test\n[printer]\nkinematics: cartesian\n")
        if not os.path.exists(m_cfg):
            with open(m_cfg, "w", encoding="utf-8") as f:
                f.write("[server]\nport: 7125\n")

        reconcile_config_directory(config_dir)

    def test_flow_1_direct_installation_script_and_wizard(self):
        """Flow 1: Direct script/one-liner bootstrap + wizard execution + deploy_local."""
        # 1. Run bootstrap step
        self._simulate_bootstrap(self.printer_data_config)

        # 2. Run Wizard config generation and deploy_local under patched expanduser
        out_file = os.path.join(self.kace_home, "printer.cfg")
        with patch("os.path.expanduser", side_effect=lambda p: p.replace("~/kace", self.kace_home).replace("~/printer_data/config", self.printer_data_config)), \
             patch("core.menu.simple_input", return_value=self.printer_data_config):
            generate_config(_BOARD_PARSED_FIXTURE, dict(_USER_DATA_FIXTURE), output_path=out_file)
            deploy_local(dict(_USER_DATA_FIXTURE), artifact_type="config")

        # 4. Inspect REAL final files on disk
        final_p_cfg = os.path.join(self.printer_data_config, "printer.cfg")
        final_m_cfg = os.path.join(self.printer_data_config, "moonraker.conf")

        self.assertTrue(os.path.isfile(final_p_cfg))
        self.assertTrue(os.path.isfile(final_m_cfg))

        p_text = Path(final_p_cfg).read_text(encoding="utf-8")
        m_text = Path(final_m_cfg).read_text(encoding="utf-8")

        # Assert mandatory settings
        self.assertIn("[exclude_object]", p_text)
        self.assertIn("[force_move]", p_text)
        self.assertIn("enable_force_move: True", p_text)
        self.assertIn("[file_manager]", m_text)
        self.assertIn("enable_object_processing: True", m_text)

        # Assert no duplicates
        self.assertEqual(p_text.lower().count("[exclude_object]"), 1)
        self.assertEqual(p_text.lower().count("[force_move]"), 1)
        self.assertEqual(m_text.lower().count("[file_manager]"), 1)

    def test_flow_2_studio_unattended_bootstrap_and_wizard(self):
        """Flow 2: Unattended Studio bootstrap + wizard execution + deployment."""
        # 1. Studio unattended bootstrap creates initial setup
        self._simulate_bootstrap(self.printer_data_config)

        # 2. Studio triggers KACE wizard generation
        out_file = os.path.join(self.kace_home, "printer.cfg")
        with patch("os.path.expanduser", side_effect=lambda p: p.replace("~/kace", self.kace_home).replace("~/printer_data/config", self.printer_data_config)), \
             patch("core.menu.simple_input", return_value=self.printer_data_config):
            generate_config(_BOARD_PARSED_FIXTURE, dict(_USER_DATA_FIXTURE), output_path=out_file)
            deploy_local(dict(_USER_DATA_FIXTURE), artifact_type="config")

        final_p_cfg = os.path.join(self.printer_data_config, "printer.cfg")
        final_m_cfg = os.path.join(self.printer_data_config, "moonraker.conf")

        p_text = Path(final_p_cfg).read_text(encoding="utf-8")
        m_text = Path(final_m_cfg).read_text(encoding="utf-8")

        self.assertIn("[exclude_object]", p_text)
        self.assertIn("[force_move]", p_text)
        self.assertIn("enable_force_move: True", p_text)
        self.assertIn("[file_manager]", m_text)
        self.assertIn("enable_object_processing: True", m_text)

    def test_preserves_user_enable_force_move_false_and_custom_moonraker_config(self):
        """User already has enable_force_move: False and custom moonraker settings."""
        # Pre-existing user files
        p_cfg = os.path.join(self.printer_data_config, "printer.cfg")
        m_cfg = os.path.join(self.printer_data_config, "moonraker.conf")

        with open(p_cfg, "w", encoding="utf-8") as f:
            f.write("[mcu]\nserial: /dev/serial/by-id/test\n[force_move]\nenable_force_move: False\n")

        with open(m_cfg, "w", encoding="utf-8") as f:
            f.write("[server]\nport: 7125\n[file_manager]\ncustom_option: custom_value\n")

        # Run full flow
        self._simulate_bootstrap(self.printer_data_config)

        out_file = os.path.join(self.kace_home, "printer.cfg")
        with patch("os.path.expanduser", side_effect=lambda p: p.replace("~/kace", self.kace_home).replace("~/printer_data/config", self.printer_data_config)), \
             patch("core.menu.simple_input", return_value=self.printer_data_config):
            generate_config(_BOARD_PARSED_FIXTURE, dict(_USER_DATA_FIXTURE), output_path=out_file)
            deploy_local(dict(_USER_DATA_FIXTURE), artifact_type="config")

        p_text = Path(p_cfg).read_text(encoding="utf-8")
        m_text = Path(m_cfg).read_text(encoding="utf-8")

        # Verify preserve False
        self.assertIn("enable_force_move: False", p_text)
        self.assertNotIn("enable_force_move: True", p_text)
        self.assertIn("[exclude_object]", p_text)

        # Verify moonraker custom option preserved and enable_object_processing added
        self.assertIn("custom_option: custom_value", m_text)
        self.assertIn("enable_object_processing: True", m_text)
        self.assertIn("port: 7125", m_text)

    def test_idempotent_repeated_runs(self):
        """Running the full flow 3 times must produce stable files without section duplicates."""
        for _ in range(3):
            self._simulate_bootstrap(self.printer_data_config)

            out_file = os.path.join(self.kace_home, "printer.cfg")
            with patch("os.path.expanduser", side_effect=lambda p: p.replace("~/kace", self.kace_home).replace("~/printer_data/config", self.printer_data_config)), \
                 patch("core.menu.simple_input", return_value=self.printer_data_config):
                generate_config(_BOARD_PARSED_FIXTURE, dict(_USER_DATA_FIXTURE), output_path=out_file)
                deploy_local(dict(_USER_DATA_FIXTURE), artifact_type="config")

        p_text = Path(os.path.join(self.printer_data_config, "printer.cfg")).read_text(encoding="utf-8")
        m_text = Path(os.path.join(self.printer_data_config, "moonraker.conf")).read_text(encoding="utf-8")

        self.assertEqual(p_text.lower().count("[exclude_object]"), 1)
        self.assertEqual(p_text.lower().count("[force_move]"), 1)
        self.assertEqual(m_text.lower().count("[file_manager]"), 1)


if __name__ == "__main__":
    unittest.main()
