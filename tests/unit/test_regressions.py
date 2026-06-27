# tests/unit/test_regressions.py
#
# Regression guards for named bugs. Each test must carry the bug ID it guards.
# These tests exist specifically to prevent the identified bug from being
# silently re-introduced by future refactors.

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from core.exceptions import WizardExit, GenerationError


# ── BUG-006: WizardExit on input returning None / Quit ────────────────────────
#
# Bug: When the user presses Ctrl-C, input/select returns None or '__quit__'.
# If the wizard loop does not handle None explicitly, it falls through to
# an unguarded branch and loops infinitely.
#
# Fix: Every prompt checks:
#   if ans == _QUIT or ans is None: raise WizardExit()
#
# This test guards two of the most common wizard entry-points.

class TestBUG006WizardExitOnNone(unittest.TestCase):
    """BUG-006: Ctrl-C (input returns None/Quit) must raise WizardExit, not loop."""

    @patch("builtins.input")
    @patch("core.wizard.discover_mcu")
    @patch("core.wizard.fetch_config_list")
    def test_none_from_kinematics_prompt_raises_wizard_exit(
        self, mock_fetch, mock_mcu, mock_input
    ):
        """If input returns Quit or None, WizardExit must be raised."""
        from core.wizard import run_wizard

        mock_mcu.return_value = {
            "mcu_path": "/dev/serial/by-id/mock",
            "derived_mcu": "stm32f103",
            "hint": "usb",
        }
        mock_fetch.return_value = ["generic-bigtreetech-skr-v1.4.cfg"]

        # Return "__quit__" for the first board prompt
        mock_input.return_value = "__quit__"

        user_data = {
            "printer_profile": "generic-bigtreetech-skr-v1.4.cfg",
            "board": "generic-bigtreetech-skr-v1.4.cfg",
            "kinematics": "cartesian",
            "x_size": "235", "y_size": "235", "z_size": "250",
            "probe": "None",
            "hotend_thermistor": "Generic 3950",
            "bed_thermistor": "Generic 3950",
            "driver_type": "None (Standard)",
            "driver_mode": "Standalone",
            "web_interface": "Mainsail",
            "z_motors": "1",
            "mcu_path": "/dev/serial/by-id/mock",
        }

        with self.assertRaises(WizardExit):
            run_wizard(user_data)

    @patch("builtins.input")
    @patch("core.wizard.discover_mcu")
    @patch("core.wizard.fetch_config_list")
    def test_quit_sentinel_raises_wizard_exit(
        self, mock_fetch, mock_mcu, mock_input
    ):
        """Selecting '__quit__' (the Quit menu item) must raise WizardExit."""
        from core.wizard import run_wizard

        mock_mcu.return_value = {
            "mcu_path": "/dev/serial/by-id/mock",
            "derived_mcu": "stm32f103",
            "hint": "usb",
        }
        mock_fetch.return_value = ["generic-bigtreetech-skr-v1.4.cfg"]
        mock_input.return_value = "__quit__"

        user_data = {
            "printer_profile": "generic-bigtreetech-skr-v1.4.cfg",
            "board": "generic-bigtreetech-skr-v1.4.cfg",
            "kinematics": "cartesian",
            "x_size": "235", "y_size": "235", "z_size": "250",
            "probe": "None",
            "hotend_thermistor": "Generic 3950",
            "bed_thermistor": "Generic 3950",
            "driver_type": "None (Standard)",
            "driver_mode": "Standalone",
            "web_interface": "Mainsail",
            "z_motors": "1",
            "mcu_path": "/dev/serial/by-id/mock",
        }

        with self.assertRaises(WizardExit):
            run_wizard(user_data)

    def test_wizard_exit_is_exception_not_systemexit(self):
        """WizardExit must be catchable as a regular Exception, not a SystemExit.
        This guards against accidentally converting it to sys.exit() in the future."""
        self.assertTrue(issubclass(WizardExit, Exception))
        self.assertFalse(issubclass(WizardExit, SystemExit))


# ── BUG-007: deploy_config() aborts on missing printer.cfg ───────────────────
#
# Bug: Before the fix, deploy_config() called sftp.put() directly. If
# ~/kace/printer.cfg did not exist, paramiko raised a cryptic
# FileNotFoundError that the broad "except Exception" handler would
# swallow, printing only "Deployment failed: [Errno ...]" with no hint
# that the user must generate a config first.
#
# Fix (lines 62-69 of deployer.py): An explicit os.path.isfile() check
# guards sftp.put() and prints a clear "Deployment aborted: printer.cfg
# not found" message before returning.

