import unittest
from core.wizard import _load_mcu_search_terms
from core.scraper import _load_bltouch_db
from firmware.derivation import _load_firmware_db, _FW_DB_FALLBACK
import os
import builtins
import firmware.derivation as drv

class TestYamlDb(unittest.TestCase):

    def test_mcu_search_terms_loader(self):
        db = _load_mcu_search_terms()
        self.assertIn('lpc1769', db)
        self.assertIn('skr-v1.4', db['lpc1769'])
        self.assertIn('stm32f446', db)
        self.assertIn('octopus', db['stm32f446'])

    def test_bltouch_db_loader(self):
        db = _load_bltouch_db()
        self.assertIn('skr-v1.4', db)
        self.assertEqual(db['skr-v1.4']['sensor_pin'], '^P0.10')
        self.assertIn('creality-v4.2.2', db)
        self.assertEqual(db['creality-v4.2.2']['control_pin'], 'PB0')

    def test_firmware_db_loader_order(self):
        db = _load_firmware_db()
        patterns = [e['pattern'] for e in db]
        self.assertIn('stm32f103', patterns)
        self.assertIn('rp2040', patterns)
        self.assertIn('linux', patterns)
        
        idx_f103 = patterns.index('stm32f103')
        idx_f1   = patterns.index('stm32f1')
        idx_stm  = patterns.index('stm32')
        self.assertTrue(idx_f103 < idx_f1 < idx_stm, "STM32 pattern order is wrong in boards.yaml")

    def test_yaml_parse_failure_recovery(self):
        """Simulate a broken YAML file and ensure it gracefully falls back without crashing."""
        from unittest.mock import patch
        logs = []
        original_print = builtins.print
        def mock_print(*args, **kwargs):
            logs.append(" ".join(map(str, args)))
        builtins.print = mock_print

        with patch("core.loader.load_boards_yaml", side_effect=Exception("Mock YAML parse error")):
            try:
                fallback = drv._load_firmware_db()
                self.assertEqual(fallback, _FW_DB_FALLBACK, "Failed to fall back on broken YAML")
                self.assertTrue(any("Failed to load modular hardware database" in log for log in logs), "Missing warning log")
            finally:
                builtins.print = original_print

if __name__ == '__main__':
    unittest.main()
