import unittest
from unittest.mock import patch, MagicMock, call
import sys
import os
import posixpath

# Add project root to sys.path so imports resolve
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

class TestPinCollisionValidation(unittest.TestCase):

    def test_pin_collision_basic(self):
        """Validate pin collision detection raises validation errors when pin is in use."""
        from core.wizard.steps.sensors import make_pin_validator_with_collision_check
        
        # Build mock user_data that get_current_board_parsed can consume without file system access
        user_data = {
            "board": "custom",
            "printer_profile": "custom",
            "profile_loaded": True,
            "raw_config": "[stepper_x]\nstep_pin: gpio0\n[heater_bed]\nsensor_pin: gpio1\n",
            "mcu_type": "rp2040"
        }
        
        validator = make_pin_validator_with_collision_check(user_data)
        
        # Unique/unused pin should pass validation
        self.assertEqual(validator("gpio5"), True)
        
        # Colliding pin (gpio0 is used by stepper_x) should fail validation
        res_gpio0 = validator("gpio0")
        self.assertNotEqual(res_gpio0, True)
        self.assertIn("gpio0", res_gpio0.lower())
        
        # Colliding pin (gpio1 is used by heater_bed) should fail validation
        res_gpio1 = validator("gpio1")
        self.assertNotEqual(res_gpio1, True)
        self.assertIn("gpio1", res_gpio1.lower())

    @patch("core.wizard.steps.sensors.get_lang")
    def test_pin_collision_languages(self, mock_get_lang):
        """Verify collision messages format correctly in Spanish, Portuguese, and English."""
        from core.wizard.steps.sensors import make_pin_validator_with_collision_check
        
        user_data = {
            "board": "custom",
            "printer_profile": "custom",
            "profile_loaded": True,
            "raw_config": "[stepper_x]\nstep_pin: gpio0\n",
            "mcu_type": "rp2040"
        }
        
        # Spanish Mode
        mock_get_lang.return_value = "Español"
        validator_es = make_pin_validator_with_collision_check(user_data)
        res_es = validator_es("gpio0")
        self.assertIn("ya está en uso", res_es)

        # Portuguese Mode
        mock_get_lang.return_value = "Português"
        validator_pt = make_pin_validator_with_collision_check(user_data)
        res_pt = validator_pt("gpio0")
        self.assertIn("já está em uso", res_pt)

        # English/Default Mode
        mock_get_lang.return_value = "English"
        validator_en = make_pin_validator_with_collision_check(user_data)
        res_en = validator_en("gpio0")
        self.assertIn("is already in use", res_en)


class TestDisplayVoltageSafety(unittest.TestCase):

    def test_rp2040_voltage_safety_checks(self):
        """Ensure RP2040 3.3V-only limits generate mandatory warnings for 5V display logic."""
        from core.display_checker import classify_hardware_combination, run_manual_selection_analysis
        
        parsed_cfg = {}
        board_file = "generic-skr-pico-rp2040.cfg" # Inferred as rp2040 (3.3V_only tolerance)
        
        # 1. DWIN display requires 5V logic feedback (WS2812/5V rules)
        # Verify custom voltage checks flag danger
        res_dwin = run_manual_selection_analysis("dwin_set", board_file, "rp2040", parsed_cfg)
        self.assertEqual(res_dwin["voltage_validation"]["result"], "danger")
        self.assertIn("RP2040 GPIO pins", res_dwin["voltage_validation"]["detail"])
        
        # 2. NeopixelWS2812 expected level shifter mods
        res_neo = run_manual_selection_analysis("neopixel", board_file, "rp2040", parsed_cfg)
        self.assertEqual(res_neo["voltage_validation"]["result"], "danger")
        self.assertTrue(any("level shifter" in m.lower() for m in res_neo["required_modifications"]))

    def test_stm32_voltage_safety_checks(self):
        """Verify STM32 3.3V-tolerant MCU triggers warnings rather than absolute blocks for 5V logic."""
        from core.display_checker import run_manual_selection_analysis
        
        parsed_cfg = {}
        board_file = "generic-creality-v4.2.2.cfg" # Inferred as stm32 (3.3V_tolerant tolerance)
        
        res_dwin = run_manual_selection_analysis("dwin_set", board_file, "stm32f103", parsed_cfg)
        # Should be a warning/unsafe default, but let's check exact outcome
        self.assertEqual(res_dwin["voltage_validation"]["result"], "warn")
        self.assertIn("5V-tolerant", res_dwin["voltage_validation"]["detail"])


