# tests/unit/test_firmware_wizard.py
#
# Unit tests for core/firmware_wizard.py (run_firmware_wizard).

import unittest
from unittest.mock import patch, MagicMock
import io
import sys

from core.firmware_wizard import _processor_validator_for_architecture, run_firmware_wizard
from core.exceptions import DerivationAmbiguityError
from core.moonraker_deployer import DeployResult, DeployState
from core.translations import t
from firmware.deployment import DeploymentMethodId

class TestFirmwareWizard(unittest.TestCase):

    def test_architecture_processor_validator_returns_error_instead_of_raising(self):
        result = _processor_validator_for_architecture("stm32")("not-a-processor")
        self.assertIsInstance(result, str)
        self.assertIn("Unsupported", result)

    @patch('core.firmware_wizard.yes_no', return_value=True)
    @patch('core.firmware_wizard.numbered_select')
    @patch('core.firmware_wizard.build_firmware_orchestrator')
    def test_offset_not_applicable_is_not_presented_as_editable_bootloader(
        self, mock_build, mock_select, _mock_confirm
    ):
        mock_select.side_effect = [t("builder.compile_now"), "none"]
        mock_build.return_value = {
            "status": "success",
            "mcu": "rp2040",
            "firmware": "klipper.uf2",
            "path": "/fake/kace/klipper.uf2",
        }

        with patch('sys.stdout', new_callable=io.StringIO) as output:
            run_firmware_wizard({"mcu_type": "rp2040", "mcu_hint": "usb"})

        summary_choices = mock_select.call_args_list[0].kwargs["choices"]
        self.assertNotIn(t("builder.edit_boot"), summary_choices)
        self.assertIn("N/A", output.getvalue())

    @patch('core.firmware_wizard.yes_no', return_value=True)
    @patch('core.firmware_wizard.numbered_select')
    @patch('core.firmware_wizard.simple_input', return_value="stm32f446xx")
    @patch('core.firmware_wizard.build_firmware_orchestrator')
    def test_processor_edit_rederives_all_dependent_fields_and_shows_diff(
        self, mock_build, _mock_input, mock_select, _mock_confirm
    ):
        mock_select.side_effect = [
            t("builder.edit_proc"),
            t("builder.compile_now"),
            "none",
        ]
        mock_build.return_value = {
            "status": "success",
            "mcu": "stm32f446xx",
            "firmware": "klipper.bin",
            "path": "/fake/kace/klipper.bin",
        }
        user_data = {"mcu_type": "lpc1769", "mcu_hint": "usb"}

        with patch('sys.stdout', new_callable=io.StringIO) as output:
            run_firmware_wizard(user_data)

        config = mock_build.call_args.kwargs["config_dict"]
        self.assertEqual(config["CONFIG_MCU"], '"stm32"')
        self.assertEqual(config["CONFIG_MCU_STM32F446XX"], "y")
        self.assertEqual(config["CONFIG_FLASH_START"], "0x8000")
        self.assertNotIn("CONFIG_MACH_LPC176X", config)
        self.assertNotIn("CONFIG_CLOCK_FREQ", config)
        self.assertIn("Firmware configuration diff", output.getvalue())
        self.assertIn("-CONFIG_CLOCK_FREQ=120000000", output.getvalue())

    @patch('core.firmware_wizard.yes_no', return_value=True)
    @patch('core.firmware_wizard.numbered_select')
    @patch('core.firmware_wizard.simple_input')
    @patch('core.firmware_wizard.build_firmware_orchestrator')
    def test_architecture_edit_requires_compatible_processor_and_rederives(
        self, mock_build, mock_input, mock_select, _mock_confirm
    ):
        mock_select.side_effect = [
            t("builder.edit_arch"),
            t("builder.compile_now"),
            "none",
        ]
        mock_input.side_effect = ["avr", "atmega2560"]
        mock_build.return_value = {
            "status": "success",
            "mcu": "atmega2560",
            "firmware": "klipper.elf.hex",
            "path": "/fake/kace/klipper.elf.hex",
        }
        user_data = {"mcu_type": "stm32f446xx", "mcu_hint": "uart"}

        with patch('sys.stdout', new_callable=io.StringIO):
            run_firmware_wizard(user_data)

        config = mock_build.call_args.kwargs["config_dict"]
        self.assertEqual(config["CONFIG_MCU"], '"avr"')
        self.assertEqual(config["CONFIG_MCU_ATMEGA2560"], "y")
        self.assertNotIn("CONFIG_FLASH_START", config)
        self.assertFalse(any(key.startswith("CONFIG_MCU_STM32") for key in config))

    @patch('core.firmware_wizard.yes_no', return_value=True)
    @patch('core.firmware_wizard.numbered_select')
    @patch('core.firmware_wizard.simple_input', return_value="<")
    @patch('core.firmware_wizard.build_firmware_orchestrator')
    def test_processor_edit_back_keeps_complete_original_configuration(
        self, mock_build, _mock_input, mock_select, _mock_confirm
    ):
        mock_select.side_effect = [
            t("builder.edit_proc"),
            t("builder.compile_now"),
            "none",
        ]
        mock_build.return_value = {
            "status": "success",
            "mcu": "lpc1769",
            "firmware": "klipper.bin",
            "path": "/fake/kace/klipper.bin",
        }

        with patch('sys.stdout', new_callable=io.StringIO):
            run_firmware_wizard({"mcu_type": "lpc1769", "mcu_hint": "usb"})

        config = mock_build.call_args.kwargs["config_dict"]
        self.assertEqual(config["CONFIG_MCU"], '"lpc176x"')
        self.assertEqual(config["CONFIG_MACH_LPC176X"], "y")
        self.assertEqual(config["CONFIG_CLOCK_FREQ"], "120000000")
        self.assertEqual(config["CONFIG_FLASH_START"], "0x4000")

    @patch('core.firmware_wizard.yes_no')
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

    @patch('core.firmware_wizard.yes_no')
    def test_wizard_decline_compilation(self, mock_confirm):
        """Verify the wizard exits gracefully if compilation confirmation is declined."""
        mock_confirm.return_value = False
        user_data = {"mcu_type": "stm32f103", "mcu_hint": "usb"}
        
        captured = io.StringIO()
        sys.stdout = captured
        try:
            run_firmware_wizard(user_data)
        finally:
            sys.stdout = sys.__stdout__

        self.assertIn("Skipping firmware compilation", captured.getvalue())

    @patch('core.firmware_wizard.yes_no')
    @patch('core.firmware_wizard.numbered_select')
    @patch('core.firmware_wizard.simple_input')
    @patch('core.firmware_wizard.build_firmware_orchestrator')
    def test_mcu_family_ambiguity_handling(self, mock_build, mock_text, mock_select, mock_confirm):
        """Verify DerivationAmbiguityError on mcu_family prompts the user and continues."""
        mock_confirm.return_value = True
        
        # Ambiguity error triggers: select arch -> select bootloader -> select interface -> select config summary choice -> loop exit on build_now
        # 1. First choice for select: "stm32" (to resolve MCU family ambiguity)
        # 2. Second choice for select: "No bootloader (0x0)" (to resolve bootloader ambiguity)
        # 3. Third choice for select: "USB" (to resolve communication interface ambiguity)
        # 4. Fourth choice for select: compile choice (builder.compile_now)
        # 5. Fifth choice for select: deploy method ("none")
        mock_select.side_effect = [
            "stm32",
            "No bootloader (0x0)",
            "USB",
            "🚀  Compile Firmware Now",
            "none"
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

    @patch('core.firmware_wizard.yes_no')
    @patch('core.firmware_wizard.numbered_select')
    @patch('core.firmware_wizard.build_firmware_orchestrator')
    def test_bootloader_offset_ambiguity_handling(self, mock_build, mock_select, mock_confirm):
        """Verify DerivationAmbiguityError on bootloader offset prompts the user and continues."""
        mock_confirm.return_value = True
        
        # First select: "8KiB bootloader (0x2000)"
        # Second select: "Compile now"
        # Third select: deploy method "none"
        mock_select.side_effect = [
            "8KiB bootloader (0x2000)",
            "🚀  Compile Firmware Now",
            "none"
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

    @patch('core.firmware_wizard.yes_no', return_value=True)
    @patch('core.firmware_wizard.numbered_select')
    @patch('core.firmware_wizard.build_firmware_orchestrator')
    @patch('core.firmware_wizard.FirmwareDeploymentService')
    def test_manual_option_prepares_deployment_until_config_exists(
        self, mock_service_cls, mock_build, mock_select, _mock_confirm
    ):
        """The wizard plans/stages firmware but defers physical execution."""
        mock_select.side_effect = [
            t("builder.compile_now"),
            "MANUAL",
        ]
        mock_build.return_value = {
            "status": "success",
            "mcu": "stm32f103",
            "firmware": "klipper.bin",
            "path": "/fake/kace/klipper.bin",
            "klipper_version": "kace-new123",
            "mcu_name": "mcu",
        }
        service = mock_service_cls.return_value
        service.available_methods.return_value = (DeploymentMethodId.MANUAL,)
        service.plan.return_value = MagicMock(
            final_filename="firmware.bin", instructions=(), automation_blockers=(),
            automation_supported=False,
        )
        service.prepare.return_value = MagicMock(staged_path="/fake/kace/deploy/id/firmware.bin")
        user_data = {"mcu_type": "stm32f103", "mcu_hint": "usb", "board": "board.cfg"}
        with patch('sys.stdout', new_callable=io.StringIO):
            result = run_firmware_wizard(user_data)

        self.assertEqual(result, {"status": "deployment_prepared", "method": "MANUAL"})
        self.assertTrue(user_data["pending_firmware_deployment"])

if __name__ == '__main__':
    unittest.main()
