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
            moonraker_cfg.write_text(
                "[server]\nport: 7125\n\n[authorization]\ntrusted_clients:\n    127.0.0.1\n"
                "\n[file_manager]\ncustom_option: preserved\n",
                encoding="utf-8",
            )

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

    def test_bootstrap_only_reconciles_the_moonraker_default(self):
        script = BOOTSTRAP.read_text(encoding="utf-8")
        config_block = script.split('# ── 5. Printer Data Directories & Config Files', 1)[1].split(
            '# ── 6. Dashboard UI', 1
        )[0]
        self.assertNotIn('"exclude_object"', config_block)
        self.assertNotIn('"force_move" "enable_force_move" "True"', config_block)
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
            power_json = root / "power.json"
            power_json.write_text(
                '{"schema":1,"enabled":true,"device":"printer"}\n',
                encoding="utf-8",
            )
            command = """
POWER_CONFIG_PATH="$3"
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
                command, moonraker_cfg, root / "comms" / "klippy.sock", power_json
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
            self.assertIn("# BEGIN KACE MANAGED: power", content)
            self.assertIn("# END KACE MANAGED: power", content)

    def test_power_reconciliation_is_idempotent_before_state_is_persisted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_dir = root / "printer_data" / "config"
            config_dir.mkdir(parents=True)
            moonraker_cfg = config_dir / "moonraker.conf"
            moonraker_cfg.write_text(
                "[server]\nport: 7125\n\n[authorization]\ntrusted_clients:\n    127.0.0.1\n"
                "\n[file_manager]\ncustom_option: preserved\n",
                encoding="utf-8",
            )
            command = """
PRINTER_HOME="$3"
POWER_RELAY=true
POWER_DEVICE=printer
POWER_GPIO=20
POWER_ACTIVE_LOW=true
POWER_RESTART_KLIPPER=true
POWER_INITIAL_STATE=on
POWER_OFF_WHEN_SHUTDOWN=false
ensure_moonraker_config "$1" "$2"
"""
            first = self._run_bootstrap_library(
                command, moonraker_cfg, root / "comms" / "klippy.sock", root
            )
            self.assertEqual(first.returncode, 0, first.stderr or first.stdout)
            result = self._run_bootstrap_library(
                command, moonraker_cfg, root / "comms" / "klippy.sock", root
            )
            self.assertEqual(
                result.returncode,
                0,
                (result.stderr or result.stdout) + "\n" + moonraker_cfg.read_text(encoding="utf-8"),
            )
            self.assertEqual(
                moonraker_cfg.read_text(encoding="utf-8").count("[power printer]"),
                1,
            )

    def test_power_rename_and_disable_remove_only_previous_managed_device(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            moonraker_cfg = root / "moonraker.conf"
            power_json = root / "power.json"
            moonraker_cfg.write_text(
                "[server]\nport: 7125\n\n"
                "[power printer]\ntype: gpio\npin: gpiochip0/gpio5\n\n"
                "[power lights]\ntype: gpio\npin: gpiochip0/gpio6\n",
                encoding="utf-8",
            )
            power_json.write_text(
                '{"schema":1,"enabled":true,"device":"printer"}\n',
                encoding="utf-8",
            )
            rename = """
POWER_CONFIG_PATH="$3"
POWER_RELAY=true
POWER_DEVICE=main_psu
POWER_GPIO=20
POWER_ACTIVE_LOW=false
POWER_RESTART_KLIPPER=true
POWER_INITIAL_STATE=on
POWER_OFF_WHEN_SHUTDOWN=false
validate_power_relay_settings
ensure_moonraker_config "$1" "$2"
"""
            result = self._run_bootstrap_library(
                rename, moonraker_cfg, root / "comms" / "klippy.sock", power_json
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            renamed = moonraker_cfg.read_text(encoding="utf-8")
            self.assertNotIn("[power printer]", renamed)
            self.assertIn("[power main_psu]", renamed)
            self.assertIn("[power lights]", renamed)

            power_json.write_text(
                '{"schema":"kace-power/v1","revision":2,"enabled":true,'
                '"device":"main_psu","pin":"gpiochip0/gpio20","active_low":false,'
                '"initial_state":"on","restart_klipper_when_powered":true,'
                '"off_when_shutdown":false}\n',
                encoding="utf-8",
            )
            disable = """
