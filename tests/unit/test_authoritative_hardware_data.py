"""Regression coverage for authoritative KACE hardware YAML databases."""

import ast
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]


class TestAuthoritativeHardwareData(unittest.TestCase):
    def test_runtime_modules_do_not_embed_shadow_hardware_databases(self):
        forbidden = {
            "firmware/derivation.py": {"_FW_DB_FALLBACK"},
            "core/scraper.py": {"_BLTOUCH_FALLBACK"},
            "core/display_checker.py": {
                "_DISPLAY_CONFIGS_FALLBACK",
                "_PRINTER_PROFILES_FALLBACK",
            },
            "core/advanced_module_handler.py": {"_FALLBACK_SCHEMAS"},
            "core/wizard/steps/hardware.py": {"_MCU_SEARCH_TERMS_FALLBACK"},
        }
        violations = []
        for relative_path, names in forbidden.items():
            tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
            assigned = {
                target.id
                for node in ast.walk(tree)
                if isinstance(node, (ast.Assign, ast.AnnAssign))
                for target in (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                if isinstance(target, ast.Name)
            }
            violations.extend(
                f"{relative_path}:{name}" for name in sorted(names & assigned)
            )
        self.assertEqual(violations, [])

    def test_missing_or_invalid_hardware_database_fails_closed(self):
        from core import advanced_module_handler, display_checker, scraper
        from firmware import derivation
        from core.wizard.steps import hardware

        with patch("core.loader.load_advanced_modules_yaml", side_effect=RuntimeError("missing")):
            with self.assertRaisesRegex(RuntimeError, "advanced_modules"):
                advanced_module_handler._load_schemas()
        with patch("core.loader.load_displays_yaml", side_effect=RuntimeError("missing")):
            with self.assertRaisesRegex(RuntimeError, "displays"):
                display_checker._load_display_db()
        with patch("core.loader.load_boards_yaml", side_effect=RuntimeError("missing")):
            with self.assertRaisesRegex(RuntimeError, "boards"):
                display_checker._load_boards_db()
            with self.assertRaisesRegex(RuntimeError, "boards"):
                scraper._load_bltouch_db()
            with self.assertRaisesRegex(RuntimeError, "boards"):
                derivation._load_firmware_db()
            with self.assertRaisesRegex(RuntimeError, "boards"):
                hardware._load_mcu_search_terms()


if __name__ == "__main__":
    unittest.main()
