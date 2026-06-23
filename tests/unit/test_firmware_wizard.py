# tests/unit/test_firmware_wizard.py
#
# Unit tests for core/firmware_wizard.py (run_firmware_wizard).

import unittest
from unittest.mock import patch, MagicMock
import io
import sys

from core.firmware_wizard import run_firmware_wizard
from core.exceptions import DerivationAmbiguityError

class TestFirmwareWizard(unittest.TestCase):

    @patch('core.firmware_wizard.questionary.confirm')
    def test_skip_wizard_if_no_mcu(self, mock_confirm):
        """Verify the wizard skips if no MCU is designated and manual mode is off."""
        user_data = {"mcu_type": None, "mcu_hint": None}
        
        captured = io.StringIO()
        sys.stdout = captured
        try:
            run_firmware_wizard(user_data)
        finally:
            sys.stdout = sys.__stdout__

        mock_confirm.assert_not_called()
        self.assertIn("Skipping firmware compilation", captured.getvalue())

    @patch('core.firmware_wizard.questionary.confirm')
    def test_wizard_decline_compilation(self, mock_confirm):
        """Verify the wizard exits gracefully if compilation confirmation is declined."""
        mock_confirm.return_value.ask.return_value = False
        user_data = {"mcu_type": "stm32f103", "mcu_hint": "usb"}
        
        captured = io.StringIO()
        sys.stdout = captured
        try:
            run_firmware_wizard(user_data)
        finally:
            sys.stdout = sys.__stdout__

        self.assertIn("Skipping firmware compilation", captured.getvalue())

    @patch('core.firmware_wizard.questionary.confirm')
    @patch('core.firmware_wizard.questionary.select')
    @patch('core.firmware_wizard.questionary.text')
    @patch('core.firmware_wizard.build_firmware_orchestrator')
    def test_mcu_family_ambiguity_handling(self, mock_build, mock_text, mock_select, mock_confirm):
        """Verify DerivationAmbiguityError on mcu_family prompts the user and continues."""
        mock_confirm.return_value.ask.return_value = True
        
        # Ambiguity error triggers: select arch -> select bootloader -> select interface -> select config summary choice -> loop exit on build_now
        # 1. First choice for select: "stm32" (to resolve MCU family ambiguity)
        # 2. Second choice for select: "No bootloader (0x0)" (to resolve bootloader ambiguity)
        # 3. Third choice for select: "USB" (to resolve communication interface ambiguity)
        # 4. Fourth choice for select: compile choice (builder.compile_now)
        # 5. Fifth choice for select: deploy method ("none")
        mock_select.side_effect = [
            MagicMock(ask=lambda: "stm32"),
            MagicMock(ask=lambda: "No bootloader (0x0)"),
            MagicMock(ask=lambda: "USB"),
            MagicMock(ask=lambda: "🚀  Compile Firmware Now"),
            MagicMock(ask=lambda: "none")
        ]
        
        mock_build.return_value = {
            "status": "success",
            "mcu": "stm32f103",
            "firmware": "klipper.bin",
            "path": "/fake/kace/klipper.bin"
        }
        
        # Start with None mcu to force DerivationAmbiguityError on mcu_family
        user_data = {"mcu_type": None, "mcu_hint": "manual"}
        
        captured = io.StringIO()
        sys.stdout = captured
        try:
            run_firmware_wizard(user_data)
        finally:
            sys.stdout = sys.__stdout__
        
        # Verify the builder was called with the resolved architecture
        mock_build.assert_called_once()
        config_dict = mock_build.call_args[1]["config_dict"]
        self.assertEqual(config_dict.get("CONFIG_MCU"), '"stm32"')

    @patch('core.firmware_wizard.questionary.confirm')
    @patch('core.firmware_wizard.questionary.select')
    @patch('core.firmware_wizard.build_firmware_orchestrator')
    def test_bootloader_offset_ambiguity_handling(self, mock_build, mock_select, mock_confirm):
        """Verify DerivationAmbiguityError on bootloader offset prompts the user and continues."""
        mock_confirm.return_value.ask.return_value = True
        
        # First select: "8KiB bootloader (0x2000)"
        # Second select: "Compile now"
        # Third select: deploy method "none"
        mock_select.side_effect = [
            MagicMock(ask=lambda: "8KiB bootloader (0x2000)"),
            MagicMock(ask=lambda: "🚀  Compile Firmware Now"),
            MagicMock(ask=lambda: "none")
        ]
        
        mock_build.return_value = {
            "status": "success",
            "mcu": "stm32",
            "firmware": "klipper.bin",
            "path": "/fake/kace/klipper.bin"
        }
        
        # Trigger bootloader offset ambiguity by passing stm32 with no flash_start (e.g. "stm32" generic matches pattern "stm32" which has flash_start: None)
        user_data = {"mcu_type": "stm32", "mcu_hint": "usb"}
        
        captured = io.StringIO()
        sys.stdout = captured
        try:
            run_firmware_wizard(user_data)
        finally:
            sys.stdout = sys.__stdout__
        
        mock_build.assert_called_once()
        config_dict = mock_build.call_args[1]["config_dict"]
        self.assertEqual(config_dict.get("CONFIG_FLASH_START"), "0x2000")

if __name__ == '__main__':
    unittest.main()
