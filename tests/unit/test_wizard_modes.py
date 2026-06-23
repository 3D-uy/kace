import os
import unittest
from unittest.mock import patch, MagicMock
import questionary

from core.translations import get_mode, set_mode, t
from core.wizard.ui import _print_step_header
from core.wizard.runner import WizardRunner, PHASE_MAP
from core.wizard.steps.hardware import _step_driver_type, _step_driver_mode, _step_z_socket_assignment

class TestWizardModes(unittest.TestCase):

    def setUp(self):
        self.original_mode = get_mode()

    def tearDown(self):
        set_mode(self.original_mode)

    def test_mode_transitions(self):
        """Verify that mode state can be set and retrieved correctly."""
        set_mode("Beginner")
        self.assertEqual(get_mode(), "Beginner")

        set_mode("Advanced")
        self.assertEqual(get_mode(), "Advanced")

        # Invalid mode should be ignored, leaving the current mode unchanged
        set_mode("InvalidMode")
        self.assertEqual(get_mode(), "Advanced")

    @patch("sys.stdout", new_callable=lambda: __import__("io").StringIO())
    def test_step_header_beginner_mode(self, mock_stdout):
        """Verify that step headers are printed in Beginner mode."""
        set_mode("Beginner")
        # Temporarily clear environment flags that silence output
        with patch.dict(os.environ, {"KACE_AUTO": "0", "KACE_QUIET": "0", "KACE_TESTING": "0"}):
            _print_step_header("board", {})
            output = mock_stdout.getvalue()
            self.assertIn("┌", output)
            self.assertIn("Phase", output)

    @patch("sys.stdout", new_callable=lambda: __import__("io").StringIO())
    def test_step_header_advanced_mode(self, mock_stdout):
        """Verify that step headers are not printed in Advanced mode (early return)."""
        set_mode("Advanced")
        with patch.dict(os.environ, {"KACE_AUTO": "0", "KACE_QUIET": "0", "KACE_TESTING": "0"}):
            _print_step_header("board", {})
            output = mock_stdout.getvalue()
            self.assertEqual(output, "")

    @patch("questionary.select")
    @patch("core.wizard.steps.hardware.detect_driver_info")
    @patch("core.wizard.steps.hardware._get_parsed")
    def test_choice_recommendations_beginner(self, mock_get_parsed, mock_detect, mock_select):
        """Verify choice recommendation suffixes are present in Beginner mode."""
        set_mode("Beginner")
        mock_get_parsed.return_value = {}
        mock_detect.return_value = {
            "driver_type": "TMC2209",
            "integrated": True,
            "is_socketed": False,
            "driver_mode": "UART"
        }
        mock_select.return_value.ask.return_value = "TMC2209"

        user_data = {"board": "generic-skr.cfg"}
        _step_driver_type(user_data)

        # Inspect choices passed to questionary.select
        args, kwargs = mock_select.call_args
        choices = kwargs.get("choices", [])
        titles = [c.title if hasattr(c, 'title') else c.get('name', '') for c in choices]

        # Verify recommended suffixes exist
        self.assertTrue(any("✓ Recommended" in t for t in titles))
        self.assertTrue(any("Not Recommended" in t for t in titles))

    @patch("questionary.select")
    @patch("core.wizard.steps.hardware.detect_driver_info")
    @patch("core.wizard.steps.hardware._get_parsed")
    def test_choice_recommendations_advanced(self, mock_get_parsed, mock_detect, mock_select):
        """Verify choice recommendation suffixes are omitted in Advanced mode."""
        set_mode("Advanced")
        mock_get_parsed.return_value = {}
        mock_detect.return_value = {
            "driver_type": "TMC2209",
            "integrated": True,
            "is_socketed": False,
            "driver_mode": "UART"
        }
        mock_select.return_value.ask.return_value = "TMC2209"

        user_data = {"board": "generic-skr.cfg"}
        _step_driver_type(user_data)

        args, kwargs = mock_select.call_args
        choices = kwargs.get("choices", [])
        titles = [c.title if hasattr(c, 'title') else c.get('name', '') for c in choices]

        # Verify recommended suffixes do not exist
        for title in titles:
            self.assertNotIn("✓ Recommended", title)
            self.assertNotIn("Not Recommended", title)

    @patch("questionary.select")
    @patch("core.wizard.steps.hardware.get_reusable_driver_sockets")
    def test_z_socket_recommendations_beginner(self, mock_get_sockets, mock_select):
        """Verify socket recommendation suffix in Beginner mode."""
        set_mode("Beginner")
        mock_get_sockets.return_value = [("extruder1", "E1")]
        mock_select.return_value.ask.return_value = "extruder1"

        user_data = {
            "z_motors": "2",
            "board": "generic-skr.cfg",
            "board_raw_config": "[extruder1]\nstep_pin: PE1\n",
            "board_parsed": {"extruder1": {"step_pin": "PE1"}}
        }
        _step_z_socket_assignment(user_data)

        args, kwargs = mock_select.call_args
        choices = kwargs.get("choices", [])
        names = [c.get("name", "") if isinstance(c, dict) else str(c) for c in choices]

        self.assertTrue(any("✓ Recommended" in n for n in names))

    @patch("questionary.select")
    @patch("core.wizard.steps.hardware.get_reusable_driver_sockets")
    def test_z_socket_recommendations_advanced(self, mock_get_sockets, mock_select):
        """Verify socket recommendation suffix is omitted in Advanced mode."""
        set_mode("Advanced")
        mock_get_sockets.return_value = [("extruder1", "E1")]
        mock_select.return_value.ask.return_value = "extruder1"

        user_data = {
            "z_motors": "2",
            "board": "generic-skr.cfg",
            "board_raw_config": "[extruder1]\nstep_pin: PE1\n",
            "board_parsed": {"extruder1": {"step_pin": "PE1"}}
        }
        _step_z_socket_assignment(user_data)

        args, kwargs = mock_select.call_args
        choices = kwargs.get("choices", [])
        names = [c.get("name", "") if isinstance(c, dict) else str(c) for c in choices]

        for name in names:
            self.assertNotIn("✓ Recommended", name)

    @patch("sys.stdout", new_callable=lambda: __import__("io").StringIO())
    def test_phase_complete_banner_beginner(self, mock_stdout):
        """Verify phase complete banner prints in Beginner mode."""
        set_mode("Beginner")
        steps_config = {
            "stepA": {"prompt": lambda ud: "ansA", "next": lambda ans, ud: "stepB"},
            "stepB": {"prompt": lambda ud: "ansB"}
        }
        step_order = ["stepA", "stepB"]

        # Temporarily patch PHASE_MAP
        original_phase_map = PHASE_MAP.copy()
        PHASE_MAP["stepA"] = "Hardware"
        PHASE_MAP["stepB"] = "Motion"

        try:
            with patch.dict(os.environ, {"KACE_AUTO": "0", "KACE_QUIET": "0", "KACE_TESTING": "0"}), \
                 patch("core.wizard.ui._print_step_header"):
                runner = WizardRunner(steps_config, step_order, initial_data={})
                runner.run("stepA")
                output = mock_stdout.getvalue()
                self.assertIn("Phase complete: Hardware", output)
        finally:
            PHASE_MAP.clear()
            PHASE_MAP.update(original_phase_map)

    @patch("sys.stdout", new_callable=lambda: __import__("io").StringIO())
    def test_phase_complete_banner_advanced(self, mock_stdout):
        """Verify phase complete banner is omitted in Advanced mode."""
        set_mode("Advanced")
        steps_config = {
            "stepA": {"prompt": lambda ud: "ansA", "next": lambda ans, ud: "stepB"},
            "stepB": {"prompt": lambda ud: "ansB"}
        }
        step_order = ["stepA", "stepB"]

        original_phase_map = PHASE_MAP.copy()
        PHASE_MAP["stepA"] = "Hardware"
        PHASE_MAP["stepB"] = "Motion"

        try:
            with patch.dict(os.environ, {"KACE_AUTO": "0", "KACE_QUIET": "0", "KACE_TESTING": "0"}), \
                 patch("core.wizard.ui._print_step_header"):
                runner = WizardRunner(steps_config, step_order, initial_data={})
                runner.run("stepA")
                output = mock_stdout.getvalue()
                self.assertEqual(output.strip(), "")
        finally:
            PHASE_MAP.clear()
            PHASE_MAP.update(original_phase_map)


if __name__ == "__main__":
    unittest.main()
