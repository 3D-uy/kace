import unittest
import os
import unittest.mock
from unittest.mock import patch, MagicMock
import sys
import subprocess
import builtins

# Stub questionary in sys.modules if missing to prevent @patch('questionary.text') crashing at import time
if 'questionary' not in sys.modules:
    try:
        import questionary
    except ImportError:
        sys.modules['questionary'] = MagicMock()

from core.deployer import _require_paramiko

class TestDeployer(unittest.TestCase):

    def setUp(self):
        self.patches = [
            patch('core.moonraker.check_moonraker', return_value=(False, "unreachable")),
            patch('core.moonraker.upload_printer_cfg', return_value=(False, "unreachable")),
            patch('core.moonraker.restart_firmware', return_value=(False, "unreachable")),
            patch('core.moonraker.restart_klipper_service', return_value=(False, "unreachable")),
            patch('core.moonraker.download_printer_cfg', return_value=(False, b"")),
            patch('core.moonraker.check_klipper_ready', return_value=(False, "unreachable")),
            patch('core.moonraker.verify_remote_file_exists', return_value=False),
            patch('time.sleep'),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_lazy_paramiko_offline_handling(self):
        """S-01: _require_paramiko() must never auto-install; it returns None
        and prints manual install instructions when paramiko is absent."""
        orig_print = builtins.print
        orig_paramiko = sys.modules.get('paramiko')

        sys.modules['paramiko'] = None  # Force ImportError path

        logs = []
        def mock_print(*args, **kwargs):
            logs.append(" ".join(map(str, args)))
        builtins.print = mock_print

        try:
            result = _require_paramiko()
            self.assertIsNone(result, "Should return None when paramiko is not installed")
            # Must tell the user to install manually, not auto-install
            joined = " ".join(logs)
            self.assertIn("requirements-ssh.txt", joined, "Should show manual install command")
            # Must NOT have attempted a pip install
            self.assertNotIn("Downloading and installing", joined)
            self.assertNotIn("installed successfully", joined)
        finally:
            builtins.print = orig_print
            if orig_paramiko is not None:
                sys.modules['paramiko'] = orig_paramiko
            else:
                del sys.modules['paramiko']

    @unittest.mock.patch('core.deployer.platform.system', return_value="Linux")
    @unittest.mock.patch('core.deployer.os.path.exists')
    @unittest.mock.patch('questionary.text')
    @unittest.mock.patch('builtins.print')
    def test_deploy_local_validation_non_windows(self, mock_print, mock_q_text, mock_exists, mock_system):
        """Verify that Windows-style paths are blocked on native non-Windows OS."""
        mock_ask = unittest.mock.MagicMock(side_effect=["E:\\", ""])
        mock_text_instance = unittest.mock.MagicMock()
        mock_text_instance.ask = mock_ask
        mock_q_text.return_value = mock_text_instance
        
        mock_exists.return_value = False
        
        import os
        orig_environ = os.environ.copy()
        if "KACE_DOCKER" in os.environ:
            del os.environ["KACE_DOCKER"]
            
        try:
            from core.deployer import deploy_local
            deploy_local({}, artifact_type="config")
        finally:
            os.environ.clear()
            os.environ.update(orig_environ)
        
        printed_messages = [call[0][0] for call in mock_print.call_args_list]
        self.assertTrue(any("not supported on non-Windows platforms" in msg for msg in printed_messages))

    @unittest.mock.patch('core.deployer.platform.system', return_value="Linux")
    @unittest.mock.patch('core.deployer.os.path.exists')
    @unittest.mock.patch('questionary.text')
    @unittest.mock.patch('builtins.print')
    def test_deploy_local_validation_docker(self, mock_print, mock_q_text, mock_exists, mock_system):
        """Verify that Windows-style paths are blocked and direct users to /workspace inside Docker."""
        mock_ask = unittest.mock.MagicMock(side_effect=["E:\\", ""])
        mock_text_instance = unittest.mock.MagicMock()
        mock_text_instance.ask = mock_ask
        mock_q_text.return_value = mock_text_instance
        
        mock_exists.side_effect = lambda path: True if path == '/.dockerenv' else False
        
        from core.deployer import deploy_local
        deploy_local({}, artifact_type="config")
        
        printed_messages = [call[0][0] for call in mock_print.call_args_list]
        self.assertTrue(any("not accessible inside Docker" in msg for msg in printed_messages))
        self.assertTrue(any("please use /workspace" in msg for msg in printed_messages))

    @patch('core.deployer._require_paramiko')
    @patch('core.deployer.os.path.isfile')
    @patch('builtins.print')
    def test_deploy_config_missing_file(self, mock_print, mock_isfile, mock_paramiko_func):
        """If local printer.cfg is missing, deploy_config aborts."""
        mock_isfile.return_value = False
        mock_paramiko = MagicMock()
        mock_paramiko.AuthenticationException = type('AuthenticationException', (Exception,), {})
        mock_paramiko_func.return_value = mock_paramiko
        
        from core.deployer import deploy_config
        deploy_config({'host': '127.0.0.1', 'user': 'pi', 'dest_path': '~/printer_data'})
        
        printed = [c[0][0] for c in mock_print.call_args_list]
        self.assertTrue(any("Deployment aborted: printer.cfg not found" in msg for msg in printed))

    @patch('core.deployer._require_paramiko')
    @patch('core.deployer.os.path.isfile')
    @patch('builtins.print')
    def test_deploy_config_ssh_exception(self, mock_print, mock_isfile, mock_paramiko_func):
        """Mock SSH connection exception, deploy_config should catch and print."""
        mock_isfile.return_value = True
        mock_paramiko = MagicMock()
        mock_paramiko.AuthenticationException = type('AuthenticationException', (Exception,), {})
        mock_paramiko_func.return_value = mock_paramiko
        
        # Mock SSH Client connect to raise an exception
        mock_client = MagicMock()
        mock_client.connect.side_effect = Exception("Connection timed out")
        mock_paramiko.SSHClient.return_value = mock_client
        
        from core.deployer import deploy_config
        deploy_config({'host': '127.0.0.1', 'user': 'pi', 'dest_path': '~/printer_data'})
        
        printed = [c[0][0] for c in mock_print.call_args_list]
        self.assertTrue(any("Deployment failed: Connection timed out" in msg for msg in printed))

    @patch('core.deployer._require_paramiko')
    @patch('core.deployer.os.path.isfile')
    @patch('core.deployer.os.path.exists')
    @patch('core.menu.numbered_select', return_value='skip')
    @patch('builtins.print')
    def test_deploy_config_sftp_success(self, mock_print, mock_select, mock_exists, mock_isfile, mock_paramiko_func):
        """Test successful config & macros SSH upload."""
        import os
        mock_isfile.return_value = True
        mock_exists.side_effect = lambda path: True if "macros.cfg" in path else False
        
        mock_paramiko = MagicMock()
        mock_paramiko.AuthenticationException = type('AuthenticationException', (Exception,), {})
        mock_paramiko_func.return_value = mock_paramiko
        
        mock_client = MagicMock()
        mock_sftp = MagicMock()
        mock_client.open_sftp.return_value = mock_sftp
        mock_paramiko.SSHClient.return_value = mock_client
        
        from core.deployer import deploy_config
        deploy_config({'host': '127.0.0.1', 'user': 'pi', 'dest_path': '~/printer_data/config/printer.cfg'})
        
        mock_client.connect.assert_called_once_with('127.0.0.1', username='pi', password='')
        mock_sftp.put.assert_any_call(os.path.expanduser('~/kace/printer.cfg'), '/home/pi/printer_data/config/printer.cfg')
        mock_sftp.put.assert_any_call(os.path.expanduser('~/kace/macros.cfg'), '/home/pi/printer_data/config/macros.cfg')

    @patch('shutil.which', return_value="/usr/bin/avrdude")
    @patch('subprocess.run')
    @patch('questionary.text')
    @patch('questionary.confirm')
    @patch('builtins.print')
    def test_deploy_avrdude_success(self, mock_print, mock_confirm, mock_q_text, mock_run, mock_which):
        """Test avrdude flashing executes successfully."""
        mock_text_inst = MagicMock()
        mock_text_inst.ask.return_value = "/dev/ttyUSB0"
        mock_q_text.return_value = mock_text_inst
        
        mock_confirm_inst = MagicMock()
        mock_confirm_inst.ask.return_value = True
        mock_confirm.return_value = mock_confirm_inst
        
        from core.deployer import deploy_avrdude
        deploy_avrdude({'mcu_path': '/dev/ttyUSB0'}, 'klipper.bin', 'atmega2560')
        
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertIn("avrdude", cmd)
        self.assertIn("atmega2560", cmd)
        self.assertIn("/dev/ttyUSB0", cmd)

    @patch('shutil.which', return_value=None)
    @patch('builtins.print')
    def test_deploy_avrdude_missing_binary(self, mock_print, mock_which):
        """If avrdude is missing, it prints error."""
        from core.deployer import deploy_avrdude
        deploy_avrdude({}, 'klipper.bin', 'atmega2560')
        printed = [c[0][0] for c in mock_print.call_args_list]
        self.assertTrue(any("avrdude' is not installed" in msg for msg in printed))

    @patch('questionary.text')
    @patch('questionary.select')
    @patch('core.moonraker.check_moonraker')
    @patch('core.moonraker.upload_printer_cfg')
    @patch('core.moonraker.restart_firmware')
    @patch('builtins.print')
    def test_deploy_moonraker_success(self, mock_print, mock_restart, mock_upload, mock_check, mock_select, mock_text):
        """Test successful moonraker deploy & restart firmware."""
        # Mock connection prompts
        mock_text.side_effect = [
            MagicMock(ask=lambda: "192.168.1.50"), # host
            MagicMock(ask=lambda: "7125"),          # port
            MagicMock(ask=lambda: ""),              # api key
        ]
        mock_check.return_value = (True, "v0.1.0")
        mock_upload.return_value = (True, "Success")
        mock_select.return_value = MagicMock(ask=lambda: "firmware")
        mock_restart.return_value = (True, "Restarted")
        
        from core.deployer import deploy_moonraker
        deploy_moonraker({})
        
        mock_check.assert_called_once_with("192.168.1.50", 7125, api_key="")
        mock_upload.assert_called_once_with("192.168.1.50", 7125, mock_upload.call_args[0][2], api_key="")
        mock_restart.assert_called_once_with("192.168.1.50", 7125, api_key="")

    @patch('questionary.text')
    @patch('questionary.confirm')
    @patch('questionary.select')
    @patch('core.moonraker.check_moonraker')
    @patch('builtins.print')
    def test_deploy_moonraker_warning_http_accepted(self, mock_print, mock_check, mock_select, mock_confirm, mock_text):
        """S-04: http:// + API key must be a hard block — no confirmation prompt,
        no deployment proceeds, check_moonraker is never reached."""
        mock_text.side_effect = [
            MagicMock(ask=lambda: "http://192.168.1.50"), # host starts with http://
            MagicMock(ask=lambda: "7125"),          # port
            MagicMock(ask=lambda: "secret_key"),    # api key
        ]

        from core.deployer import deploy_moonraker
        deploy_moonraker({})

        # Hard block: must not proceed to check reachability
        mock_check.assert_not_called()
        # Must print a clear security error
        printed = " ".join(str(c[0][0]) for c in mock_print.call_args_list if c[0])
        self.assertTrue(
            "plain HTTP" in printed or "http_warning" in printed or "plain" in printed.lower(),
            f"Expected plain-HTTP security message. Got: {printed[:300]}"
        )

    @patch('questionary.text')
    @patch('questionary.confirm')
    @patch('core.moonraker.check_moonraker')
    @patch('builtins.print')
    def test_deploy_moonraker_warning_http_rejected(self, mock_print, mock_check, mock_confirm, mock_text):
        """Test http warning triggered and rejected by user, aborting deploy."""
        mock_text.side_effect = [
            MagicMock(ask=lambda: "http://192.168.1.50"),  # host (implicitly http://)
            MagicMock(ask=lambda: "7125"),          # port
            MagicMock(ask=lambda: "secret_key"),    # api key
        ]
        mock_confirm.side_effect = [
            MagicMock(ask=lambda: False),           # Warning confirm: No
        ]
        
        from core.deployer import deploy_moonraker
        deploy_moonraker({})
        
        mock_check.assert_not_called()
        printed = [c[0][0] for c in mock_print.call_args_list]
        self.assertTrue(any("cancelled for security reasons" in msg or "cancelado" in msg or "cancelado" in msg for msg in printed))

    @patch('questionary.text')
    @patch('core.moonraker.check_moonraker')
    @patch('questionary.confirm')
    @patch('core.deployer.deploy_config')
    @patch('builtins.print')
    def test_deploy_moonraker_unreachable_ssh_fallback(self, mock_print, mock_deploy_ssh, mock_confirm, mock_check, mock_text):
        """If Moonraker is unreachable, check SSH fallback option."""
        mock_text.side_effect = [
            MagicMock(ask=lambda: "192.168.1.50"), # host
            MagicMock(ask=lambda: "7125"),          # port
            MagicMock(ask=lambda: ""),              # api key
            MagicMock(ask=lambda: "pi"),            # SSH user
            MagicMock(ask=lambda: "/home/pi"),      # SSH dest_path
        ]
        mock_check.return_value = (False, "Timeout connection")
        mock_confirm.return_value = MagicMock(ask=lambda: True)
        
        with patch('questionary.password', return_value=MagicMock(ask=lambda: "raspberry")):
            from core.deployer import deploy_moonraker
            deploy_moonraker({})
        
        mock_deploy_ssh.assert_called_once()
        # Verify SSH user context was set
        user_data = mock_deploy_ssh.call_args[0][0]
        self.assertEqual(user_data['host'], '192.168.1.50')
        self.assertEqual(user_data['user'], 'pi')
        self.assertEqual(user_data['dest_path'], '/home/pi')

    @patch('questionary.text')
    @patch('core.deployer.os.path.isdir', return_value=True)
    @patch('core.deployer.os.path.exists', return_value=True)
    @patch('shutil.copy2')
    @patch('builtins.print')
    def test_deploy_usb_success(self, mock_print, mock_copy, mock_exists, mock_isdir, mock_text):
        """Test successful copy of printer.cfg and macros.cfg to USB."""
        import os
        mock_text.return_value = MagicMock(ask=lambda: "/media/usb")
        
        from core.deployer import deploy_usb
        deploy_usb({}, artifact_type="config")
        
        mock_copy.assert_any_call(os.path.expanduser('~/kace/printer.cfg'), os.path.join('/media/usb', 'printer.cfg'))
        mock_copy.assert_any_call(os.path.expanduser('~/kace/macros.cfg'), os.path.join('/media/usb', 'macros.cfg'))

    @patch('questionary.text')
    @patch('core.deployer.os.path.isdir', return_value=False)
    @patch('builtins.print')
    def test_deploy_usb_invalid_path(self, mock_print, mock_isdir, mock_text):
        """If USB directory path is invalid, deployment fails."""
        mock_text.return_value = MagicMock(ask=lambda: "/media/nonexistent")
        
        from core.deployer import deploy_usb
        deploy_usb({}, artifact_type="config")
        
        printed = [c[0][0] for c in mock_print.call_args_list]
        self.assertTrue(any("Invalid path or directory does not exist" in msg for msg in printed))


class TestDeployMoonrakerWorkflow(unittest.TestCase):

    def setUp(self):
        self.patches = [
            patch('core.moonraker.check_moonraker', return_value=(False, "unreachable")),
            patch('core.moonraker.upload_printer_cfg', return_value=(False, "unreachable")),
            patch('core.moonraker.restart_firmware', return_value=(False, "unreachable")),
            patch('core.moonraker.restart_klipper_service', return_value=(False, "unreachable")),
            patch('core.moonraker.download_printer_cfg', return_value=(False, b"")),
            patch('core.moonraker.check_klipper_ready', return_value=(False, "unreachable")),
            patch('core.moonraker.verify_remote_file_exists', return_value=False),
            patch('time.sleep'),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    @patch('questionary.text')
    @patch('core.deployer.os.path.exists')
    @patch('core.moonraker.check_moonraker')
    @patch('core.moonraker.upload_printer_cfg')
    @patch('questionary.select')
    @patch('core.moonraker.restart_firmware')
    @patch('builtins.print')
    def test_macros_uploaded_when_present(self, mock_print, mock_restart, mock_select, mock_upload, mock_check, mock_exists, mock_text):
        """When macros.cfg exists locally, exactly two upload_printer_cfg calls must occur."""
        mock_text.side_effect = [
            MagicMock(ask=lambda: "192.168.1.50"), # host
            MagicMock(ask=lambda: "7125"),          # port
            MagicMock(ask=lambda: ""),              # api key
        ]
        mock_check.return_value = (True, "v0.1.0")
        mock_upload.return_value = (True, "Success")
        mock_exists.side_effect = lambda path: True if "macros.cfg" in path or "printer.cfg" in path else False
        mock_select.return_value = MagicMock(ask=lambda: "skip")
        
        from core.deployer import deploy_moonraker
        deploy_moonraker({})
        
        # Check that we had two upload calls: printer.cfg and macros.cfg
        self.assertEqual(mock_upload.call_count, 2)
        # Verify first call was for printer.cfg, second was for macros.cfg
        calls = mock_upload.call_args_list
        self.assertIn("printer.cfg", calls[0][0][2])
        self.assertIn("macros.cfg", calls[1][0][2])

    @patch('questionary.text')
    @patch('core.deployer.os.path.exists')
    @patch('core.moonraker.check_moonraker')
    @patch('core.moonraker.upload_printer_cfg')
    @patch('questionary.select')
    @patch('builtins.print')
    def test_macros_not_uploaded_when_absent(self, mock_print, mock_select, mock_upload, mock_check, mock_exists, mock_text):
        """When macros.cfg does not exist locally, only printer.cfg must be uploaded."""
        mock_text.side_effect = [
            MagicMock(ask=lambda: "192.168.1.50"), # host
            MagicMock(ask=lambda: "7125"),          # port
            MagicMock(ask=lambda: ""),              # api key
        ]
        mock_check.return_value = (True, "v0.1.0")
        mock_upload.return_value = (True, "Success")
        # macros.cfg does not exist
        mock_exists.side_effect = lambda path: False if "macros.cfg" in path else True
        mock_select.return_value = MagicMock(ask=lambda: "skip")
        
        from core.deployer import deploy_moonraker
        deploy_moonraker({})
        
        self.assertEqual(mock_upload.call_count, 1)
        self.assertIn("printer.cfg", mock_upload.call_args[0][2])

    @patch('questionary.text')
    @patch('core.deployer.os.path.exists')
    @patch('core.moonraker.check_moonraker')
    @patch('core.moonraker.upload_printer_cfg')
    @patch('questionary.select')
    @patch('builtins.print')
    def test_macros_upload_failure_is_non_fatal(self, mock_print, mock_select, mock_upload, mock_check, mock_exists, mock_text):
        """If macros.cfg upload fails, the deployment continues and does not abort early."""
        mock_text.side_effect = [
            MagicMock(ask=lambda: "192.168.1.50"), # host
            MagicMock(ask=lambda: "7125"),          # port
            MagicMock(ask=lambda: ""),              # api key
        ]
        mock_check.return_value = (True, "v0.1.0")
        # printer.cfg succeeds, macros.cfg fails
        mock_upload.side_effect = [(True, "Success"), (False, "Network error")]
        mock_exists.side_effect = lambda path: True if "macros.cfg" in path or "printer.cfg" in path else False
        mock_select.return_value = MagicMock(ask=lambda: "skip")
        
        from core.deployer import deploy_moonraker
        deploy_moonraker({})
        
        # Should have attempted both uploads
        self.assertEqual(mock_upload.call_count, 2)
        # Should have called the select prompt for restart
        mock_select.assert_called_once()
        # Verify failure warning was printed
        printed = [c[0][0] for c in mock_print.call_args_list]
        self.assertTrue(any("Failed to upload macros.cfg" in msg for msg in printed))

    @patch('questionary.text')
    @patch('core.moonraker.check_moonraker')
    @patch('core.moonraker.upload_printer_cfg')
    @patch('questionary.select')
    @patch('builtins.print')
    def test_printer_cfg_upload_failure_returns_early(self, mock_print, mock_select, mock_upload, mock_check, mock_text):
        """If printer.cfg upload fails, deployment aborts early and does not prompt for restart."""
        mock_text.side_effect = [
            MagicMock(ask=lambda: "192.168.1.50"), # host
            MagicMock(ask=lambda: "7125"),          # port
            MagicMock(ask=lambda: ""),              # api key
        ]
        mock_check.return_value = (True, "v0.1.0")
        mock_upload.return_value = (False, "Connection reset")
        
        from core.deployer import deploy_moonraker
        deploy_moonraker({})
        
        self.assertEqual(mock_upload.call_count, 1)
        mock_select.assert_not_called()
        printed = [c[0][0] for c in mock_print.call_args_list]
        self.assertTrue(any("Connection reset" in msg for msg in printed))

    @patch('questionary.text')
    @patch('core.moonraker.check_moonraker')
    @patch('core.moonraker.upload_printer_cfg')
    @patch('questionary.select')
    @patch('core.moonraker.restart_klipper_service')
    @patch('core.moonraker.restart_firmware')
    @patch('builtins.print')
    def test_restart_service_branch(self, mock_print, mock_restart_fw, mock_restart_service, mock_select, mock_upload, mock_check, mock_text):
        """If restart_choice is 'service', restart_klipper_service must be invoked, not restart_firmware."""
        mock_text.side_effect = [
            MagicMock(ask=lambda: "192.168.1.50"), # host
            MagicMock(ask=lambda: "7125"),          # port
            MagicMock(ask=lambda: ""),              # api key
        ]
        mock_check.return_value = (True, "v0.1.0")
        mock_upload.return_value = (True, "Success")
        mock_select.return_value = MagicMock(ask=lambda: "service")
        mock_restart_service.return_value = (True, "Service Restarted")
        
        from core.deployer import deploy_moonraker
        deploy_moonraker({})
        
        mock_restart_service.assert_called_once_with("192.168.1.50", 7125, api_key="")
        mock_restart_fw.assert_not_called()

    @patch('questionary.text')
    @patch('core.moonraker.check_moonraker')
    @patch('core.moonraker.upload_printer_cfg')
    @patch('questionary.select')
    @patch('core.moonraker.restart_klipper_service')
    @patch('core.moonraker.restart_firmware')
    @patch('builtins.print')
    def test_restart_skip_branch(self, mock_print, mock_restart_fw, mock_restart_service, mock_select, mock_upload, mock_check, mock_text):
        """If restart_choice is 'skip', neither restart call must be invoked."""
        mock_text.side_effect = [
            MagicMock(ask=lambda: "192.168.1.50"), # host
            MagicMock(ask=lambda: "7125"),          # port
            MagicMock(ask=lambda: ""),              # api key
        ]
        mock_check.return_value = (True, "v0.1.0")
        mock_upload.return_value = (True, "Success")
        mock_select.return_value = MagicMock(ask=lambda: "skip")
        
        from core.deployer import deploy_moonraker
        deploy_moonraker({})
        
        mock_restart_service.assert_not_called()
        mock_restart_fw.assert_not_called()

    @patch('questionary.text')
    @patch('core.moonraker.check_moonraker')
    @patch('core.moonraker.upload_printer_cfg')
    @patch('questionary.select')
    @patch('core.moonraker.restart_firmware')
    @patch('builtins.print')
    def test_restart_firmware_failure_prints_error(self, mock_print, mock_restart_fw, mock_select, mock_upload, mock_check, mock_text):
        """If firmware restart fails, it prints the error diagnostic."""
        mock_text.side_effect = [
            MagicMock(ask=lambda: "192.168.1.50"), # host
            MagicMock(ask=lambda: "7125"),          # port
            MagicMock(ask=lambda: ""),              # api key
        ]
        mock_check.return_value = (True, "v0.1.0")
        mock_upload.return_value = (True, "Success")
        mock_select.return_value = MagicMock(ask=lambda: "firmware")
        mock_restart_fw.return_value = (False, "Timeout communicating with MCU")
        
        from core.deployer import deploy_moonraker
        deploy_moonraker({})
        
        printed = [c[0][0] for c in mock_print.call_args_list]
        self.assertTrue(any("Timeout communicating with MCU" in msg for msg in printed))

    @patch('questionary.text')
    @patch('core.moonraker.check_moonraker')
    @patch('core.moonraker.upload_printer_cfg')
    @patch('questionary.select')
    @patch('core.moonraker.restart_klipper_service')
    @patch('builtins.print')
    def test_restart_service_failure_prints_error(self, mock_print, mock_restart_service, mock_select, mock_upload, mock_check, mock_text):
        """If service restart fails, it prints the error diagnostic."""
        mock_text.side_effect = [
            MagicMock(ask=lambda: "192.168.1.50"), # host
            MagicMock(ask=lambda: "7125"),          # port
            MagicMock(ask=lambda: ""),              # api key
        ]
        mock_check.return_value = (True, "v0.1.0")
        mock_upload.return_value = (True, "Success")
        mock_select.return_value = MagicMock(ask=lambda: "service")
        mock_restart_service.return_value = (False, "Service restart failed")
        
        from core.deployer import deploy_moonraker
        deploy_moonraker({})
        
        printed = [c[0][0] for c in mock_print.call_args_list]
        self.assertTrue(any("Service restart failed" in msg for msg in printed))

    @patch('questionary.text')
    @patch('core.moonraker.check_moonraker')
    @patch('builtins.print')
    def test_host_prompt_empty_cancels(self, mock_print, mock_check, mock_text):
        """If the user enters an empty host, the function returns immediately and does not connect."""
        mock_text.return_value = MagicMock(ask=lambda: "")
        
        from core.deployer import deploy_moonraker
        deploy_moonraker({})
        
        mock_check.assert_not_called()
        printed = [c[0][0] for c in mock_print.call_args_list]
        self.assertTrue(any("deployment cancelled" in msg.lower() for msg in printed))


class TestDeployUSBFirmware(unittest.TestCase):

    @patch('questionary.text')
    @patch('core.deployer.os.path.isdir', return_value=True)
    @patch('core.deployer.os.path.exists')
    @patch('shutil.copy2')
    @patch('builtins.print')
    def test_firmware_explicit_path_copied(self, mock_print, mock_copy, mock_exists, mock_isdir, mock_text):
        """If firmware_path is in user_data and file exists, it is copied directly."""
        mock_text.return_value = MagicMock(ask=lambda: "/media/usb")
        mock_exists.side_effect = lambda p: True if "my_fw.bin" in p else False
        
        from core.deployer import deploy_usb
        deploy_usb({"firmware_path": "~/my_fw.bin"}, artifact_type="firmware")
        
        mock_copy.assert_called_once_with(
            os.path.expanduser("~/my_fw.bin"),
            os.path.join("/media/usb", "my_fw.bin")
        )
        printed = [c[0][0] for c in mock_print.call_args_list]
        self.assertTrue(any("USB Deployment Successful" in msg for msg in printed))

    @patch('questionary.text')
    @patch('core.deployer.os.path.isdir', return_value=True)
    @patch('core.deployer.os.path.exists')
    @patch('shutil.copy2')
    @patch('builtins.print')
    def test_firmware_fallback_bin(self, mock_print, mock_copy, mock_exists, mock_isdir, mock_text):
        """If no firmware_path in user_data, falls back to scanning and copies klipper.bin if present."""
        mock_text.return_value = MagicMock(ask=lambda: "/media/usb")
        mock_exists.side_effect = lambda p: True if "klipper.bin" in p else False
        
        from core.deployer import deploy_usb
        deploy_usb({}, artifact_type="firmware")
        
        mock_copy.assert_called_once_with(
            os.path.expanduser("~/kace/klipper.bin"),
            os.path.join("/media/usb", "klipper.bin")
        )

    @patch('questionary.text')
    @patch('core.deployer.os.path.isdir', return_value=True)
    @patch('core.deployer.os.path.exists')
    @patch('shutil.copy2')
    @patch('builtins.print')
    def test_firmware_fallback_uf2_when_no_bin(self, mock_print, mock_copy, mock_exists, mock_isdir, mock_text):
        """If no klipper.bin, copies klipper.uf2 if present."""
        mock_text.return_value = MagicMock(ask=lambda: "/media/usb")
        mock_exists.side_effect = lambda p: True if "klipper.uf2" in p else False
        
        from core.deployer import deploy_usb
        deploy_usb({}, artifact_type="firmware")
        
        mock_copy.assert_called_once_with(
            os.path.expanduser("~/kace/klipper.uf2"),
            os.path.join("/media/usb", "klipper.uf2")
        )

    @patch('questionary.text')
    @patch('core.deployer.os.path.isdir', return_value=True)
    @patch('core.deployer.os.path.exists')
    @patch('shutil.copy2')
    @patch('builtins.print')
    def test_firmware_fallback_hex_when_no_bin_or_uf2(self, mock_print, mock_copy, mock_exists, mock_isdir, mock_text):
        """If no klipper.bin or klipper.uf2, copies klipper.elf.hex if present."""
        mock_text.return_value = MagicMock(ask=lambda: "/media/usb")
        mock_exists.side_effect = lambda p: True if "klipper.elf.hex" in p else False
        
        from core.deployer import deploy_usb
        deploy_usb({}, artifact_type="firmware")
        
        mock_copy.assert_called_once_with(
            os.path.expanduser("~/kace/klipper.elf.hex"),
            os.path.join("/media/usb", "klipper.elf.hex")
        )

    @patch('questionary.text')
    @patch('core.deployer.os.path.isdir', return_value=True)
    @patch('core.deployer.os.path.exists')
    @patch('shutil.copy2')
    @patch('builtins.print')
    def test_all_matching_firmware_copied_no_break_behaviour(self, mock_print, mock_copy, mock_exists, mock_isdir, mock_text):
        """
        [DOCUMENTATION / BEHAVIOR CHECK]
        Verify the current fallback scan logic: it loops through all extensions
        and copies all files that exist (does not break after finding the first match).
        This is recorded here to document this current behavior which might be unintended.
        """
        mock_text.return_value = MagicMock(ask=lambda: "/media/usb")
        mock_exists.side_effect = lambda p: True if any(ext in p for ext in ["klipper.bin", "klipper.uf2", "klipper.elf.hex"]) else False
        
        from core.deployer import deploy_usb
        deploy_usb({}, artifact_type="firmware")
        
        self.assertEqual(mock_copy.call_count, 3)
        copied_dest_files = [call[0][1] for call in mock_copy.call_args_list]
        self.assertIn(os.path.join("/media/usb", "klipper.bin"), copied_dest_files)
        self.assertIn(os.path.join("/media/usb", "klipper.uf2"), copied_dest_files)
        self.assertIn(os.path.join("/media/usb", "klipper.elf.hex"), copied_dest_files)

    @patch('questionary.text')
    @patch('core.deployer.os.path.isdir', return_value=True)
    @patch('core.deployer.os.path.exists')
    @patch('shutil.copy2')
    @patch('builtins.print')
    def test_artifact_type_all_copies_config_and_firmware(self, mock_print, mock_copy, mock_exists, mock_isdir, mock_text):
        """When artifact_type is 'all', copies both configs (printer.cfg, macros.cfg) and firmware."""
        mock_text.return_value = MagicMock(ask=lambda: "/media/usb")
        mock_exists.side_effect = lambda p: True if any(f in p for f in ["printer.cfg", "macros.cfg", "klipper.bin"]) else False
        
        from core.deployer import deploy_usb
        deploy_usb({}, artifact_type="all")
        
        self.assertEqual(mock_copy.call_count, 3)
        copied_dest_files = [call[0][1] for call in mock_copy.call_args_list]
        self.assertIn(os.path.join("/media/usb", "printer.cfg"), copied_dest_files)
        self.assertIn(os.path.join("/media/usb", "macros.cfg"), copied_dest_files)
        self.assertIn(os.path.join("/media/usb", "klipper.bin"), copied_dest_files)

    @patch('questionary.text')
    @patch('core.deployer.os.path.isdir', return_value=True)
    @patch('core.deployer.os.path.exists', return_value=False)
    @patch('shutil.copy2')
    @patch('builtins.print')
    def test_no_artifacts_found_prints_warning(self, mock_print, mock_copy, mock_exists, mock_isdir, mock_text):
        """If no artifacts exist to copy, copy is not called and a warning is printed."""
        mock_text.return_value = MagicMock(ask=lambda: "/media/usb")
        
        from core.deployer import deploy_usb
        deploy_usb({}, artifact_type="all")
        
        mock_copy.assert_not_called()
        printed = [c[0][0] for c in mock_print.call_args_list]
        self.assertTrue(any("No requested artifacts found to copy" in msg for msg in printed))

    @patch('questionary.text')
    @patch('core.deployer.os.path.isdir', return_value=True)
    @patch('core.deployer.os.path.exists', return_value=True)
    @patch('shutil.copy2')
    @patch('builtins.print')
    def test_permission_error_caught(self, mock_print, mock_copy, mock_exists, mock_isdir, mock_text):
        """If shutil.copy2 raises PermissionError, it is caught and printed cleanly."""
        mock_text.return_value = MagicMock(ask=lambda: "/media/usb")
        mock_copy.side_effect = PermissionError("Permission denied")
        
        from core.deployer import deploy_usb
        deploy_usb({}, artifact_type="config")
        
        printed = [c[0][0] for c in mock_print.call_args_list]
        self.assertTrue(any("Deployment failed" in msg and "Permission denied" in msg for msg in printed))

    @patch('questionary.text')
    @patch('shutil.copy2')
    def test_empty_path_returns_without_copy(self, mock_copy, mock_text):
        """If the user submits an empty destination path, it returns without attempting copy."""
        mock_text.return_value = MagicMock(ask=lambda: "")
        
        from core.deployer import deploy_usb
        deploy_usb({}, artifact_type="config")
        
        mock_copy.assert_not_called()


class TestDeployLocalFirmware(unittest.TestCase):

    @patch('questionary.text')
    @patch('core.deployer.os.path.exists', return_value=False)
    @patch('core.deployer.os.makedirs')
    @patch('shutil.copy2')
    @patch('builtins.print')
    def test_creates_directory_when_missing(self, mock_print, mock_copy, mock_makedirs, mock_exists, mock_text):
        """If the local destination directory does not exist, os.makedirs is called to create it."""
        mock_text.return_value = MagicMock(ask=lambda: "/tmp/nonexistent")
        
        from core.deployer import deploy_local
        deploy_local({}, artifact_type="config")
        
        mock_makedirs.assert_called_once_with("/tmp/nonexistent", exist_ok=True)

    @patch('questionary.text')
    @patch('core.deployer.os.path.exists', return_value=True)
    @patch('core.deployer.os.makedirs')
    @patch('shutil.copy2')
    @patch('builtins.print')
    def test_no_makedirs_when_directory_exists(self, mock_print, mock_copy, mock_makedirs, mock_exists, mock_text):
        """If the local destination directory already exists, os.makedirs is NOT called."""
        mock_text.return_value = MagicMock(ask=lambda: "/tmp/exists")
        
        from core.deployer import deploy_local
        deploy_local({}, artifact_type="config")
        
        mock_makedirs.assert_not_called()

    @patch('questionary.text')
    @patch('core.deployer.os.path.exists')
    @patch('shutil.copy2')
    @patch('builtins.print')
    def test_firmware_fallback_scan(self, mock_print, mock_copy, mock_exists, mock_text):
        """Checks fallback scanning logic for local directory copies."""
        mock_text.return_value = MagicMock(ask=lambda: "/tmp/dest")
        mock_exists.side_effect = lambda p: True if "klipper.uf2" in p or p == "/tmp/dest" else False
        
        from core.deployer import deploy_local
        deploy_local({}, artifact_type="firmware")
        
        mock_copy.assert_called_once_with(
            os.path.expanduser("~/kace/klipper.uf2"),
            os.path.join("/tmp/dest", "klipper.uf2")
        )

    @patch('questionary.text')
    @patch('core.deployer.os.path.exists', return_value=True)
    @patch('shutil.copy2')
    @patch('builtins.print')
    def test_success_message_contains_dest_path(self, mock_print, mock_copy, mock_exists, mock_text):
        """On successful copy, the print statement must state the exact destination path."""
        mock_text.return_value = MagicMock(ask=lambda: "/tmp/dest")
        
        from core.deployer import deploy_local
        deploy_local({}, artifact_type="config")
        
        printed = [c[0][0] for c in mock_print.call_args_list]
        self.assertTrue(any("Successfully saved to /tmp/dest" in msg for msg in printed))

    @patch('questionary.text')
    @patch('core.deployer.os.path.exists', return_value=True)
    @patch('shutil.copy2')
    @patch('builtins.print')
    def test_permission_error_caught_local(self, mock_print, mock_copy, mock_exists, mock_text):
        """If copying raises PermissionError, it is caught and printed as 'Save failed'."""
        mock_text.return_value = MagicMock(ask=lambda: "/tmp/dest")
        mock_copy.side_effect = PermissionError("Write access denied")
        
        from core.deployer import deploy_local
        deploy_local({}, artifact_type="config")
        
        printed = [c[0][0] for c in mock_print.call_args_list]
        self.assertTrue(any("Save failed" in msg and "Write access denied" in msg for msg in printed))


    @patch('questionary.text')
    @patch('core.deployer.os.path.exists', return_value=True)
    @patch('shutil.copy2')
    @patch('builtins.print')
    def test_tilde_expanded_in_dest_path(self, mock_print, mock_copy, mock_exists, mock_text):
        """Any tilde (~) prefix in the local destination path must be expanded via os.path.expanduser."""
        mock_text.return_value = MagicMock(ask=lambda: "~/my_folder")
        
        from core.deployer import deploy_local
        deploy_local({}, artifact_type="config")
        
        expanded = os.path.expanduser("~/my_folder")
        mock_copy.assert_any_call(
            os.path.expanduser("~/kace/printer.cfg"),
            os.path.join(expanded, "printer.cfg")
        )


# ── T-01: _require_paramiko() additional failure path coverage ────────────────

class TestRequireParamikoFailurePaths(unittest.TestCase):
    """T-01: Ensure _require_paramiko() handles all ImportError variants correctly.

    The baseline case (paramiko absent → None + manual install message) is
    already covered by test_lazy_paramiko_offline_handling in TestDeployer.
    These tests cover the remaining edge cases.
    """

    def test_require_paramiko_module_not_found_error(self):
        """T-01a: ModuleNotFoundError (C-extension missing) treated same as ImportError.

        When 'cryptography' or another C extension that paramiko depends on is
        absent, Python raises ModuleNotFoundError (a subclass of ImportError).
        _require_paramiko() must return None and print manual install instructions.
        """
        orig_print = builtins.print
        orig_paramiko = sys.modules.get('paramiko', 'ABSENT')

        # Force a ModuleNotFoundError by setting the entry to None
        sys.modules['paramiko'] = None

        logs = []
        builtins.print = lambda *a, **kw: logs.append(" ".join(map(str, a)))

        try:
            result = _require_paramiko()
            self.assertIsNone(result, "_require_paramiko() must return None when paramiko is absent")
            joined = " ".join(logs)
            self.assertIn("requirements-ssh.txt", joined,
                          "Manual install instructions must reference requirements-ssh.txt")
            self.assertNotIn("Downloading", joined,
                             "_require_paramiko() must never auto-install packages")
        finally:
            builtins.print = orig_print
            if orig_paramiko == 'ABSENT':
                del sys.modules['paramiko']
            else:
                sys.modules['paramiko'] = orig_paramiko

    @patch('core.deployer._require_paramiko', return_value=None)
    @patch('builtins.print')
    def test_deploy_config_returns_gracefully_when_no_paramiko(self, mock_print, mock_req_p):
        """T-01b: deploy_config() short-circuits cleanly when _require_paramiko returns None.

        No SSHClient must be instantiated and no exception must propagate.
        """
        from core.deployer import deploy_config
        # Should not raise
        try:
            deploy_config({'host': '192.168.1.10', 'user': 'pi', 'dest_path': '~/p'})
        except Exception as exc:
            self.fail(f"deploy_config() raised unexpectedly when paramiko is absent: {exc}")


# ── T-04: deploy_moonraker() SSH fallback via core.menu wrappers ─────────────

class TestDeployMoonrakerSSHFallbackMenuPrompts(unittest.TestCase):
    """T-04: deploy_moonraker() SSH fallback branch via core.menu wrappers.

    The existing test_deploy_moonraker_unreachable_ssh_fallback patches
    'questionary.confirm' and 'questionary.text', but deploy_moonraker()
    now calls core.menu.yes_no / simple_input / password_input directly
    (post Q-03 refactor). This class uses the correct patch targets.
    """

    def setUp(self):
        self.patches = [
            patch('core.moonraker.check_moonraker', return_value=(False, "unreachable")),
            patch('core.moonraker.upload_printer_cfg', return_value=(False, "unreachable")),
            patch('core.moonraker.restart_firmware', return_value=(False, "unreachable")),
            patch('core.moonraker.restart_klipper_service', return_value=(False, "unreachable")),
            patch('core.moonraker.download_printer_cfg', return_value=(False, b"")),
            patch('core.moonraker.check_klipper_ready', return_value=(False, "unreachable")),
            patch('core.moonraker.verify_remote_file_exists', return_value=False),
            patch('time.sleep'),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    @patch('builtins.print')
    @patch('core.deployer.deploy_config')
    @patch('core.menu.password_input', return_value='raspberry')
    @patch('core.menu.simple_input', side_effect=[
        '192.168.1.50',  # moonraker host
        '7125',          # moonraker port
        '',              # api key (empty)
        'pi',            # ssh user
        '/home/pi/printer_data/config/',  # ssh dest_path
    ])
    @patch('core.menu.yes_no', return_value=True)   # accept SSH fallback
    def test_ssh_fallback_calls_deploy_config_with_correct_user_data(
            self, mock_yn, mock_si, mock_pw, mock_deploy, mock_print):
        """T-04: When Moonraker is unreachable and user accepts SSH fallback,
        deploy_config() must be called with host, user, dest_path, and password
        collected from the core.menu prompts.
        """
        from core.deployer import deploy_moonraker
        deploy_moonraker({})

        mock_deploy.assert_called_once()
        user_data = mock_deploy.call_args[0][0]
        self.assertEqual(user_data['user'], 'pi')
        self.assertEqual(user_data['dest_path'], '/home/pi/printer_data/config/')
        self.assertEqual(user_data['password'], 'raspberry')

    @patch('builtins.print')
    @patch('core.deployer.deploy_config')
    @patch('core.menu.password_input', return_value='raspberry')
    @patch('core.menu.simple_input', side_effect=[
        '192.168.1.50', '7125', '', 'pi', '/home/pi/printer_data/config/',
    ])
    @patch('core.menu.yes_no', return_value=False)  # decline SSH fallback
    def test_ssh_fallback_declined_does_not_call_deploy_config(
            self, mock_yn, mock_si, mock_pw, mock_deploy, mock_print):
        """T-04b: When user declines the SSH fallback, deploy_config must NOT be called."""
        from core.deployer import deploy_moonraker
        deploy_moonraker({})
        mock_deploy.assert_not_called()


if __name__ == '__main__':
    import unittest.mock
    unittest.main()

