import unittest
from unittest.mock import patch, MagicMock
from core.dashboard import detect_system_state, get_suggestions, run_dashboard

class TestDashboard(unittest.TestCase):

    @patch("firmware.detector.discover_mcu_hardware")
    @patch("core.dashboard._service_active")
    @patch("os.path.isdir")
    @patch("os.path.isfile")
    def test_detect_system_state(self, mock_isfile, mock_isdir, mock_service_active, mock_mcu):
        """Verify detect_system_state correctly probes files and services."""
        mock_isdir.side_effect = lambda p: True if "klipper" in p or "moonraker" in p else False
        mock_isfile.return_value = True
        mock_service_active.return_value = False
        mock_mcu.return_value = {"derived_mcu": "stm32f103", "mcu_path": "/dev/serial/by-id/mock"}

        state = detect_system_state()
        self.assertTrue(state["klipper"])
        self.assertTrue(state["moonraker"])
        self.assertFalse(state["mainsail"])
        self.assertTrue(state["printer_cfg"])
        self.assertEqual(state["mcu"], "stm32f103")

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
    @patch("questionary.select")
    def test_run_dashboard_flow(self, mock_select, mock_render_sugg, mock_render_status, mock_banner, mock_show_manage):
        """Verify run_dashboard navigation flows: select language and select generate."""
        # 1st call selects language, 2nd selects mode, 3rd selects generate
        mock_ask = MagicMock(side_effect=["English", "Beginner", "generate"])
        mock_select.return_value.ask = mock_ask

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
        self.assertEqual(mock_ask.call_count, 3)

if __name__ == "__main__":
    unittest.main()
