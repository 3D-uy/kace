"""Integration tests for bootstrap-managed Klipper and Moonraker defaults."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = ROOT / "scripts" / "bootstrap.sh"
BEGIN = "# BEGIN KACE_CONFIG_DEFAULT_HELPER"
END = "# END KACE_CONFIG_DEFAULT_HELPER"


def _helper_source() -> str:
    script = BOOTSTRAP.read_text(encoding="utf-8")
    return script.split(BEGIN, 1)[1].split(END, 1)[0]


def _bash_with_python3() -> str | None:
    bash = shutil.which("bash")
    if not bash:
        return None
    result = subprocess.run(
        [bash, "-lc", "command -v python3"],
        capture_output=True,
        text=True,
        check=False,
    )
    return bash if result.returncode == 0 else None


@unittest.skipUnless(_bash_with_python3(), "bash and python3 are required")
class TestBootstrapConfigDefaults(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.bash = _bash_with_python3()

    def _apply_defaults(self, printer_cfg: Path, moonraker_cfg: Path) -> None:
        runner = printer_cfg.parent / "apply-defaults.sh"
        runner.write_text(
            "#!/bin/bash\nset -e\n"
            + _helper_source()
            + "\nensure_config_entry \"$1\" exclude_object\n"
            + "ensure_config_entry \"$1\" force_move enable_force_move True\n"
            + "ensure_config_entry \"$2\" file_manager enable_object_processing True\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [self.bash, str(runner), str(printer_cfg), str(moonraker_cfg)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

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


if __name__ == "__main__":
    unittest.main()
