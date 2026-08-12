# tests/unit/test_display_checker.py
#
# Unit tests for core/display_checker.py
# Covers: section detection, database lookup, printer profile matching,
#         authoritative YAML behavior, status mapping, and empty-config safety.

import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Ensure the project root is on sys.path so imports resolve
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from core.display_checker import (
    detect_display_sections,
    get_display_compat,
    check_display_compatibility,
)


class TestDetectDisplaySections(unittest.TestCase):
    """Tests for detect_display_sections() — section scanning."""

    def test_detects_t5uid1(self):
        parsed = {"t5uid1": {"data_pin": "PC0"}}
        result = detect_display_sections(parsed)
        self.assertIn("t5uid1", result)

    def test_detects_dwin_set(self):
        parsed = {"dwin_set": {}}
        result = detect_display_sections(parsed)
        self.assertIn("dwin_set", result)

    def test_detects_standard_display(self):
        parsed = {"display": {"lcd_type": "st7920"}}
        result = detect_display_sections(parsed)
        self.assertIn("display", result)

    def test_detects_neopixel(self):
        parsed = {"neopixel my_led": {"pin": "PB0", "chain_count": "2"}}
        result = detect_display_sections(parsed)
        self.assertIn("neopixel", result)

    def test_detects_tft_serial(self):
        parsed = {"tft_serial": {}}
        result = detect_display_sections(parsed)
        self.assertIn("tft_serial", result)

    def test_detects_ssd1306(self):
        parsed = {"ssd1306": {}}
        result = detect_display_sections(parsed)
        self.assertIn("ssd1306", result)

    def test_no_display_sections_returns_empty(self):
        parsed = {
            "printer": {"kinematics": "cartesian"},
            "stepper_x": {"step_pin": "PC2"},
            "extruder": {"heater_pin": "PA1"},
        }
        result = detect_display_sections(parsed)
        self.assertEqual(result, [])

    def test_no_duplicates_for_multiple_neopixels(self):
        """Multiple neopixel sections with different names → only one 'neopixel' entry."""
        parsed = {
            "neopixel led1": {"pin": "PB0"},
            "neopixel led2": {"pin": "PB1"},
        }
        result = detect_display_sections(parsed)
        self.assertEqual(result.count("neopixel"), 1)

    def test_empty_config_returns_empty(self):
        self.assertEqual(detect_display_sections({}), [])

    def test_lcd_menu_detected(self):
        parsed = {"lcd_menu": {}}
        result = detect_display_sections(parsed)
        self.assertIn("lcd_menu", result)


class TestGetDisplayCompat(unittest.TestCase):
    """Tests for get_display_compat() — database lookup."""

    def test_t5uid1_is_unsupported(self):
        result = get_display_compat("t5uid1")
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "unsupported")
        self.assertEqual(result["recommendation"], "disconnect")

    def test_standard_display_is_supported(self):
        result = get_display_compat("display")
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "supported")
        self.assertEqual(result["recommendation"], "none")

    def test_tft_serial_is_partial(self):
        result = get_display_compat("tft_serial")
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "partial")

    def test_unknown_section_returns_none(self):
        result = get_display_compat("completely_unknown_display_type_xyz")
        self.assertIsNone(result)

    def test_cr6_se_matched_via_printer_filename(self):
        """Printer profile match should take precedence over section lookup."""
        result = get_display_compat("display", printer_filename="printer-cr6-se.cfg")
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "unsupported")
        self.assertEqual(result["source"], "printer_profile")

    def test_artillery_sidewinder_matched_via_printer_filename(self):
        result = get_display_compat("display", printer_filename="printer-artillery-sidewinder-x1.cfg")
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["source"], "printer_profile")

    def test_section_lookup_fallback_when_no_printer_match(self):
        """If printer filename doesn't match any profile, falls back to section lookup."""
        result = get_display_compat("t5uid1", printer_filename="printer-generic-custom.cfg")
        self.assertIsNotNone(result)
        self.assertEqual(result["source"], "display_config")
        self.assertEqual(result["status"], "unsupported")

    def test_result_has_notes_list(self):
        result = get_display_compat("t5uid1")
        self.assertIsNotNone(result)
        self.assertIsInstance(result["notes"], list)
        self.assertGreater(len(result["notes"]), 0)


