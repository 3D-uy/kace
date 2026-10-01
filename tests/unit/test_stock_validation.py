import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Ensure core can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from core import wizard
from core.wizard import _normalize_mcu_family

class TestStockValidation(unittest.TestCase):

    def test_normalize_mcu_family(self):
        self.assertEqual(_normalize_mcu_family("LPC1769"), "lpc176x")
        self.assertEqual(_normalize_mcu_family("lpc1768"), "lpc176x")
        self.assertEqual(_normalize_mcu_family("stm32f103"), "stm32f103")
        self.assertEqual(_normalize_mcu_family("stm32f446"), "stm32f4")
        self.assertEqual(_normalize_mcu_family("rp2040"), "rp2040")

    def test_exact_model_suggestions_use_reviewed_filenames(self):
        from core.board_identity import suggested_board_configs
        names = ['generic-bigtreetech-skr-v1.4.cfg', 'generic-bigtreetech-skr-v1.3.cfg']
        self.assertEqual(suggested_board_configs(names, 'lpc1769'), names[:1])

    def test_unknown_family_does_not_invent_model_suggestions(self):
        from core.board_identity import suggested_board_configs
        names = ['generic-bigtreetech-skr-v1.4.cfg', 'generic-bigtreetech-skr-v1.3.cfg']
        self.assertEqual(suggested_board_configs(names, 'lpc176x_custom'), [])

    def test_generic_stock_validation(self):
        """Test validation behavior with exact/family matching and missing expectations."""
        printer_prof = "printer-creality-cr6se-2020.cfg"
        db = [
            {"search_terms": ["cr6se", "cr-6"], "expected_mcu": ["stm32f103"]}
        ]
        
        detected = "lpc1769"
        expected_mcus = []
        for entry in db:
            if any(term in printer_prof.lower() for term in entry["search_terms"]):
                expected_mcus.extend(entry["expected_mcu"])
                break
                
        self.assertEqual(expected_mcus, ["stm32f103"])
        
        # Mismatch
        norm_detected = _normalize_mcu_family(detected)
        match_found = any(norm_detected == _normalize_mcu_family(exp) or detected.startswith(exp) or exp.startswith(detected) for exp in expected_mcus)
        self.assertFalse(match_found)
        
        # Match (Ender 3 V2 expecting stm32f103)
        detected_ok = "stm32f103"
        norm_detected_ok = _normalize_mcu_family(detected_ok)
        match_found_ok = any(norm_detected_ok == _normalize_mcu_family(exp) or detected_ok.startswith(exp) or exp.startswith(detected_ok) for exp in expected_mcus)
        self.assertTrue(match_found_ok)

    def test_missing_expected_mcu(self):
        """Test behavior when no OEM expectation is defined."""
        printer_prof = "printer-unknown-model.cfg"
        db = [
            {"search_terms": ["cr6se", "cr-6"], "expected_mcu": ["stm32f103"]}
        ]
        
        expected_mcus = []
        for entry in db:
            if any(term in printer_prof.lower() for term in entry["search_terms"]):
                expected_mcus.extend(entry["expected_mcu"])
                break
                
        self.assertEqual(len(expected_mcus), 0)

if __name__ == '__main__':
    unittest.main()