class TestProbeOffsetVisualizerHardening(unittest.TestCase):

    @patch("core.probe_offset_visualizer.simple_input")
    @patch("core.probe_offset_visualizer.numbered_select")
    @patch("builtins.print")
    def test_run_probe_offset_step_retry_then_yes(self, mock_print, mock_select, mock_text):
        """Verify the probe offset setup loop handles retry and final acceptance."""
        from core.probe_offset_visualizer import run_probe_offset_step
        
        user_data = {
            "probe": "BLTouch",
            "x_size": "235",
            "y_size": "235"
        }
        
        # Simulate user inputs:
        # First round: x_off = "-38.0", y_off = "10.0" -> confirm choice = "retry"
        # Second round: x_off = "-40.0", y_off = "5.0" -> confirm choice = "yes"
        mock_text.side_effect = ["-38.0", "10.0", "-40.0", "5.0"]
        mock_select.side_effect = ["retry", "yes"]
        
        res = run_probe_offset_step(user_data, "generic-creality-v4.2.2.cfg")
        
        self.assertEqual(res["probe_x_offset"], "-40.0")
        self.assertEqual(res["probe_y_offset"], "5.0")

    @patch("core.probe_offset_visualizer.simple_input")
    def test_run_probe_offset_step_cancel(self, mock_text):
        """Verify user cancellation (Ctrl+C/Escape returning None) returns __back__."""
        from core.probe_offset_visualizer import run_probe_offset_step
        
        user_data = {"probe": "BLTouch", "x_size": "235", "y_size": "235"}
        
        # User cancels at X offset prompt
        mock_text.return_value = None
        
        res = run_probe_offset_step(user_data, "generic-creality-v4.2.2.cfg")
        self.assertEqual(res["probe_x_offset"], "__back__")


class TestMCUDetectorFallbacks(unittest.TestCase):

    @patch("glob.glob")
    @patch("builtins.print")
    def test_discover_mcu_by_path_fallback(self, mock_print, mock_glob):
        """Verify by-path fallback is used when by-id returns empty."""
        from firmware.detector import discover_mcu_hardware
        
        glob_calls = []
        def mock_glob_fn(pattern):
            glob_calls.append(pattern)
            if "by-id" in pattern:
                return []
            if "by-path" in pattern:
                return ["/dev/serial/by-path/pci-0000:00:14.0-usb-0:1:1.0-port0"]
            return []
            
        mock_glob.side_effect = mock_glob_fn
        
        ctx = discover_mcu_hardware(interactive=False)
        self.assertEqual(ctx["mcu_path"], "/dev/serial/by-path/pci-0000:00:14.0-usb-0:1:1.0-port0")
        self.assertEqual(ctx["hint"], "usb")

    @patch("glob.glob")
    @patch("core.deployer.os.path.isfile", return_value=True)
    @patch("builtins.open")
    def test_discover_mcu_printer_cfg_scrape(self, mock_open, mock_isfile, mock_glob):
        """Verify printer.cfg scraping works as a final fallback if serial devices are missing."""
        from firmware.detector import discover_mcu_hardware
        
        # All device nodes return empty
        mock_glob.return_value = []
        
        # Mock file content read returning [mcu] serial path
        mock_file = MagicMock()
        mock_file.read.return_value = "[mcu]\nserial: /dev/ttyACM9\npin_map: stm32\n"
        mock_open.return_value.__enter__.return_value = mock_file
        
        ctx = discover_mcu_hardware(interactive=False)
        self.assertEqual(ctx["mcu_path"], "/dev/ttyACM9")