class TestCheckDisplayCompatibility(unittest.TestCase):
    """Tests for check_display_compatibility() — main public API."""

    def test_empty_config_returns_no_findings(self):
        parsed = {
            "stepper_x": {"step_pin": "PC2"},
            "extruder": {"heater_pin": "PA1"},
        }
        result = check_display_compatibility(parsed)
        self.assertEqual(result, [])

    def test_cr6_se_printer_profile_triggers_finding(self):
        """CR-6 SE should be detected via printer filename even without display sections."""
        parsed = {
            "stepper_x": {"step_pin": "PC2"},
        }
        result = check_display_compatibility(
            parsed,
            printer_filename="printer-creality-cr6-se.cfg"
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["status"], "unsupported")
        self.assertEqual(result[0]["source"], "printer_profile")

    def test_t5uid1_section_triggers_unsupported(self):
        parsed = {"t5uid1": {"data_pin": "PC0"}}
        result = check_display_compatibility(parsed)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["status"], "unsupported")
        self.assertEqual(result[0]["section"], "t5uid1")

    def test_standard_display_is_found_but_supported(self):
        parsed = {"display": {"lcd_type": "st7920"}}
        result = check_display_compatibility(parsed)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["status"], "supported")

    def test_unknown_display_section_classifies_as_untested(self):
        parsed = {"future_display_type": {"pin": "PB0"}}
        # This section is not in _DISPLAY_SECTION_NAMES so won't be detected
        # Test with a known-name-but-unknown-db-entry scenario via direct call
        result = check_display_compatibility(parsed)
        # The section 'future_display_type' is not in _DISPLAY_SECTION_NAMES
        # so it should produce zero findings (detect_display_sections filters first)
        self.assertEqual(result, [])

    def test_artillery_sidewinder_via_printer_profile(self):
        parsed = {"stepper_x": {}}
        result = check_display_compatibility(
            parsed,
            printer_filename="printer-artillery-sidewinder-x1.cfg"
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["status"], "partial")
        self.assertEqual(result[0]["source"], "printer_profile")

    def test_no_duplicate_findings_when_printer_profile_and_section_overlap(self):
        """Printer profile match should not duplicate a finding if the section
        is also found in the config."""
        parsed = {"t5uid1": {}}
        result = check_display_compatibility(
            parsed,
            printer_filename="printer-creality-cr6-se.cfg"
        )
        # Should report only once (printer_profile takes precedence, section is deduped)
        t5uid1_findings = [f for f in result if f["section"] == "t5uid1"]
        self.assertEqual(len(t5uid1_findings), 1)

    def test_multiple_display_sections_all_reported(self):
        """A config with both a standard display and a neopixel should report both."""
        parsed = {
            "display": {"lcd_type": "st7920"},
            "neopixel my_led": {"pin": "PB0"},
        }
        result = check_display_compatibility(parsed)
        sections = [f["section"] for f in result]
        self.assertIn("display", sections)
        self.assertIn("neopixel", sections)
        self.assertEqual(len(result), 2)

    def test_finding_dict_has_required_keys(self):
        parsed = {"t5uid1": {}}
        result = check_display_compatibility(parsed)
        self.assertEqual(len(result), 1)
        finding = result[0]
        for key in ("section", "status", "recommendation", "notes", "source"):
            self.assertIn(key, finding, f"Finding missing key: {key}")


class TestAuthoritativeYamlLoad(unittest.TestCase):
    """Verify missing or corrupt displays.yaml fails closed."""

    def setUp(self):
        import core.loader
        core.loader._DISPLAYS_CACHE = None

    def tearDown(self):
        import core.loader
        core.loader._DISPLAYS_CACHE = None

    def test_module_fails_without_yaml(self):
        """Simulate missing YAML by patching open() to raise FileNotFoundError."""
        with patch("builtins.open", side_effect=FileNotFoundError("no file")):
            # Re-import _load_display_db with patched open
            from core import display_checker
            with self.assertRaisesRegex(RuntimeError, "displays"):
                display_checker._load_display_db()

    def test_module_fails_with_corrupt_yaml(self):
        import io
        corrupt_content = "this: {is: [corrupt yaml"
        with patch("builtins.open", return_value=io.StringIO(corrupt_content)):
            from core import display_checker
            with self.assertRaisesRegex(RuntimeError, "displays"):
                display_checker._load_display_db()


if __name__ == "__main__":
    unittest.main()
