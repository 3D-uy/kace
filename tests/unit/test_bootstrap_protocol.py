import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = ROOT / "scripts" / "bootstrap.sh"
PREFIX = "=== KACE_BOOTSTRAP_EVENT: "


def _bash():
    if os.name == "nt":
        program_files = os.environ.get("ProgramFiles")
        if program_files:
            git_bash = Path(program_files) / "Git" / "bin" / "bash.exe"
            if git_bash.is_file():
                return str(git_bash)
    return shutil.which("bash")


def _events(output):
    parsed = []
    for line in output.splitlines():
        if line.startswith(PREFIX) and line.endswith(" ==="):
            parsed.append(json.loads(line[len(PREFIX):-4]))
    return parsed


@unittest.skipIf(_bash() is None, "bash is unavailable")
class TestBootstrapProtocol(unittest.TestCase):
    def _run(self, body):
        command = f"""
export KACE_BOOTSTRAP_LIB_ONLY=1
export KACE_BOOTSTRAP_WORKFLOW_ID=test-flow
source "$1"
{body}
"""
        return subprocess.run(
            [_bash(), "-c", command, "bootstrap-protocol-test", BOOTSTRAP.as_posix()],
            capture_output=True,
            text=True,
        )

    def test_stage_events_are_ordered_and_terminal_is_emitted_once(self):
        result = self._run("""
emit_bootstrap_event workflow_started INIT
log_stage KLIPPER "Installing Klipper"
emit_bootstrap_terminal workflow_succeeded SUCCESS 0
emit_bootstrap_terminal workflow_failed SHOULD_NOT_APPEAR 1
""")
        self.assertEqual(result.returncode, 0, result.stderr)
        events = _events(result.stdout)
        self.assertEqual([event["sequence"] for event in events], [1, 2, 3])
        self.assertEqual([event["event"] for event in events], [
            "workflow_started", "stage_started", "workflow_succeeded",
        ])
        self.assertEqual(events[1]["stage"], "KLIPPER")
        self.assertEqual(events[-1]["code"], "SUCCESS")
        self.assertIn("=== STAGE: KLIPPER ===", result.stdout)

    def test_failure_and_signal_handlers_use_guarded_terminal_emitter(self):
        script = BOOTSTRAP.read_text(encoding="utf-8")
        failure_handler = script.split("failure_handler()", 1)[1].split(
            "trap 'failure_handler", 1
        )[0]
        cancel_handler = script.split("cancel_handler()", 1)[1].split(
            "trap 'cancel_handler INT", 1
        )[0]
        self.assertIn(
            'emit_bootstrap_terminal "workflow_failed" "BOOTSTRAP_ERROR" "$exit_status"',
            failure_handler,
        )
        self.assertIn(
            'emit_bootstrap_terminal "workflow_cancelled" "SIGNAL_${signal_name}" 2',
            cancel_handler,
        )

    def test_script_maps_typed_kace_exit_codes(self):
        script = BOOTSTRAP.read_text(encoding="utf-8")
        for code, outcome in ((2, "CANCELLED"), (10, "PRECONDITION_FAILED"),
                              (20, "GENERATION_FAILED"), (30, "FIRMWARE_FAILED"),
                              (40, "DEPLOYMENT_FAILED")):
            self.assertIn(f"{code})", script)
            self.assertIn(f'"{outcome}" "$INSTALL_EXIT"', script)


if __name__ == "__main__":
    unittest.main()
