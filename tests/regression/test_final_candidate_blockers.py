"""End-to-end regressions for the final software candidate gates."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

from core.exceptions import WizardExit
from core.workflow_outcome import WorkflowOutcome, WorkflowResult
from core.firmware_wizard import (
    _cancel_firmware_configuration,
    run_firmware_wizard,
)
from core.dashboard import run_dashboard
from core.probe_offset_visualizer import run_probe_offset_step
from core.translations import t
from firmware.detector import discover_mcu_hardware
from firmware.deployment import DeploymentMethodId


ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = ROOT / "scripts" / "bootstrap.sh"


def _assignment(content: str, name: str) -> str:
    match = re.search(rf'^{name}="?([^"\n]+)"?$', content, re.MULTILINE)
    if not match:
        raise AssertionError(f"missing assignment: {name}")
    return match.group(1)


def _bash() -> str | None:
    candidates = (
        (r"C:\Program Files\Git\bin\bash.exe", "bash")
        if os.name == "nt"
        else ("bash",)
    )
    for candidate in candidates:
        try:
            subprocess.run(
                [candidate, "--version"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            return candidate
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    return None


class TestImmutableCandidateDistribution(unittest.TestCase):
    def test_every_public_installer_delivers_the_declared_candidate(self):
        script = BOOTSTRAP.read_text(encoding="utf-8")
        candidate = _assignment(script, "KACE_INSTALL_REF")
        installer_hash = _assignment(script, "KACE_INSTALL_SHA256")
        self.assertRegex(candidate, r"^[0-9a-f]{40}$")
        self.assertRegex(installer_hash, r"^[0-9a-f]{64}$")

        installer = subprocess.run(
            ["git", "show", f"{candidate}:install.sh"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        ).stdout
        self.assertEqual(hashlib.sha256(installer).hexdigest(), installer_hash)

        for relative in ("README.md", "docs/es/README.md", "docs/pt/README.md"):
            content = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn(f"KACE_COMMIT='{candidate}'", content, relative)
            self.assertIn(f"KACE_INSTALL_SHA256='{installer_hash}'", content, relative)

        changed_runtime = subprocess.run(
            [
                "git", "diff", "--name-only", f"{candidate}..HEAD", "--",
                "core", "firmware", "data", "templates", "kace.py", "install.sh",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        self.assertEqual(
            changed_runtime,
            "",
            f"declared candidate does not contain current runtime files: {changed_runtime}",
        )


class TestCancellationContract(unittest.TestCase):
    def test_interactive_modules_do_not_exit_zero(self):
        for relative in (
            "core/dashboard.py",
            "core/firmware_wizard.py",
            "core/probe_offset_visualizer.py",
            "firmware/detector.py",
        ):
            content = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotRegex(content, r"(?:sys\.)?exit\(0\)", relative)

    def test_firmware_cancel_raises_typed_wizard_exit(self):
        with patch("builtins.print"):
            with self.assertRaises(WizardExit):
                _cancel_firmware_configuration()

    def test_dashboard_interrupt_raises_typed_wizard_exit(self):
        state = {
            "klipper": False,
            "moonraker": False,
            "mainsail": False,
            "fluidd": False,
            "printer_cfg": False,
        }
        with patch("core.dashboard._select_language"), \
             patch("core.dashboard._select_mode"), \
             patch("core.dashboard.print_kace_banner"), \
             patch("core.dashboard._render_status_panel"), \
             patch("core.dashboard._render_suggestions"), \
             patch("builtins.input", side_effect=KeyboardInterrupt), \
             patch("builtins.print"):
            with self.assertRaises(WizardExit):
                run_dashboard(state)

    def test_mcu_quit_raises_typed_wizard_exit(self):
        with patch("firmware.detector.glob.glob", return_value=[]), \
             patch("firmware.detector.os.path.isfile", return_value=False), \
             patch("firmware.detector.numbered_select", return_value="quit"), \
             patch("builtins.print"):
            with self.assertRaises(WizardExit):
                discover_mcu_hardware(interactive=True)

    def test_probe_quit_raises_typed_wizard_exit(self):
        with patch("core.probe_offset_visualizer._print_frame"), \
             patch("core.probe_offset_visualizer.simple_input", side_effect=["0", "0"]), \
             patch("core.probe_offset_visualizer.numbered_select", return_value="quit"), \
             patch("builtins.print"):
            with self.assertRaises(WizardExit):
                run_probe_offset_step({"probe": "BLTouch", "x_size": 220, "y_size": 220})


class TestFirmwareWizardTerminalResult(unittest.TestCase):
    @patch("core.firmware_wizard.yes_no", return_value=True)
    @patch("core.firmware_wizard.numbered_select", return_value=None)
    @patch("core.firmware_wizard.build_firmware_orchestrator")
    def test_build_exception_is_a_typed_firmware_failure(
        self, mock_build, mock_select, mock_confirm
    ):
        mock_select.side_effect = [t("builder.compile_now")]
        mock_build.side_effect = RuntimeError("compiler crashed")

        with patch("builtins.print"):
            result = run_firmware_wizard({"mcu_type": "rp2040", "mcu_hint": "usb"})

        self.assertIsInstance(result, WorkflowResult)
        self.assertEqual(result.outcome, WorkflowOutcome.FIRMWARE_FAILED)
        self.assertIn("compiler crashed", result.detail)

    @patch("core.firmware_wizard.yes_no", return_value=True)
    @patch("core.firmware_wizard.numbered_select", return_value=None)
    @patch("core.firmware_wizard.build_firmware_orchestrator")
    def test_build_failure_is_a_typed_firmware_failure(
        self, mock_build, mock_select, mock_confirm
    ):
        mock_select.side_effect = [t("builder.compile_now")]
        mock_build.return_value = {"status": "failed", "message": "compiler failed"}

        with patch("builtins.print"):
            result = run_firmware_wizard({"mcu_type": "rp2040", "mcu_hint": "usb"})

        self.assertIsInstance(result, WorkflowResult)
        self.assertEqual(result.outcome, WorkflowOutcome.FIRMWARE_FAILED)
        self.assertIn("compiler failed", result.detail)

    @patch("core.firmware_wizard.yes_no", return_value=True)
    @patch("core.firmware_wizard.numbered_select")
    @patch("core.firmware_wizard.build_firmware_orchestrator")
    @patch("core.firmware_wizard.FirmwareDeploymentService")
    def test_prepare_failure_is_a_typed_firmware_failure(
        self, mock_service_cls, mock_build, mock_select, mock_confirm
    ):
        mock_select.side_effect = [t("builder.compile_now"), DeploymentMethodId.MANUAL.value]
        mock_build.return_value = {
            "status": "success",
            "mcu": "rp2040",
            "firmware": "klipper.uf2",
            "path": "/fake/kace/klipper.uf2",
        }
        service = mock_service_cls.return_value
        service.available_methods.return_value = (DeploymentMethodId.MANUAL,)
        service.plan.return_value = MagicMock()
        service.prepare.side_effect = RuntimeError("staging failed")

        with patch("builtins.print"):
            result = run_firmware_wizard({"mcu_type": "rp2040", "mcu_hint": "usb"})

        self.assertIsInstance(result, WorkflowResult)
        self.assertEqual(result.outcome, WorkflowOutcome.FIRMWARE_FAILED)
        self.assertIn("staging failed", result.detail)


@unittest.skipIf(_bash() is None, "bash is not available")
class TestCrowsnestFailClosed(unittest.TestCase):
    def _run_harness(
        self,
        tmp_path: Path,
        install_exit: int,
        *,
        fail_command: str = "",
        service_exit: int = 0,
    ):
        command = r'''
set -euo pipefail
export KACE_BOOTSTRAP_LIB_ONLY=1
source "$1"
type provision_crowsnest >/dev/null
PRINTER_HOME="$2"
PRINTER_USER="pi"
PRINTER_GROUP="pi"
PREBAKED="false"
SUDO=""
mkdir -p "$PRINTER_HOME/crowsnest/tools"
cat > "$PRINTER_HOME/crowsnest/tools/install.sh" <<'SCRIPT'
#!/bin/bash
exit "${KACE_TEST_INSTALL_EXIT}"
SCRIPT
chmod +x "$PRINTER_HOME/crowsnest/tools/install.sh"
ensure_pinned_git_checkout() { return 0; }
wait_for_apt_locks() { return 0; }
install_service_identity_dropin() { return 0; }
detect_camera_hardware() { return 0; }
sudo() { "$@"; }
systemctl() {
    if [ "$1" = "${KACE_TEST_FAIL_COMMAND}" ]; then
        return "${KACE_TEST_SERVICE_EXIT}"
    fi
    return 0
}
provision_crowsnest
'''
        return subprocess.run(
            [_bash(), "-c", command, "crowsnest-test", BOOTSTRAP.as_posix(), tmp_path.as_posix()],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "KACE_TEST_INSTALL_EXIT": str(install_exit),
                "KACE_TEST_FAIL_COMMAND": fail_command,
                "KACE_TEST_SERVICE_EXIT": str(service_exit),
            },
        )

    def test_requested_crowsnest_installer_failure_is_terminal(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            result = self._run_harness(Path(directory), install_exit=17)
        self.assertEqual(result.returncode, 17, result.stdout + result.stderr)

    def test_requested_crowsnest_missing_unit_is_terminal(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            result = self._run_harness(
                Path(directory), install_exit=0, fail_command="cat", service_exit=19
            )
        self.assertEqual(result.returncode, 19, result.stdout + result.stderr)

    def test_requested_crowsnest_enable_failure_is_terminal(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            result = self._run_harness(
                Path(directory), install_exit=0, fail_command="enable", service_exit=20
            )
        self.assertEqual(result.returncode, 20, result.stdout + result.stderr)

    def test_requested_crowsnest_start_failure_is_terminal(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            result = self._run_harness(
                Path(directory), install_exit=0, fail_command="restart", service_exit=21
            )
        self.assertEqual(result.returncode, 21, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