class TestDriverSelectionSafety(unittest.TestCase):

    @patch("core.wizard.steps.hardware._get_parsed")
    @patch("core.wizard.steps.hardware.numbered_select")
    def test_integrated_driver_warning_generation(self, mock_select, mock_get_parsed):
        """Verify integrated boards emit warning suffixes on non-matching stepper choices."""
        from core.wizard.steps.hardware import _step_driver_type
        
        mock_get_parsed.return_value = {}
        # Integrated board TMC2209 info
        with patch("core.wizard.steps.hardware.detect_driver_info", return_value={
            "driver_type": "TMC2209",
            "integrated": True,
            "is_socketed": False,
            "driver_mode": "UART"
        }):
            mock_select.return_value = "TMC2209"
            
            # Beginner mode to force recommendation formatting
            with patch("core.translations.get_mode", return_value="Beginner"):
                _step_driver_type({"board": "generic-skr.cfg"})
                
                # Check choices passed to questionary
                choices = mock_select.call_args[1]["choices"]
                names = [c.title if hasattr(c, 'title') else c.get('name', '') for c in choices]
                
                # Recommended matching choice TMC2209 should have recommended flag
                self.assertTrue(any("TMC2209" in n and "Recommended" in n for n in names))
                # Non-matching standard driver should show Warning/Not Recommended
                self.assertTrue(any("None (Standard)" in n and "Not Recommended" in n for n in names))


