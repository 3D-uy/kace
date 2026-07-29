import unittest
import glob
import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from firmware.detector import discover_mcu_hardware
from core.translations import get_lang, set_lang

class TestDetector(unittest.TestCase):

    def setUp(self):
        self.original_language = get_lang()

    def tearDown(self):
        set_lang(self.original_language)

    @patch('glob.glob')
    @patch('builtins.print')
    def test_one_mcu_detected_auto_continues(self, mock_print, mock_glob):
        """Verify that if exactly 1 MCU is detected, it is selected automatically without prompts."""
        mock_glob.side_effect = lambda pattern: ['/dev/serial/by-id/usb-Klipper_stm32f446xx_Octopus-v1.1-if00'] if 'by-id' in pattern else []
        
        ctx = discover_mcu_hardware(interactive=True)
        
        self.assertEqual(ctx['mcu_path'], '/dev/serial/by-id/usb-Klipper_stm32f446xx_Octopus-v1.1-if00')
        self.assertEqual(ctx['derived_mcu'], 'stm32f446xx')
        self.assertEqual(ctx['hint'], 'usb')
        
        # Verify success banner printed
        printed = [call[0][0] for call in mock_print.call_args_list]
        self.assertTrue(any("Connected MCU auto-detected" in msg for msg in printed))

    @patch('glob.glob')
    @patch('firmware.detector.numbered_select')
    def test_multiple_mcus_prompts_user(self, mock_q_select, mock_glob):
        """Verify that multiple MCUs prompt the user to choose, and manual choice is removed."""
        ports_list = [
            '/dev/serial/by-id/usb-Klipper_stm32f446xx_Octopus-if00',
            '/dev/serial/by-id/usb-Klipper_rp2040_SKRPico-if00'
        ]
        mock_glob.side_effect = lambda pattern: ports_list if 'by-id' in pattern else []
        
        mock_q_select.return_value = '/dev/serial/by-id/usb-Klipper_rp2040_SKRPico-if00'
        
        ctx = discover_mcu_hardware(interactive=True)
        
        self.assertEqual(ctx['mcu_path'], '/dev/serial/by-id/usb-Klipper_rp2040_SKRPico-if00')
        self.assertEqual(ctx['derived_mcu'], 'rp2040')
        self.assertEqual(ctx['hint'], 'usb')
        
        # Verify prompt choices
        q_args, q_kwargs = mock_q_select.call_args
        choices = q_kwargs.get('choices') if 'choices' in q_kwargs else q_args[1]
        
        self.assertNotIn("Enter manually...", choices)
        self.assertNotIn("Skip detection", choices)
        self.assertIn('/dev/serial/by-id/usb-Klipper_stm32f446xx_Octopus-if00', choices)

    @patch('glob.glob')
    @patch('firmware.detector.numbered_select')
    @patch('builtins.print')
    def test_no_mcus_shows_diagnostics_and_retries(self, mock_print, mock_q_select, mock_glob):
        """Verify that no MCUs found displays diagnostics and allows retrying to find one."""
        glob_calls = []
        def mock_glob_fn(pattern):
            if 'by-id' in pattern:
                glob_calls.append(pattern)
                if len(glob_calls) == 1:
                    return []
                else:
                    return ['/dev/serial/by-id/usb-Klipper_stm32f446xx_Octopus-if00']
            return []
        
        mock_glob.side_effect = mock_glob_fn
        
        mock_q_select.return_value = 'retry'
        
        ctx = discover_mcu_hardware(interactive=True)
        
        self.assertEqual(ctx['mcu_path'], '/dev/serial/by-id/usb-Klipper_stm32f446xx_Octopus-if00')
        self.assertEqual(ctx['derived_mcu'], 'stm32f446xx')
        
        # Verify diagnostics printed
        printed = [call[0][0] for call in mock_print.call_args_list]
        self.assertTrue(any("No MCU serial devices detected" in msg for msg in printed))
        self.assertTrue(any("USB Connection" in msg for msg in printed))
        self.assertTrue(any("Board Power" in msg for msg in printed))

    @patch('glob.glob', return_value=[])
    @patch('firmware.detector.numbered_select', return_value='quit')
    @patch('builtins.print')
    def test_no_mcu_flow_uses_selected_spanish_locale(self, mock_print, _select, _glob):
        """The post-dashboard MCU recovery path must not revert to English."""
        set_lang("Español")
        with self.assertRaises(SystemExit):
            discover_mcu_hardware(interactive=True)

        printed = "\n".join(call.args[0] for call in mock_print.call_args_list)
        self.assertIn("No se detectaron dispositivos seriales", printed)
        self.assertIn("Conexión USB", printed)
        self.assertNotIn("No MCU serial devices detected", printed)

        prompt = _select.call_args.args[0]
        choices = _select.call_args.kwargs["choices"]
        self.assertEqual(prompt, "¿Cómo desea continuar?")
        self.assertIn("Reintentar detección de hardware", choices[0]["name"])

if __name__ == '__main__':
    unittest.main()