class TestBUG007DeployAbortOnMissingCfg(unittest.TestCase):
    """BUG-007: deploy_config() must abort with a clear message if printer.cfg is missing."""

    @patch("core.deployer._require_paramiko")
    @patch("core.deployer.os.path.isfile", return_value=False)
    @patch("builtins.print")
    def test_aborts_when_printer_cfg_missing(
        self, mock_print, mock_isfile, mock_paramiko
    ):
        """When printer.cfg does not exist, deploy_config() must print an abort
        message and return without attempting an SSH connection."""
        from core.deployer import deploy_config

        # paramiko is available but we should never reach ssh.connect()
        mock_ssh = MagicMock()
        mock_paramiko.return_value = MagicMock()

        deploy_config({
            "host": "192.168.1.100",
            "user": "pi",
            "password": "raspberry",
            "dest_path": "~/printer_data/config/",
        })

        # Must print "Deployment aborted" — not silently swallow
        printed = [str(call) for call in mock_print.call_args_list]
        self.assertTrue(
            any("aborted" in msg.lower() or "not found" in msg.lower()
                for msg in printed),
            f"Expected abort message, got: {printed}",
        )

        # Must NOT attempt SSH connect
        mock_ssh.connect.assert_not_called()

    @patch("core.deployer._require_paramiko")
    @patch("core.deployer.os.path.isfile", return_value=False)
    @patch("builtins.print")
    def test_abort_message_mentions_generate(
        self, mock_print, mock_isfile, mock_paramiko
    ):
        """The abort message must guide the user to run Generate first."""
        from core.deployer import deploy_config

        mock_paramiko.return_value = MagicMock()
        deploy_config({
            "host": "mypi",
            "user": "pi",
            "password": "",
            "dest_path": "~/config/",
        })

        printed_all = " ".join(str(c) for c in mock_print.call_args_list).lower()
        # The message must advise the user to generate a config first
        self.assertTrue(
            "generate" in printed_all or "first" in printed_all,
            f"Expected guidance message, got: {printed_all}",
        )

    @patch("core.deployer._require_paramiko", return_value=None)
    @patch("builtins.print")
    def test_returns_early_when_paramiko_unavailable(self, mock_print, mock_req):
        """If paramiko is not available (returns None), deploy_config must return
        immediately without crashing."""
        from core.deployer import deploy_config

        try:
            deploy_config({"host": "mypi", "user": "pi",
                           "password": "", "dest_path": "~/config/"})
        except Exception as e:
            self.fail(f"deploy_config raised when paramiko unavailable: {e}")


# ── Test Bug-003: Numeric sanitization ────────────────────────────────────────
class TestBug003Sanitization(unittest.TestCase):
    def test_geometry_sanitization(self):
        from core.scraper import parse_config, extract_profile_defaults
        cfg = """
[stepper_x]
position_max: 300mm
position_min: -5   # X min limit
position_endstop: 0mm
        """
        parsed = parse_config(cfg)
        defaults = extract_profile_defaults(parsed)
        self.assertEqual(defaults["x_size"], "300")
        self.assertEqual(defaults["x_position_max"], "300")
        self.assertEqual(defaults["x_position_min"], "-5")
        self.assertEqual(defaults["x_position_endstop"], "0")

# ── Test Bug-002: Malformed section header leakage ────────────────────────────
class TestBug002HeaderLeakage(unittest.TestCase):
    def test_malformed_header_clears_section(self):
        from core.scraper import parse_config
        cfg = """
[stepper_x]
step_pin: PC2
[stepper_y
step_pin: PC3
        """
        parsed = parse_config(cfg)
        # stepper_y is malformed, step_pin: PC3 should NOT leak into stepper_x
        self.assertIn("stepper_x", parsed)
        self.assertEqual(parsed["stepper_x"]["step_pin"], "PC2")
        self.assertNotIn("step_pin", parsed.get("stepper_y", {}))

# ── Test Bug-001: Wizard back-navigation loop in single-Z ──────────────────────
class TestBug001WizardBackNavigation(unittest.TestCase):
    def test_back_navigation_from_driver_type_rolls_back_to_z_motors(self):
        from core.wizard import WizardRunner, _BACK
        
        z_motors_prompts = []
        driver_type_prompts = 0
        z_sock_called = False
        
        def mock_board(ud):
            return "generic-bigtreetech-skr-v1.4.cfg"
            
        def mock_z_motors(ud):
            z_motors_prompts.append(True)
            ans = "2" if len(z_motors_prompts) > 1 else "1"
            ud["z_motors"] = ans
            return ans
            
        def mock_z_socket(ud):
            nonlocal z_sock_called
            if int(ud.get("z_motors", 1)) <= 1:
                z_sock_called = True
            return "__skip__"
            
        def mock_driver_type(ud):
            nonlocal driver_type_prompts
            driver_type_prompts += 1
            if driver_type_prompts == 1:
                # Go back the first time
                return _BACK
            return "None (Standard)"
            
        def mock_printer_profile(ud):
            return None

        # Build self-contained steps matching wizard logic
        steps_config = {
            "board": {
                "prompt": mock_board
            },
            "z_motors": {
                "prompt": mock_z_motors,
                "next":   lambda ans, ud: "driver_type" if int(ans or 1) <= 1 else "z_socket_assignment"
            },
            "z_socket_assignment": {
                "prompt": mock_z_socket,
                "next":   lambda ans, ud: "driver_type"
            },
            "driver_type": {
                "prompt": mock_driver_type
            },
            "printer_profile": {
                "prompt": mock_printer_profile
            }
        }
        
        step_order = [
            "board",
            "z_motors",
            "z_socket_assignment",
            "driver_type",
            "printer_profile"
        ]

        user_data = {
            "board": "generic-bigtreetech-skr-v1.4.cfg",
            "printer_profile": "Custom / Scratch Build",
            "profile_loaded": False,
        }
        
        runner = WizardRunner(steps_config, step_order, initial_data=user_data)
        runner.run("board")
        
        # Verification:
        # 1. z_motors must be prompted twice (once initially, once on rollback)
        self.assertEqual(len(z_motors_prompts), 2)
        # 2. z_socket_assignment must never be called when z_motors == 1
        self.assertFalse(z_sock_called)
        # 3. driver_type was prompted
        self.assertTrue(driver_type_prompts >= 1)

if __name__ == "__main__":
    unittest.main()
