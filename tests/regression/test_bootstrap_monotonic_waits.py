"""Polling deadlines must survive first-boot wall-clock corrections."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.regression.test_bootstrap_config_defaults import BOOTSTRAP, _find_bash


@unittest.skipUnless(_find_bash(), "bash is required")
class TestBootstrapMonotonicWaits(unittest.TestCase):
    def run_wait(self, function, *, jump, ready_at):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = r'''
set -e
python3() { "$KACE_TEST_PYTHON" "$@"; }
export KACE_BOOTSTRAP_LIB_ONLY=1
source "$1"
TEST_MONOTONIC_SECONDS=0
_monotonic_seconds() { printf '%s\n' "$TEST_MONOTONIC_SECONDS"; }
sleep() {
    TEST_MONOTONIC_SECONDS=$((TEST_MONOTONIC_SECONDS + ${1:-1}))
    SECONDS=$((SECONDS + TEST_CLOCK_JUMP))
}
record_poll() { printf '%s\n' "$TEST_MONOTONIC_SECONDS" >> "$TEST_POLLS"; }
curl() {
    record_poll
    if (( TEST_MONOTONIC_SECONDS < TEST_READY_AT )); then
        return 22
    fi
    printf '%s\n' '{"result":{"moonraker_version":"test","components":[],"failed_components":[]}}'
}
read_power_device_state() {
    record_poll
    if (( TEST_MONOTONIC_SECONDS < TEST_READY_AT )); then
        printf 'init\n'
    else
        printf 'on\n'
    fi
}
find_connected_mcu_path() {
    record_poll
    if (( TEST_MONOTONIC_SECONDS < TEST_READY_AT )); then
        return 1
    fi
    printf '/fixture/dev/serial/by-id/usb-Klipper_test-if00\n'
}
case "$TEST_WAIT" in
    wait_for_moonraker_api) "$TEST_WAIT" http://fixture.invalid 3 ;;
    wait_for_power_device_ready|wait_for_power_device_on) "$TEST_WAIT" http://fixture.invalid printer 3 ;;
    wait_for_powered_mcu) "$TEST_WAIT" 3 ;;
esac
'''
            polls = root / "polls"
            env = dict(os.environ, KACE_TEST_PYTHON=Path(sys.executable).as_posix(),
                       TEST_POLLS=polls.as_posix(), TEST_WAIT=function,
                       TEST_CLOCK_JUMP=str(jump), TEST_READY_AT=str(ready_at))
            result = subprocess.run([_find_bash(), "-c", script, "clock-test", BOOTSTRAP.as_posix()],
                                    capture_output=True, text=True, timeout=15, env=env)
            return result, polls.read_text().splitlines()

    def test_readiness_is_not_cut_short_by_wall_clock_changes(self):
        for function in ("wait_for_moonraker_api", "wait_for_power_device_ready",
                         "wait_for_power_device_on", "wait_for_powered_mcu"):
            for jump in (10000000, -10000000):
                with self.subTest(function=function, jump=jump):
                    result, polls = self.run_wait(function, jump=jump, ready_at=2)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(polls, ["0", "1", "2"])

    def test_real_elapsed_deadline_still_expires_after_wall_clock_changes(self):
        for function in ("wait_for_moonraker_api", "wait_for_power_device_ready",
                         "wait_for_power_device_on", "wait_for_powered_mcu"):
            for jump in (10000000, -10000000):
                with self.subTest(function=function, jump=jump):
                    result, polls = self.run_wait(function, jump=jump, ready_at=99)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(polls, ["0", "1", "2", "3"])
                    self.assertIn("3s", result.stderr)

    def test_clock_helper_reads_python_monotonic_time(self):
        script = r'''
set -e
python3() { "$KACE_TEST_PYTHON" "$@"; }
export KACE_BOOTSTRAP_LIB_ONLY=1
source "$1"
# A deliberately unrelated wall-clock value must not influence the helper.
SECONDS=1000000000
python3 -c 'import time; print(time.monotonic_ns() // 1000000000)'
_monotonic_seconds
python3 -c 'import time; print(time.monotonic_ns() // 1000000000)'
'''
        env = dict(os.environ, KACE_TEST_PYTHON=Path(sys.executable).as_posix())
        result = subprocess.run([_find_bash(), "-c", script, "clock-helper", BOOTSTRAP.as_posix()],
                                capture_output=True, text=True, timeout=15, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        before, actual, after = map(int, result.stdout.splitlines())
        self.assertLessEqual(before, actual)
        self.assertLessEqual(actual, after)

    def test_unavailable_clock_fails_without_polling(self):
        script = r'''
set -e
export KACE_BOOTSTRAP_LIB_ONLY=1
source "$1"
_monotonic_seconds() { return 1; }
curl() { printf 'unexpected poll\n'; return 0; }
read_power_device_state() { printf 'unexpected poll\n'; return 0; }
find_connected_mcu_path() { printf 'unexpected poll\n'; return 0; }
if wait_for_moonraker_api http://fixture.invalid 3; then exit 9; fi
if wait_for_power_device_ready http://fixture.invalid printer 3; then exit 9; fi
if wait_for_power_device_on http://fixture.invalid printer 3; then exit 9; fi
if wait_for_powered_mcu 3; then exit 9; fi
'''
        result = subprocess.run([_find_bash(), "-c", script, "clock-failure", BOOTSTRAP.as_posix()],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
