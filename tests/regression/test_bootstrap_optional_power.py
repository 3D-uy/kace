"""Execute the real reconciliation/services block against a local HTTP server.

Only systemd, ownership and the MCU node are simulated. The bootstrap Bash,
curl HTTP status handling, JSON validation and state persistence are real.
"""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

from tests.regression.test_bootstrap_config_defaults import BOOTSTRAP, _find_bash


def server_info(*, power=False, failed=None):
    return {"result": {"moonraker_version": "test", "klippy_state": "disconnected",
                       "components": ["server", "power"] if power else ["server"],
                       "failed_components": failed or []}}


@contextmanager
def api_server(info, devices, *, info_status=200, power_status=200, startup_failures=0):
    state = {"requests": [], "powered": False, "startup_failures": startup_failures}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def respond(self, status, payload):
            body = (json.dumps(payload) if not isinstance(payload, str) else payload).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            state["requests"].append(("GET", self.path))
            if self.path == "/server/info":
                if state["startup_failures"]:
                    state["startup_failures"] -= 1
                    self.respond(503, {"error": "starting"})
                else:
                    self.respond(info_status, info)
            elif self.path == "/machine/device_power/devices":
                payload = devices
                if isinstance(devices, list):
                    payload = {"result": {"devices": [dict(item, status="on" if state["powered"] else "off") for item in devices]}}
                self.respond(power_status, payload)
            else:
                self.respond(404, {"error": "not found"})

        def do_POST(self):
            state["requests"].append(("POST", self.path))
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            payload = json.loads(body)
            if self.path != "/machine/device_power/device" or payload != {"device": "new_psu", "action": "on"}:
                self.respond(400, {"error": "unexpected command"})
                return
            state["powered"] = True
            self.respond(200, {"result": {"new_psu": "on"}})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.05), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@unittest.skipUnless(_find_bash(), "bash is required")