class TestBackupRollbackIntegration(unittest.TestCase):

    def test_multi_mcu_pin_ownership_validation(self):
        """Verify pin collision detection with MCU prefix stripping.

        Because KACE strips MCU prefixes before collision checks, pins on ANY
        MCU (toolhead:, mcu:, z:, etc.) that share the same physical identifier
        are detected as collisions.  The full rule set is:

        - gpio5 vs gpio5           -> collision (same bare pin)
        - toolhead:gpio5 vs gpio5  -> collision (prefix stripped -> same pin)
        - gpio5 vs toolhead:gpio5  -> collision (prefix stripped -> same pin)
        - mcu:PB1 vs PB1           -> collision
        - z:P1.27 vs P1.27         -> collision
        """
        from core.wizard.steps.sensors import make_pin_validator_with_collision_check

        # ── RP2040 gpio collision tests ────────────────────────────
        user_data_rp = {
            "board": "custom",
            "printer_profile": "custom",
            "profile_loaded": True,
            "raw_config": "[stepper_x]\nstep_pin: gpio5\n",
            "mcu_type": "rp2040"
        }
        validator_rp = make_pin_validator_with_collision_check(user_data_rp)

        # gpio5 conflicts with gpio5 in stepper_x
        self.assertNotEqual(validator_rp("gpio5"), True)

        # toolhead:gpio5 -> stripped to GPIO5 -> collides with gpio5 in stepper_x
        self.assertNotEqual(validator_rp("toolhead:gpio5"), True,
                            "toolhead:gpio5 should collide with gpio5")

        # modifier variants all collapse to GPIO5 -> collision
        self.assertNotEqual(validator_rp("toolhead:!gpio5"), True)
        self.assertNotEqual(validator_rp("!toolhead:gpio5"), True)
        self.assertNotEqual(validator_rp("^toolhead:gpio5"), True)

        # gpio10 is unused -> no collision
        self.assertEqual(validator_rp("gpio10"), True)

        # ── STM32 PB1 collision tests ──────────────────────────────
        user_data_stm = {
            "board": "custom",
            "printer_profile": "custom",
            "profile_loaded": True,
            "raw_config": "[heater_bed]\nheater_pin: PB1\n",
            "mcu_type": "stm32f103"
        }
        validator_stm = make_pin_validator_with_collision_check(user_data_stm)

        # Direct bare pin collision
        self.assertNotEqual(validator_stm("PB1"), True)

        # mcu:PB1 -> stripped to PB1 -> collides
        self.assertNotEqual(validator_stm("mcu:PB1"), True,
                            "mcu:PB1 should collide with PB1")

        # PB2 is unused -> no collision
        self.assertEqual(validator_stm("PB2"), True)

        # ── LPC176x P1.27 collision tests ─────────────────────────
        user_data_lpc = {
            "board": "custom",
            "printer_profile": "custom",
            "profile_loaded": True,
            "raw_config": "[fan]\npin: P1.27\n",
            "mcu_type": "lpc1768"
        }
        validator_lpc = make_pin_validator_with_collision_check(user_data_lpc)

        # Bare pin collision
        self.assertNotEqual(validator_lpc("P1.27"), True)

        # z:P1.27 -> stripped to P1.27 -> collides
        self.assertNotEqual(validator_lpc("z:P1.27"), True,
                            "z:P1.27 should collide with P1.27")

        # P1.28 is unused -> no collision
        self.assertEqual(validator_lpc("P1.28"), True)


    @patch("time.sleep")
    @patch("core.deployer._require_paramiko")
    @patch("core.deployer.os.path.isfile", return_value=True)
    @patch("core.deployer.os.path.exists", return_value=False)
    @patch("core.moonraker.check_moonraker", return_value=(False, "unreachable"))
    @patch("core.menu.numbered_select", return_value="service")
    @patch("builtins.print")
    def _legacy_sudo_non_interactive_fallback(
        self, mock_print, mock_select, mock_check_mr, mock_exists, mock_isfile, mock_paramiko, mock_sleep
    ):
        """Verify that SSH restart and validation calls use sudo -n with fallbacks."""
        from core.deployer import deploy_config
        
        mock_p = MagicMock()
        mock_client = MagicMock()
        mock_sftp = MagicMock()
        mock_client.open_sftp.return_value = mock_sftp
        mock_paramiko.return_value = mock_p
        mock_p.SSHClient.return_value = mock_client
        mock_p.AuthenticationException = Exception
        
        # Mock SSH executes trace
        executed_cmds = []
        def mock_exec_command(cmd, *args, **kwargs):
            executed_cmds.append(cmd)
            stdout = MagicMock()
            stdout.read.return_value = b"active\n" if "is-active" in cmd else b""
            return (MagicMock(), stdout, MagicMock())
        mock_client.exec_command.side_effect = mock_exec_command
        
        user_data = {"host": "pi", "user": "pi", "dest_path": "~/printer_data"}
        deploy_config(user_data)
        
        # Verify that sudo -n was used in restart
        restart_cmd = next((c for c in executed_cmds if "restart" in c), None)
        self.assertIsNotNone(restart_cmd)
        self.assertIn("sudo -n systemctl restart klipper", restart_cmd)
        self.assertIn("|| systemctl --user restart klipper", restart_cmd)

    @patch("time.sleep")
    @patch("core.deployer._require_paramiko")
    @patch("core.deployer.os.path.isfile", return_value=True)
    @patch("core.deployer.os.path.exists", return_value=False)
    @patch("core.moonraker.check_moonraker", return_value=(False, "unreachable"))
    @patch("builtins.print")
    def _legacy_ssh_unconditional_rollback_and_reconnection_on_network_drop(
        self, mock_print, mock_check_mr, mock_exists, mock_isfile, mock_paramiko, mock_sleep
    ):
        """Verify that a network drop during upload triggers reconnection and rollback."""
        from core.deployer import deploy_config
        
        mock_p = MagicMock()
        mock_paramiko.return_value = mock_p
        mock_p.AuthenticationException = Exception
        
        # We need two SSH clients: the original one and the reconnect one
        original_client = MagicMock()
        reconnect_client = MagicMock()
        
        clients = [original_client, reconnect_client]
        def get_client(*args, **kwargs):
            if clients:
                return clients.pop(0)
            return MagicMock()
        mock_p.SSHClient.side_effect = get_client
        
        # Original sftp raises OSError on put (connection drop)
        original_sftp = MagicMock()
        original_sftp.stat.return_value = MagicMock() # stat to check if backup needed succeeds
        original_sftp.put.side_effect = OSError("Connection dropped mid-upload")
        original_client.open_sftp.return_value = original_sftp
        
        # Reconnect sftp works
        reconnect_sftp = MagicMock()
        reconnect_client.open_sftp.return_value = reconnect_sftp
        
        # Simulating sftp.stat inside finally/rollback block:
        # original_sftp.stat raises exception to trigger reconnection
        original_sftp.stat.side_effect = [MagicMock(), OSError("Connection dead")] # 1st for backup check, 2nd for rollback check
        
        user_data = {"host": "pi", "user": "pi", "dest_path": "~/printer_data", "password": "supersecretpassword"}
        deploy_config(user_data)
        
        # Verify that reconnect client connected with the correct host and password
        reconnect_client.connect.assert_called_with(
            "pi",
            username="pi",
            password="supersecretpassword",
            timeout=10
        )
        
        # Verify the rollback renamed files on the reconnected SFTP session
        reconnect_sftp.rename.assert_any_call("/home/pi/printer_data/printer.cfg.bak", "/home/pi/printer_data/printer.cfg")
        
        # Verify rollback messages
        printed = [call[0][0] for call in mock_print.call_args_list]
        self.assertTrue(any("connection is dead" in msg.lower() for msg in printed))
        self.assertTrue(any("reconnection successful" in msg.lower() for msg in printed))
        self.assertTrue(any("rollback complete" in msg.lower() for msg in printed))

    @patch("core.moonraker.check_moonraker")
    @patch("time.sleep")
    @patch("core.menu.simple_input")
    @patch("core.moonraker.verify_remote_file_exists")
    @patch("core.moonraker.list_config_files")
    @patch("core.snapshot.download_printer_cfg")
    @patch("core.snapshot.upload_printer_cfg")
    @patch("core.moonraker.upload_printer_cfg")
    @patch("core.snapshot.restart_firmware")
    @patch("builtins.print")
    @patch("core.deployer.os.path.isfile", return_value=True)
    def _legacy_moonraker_unconditional_rollback_on_upload_failure(
        self, mock_isfile, mock_print, mock_snap_restart, mock_upload,
        mock_snap_upload, mock_download, mock_list_files, mock_exists,
        mock_text, mock_sleep, mock_check_mr
    ):
        """Verify Moonraker deployment triggers rollback on exception/upload failure."""
        from core.deployer import deploy_moonraker

        # Connection succeeds
        mock_check_mr.return_value = (True, "v1.0.0")
        mock_text.side_effect = ["192.168.1.100", "7125", ""]

        # list_config_files returns the files present on the remote
        mock_list_files.return_value = ["printer.cfg"]

        # Backup download succeeds
        mock_exists.side_effect = lambda h, p, f, **kw: True if f == "printer.cfg" else False
        mock_download.return_value = (True, b"backup_cfg_content")

        # Upload throws an exception (simulating network drop / HTTP timeout)
        mock_upload.side_effect = Exception("HTTP POST Timeout")

        # Snapshot restore upload succeeds so rollback can complete
        mock_snap_upload.return_value = (True, "printer.cfg")

        deploy_moonraker({"moonraker_host": "192.168.1.100", "moonraker_port": 7125})

        # The moonraker upload was called once (the failed attempt that raised).
        # The rollback restore goes through core.snapshot.upload_printer_cfg.
        self.assertEqual(mock_upload.call_count, 1)   # 1 failed deploy upload
        self.assertEqual(mock_snap_upload.call_count, 1)  # 1 rollback restore

        # Verify restart_firmware was called during rollback
        mock_snap_restart.assert_called_once_with("192.168.1.100", 7125, api_key="")

        printed = [call[0][0] for call in mock_print.call_args_list]
        self.assertTrue(any("Initiating automatic rollback" in msg for msg in printed))

    def test_public_ssh_deployer_has_no_remote_shell_restart_path(self):
        """Activation is API-driven; config values never enter a shell command."""
        import inspect
        from core.deployer import deploy_config

        source = inspect.getsource(deploy_config)
        self.assertNotIn("exec_command", source)
        self.assertNotIn("systemctl", source)

    def test_transaction_module_has_no_fixed_backup_filename(self):
        """Unique persisted snapshots replace collision-prone remote .bak files."""
        import inspect
        import core.config_transaction as transaction

        source = inspect.getsource(transaction)
        self.assertNotIn('".bak"', source)
        self.assertIn("create_snapshot", source)

if __name__ == '__main__':
    unittest.main()