POWER_CONFIG_PATH="$3"
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
                disable, moonraker_cfg, root / "comms" / "klippy.sock", power_json
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            disabled = moonraker_cfg.read_text(encoding="utf-8")
            self.assertNotIn("[power main_psu]", disabled)
            self.assertNotIn("KACE MANAGED: power", disabled)
            self.assertIn("[power lights]", disabled)

    def test_isolated_end_marker_does_not_claim_user_power_section(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            moonraker_cfg = root / "moonraker.conf"
            moonraker_cfg.write_text(
                "[server]\nport: 7125\n\n"
                "[power lights]\ntype: gpio\npin: gpiochip0/gpio6\n"
                "# END KACE MANAGED: power\n",
                encoding="utf-8",
            )
            command = """
POWER_CONFIG_PATH="$3"
POWER_RELAY=true
POWER_DEVICE=main_psu
POWER_GPIO=20
POWER_ACTIVE_LOW=false
POWER_RESTART_KLIPPER=true
POWER_INITIAL_STATE=on
POWER_OFF_WHEN_SHUTDOWN=false
validate_power_relay_settings
ensure_moonraker_config "$1" "$2"
"""
            result = self._run_bootstrap_library(
                command, moonraker_cfg, root / "comms" / "klippy.sock", root / "power.json"
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            content = moonraker_cfg.read_text(encoding="utf-8")
            self.assertIn("[power lights]", content)
            self.assertIn("pin: gpiochip0/gpio6", content)
            self.assertIn("[power main_psu]", content)

    def test_stray_begin_marker_does_not_jump_to_later_user_power_section(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            moonraker_cfg = root / "moonraker.conf"
            moonraker_cfg.write_text(
                "# BEGIN KACE MANAGED: power\n"
                "[server]\nport: 7125\n\n"
                "[power lights]\ntype: gpio\npin: gpiochip0/gpio6\n",
                encoding="utf-8",
            )
            command = """
POWER_CONFIG_PATH="$3"
POWER_RELAY=true
POWER_DEVICE=main_psu
POWER_GPIO=20
POWER_ACTIVE_LOW=false
POWER_RESTART_KLIPPER=true
POWER_INITIAL_STATE=on
POWER_OFF_WHEN_SHUTDOWN=false
validate_power_relay_settings
ensure_moonraker_config "$1" "$2"
"""
            result = self._run_bootstrap_library(
                command, moonraker_cfg, root / "comms" / "klippy.sock", root / "power.json"
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            content = moonraker_cfg.read_text(encoding="utf-8")
            self.assertIn("[power lights]", content)
            self.assertIn("pin: gpiochip0/gpio6", content)
            self.assertIn("[power main_psu]", content)

    def test_malformed_power_state_cannot_claim_an_unmanaged_section(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            moonraker_cfg = root / "moonraker.conf"
            power_json = root / "power.json"
            original = "[power lights]\ntype: gpio\npin: gpiochip0/gpio6\n"
            moonraker_cfg.write_text(original, encoding="utf-8")
            power_json.write_text(
                '{"schema":"unknown","enabled":true,"device":"lights"}\n',
                encoding="utf-8",
            )
            command = """
POWER_CONFIG_PATH="$3"
POWER_RELAY=true
POWER_DEVICE=main_psu
POWER_GPIO=20
POWER_ACTIVE_LOW=false
POWER_RESTART_KLIPPER=true
POWER_INITIAL_STATE=on
POWER_OFF_WHEN_SHUTDOWN=false
validate_power_relay_settings
begin_power_reconciliation "$1" "$3"
if ensure_moonraker_config "$1" "$2"; then
    exit 9
fi
rollback_power_reconciliation
"""
            result = self._run_bootstrap_library(
                command, moonraker_cfg, root / "comms" / "klippy.sock", power_json
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertEqual(moonraker_cfg.read_text(encoding="utf-8"), original)

    def test_power_json_persistence_occurs_only_after_api_verification(self):
        script = BOOTSTRAP.read_text(encoding="utf-8")
        early_config = script.index(
            "ensure_moonraker_config \\",
            script.index('mkdir -p "$PRINTER_HOME/printer_data/config"'),
        )
        api_verify = script.index('verify_power_api_configuration "http://127.0.0.1:7125"')
        persist = script.index("persist_power_controller_config", api_verify)
        self.assertLess(early_config, api_verify)
        self.assertLess(api_verify, persist)

    def test_failed_power_reconciliation_restores_exact_moonraker_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            moonraker_cfg = root / "moonraker.conf"
            original = b"[server]\r\nport: 7125\r\n\r\n[power lights]\r\ntype: gpio\r\npin: gpiochip0/gpio6\r\n"
            moonraker_cfg.write_bytes(original)
            command = """
POWER_RELAY=true
POWER_DEVICE=main_psu
POWER_GPIO=20
POWER_ACTIVE_LOW=false
POWER_RESTART_KLIPPER=true
POWER_INITIAL_STATE=on
POWER_OFF_WHEN_SHUTDOWN=false
validate_power_relay_settings
begin_power_reconciliation "$1"
ensure_moonraker_config "$1" "$2"
rollback_power_reconciliation
"""
            result = self._run_bootstrap_library(
                command, moonraker_cfg, root / "comms" / "klippy.sock"
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertEqual(moonraker_cfg.read_bytes(), original)

    def test_failed_power_persistence_restores_exact_config_and_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            home = root / "home"
            state_dir = home / ".config" / "kace"
            state_dir.mkdir(parents=True)
            moonraker_cfg = root / "moonraker.conf"
            power_json = state_dir / "power.json"
            original_config = b"[server]\r\nport: 7125\r\n"
            original_state = b'{"schema":1,"enabled":false}\r\n'
            moonraker_cfg.write_bytes(original_config)
            power_json.write_bytes(original_state)
            command = """
PRINTER_HOME="$2"
PRINTER_USER="$(id -un)"
PRINTER_GROUP="$PRINTER_USER"
chown() { return 0; }
POWER_RELAY=true
POWER_DEVICE=main_psu
POWER_GPIO=20
POWER_ACTIVE_LOW=false
POWER_RESTART_KLIPPER=true
POWER_INITIAL_STATE=on
POWER_OFF_WHEN_SHUTDOWN=false
validate_power_relay_settings
begin_power_reconciliation "$1"
ensure_moonraker_config "$1" "$2/printer_data/comms/klippy.sock"
persist_power_controller_config
rollback_power_reconciliation
"""
            result = self._run_bootstrap_library(command, moonraker_cfg, home)
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertEqual(moonraker_cfg.read_bytes(), original_config)
            self.assertEqual(power_json.read_bytes(), original_state)

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

    def test_power_relay_gate_orders_api_device_on_and_mcu_before_kace(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmpdir:
            root = Path(tmpdir)
            device_root = root / "dev"
            device_root.mkdir()
            command = r'''
POWER_RELAY=true
POWER_DEVICE=main_psu
KACE_MCU_DEVICE_ROOT="$1/dev"
KACE_POWER_API_TIMEOUT=3
KACE_POWER_DEVICE_TIMEOUT=3
KACE_POWER_ON_TIMEOUT=3
KACE_POWER_MCU_TIMEOUT=3
TEST_STATE_DIR="$1/state"
mkdir -p "$TEST_STATE_DIR"

sleep() {
    SECONDS=$((SECONDS + ${1:-1}))
}

curl() {
    local argument=""
    local url=""
    local payload=""
    local capture_payload=false
    for argument in "$@"; do
        if [ "$capture_payload" = true ]; then
            payload="$argument"
            capture_payload=false
        elif [ "$argument" = "--data" ]; then
            capture_payload=true
        fi
        url="$argument"
    done

    case "$url" in
        */server/info)
            printf '%s\n' '{"result":{"moonraker_version":"test"}}'
            ;;
        */machine/device_power/devices)
            local call_count=0
            if [ -f "$TEST_STATE_DIR/device_calls" ]; then
                call_count=$(cat "$TEST_STATE_DIR/device_calls")
            fi
            call_count=$((call_count + 1))
            printf '%s\n' "$call_count" > "$TEST_STATE_DIR/device_calls"
            if [ -f "$TEST_STATE_DIR/powered" ]; then
                printf '%s\n' '{"result":{"devices":[{"device":"main_psu","status":"on","type":"gpio"}]}}'
            elif [ "$call_count" -eq 1 ]; then
                printf '%s\n' '{"result":{"devices":[{"device":"main_psu","status":"init","type":"gpio"}]}}'
            else
                printf '%s\n' '{"result":{"devices":[{"device":"main_psu","status":"off","type":"gpio"}]}}'
            fi
            ;;
        */machine/device_power/device)
            printf '%s\n' "$payload" > "$TEST_STATE_DIR/request.json"
            touch "$TEST_STATE_DIR/powered"
            mkdir -p "$KACE_MCU_DEVICE_ROOT/serial/by-id"
            touch "$KACE_MCU_DEVICE_ROOT/serial/by-id/usb-Klipper_test-if00"
            printf '%s\n' '{"result":{"main_psu":"on"}}'
            ;;
        *)
            return 22
            ;;
    esac
}

prepare_power_relay_for_kace
'''
            result = self._run_bootstrap_library(command, root)
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

            output = result.stdout
            api_ready = output.index("Moonraker API is ready.")
            device_ready = output.index("power device 'main_psu' is ready")
            on_accepted = output.index("explicit ON command for 'main_psu'")
            on_confirmed = output.index("power device 'main_psu' is confirmed ON")
            mcu_detected = output.index("MCU detected after printer power-on")
            self.assertLess(api_ready, device_ready)
            self.assertLess(device_ready, on_accepted)
            self.assertLess(on_accepted, on_confirmed)
            self.assertLess(on_confirmed, mcu_detected)
            self.assertEqual(
                (root / "state" / "request.json").read_text(encoding="utf-8").strip(),
                '{"device":"main_psu","action":"on"}',
            )

            script = BOOTSTRAP.read_text(encoding="utf-8")
            config_call = script.index(
                '    "$PRINTER_HOME/printer_data/config/moonraker.conf"'
            )
            restart_call = script.index("systemctl restart moonraker", config_call)
            power_gate_call = script.index("if ! prepare_power_relay_for_kace; then")
            kace_stage = script.index('log_stage "KACE" "Installing KACE Agent"')
            self.assertLess(config_call, restart_call)
            self.assertLess(restart_call, power_gate_call)
            self.assertLess(power_gate_call, kace_stage)

    def test_power_relay_gate_fails_when_configured_device_is_missing(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmpdir:
            root = Path(tmpdir)
            command = r'''
POWER_RELAY=true
POWER_DEVICE=main_psu
KACE_POWER_API_TIMEOUT=2
KACE_POWER_DEVICE_TIMEOUT=2
TEST_STATE_DIR="$1/state"
mkdir -p "$TEST_STATE_DIR"
curl() {
    local url="${!#}"
    case "$url" in
        */server/info) printf '%s\n' '{"result":{"moonraker_version":"test"}}' ;;
        */machine/device_power/devices) printf '%s\n' '{"result":{"devices":[]}}' ;;
        */machine/device_power/device) touch "$TEST_STATE_DIR/post-called" ; return 22 ;;
        *) return 22 ;;
    esac
}
if prepare_power_relay_for_kace; then
    exit 9
fi
test ! -e "$TEST_STATE_DIR/post-called"
'''
            result = self._run_bootstrap_library(command, root)
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertIn("power device 'main_psu' was not found", result.stderr)

    def test_power_relay_gate_fails_immediately_on_device_error(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmpdir:
            root = Path(tmpdir)
            command = r'''
POWER_RELAY=true
POWER_DEVICE=main_psu
KACE_POWER_API_TIMEOUT=2
KACE_POWER_DEVICE_TIMEOUT=2
TEST_STATE_DIR="$1/state"
mkdir -p "$TEST_STATE_DIR"
curl() {
    local url="${!#}"
    case "$url" in
        */server/info) printf '%s\n' '{"result":{"moonraker_version":"test"}}' ;;
        */machine/device_power/devices)
            printf '%s\n' '{"result":{"devices":[{"device":"main_psu","status":"error","type":"gpio"}]}}'
            ;;
        */machine/device_power/device) touch "$TEST_STATE_DIR/post-called" ; return 22 ;;
        *) return 22 ;;
    esac
}
if prepare_power_relay_for_kace; then
    exit 9
fi
test ! -e "$TEST_STATE_DIR/post-called"
'''
            result = self._run_bootstrap_library(command, root)
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertIn("power device 'main_psu' entered the error state", result.stderr)

    def test_power_relay_gate_requires_final_on_confirmation(self):
        command = r'''
POWER_RELAY=true
POWER_DEVICE=main_psu
KACE_POWER_API_TIMEOUT=2
KACE_POWER_DEVICE_TIMEOUT=2
KACE_POWER_ON_TIMEOUT=2
sleep() { SECONDS=$((SECONDS + ${1:-1})); }
curl() {
    local url="${!#}"
    case "$url" in
        */server/info) printf '%s\n' '{"result":{"moonraker_version":"test"}}' ;;
        */machine/device_power/devices)
            printf '%s\n' '{"result":{"devices":[{"device":"main_psu","status":"off","type":"gpio"}]}}'
            ;;
        */machine/device_power/device) printf '%s\n' '{"result":{"main_psu":"off"}}' ;;
        *) return 22 ;;
    esac
}
if prepare_power_relay_for_kace; then
    exit 9
fi
'''
        result = self._run_bootstrap_library(command)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertIn("power device 'main_psu' did not reach ON", result.stderr)

    def test_power_relay_gate_times_out_when_mcu_does_not_appear(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmpdir:
            root = Path(tmpdir)
            (root / "dev").mkdir()
            command = r'''
POWER_RELAY=true
POWER_DEVICE=main_psu
KACE_MCU_DEVICE_ROOT="$1/dev"
KACE_POWER_API_TIMEOUT=2
KACE_POWER_DEVICE_TIMEOUT=2
KACE_POWER_ON_TIMEOUT=2
KACE_POWER_MCU_TIMEOUT=2
TEST_STATE_DIR="$1/state"
mkdir -p "$TEST_STATE_DIR"
sleep() { SECONDS=$((SECONDS + ${1:-1})); }
curl() {
    local url="${!#}"
    case "$url" in
        */server/info) printf '%s\n' '{"result":{"moonraker_version":"test"}}' ;;
        */machine/device_power/devices)
            if [ -f "$TEST_STATE_DIR/powered" ]; then
                printf '%s\n' '{"result":{"devices":[{"device":"main_psu","status":"on","type":"gpio"}]}}'
            else
                printf '%s\n' '{"result":{"devices":[{"device":"main_psu","status":"off","type":"gpio"}]}}'
            fi
            ;;
        */machine/device_power/device)
            touch "$TEST_STATE_DIR/powered"
            printf '%s\n' '{"result":{"main_psu":"on"}}'
            ;;
        *) return 22 ;;
    esac
}
if prepare_power_relay_for_kace; then
    exit 9
fi
'''
            result = self._run_bootstrap_library(command, root)
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertIn("No MCU appeared in /dev/serial/by-id", result.stderr)

    def test_power_relay_gate_is_noop_when_relay_is_disabled(self):
        command = r'''
POWER_RELAY=false
curl() { return 99; }
find_connected_mcu_path() { return 99; }
prepare_power_relay_for_kace
'''
        result = self._run_bootstrap_library(command)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
