import io
import unittest
from unittest.mock import patch, MagicMock
from core.dashboard import (
    _select_language,
    _select_mode,
    detect_system_state,
    get_suggestions,
    run_dashboard,
)
from core.exceptions import WizardExit
from core.translations import get_lang, set_lang

class TestDashboard(unittest.TestCase):

    @patch("builtins.input", side_effect=KeyboardInterrupt)
    def test_language_selection_cancellation_raises_wizard_exit(self, mock_input):
        with self.assertRaises(WizardExit):
            _select_language()

    @patch("builtins.input", side_effect=EOFError)
    def test_mode_selection_cancellation_raises_wizard_exit(self, mock_input):
        with self.assertRaises(WizardExit):
            _select_mode()

    def setUp(self):
        self.original_language = get_lang()

    def tearDown(self):
        set_lang(self.original_language)

    @patch("firmware.detector.discover_mcu_hardware")
    @patch("core.dashboard._service_active")
    @patch("os.path.isdir")
    @patch("os.path.isfile")
    def test_detect_system_state(self, mock_isfile, mock_isdir, mock_service_active, mock_mcu):
        """Verify detect_system_state correctly probes files and services."""
        mock_isdir.side_effect = lambda p: True if "klipper" in p or "moonraker" in p else False
        mock_isfile.side_effect = lambda p: True if "printer.cfg" in p else False
        mock_service_active.return_value = False
        mock_mcu.return_value = {"derived_mcu": "stm32f103", "mcu_path": "/dev/serial/by-id/mock"}

        state = detect_system_state()
        self.assertTrue(state["klipper"])
        self.assertTrue(state["moonraker"])
        self.assertFalse(state["mainsail"])
        self.assertTrue(state["printer_cfg"])
        self.assertEqual(state["mcu"], "stm32f103")

    @patch("os.path.isdir")
    @patch("os.path.isfile")
    @patch("os.environ.get")
    @patch("glob.glob")
    def test_detect_webui_various_conditions(self, mock_glob, mock_env_get, mock_isfile, mock_isdir):
        """Test _detect_webui with different paths, sudo users, and nginx configs."""
        from core.dashboard import _detect_webui

        # Test case 1: Default path exists
        mock_isdir.side_effect = lambda p: p == "/mock/mainsail"
        mock_isfile.return_value = False
        mock_env_get.return_value = None
        mock_glob.return_value = []
        self.assertTrue(_detect_webui("mainsail", "/mock/mainsail"))

        # Test case 2: Sudo user home path exists
        mock_isdir.side_effect = lambda p: p == "/home/pi/mainsail"
        mock_env_get.side_effect = lambda key, default=None: "pi" if key == "SUDO_USER" else default
        # Since pwd might not exist on all target systems (like Windows where tests run),
        # we test the fallback branch as well.
        self.assertTrue(_detect_webui("mainsail", "/mock/not-exist"))

        # Test case 3: Glob home match
        mock_isdir.side_effect = lambda p: p == "/home/biqu/mainsail"
        mock_env_get.side_effect = lambda key, default=None: None
        mock_glob.return_value = ["/home/biqu/mainsail"]
        self.assertTrue(_detect_webui("mainsail", "/mock/not-exist"))

        # Test case 4: Typical nginx system path
        mock_isdir.side_effect = lambda p: p == "/var/www/mainsail"
        mock_glob.return_value = []
        self.assertTrue(_detect_webui("mainsail", "/mock/not-exist"))

        # Test case 5: Nginx config file exists
        mock_isdir.side_effect = None
        mock_isdir.return_value = False
        mock_isfile.side_effect = lambda p: p == "/etc/nginx/sites-enabled/mainsail"
        self.assertTrue(_detect_webui("mainsail", "/mock/not-exist"))

        # Test case 6: None exists
        mock_isfile.side_effect = None
        mock_isfile.return_value = False
        self.assertFalse(_detect_webui("mainsail", "/mock/not-exist"))

    def test_get_suggestions_all_missing(self):
        """Verify suggestions when klipper, moonraker, and config are missing."""
        state = {
            "klipper": False,
            "moonraker": False,
            "mainsail": False,
            "fluidd": False,
            "crowsnest": False,
            "printer_cfg": False,
            "mcu": None,
            "mcu_path": None,
        }
        suggestions = get_suggestions(state)
        self.assertTrue(any("klipper" in s.lower() for s in suggestions))
        self.assertTrue(any("config" in s.lower() for s in suggestions))

    @patch("core.dashboard._show_manage_view")
    @patch("core.dashboard.print_kace_banner")
    @patch("core.dashboard._render_status_panel")
    @patch("core.dashboard._render_suggestions")
    @patch("builtins.input")
    def test_run_dashboard_flow(self, mock_input, mock_render_sugg, mock_render_status, mock_banner, mock_show_manage):
        """Verify run_dashboard navigation flows: select language and select generate."""
        # 1st input: "1" → English, 2nd: "1" → Beginner, 3rd: "1" → generate
        mock_input.side_effect = ["1", "1", "1"]

        state = {
            "klipper": True,
            "moonraker": True,
            "mainsail": True,
            "fluidd": False,
            "crowsnest": False,
            "printer_cfg": True,
            "mcu": "stm32f103",
            "mcu_path": "/dev/serial/by-id/mock",
        }
        
        result = run_dashboard(state)
        self.assertEqual(result, "generate")
        self.assertEqual(mock_show_manage.call_count, 0)
        self.assertEqual(mock_input.call_count, 3)

    @patch("core.dashboard._show_manage_view")
    @patch("core.dashboard.print_kace_banner")
    @patch("core.dashboard._render_status_panel")
    @patch("core.dashboard._render_suggestions")
    @patch("builtins.input", side_effect=["2", "1", "1"])
    def test_dashboard_uses_selected_locale_for_select_prompt(
        self, mock_input, _suggestions, _status, _banner, _manage
    ):
        state = {"klipper": True, "moonraker": True, "mainsail": True,
                 "fluidd": False, "crowsnest": False, "printer_cfg": True,
                 "mcu": None, "mcu_path": None}
        with patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(run_dashboard(state), "generate")

        prompts = [call.args[0] for call in mock_input.call_args_list]
        self.assertIn("Seleccione [1-2]:", prompts[1])
        self.assertIn("Seleccione [1-2]:", prompts[2])

if __name__ == "__main__":
    unittest.main()
