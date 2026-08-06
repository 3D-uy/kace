"""Integration tests for bootstrap-managed Klipper and Moonraker defaults."""

from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = ROOT / "scripts" / "bootstrap.sh"
BEGIN = "# BEGIN KACE_CONFIG_DEFAULT_HELPER"
END = "# END KACE_CONFIG_DEFAULT_HELPER"


def _helper_source() -> str:
    script = BOOTSTRAP.read_text(encoding="utf-8")
    return script.split(BEGIN, 1)[1].split(END, 1)[0]


def _find_bash() -> str | None:
    if os.name == "nt":
        program_files = os.environ.get("ProgramFiles")
        if program_files:
            git_bash = Path(program_files) / "Git" / "bin" / "bash.exe"
            if git_bash.is_file():
                return str(git_bash)
    return shutil.which("bash")


@unittest.skipUnless(_find_bash(), "bash is required")
class TestBootstrapConfigDefaults(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.bash = _find_bash()
        cls.shell_python = Path(sys.executable).as_posix()

    def _shell_environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment["KACE_TEST_PYTHON"] = self.shell_python
        return environment

    def _apply_defaults(self, printer_cfg: Path, moonraker_cfg: Path) -> None:
        runner = printer_cfg.parent / "apply-defaults.sh"
        runner.write_text(
            "#!/bin/bash\nset -e\n"
            + 'python3() { "$KACE_TEST_PYTHON" "$@"; }\n'
            + _helper_source()
            + "\nensure_config_entry \"$1\" exclude_object\n"
            + "ensure_config_entry \"$1\" force_move enable_force_move True\n"
            + "ensure_config_entry \"$2\" file_manager enable_object_processing True\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [self.bash, runner.as_posix(), printer_cfg.as_posix(), moonraker_cfg.as_posix()],
            capture_output=True,
            text=True,
            check=False,
            env=self._shell_environment(),
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def _run_bootstrap_library(self, command: str, *args: Path) -> subprocess.CompletedProcess:
        script = """
set -e
python3() { "$KACE_TEST_PYTHON" "$@"; }
export KACE_BOOTSTRAP_LIB_ONLY=1
source "$1"
shift
SUDO=""
""" + command
        return subprocess.run(
            [self.bash, "-c", script, "bootstrap-test", BOOTSTRAP.as_posix(), *(arg.as_posix() for arg in args)],
            capture_output=True,
            text=True,
            check=False,
            env=self._shell_environment(),
        )

    def test_defaults_are_added_once_and_repeated_runs_are_noops(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            printer_cfg = root / "printer.cfg"
            moonraker_cfg = root / "moonraker.conf"
            printer_cfg.write_text("[printer]\nkinematics: none\n", encoding="utf-8")
            moonraker_cfg.write_text("[server]\nport: 7125\n", encoding="utf-8")

            self._apply_defaults(printer_cfg, moonraker_cfg)
            first_printer = printer_cfg.read_bytes()
            first_moonraker = moonraker_cfg.read_bytes()
            self._apply_defaults(printer_cfg, moonraker_cfg)

            self.assertEqual(printer_cfg.read_bytes(), first_printer)
            self.assertEqual(moonraker_cfg.read_bytes(), first_moonraker)
            printer = first_printer.decode("utf-8")
            moonraker = first_moonraker.decode("utf-8")
            self.assertEqual(printer.count("[exclude_object]"), 1)
            self.assertEqual(printer.count("[force_move]"), 1)
            self.assertEqual(printer.count("enable_force_move: True"), 1)
            self.assertEqual(moonraker.count("[file_manager]"), 1)
            self.assertEqual(moonraker.count("enable_object_processing: True"), 1)

    def test_existing_user_values_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            printer_cfg = root / "printer.cfg"
            moonraker_cfg = root / "moonraker.conf"
            original_printer = (
                "[exclude_object]\ncustom_value: keep\n\n"
                "[force_move]\nenable_force_move: False\n"
            )
            original_moonraker = (
                "[file_manager]\nenable_object_processing = False\n"
            )
            printer_cfg.write_text(original_printer, encoding="utf-8")
            moonraker_cfg.write_text(original_moonraker, encoding="utf-8")

            self._apply_defaults(printer_cfg, moonraker_cfg)

            self.assertEqual(printer_cfg.read_text(encoding="utf-8"), original_printer)
            self.assertEqual(moonraker_cfg.read_text(encoding="utf-8"), original_moonraker)

    def test_missing_options_are_added_inside_existing_sections(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            printer_cfg = root / "printer.cfg"
            moonraker_cfg = root / "moonraker.conf"
            printer_cfg.write_text(
                "[exclude_object]\n\n[force_move]\ncustom_value: keep\n\n[printer]\nkinematics: none\n",
                encoding="utf-8",
            )
            moonraker_cfg.write_text(
                "[file_manager]\nqueue_gcode_uploads: True\n\n[server]\nport: 7125\n",
                encoding="utf-8",
            )

            self._apply_defaults(printer_cfg, moonraker_cfg)

            printer = printer_cfg.read_text(encoding="utf-8")
            moonraker = moonraker_cfg.read_text(encoding="utf-8")
            self.assertEqual(printer.count("[force_move]"), 1)
            self.assertEqual(printer.count("enable_force_move: True"), 1)
            self.assertIn("custom_value: keep", printer)
            self.assertEqual(moonraker.count("[file_manager]"), 1)
            self.assertEqual(moonraker.count("enable_object_processing: True"), 1)
            self.assertIn("queue_gcode_uploads: True", moonraker)

    def test_bootstrap_applies_all_three_defaults(self):
        script = BOOTSTRAP.read_text(encoding="utf-8")
        self.assertIn('"exclude_object"', script)
        self.assertIn('"force_move" "enable_force_move" "True"', script)
        self.assertIn('"file_manager" "enable_object_processing" "True"', script)

    def test_requested_relay_replaces_existing_values_and_verifies(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            moonraker_cfg = root / "moonraker.conf"
            moonraker_cfg.write_text(
                "[server]\nport: 7125\n\n"
                "[power printer]\n"
                "type: gpio\n"
                "pin: gpiochip0/gpio5\n"
                "restart_klipper_when_powered: false\n"
                "initial_state: off\n"
                "off_when_shutdown: true\n"
                "custom_option: preserved\n",
                encoding="utf-8",
            )
            command = """
POWER_RELAY=true
POWER_DEVICE=printer
POWER_GPIO=20
POWER_ACTIVE_LOW=true
POWER_RESTART_KLIPPER=true
POWER_INITIAL_STATE=on
POWER_OFF_WHEN_SHUTDOWN=false
validate_power_relay_settings
ensure_moonraker_config "$1" "$2"
verify_requested_power_relay "$1"
"""
            result = self._run_bootstrap_library(
                command, moonraker_cfg, root / "comms" / "klippy.sock"
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            content = moonraker_cfg.read_text(encoding="utf-8")
            self.assertEqual(content.count("[power printer]"), 1)
            self.assertIn("pin: !gpiochip0/gpio20", content)
            self.assertIn("restart_klipper_when_powered: true", content)
            self.assertIn("initial_state: on", content)
            self.assertIn("off_when_shutdown: false", content)
            self.assertIn("custom_option: preserved", content)
            self.assertNotIn("gpiochip0/gpio5", content)

    def test_invalid_requested_relay_fails_and_preserves_boot_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            boot_config = Path(tmpdir) / "kace-bootstrap.txt"
            boot_config.write_text("POWER_RELAY=true\nPOWER_DEVICE=printer\n", encoding="utf-8")
            command = """
POWER_RELAY=true
POWER_DEVICE=printer
POWER_GPIO=""
POWER_ACTIVE_LOW=true
POWER_RESTART_KLIPPER=true
POWER_INITIAL_STATE=on
POWER_OFF_WHEN_SHUTDOWN=false
if validate_power_relay_settings; then
    exit 9
fi
test -f "$1"
"""
            result = self._run_bootstrap_library(command, boot_config)
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertTrue(boot_config.exists())

    def test_failed_final_verification_preserves_boot_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            moonraker_cfg = root / "moonraker.conf"
            boot_config = root / "kace-bootstrap.txt"
            moonraker_cfg.write_text(
                "[server]\nport: 7125\n\n[power printer]\ntype: gpio\npin: gpiochip0/gpio5\n",
                encoding="utf-8",
            )
            boot_config.write_text("POWER_RELAY=true\n", encoding="utf-8")
            command = """
POWER_RELAY=true
POWER_DEVICE=printer
POWER_GPIO=20
POWER_ACTIVE_LOW=true
POWER_RESTART_KLIPPER=true
POWER_INITIAL_STATE=on
POWER_OFF_WHEN_SHUTDOWN=false
if finalize_bootstrap_success "$1" "$2"; then
    exit 9
fi
test -f "$2"
"""
            result = self._run_bootstrap_library(command, moonraker_cfg, boot_config)
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertTrue(boot_config.exists())

    def test_boot_config_is_removed_only_after_successful_final_verification(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            moonraker_cfg = root / "moonraker.conf"
            boot_config = root / "kace-bootstrap.txt"
            moonraker_cfg.write_text("[server]\nport: 7125\n", encoding="utf-8")
            boot_config.write_text("POWER_RELAY=true\n", encoding="utf-8")
            command = """
POWER_RELAY=true
POWER_DEVICE=printer
POWER_GPIO=20
POWER_ACTIVE_LOW=true
POWER_RESTART_KLIPPER=true
POWER_INITIAL_STATE=on
POWER_OFF_WHEN_SHUTDOWN=false
validate_power_relay_settings
ensure_moonraker_config "$1" "$3"
finalize_bootstrap_success "$1" "$2"
test ! -e "$2"
"""
            result = self._run_bootstrap_library(
                command, moonraker_cfg, boot_config, root / "comms" / "klippy.sock"
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertFalse(boot_config.exists())
            self.assertIn(
                "Bootstrap complete! KACE wizard finished successfully.",
                result.stdout,
            )

    def test_existing_power_section_is_untouched_when_relay_not_requested(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            moonraker_cfg = root / "moonraker.conf"
            existing_power = (
                "[power printer]\n"
                "type: gpio\n"
                "pin: gpiochip0/gpio7\n"
                "initial_state: off\n"
            )
            moonraker_cfg.write_text(
                "[server]\nport: 7125\n\n" + existing_power,
                encoding="utf-8",
            )
            command = """
POWER_RELAY=false
POWER_DEVICE=""
POWER_GPIO=""
POWER_ACTIVE_LOW=""
POWER_RESTART_KLIPPER=""
POWER_INITIAL_STATE=""
POWER_OFF_WHEN_SHUTDOWN=""
validate_power_relay_settings
ensure_moonraker_config "$1" "$2"
"""
            result = self._run_bootstrap_library(
                command, moonraker_cfg, root / "comms" / "klippy.sock"
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            content = moonraker_cfg.read_text(encoding="utf-8")
            self.assertIn(existing_power, content)


if __name__ == "__main__":
    unittest.main()
