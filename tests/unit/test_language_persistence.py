"""Regression coverage for the interactive session locale."""

import sys
import types
import unittest
from unittest.mock import patch
import os

from core.translations import get_lang, set_lang, t
from core.translations._strings import UI_STRINGS


class TestLanguagePersistence(unittest.TestCase):
    def setUp(self):
        self.original_language = get_lang()

    def tearDown(self):
        set_lang(self.original_language)

    def test_every_ui_string_is_available_in_each_supported_locale(self):
        """A new key cannot reintroduce English fallback for ES/PT sessions."""
        for key, translations in UI_STRINGS.items():
            with self.subTest(key=key):
                self.assertEqual(
                    set(translations), {"English", "Español", "Português"}
                )
                self.assertTrue(all(translations.values()))

    def test_missing_selected_locale_never_falls_back_to_english(self):
        """Incomplete entries must be visible rather than changing the UI language."""
        key = "__test__.missing_selected_locale"
        with patch.dict(
            UI_STRINGS,
            {key: {"English": "English fallback must not be shown"}},
        ):
            set_lang("Español")
            self.assertEqual(t(key), key)
            set_lang("Português")
            self.assertEqual(t(key), key)

    def test_wizard_result_keeps_dashboard_locale_despite_legacy_input(self):
        """The first language choice remains attached to data through the wizard."""
        captured_initial_data = {}

        def capture_init(instance, steps_config, step_order, initial_data=None):
            captured_initial_data.update(initial_data or {})

        # This focused test exercises wizard initialization only.  The minimal
        # stub keeps it runnable in environments that intentionally omit the
        # optional prompt-toolkit UI dependency.
        if "prompt_toolkit.styles" not in sys.modules:
            prompt_toolkit = types.ModuleType("prompt_toolkit")
            styles = types.ModuleType("prompt_toolkit.styles")
            styles.Style = type(
                "Style", (), {"__init__": lambda self, *_: None, "from_dict": staticmethod(lambda _: None)}
            )
            sys.modules["prompt_toolkit"] = prompt_toolkit
            sys.modules["prompt_toolkit.styles"] = styles
        from core.wizard import run_wizard

        set_lang("Português")
        with patch.dict(os.environ, {"KACE_QUIET": "1"}), \
             patch("core.wizard.discover_mcu", return_value={}), \
             patch("core.wizard.fetch_config_list", return_value=[]), \
             patch("core.wizard.WizardRunner.__init__", capture_init), \
             patch("core.wizard.WizardRunner.run", return_value={}):
            run_wizard({"language": "English", "start_step": "board"})

        self.assertEqual(captured_initial_data["language"], "Português")
        self.assertEqual(get_lang(), "Português")


if __name__ == "__main__":
    unittest.main()
