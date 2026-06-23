import unittest
from unittest.mock import patch, MagicMock
from core.display_wizard import run_display_setup_step

class TestDisplayWizard(unittest.TestCase):
    @patch("questionary.select")
    def test_run_display_setup_step_none(self, mock_select):
        # Test selecting "none"
        mock_select.return_value.ask.return_value = "none"
        user_data = {"mcu_type": "stm32f103"}
        parsed_cfg = {}
        res = run_display_setup_step(user_data, parsed_cfg, "generic-creality-v4.2.2.cfg")
        self.assertEqual(res["display_choice"], "none")
        self.assertIsNone(res["display_section"])
        self.assertTrue(res["display_risk_accepted"])

    @patch("questionary.select")
    def test_run_display_setup_step_back(self, mock_select):
        # Test selecting back
        mock_select.return_value.ask.return_value = "__back__"
        user_data = {"mcu_type": "stm32f103"}
        parsed_cfg = {}
        res = run_display_setup_step(user_data, parsed_cfg, "generic-creality-v4.2.2.cfg")
        self.assertEqual(res["display_choice"], "__back__")

if __name__ == "__main__":
    unittest.main()