class TestBootstrapOptionalPower(unittest.TestCase):
    def run_services(self, *, enabled=False, previous=False, info=None, devices=None,
                     info_status=200, power_status=200, startup_failures=0, clock_jump=0, mcu_present=True):
        with tempfile.TemporaryDirectory() as tmp, api_server(
            server_info(power=enabled) if info is None else info,
            [] if devices is None else devices,
            info_status=info_status, power_status=power_status,
            startup_failures=startup_failures,
        ) as (url, state):
            root = Path(tmp)
            config = root / "moonraker.conf"
            unrelated = ("[power desk_lamp]\ntype: gpio\npin: gpiochip0/gpio6\n"
                         if isinstance(devices, list) and any(item.get("device") == "desk_lamp" for item in devices)
                         else "")
            config.write_text("[server]\nport: 7125\n" + unrelated, encoding="utf-8")
            power_file = root / ".config/kace/power.json"
            if previous:
                power_file.parent.mkdir(parents=True)
                power_file.write_text(json.dumps({"schema": "kace-power/v1", "revision": 1,
                    "enabled": True, "device": "old_psu", "pin": "gpiochip0/gpio5",
                    "active_low": False, "restart_klipper_when_powered": True,
                    "initial_state": "off", "off_when_shutdown": True}), encoding="utf-8")
                config.write_text(config.read_text(encoding="utf-8") +
                    "# BEGIN KACE MANAGED: power\n[power old_psu]\ntype: gpio\npin: gpiochip0/gpio5\n"
                    "restart_klipper_when_powered: true\ninitial_state: off\noff_when_shutdown: true\n"
                    "# END KACE MANAGED: power\n", encoding="utf-8")
            before = power_file.read_bytes() if previous else None
            mcu = root / "dev/serial/by-id/usb-Klipper_test-if00"
            mcu.parent.mkdir(parents=True)
            if mcu_present:
                mcu.touch()
            source = BOOTSTRAP.read_text(encoding="utf-8")
            services = source[source.index('log_stage "SERVICES"'):source.index('# ── 10. Crowsnest')]
            runner = root / "services.sh"
            runner.write_text('''set -e
python3() { "$KACE_TEST_PYTHON" "$@"; }
export KACE_BOOTSTRAP_LIB_ONLY=1
source "$1"
PRINTER_HOME="$2"
MOONRAKER_CONFIG="$2/moonraker.conf"
PRINTER_USER=test
PRINTER_GROUP=test
POWER_CONFIG_PATH="$2/.config/kace/power.json"
KACE_MCU_DEVICE_ROOT="$2/dev"
POWER_RELAY="$3"
POWER_DEVICE=new_psu
POWER_GPIO=5
POWER_ACTIVE_LOW=false
POWER_RESTART_KLIPPER=true
POWER_INITIAL_STATE=off
POWER_OFF_WHEN_SHUTDOWN=true
KACE_POWER_API_TIMEOUT=2
KACE_POWER_DEVICE_TIMEOUT=2
KACE_POWER_ON_TIMEOUT=2
KACE_POWER_MCU_TIMEOUT=2
PREBAKED=true
DASHBOARD=mainsail
SUDO=""
systemctl() { printf '%s\n' "$*" >> "$PRINTER_HOME/services.log"; }
chown() { :; }
TEST_MONOTONIC_SECONDS=0
_monotonic_seconds() { printf '%s\n' "$TEST_MONOTONIC_SECONDS"; }
sleep() {
    TEST_MONOTONIC_SECONDS=$((TEST_MONOTONIC_SECONDS + ${1:-1}))
    SECONDS=$((SECONDS + TEST_CLOCK_JUMP))
}
curl() {
    local args=() arg
    for arg in "$@"; do
        args+=("${arg/http:\\/\\/127.0.0.1:7125/$TEST_API_URL}")
    done
    command curl --noproxy '*' "${args[@]}"
}
begin_power_reconciliation "$MOONRAKER_CONFIG" "$POWER_CONFIG_PATH"
reconcile_power_relay_section "$MOONRAKER_CONFIG"
''' + services + '\nprintf "SERVICES_VERIFIED\\n"\n', encoding="utf-8")
            env = dict(os.environ, KACE_TEST_PYTHON=Path(sys.executable).as_posix(), TEST_API_URL=url, TEST_CLOCK_JUMP=str(clock_jump))
            result = subprocess.run([_find_bash(), runner.as_posix(), BOOTSTRAP.as_posix(), root.as_posix(), str(enabled).lower()],
                                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, env=env)
            after = power_file.read_bytes() if power_file.exists() else None
            self.assertIn(unrelated, config.read_text(encoding="utf-8"))
            self.assertIn("restart moonraker", (root / "services.log").read_text())
            return result, state, before, after

    def test_first_boot_without_relay_and_missing_optional_api(self):
        result, state, _, after = self.run_services(power_status=404)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SERVICES_VERIFIED", result.stdout)
        self.assertEqual(state["requests"], [("GET", "/server/info")])
        self.assertFalse(json.loads(after)["enabled"])

    def test_slow_server_is_waited_for_without_relay(self):
        result, state, _, _ = self.run_services(startup_failures=1, power_status=404)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(state["requests"], [("GET", "/server/info")] * 2)

    def assert_terminal_failure(self, result, code):
        prefix = "=== KACE_BOOTSTRAP_EVENT: "
        events = [json.loads(line[len(prefix):-4]) for line in result.stdout.splitlines()
                  if line.startswith(prefix)]
        failures = [event for event in events if event["event"] == "workflow_failed"]
        self.assertEqual(len(failures), 1, result.stdout)
        self.assertEqual(failures[0]["stage"], "SERVICES")
        self.assertEqual(failures[0]["code"], code)
        self.assertEqual(failures[0]["exit_code"], 1)

    def test_server_readiness_survives_wall_clock_correction(self):
        for jump in (10000000, -10000000):
            with self.subTest(jump=jump):
                result, state, _, after = self.run_services(
                    startup_failures=2, clock_jump=jump, power_status=404)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(state["requests"], [("GET", "/server/info")] * 3)
                self.assertFalse(json.loads(after)["enabled"])

    def test_actual_timeout_reports_api_failure_and_preserves_previous_state(self):
        result, state, before, after = self.run_services(
            previous=True, startup_failures=10, clock_jump=-10000000)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, after)
        self.assertEqual(state["requests"], [("GET", "/server/info")] * 3)
        self.assert_terminal_failure(result, "GPIO_RELAY_API_VERIFY")

    def test_missing_mcu_reports_power_on_failure_without_persisting(self):
        result, state, _, after = self.run_services(enabled=True, mcu_present=False,
            devices=[{"device": "new_psu", "type": "gpio"}], clock_jump=10000000)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(state["powered"])
        self.assertIsNone(after)
        self.assert_terminal_failure(result, "POWER_ON")

    def test_removing_last_managed_device_accepts_absent_component(self):
        result, state, _, after = self.run_services(previous=True, power_status=404)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(after)["enabled"])
        self.assertEqual(json.loads(after)["revision"], 2)
        self.assertFalse(any("device_power" in path for _, path in state["requests"]))

    def test_disable_preserves_unrelated_devices_and_rejects_stale_managed_device(self):
        for stale in (False, True):
            with self.subTest(stale=stale):
                devices = [{"device": "desk_lamp", "type": "gpio"}]
                if stale:
                    devices.append({"device": "old_psu", "type": "gpio"})
                result, _, before, after = self.run_services(previous=True, info=server_info(power=True), devices=devices)
                self.assertEqual(result.returncode == 0, not stale, result.stderr)
                if stale:
                    self.assertEqual(before, after)

    def test_enabled_and_renamed_device_requires_power_on_and_mcu(self):
        result, state, _, after = self.run_services(enabled=True, previous=True,
            devices=[{"device": "new_psu", "type": "gpio"}, {"device": "desk_lamp", "type": "gpio"}])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(state["powered"])
        self.assertEqual(json.loads(after)["device"], "new_psu")
        self.assertIn("MCU detected", result.stdout)

    def test_required_missing_power_api_never_succeeds(self):
        result, state, _, after = self.run_services(enabled=True, power_status=404)
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(after)
        self.assertFalse(state["powered"])

    def test_enabled_invalid_device_is_rejected_before_any_power_command(self):
        for devices in ([], [{"device": "new_psu", "type": "mqtt"}],
                        [{"device": "new_psu", "type": "gpio"}] * 2):
            with self.subTest(devices=devices):
                result, state, _, after = self.run_services(enabled=True, devices=devices)
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNone(after)
                self.assertFalse(state["powered"])

    def test_rename_rejects_old_device_still_loaded_before_power_command(self):
        result, state, before, after = self.run_services(enabled=True, previous=True,
            devices=[{"device": "new_psu", "type": "gpio"}, {"device": "old_psu", "type": "gpio"}])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, after)
        self.assertFalse(state["powered"])

    def test_global_http_errors_and_malformed_info_never_persist(self):
        cases = [(code, server_info()) for code in (401, 403, 404, 500, 503)]
        cases += [(200, body) for body in ("not json", [], {"result": {}}, server_info(failed=["power"]))]
        for code, info in cases:
            with self.subTest(code=code, info=info):
                result, state, before, after = self.run_services(previous=True, info=info, info_status=code, power_status=404)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(before, after)
                self.assertFalse(any("device_power" in path for _, path in state["requests"]))

    def test_loaded_power_api_errors_and_malformed_lists_never_persist(self):
        cases = [(code, []) for code in (401, 403, 404, 500)]
        cases += [(200, body) for body in ("not json", {"result": {}}, {"result": {"devices": [{}]}})]
        for code, devices in cases:
            with self.subTest(code=code, devices=devices):
                result, _, before, after = self.run_services(previous=True, info=server_info(power=True), devices=devices, power_status=code)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
