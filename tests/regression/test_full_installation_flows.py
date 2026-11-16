"""Filesystem-level bootstrap -> generation -> managed deployment regressions."""

import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.deployer import _copy_artifacts
from core.generator import generate_config
from core.managed_config import HARDWARE_REMOTE, MANAGED_BEGIN
from core.reconciler import reconcile_config_directory
from core.snapshot import create_snapshot


PARSED = {
    "stepper_x": {"step_pin": "P2.2", "dir_pin": "!P2.6", "enable_pin": "!P2.1", "endstop_pin": "P1.29", "position_max": "235"},
    "stepper_y": {"step_pin": "P0.19", "dir_pin": "P0.20", "enable_pin": "!P2.8", "endstop_pin": "P1.28", "position_max": "235"},
    "stepper_z": {"step_pin": "P0.22", "dir_pin": "!P2.11", "enable_pin": "!P0.21", "endstop_pin": "P1.25", "position_max": "250"},
    "extruder": {"step_pin": "P2.13", "dir_pin": "!P0.11", "enable_pin": "!P2.12", "heater_pin": "P2.7", "sensor_pin": "P0.24", "sensor_type": "Generic 3950"},
    "heater_bed": {"heater_pin": "P2.5", "sensor_pin": "P0.25", "sensor_type": "Generic 3950"},
}
USER = {
    "board": "generic-bigtreetech-skr-v1.4.cfg",
    "kinematics": "cartesian",
    "x_size": "235", "y_size": "235", "z_size": "250",
    "probe": "None", "driver_type": "TMC2209", "driver_mode": "UART",
    "web_interface": "Mainsail", "z_motors": "1",
    "mcu_path": "/dev/serial/by-id/usb-Klipper-test",
    "board_parsed": PARSED,
}


class TestFullInstallationFlows(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.kace_home = os.path.join(self.temp.name, "kace")
        self.config = os.path.join(self.temp.name, "printer_data", "config")
        os.makedirs(self.kace_home)
        os.makedirs(self.config)
        # Existing UI/user include dependencies are part of the reviewed input.
        Path(self.config, "mainsail.cfg").write_bytes(b"# simulated UI include\n")
        Path(self.config, "user.cfg").write_bytes(b"# simulated user include\n")

    def tearDown(self):
        self.temp.cleanup()

    def _expand(self, value):
        return value.replace("~/kace", self.kace_home).replace(
            "~/printer_data/config", self.config
        )

    def _bootstrap(self):
        printer = Path(self.config, "printer.cfg")
        moonraker = Path(self.config, "moonraker.conf")
        if not printer.exists():
            printer.write_text(
                "[include user.cfg]\n[gcode_macro USER]\ngcode: M117 keep\n",
                encoding="utf-8",
            )
        if not moonraker.exists():
            moonraker.write_text("[server]\nport: 7125\n", encoding="utf-8")
        reconcile_config_directory(self.config)

    def _generate_and_manually_apply_proposal(self):
        output = os.path.join(self.kace_home, "printer.cfg")
        with (
            patch("os.path.expanduser", side_effect=self._expand),
            patch("core.menu.yes_no", return_value=True),
        ):
            generate_config(PARSED, dict(USER), output_path=output)
            before = {p.relative_to(self.config): p.read_bytes() for p in Path(self.config).rglob("*") if p.is_file()}
            proposals = set(Path(self.kace_home, "snapshots").glob("*-proposed"))
            if _copy_artifacts(dict(USER), self.config, "config"):
                return True
            after = {p.relative_to(self.config): p.read_bytes() for p in Path(self.config).rglob("*") if p.is_file()}
            self.assertEqual(before, after)  # Unsupported replacement wrote nothing.
            new = set(Path(self.kace_home, "snapshots").glob("*-proposed")) - proposals
            self.assertEqual(len(new), 1)
            proposal = new.pop()
            metadata = json.loads((proposal / "snapshot.json").read_text(encoding="utf-8"))
            # Explicit operator application, in a fixture with no other writer.
            self.manual_backup = create_snapshot(
                {name: before.get(Path(name)) for name in metadata["files"]},
                persist_root=str(Path(self.kace_home, "manual-recovery")),
            )
            for name in metadata["files"]:
                target = Path(self.config, name)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((proposal / name.replace("/", "__")).read_bytes())
            return _copy_artifacts(dict(USER), self.config, "config")

    def _read_outputs(self):
        return {
            "root": Path(self.config, "printer.cfg").read_text(encoding="utf-8"),
            "moonraker": Path(self.config, "moonraker.conf").read_text(encoding="utf-8"),
        }

    def test_bootstrap_generation_and_fresh_deployment_replace_root_without_deleting_other_files(self):
        self._bootstrap()
        old_root = Path(self.config, "printer.cfg").read_bytes()
        self.assertTrue(self._generate_and_manually_apply_proposal())
        output = self._read_outputs()

        self.assertIn(MANAGED_BEGIN, output["root"])
        self.assertNotIn("[include user.cfg]", output["root"])
        self.assertNotIn("[gcode_macro USER]", output["root"])
        self.assertIn("[mcu]", output["root"])
        self.assertIn("[exclude_object]", output["root"])
        self.assertFalse(Path(self.config, HARDWARE_REMOTE).exists())
        self.assertEqual(Path(self.config, "user.cfg").read_bytes(), b"# simulated user include\n")
        self.assertEqual(self.manual_backup.config_files["printer.cfg"], old_root)
        self.assertIn("enable_object_processing: True", output["moonraker"])

    def test_fresh_configuration_retires_old_tuning_but_preserves_moonraker_options(self):
        Path(self.config, "printer.cfg").write_text(
            "[force_move]\nenable_force_move: False\n"
            "[extruder]\ncontrol: pid\npid_Kp: 31.5\npid_Ki: 2.2\npid_Kd: 140\n"
            "[gcode_macro USER]\ngcode: M117 keep\n",
            encoding="utf-8",
        )
        Path(self.config, "moonraker.conf").write_text(
            "[server]\nport: 7125\n[file_manager]\ncustom_option: custom_value\n",
            encoding="utf-8",
        )
        self._bootstrap()
        old_root = Path(self.config, "printer.cfg").read_bytes()
        self.assertTrue(self._generate_and_manually_apply_proposal())
        output = self._read_outputs()

        self.assertNotIn("pid_Kp: 31.5", output["root"])
        self.assertNotIn("[gcode_macro USER]", output["root"])
        self.assertEqual(self.manual_backup.config_files["printer.cfg"], old_root)
        self.assertIn("custom_option: custom_value", output["moonraker"])
        self.assertEqual(output["moonraker"].count("[file_manager]"), 1)

    def test_three_runs_are_byte_idempotent(self):
        self._bootstrap()
        self.assertTrue(self._generate_and_manually_apply_proposal())
        first = self._read_outputs()
        for _ in range(2):
            self._bootstrap()
            self.assertTrue(self._generate_and_manually_apply_proposal())
        self.assertEqual(self._read_outputs(), first)
        self.assertEqual(first["root"].count(MANAGED_BEGIN), 1)


if __name__ == "__main__":
    unittest.main()
