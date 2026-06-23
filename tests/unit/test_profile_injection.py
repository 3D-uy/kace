"""
tests/unit/test_profile_injection.py
=====================================
Priority-2 coverage for printer-profile injection safety.

Tests what happens when a printer profile contains sections that do NOT
exist in the base board config (e.g. [adxl345], [resonance_tester]).

The wizard merge loop (core/wizard/__init__.py) copies every section from
the profile's parsed data directly into board_parsed:

    for section, section_data in profile_parsed.items():
        if section not in board_parsed:
            board_parsed[section] = {}            # ← injection point
        for key, value in section_data.items():
            board_parsed[section][key] = value

After injection, the generate_config() Jinja2 pipeline runs.  Whether
the injected section ends up as ACTIVE or COMMENTED in the output depends
entirely on the advanced_module_handler routing.

This test suite validates:
  1. adxl345 (passthrough=True)  → always rendered as a COMMENTED block,
     never as an active [adxl345] section.
  2. resonance_tester (passthrough=False) → flagged as unsupported;
     must NOT appear as an active section.
  3. Completely unknown injected sections → silently absent from output;
     no active block emitted.
  4. The wizard merge correctly propagates profile values into board_parsed.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from core.advanced_module_handler import (
    get_advanced_sections,
    is_unsupported_section,
)

# jinja2 is only available in Docker — guard generation tests.
try:
    import jinja2  # noqa: F401
    _JINJA2_AVAILABLE = True
except ImportError:
    _JINJA2_AVAILABLE = False

_skip_no_jinja2 = unittest.skipUnless(
    _JINJA2_AVAILABLE,
    "jinja2 not installed — generation tests run in Docker only",
)


# ── Minimal board_parsed fixture ─────────────────────────────────────────────
# Represents a board that has no accelerometer or resonance-tester sections.

_BARE_BOARD_PARSED = {
    "printer":     {"kinematics": "cartesian", "max_velocity": "300"},
    "stepper_x":   {"step_pin": "P2.2",  "dir_pin": "!P2.6", "enable_pin": "!P2.1",
                    "microsteps": "16",   "rotation_distance": "40",
                    "endstop_pin": "P1.29", "position_endstop": "0",
                    "position_max": "235"},
    "stepper_y":   {"step_pin": "P0.19", "dir_pin": "P0.20",  "enable_pin": "!P2.8",
                    "microsteps": "16",   "rotation_distance": "40",
                    "endstop_pin": "P1.28", "position_endstop": "0",
                    "position_max": "235"},
    "stepper_z":   {"step_pin": "P0.22", "dir_pin": "!P2.11", "enable_pin": "!P0.21",
                    "microsteps": "16",   "rotation_distance": "8",
                    "endstop_pin": "P1.25", "position_endstop": "0",
                    "position_max": "250"},
    "extruder":    {"step_pin": "P2.13", "dir_pin": "!P0.11", "enable_pin": "!P2.12",
                    "microsteps": "16",   "rotation_distance": "33.5",
                    "nozzle_diameter": "0.400", "filament_diameter": "1.750",
                    "heater_pin": "P2.7", "sensor_type": "Generic 3950",
                    "sensor_pin": "P0.24", "control": "pid",
                    "pid_Kp": "22.2",     "pid_Ki": "1.08",   "pid_Kd": "114",
                    "min_temp": "0",      "max_temp": "260"},
    "heater_bed":  {"heater_pin": "P2.5", "sensor_type": "Generic 3950",
                    "sensor_pin": "P0.25", "control": "pid",
                    "pid_Kp": "54.027",   "pid_Ki": "0.770",  "pid_Kd": "948.182",
                    "min_temp": "0",      "max_temp": "130"},
    "bltouch":     {"sensor_pin": "^P0.10", "control_pin": "P2.0"},
}

# Profile-supplied accelerometer sections that are NOT on the base board.
_ADXL345_SECTION    = {"cs_pin": "PE11", "spi_bus": "spi4"}
_RESONANCE_SECTION  = {"accel_chip": "adxl345", "probe_points": "117,117,20"}
_UNKNOWN_SECTION    = {"some_key": "some_value"}   # totally unknown to KACE

# Minimal user_data for the generator tests
_USER_DATA = {
    "board":              "generic-bigtreetech-skr-v1.4.cfg",
    "kinematics":         "cartesian",
    "x_size":             "235",
    "y_size":             "235",
    "z_size":             "250",
    "probe":              "BLTouch",
    "probe_x_offset":     "0",
    "probe_y_offset":     "0",
    "hotend_thermistor":  "Generic 3950",
    "bed_thermistor":     "Generic 3950",
    "driver_type":        "TMC2209",
    "driver_mode":        "UART",
    "web_interface":      "Mainsail",
    "z_motors":           "1",
    "mcu_path":           "/dev/serial/by-id/mock",
}


# ── Advanced module handler unit tests ───────────────────────────────────────

class TestAdvancedModulePassthrough(unittest.TestCase):
    """get_advanced_sections() and is_unsupported_section() behaviour
    when profile sections are present in parsed_data after merge."""

    # ── adxl345 (passthrough=True) ────────────────────────────────────────────

    def test_adxl345_produces_commented_block_not_active_header(self):
        """After merge, adxl345 in parsed_data must produce a COMMENTED block —
        the section header must be '# [adxl345]', never an active '[adxl345]'."""
        parsed = dict(_BARE_BOARD_PARSED)
        parsed["adxl345"] = dict(_ADXL345_SECTION)

        blocks = get_advanced_sections(parsed)

        self.assertTrue(blocks, "get_advanced_sections should return at least one block")
        adxl_block = next((b for b in blocks if "adxl345" in b.lower()), None)
        self.assertIsNotNone(adxl_block, "Expected an adxl345 block in the output")

        # Must appear as a commented header, never as an active section
        self.assertIn("# [adxl345]", adxl_block,
                      "adxl345 must be commented out, not active")
        self.assertNotIn("[adxl345]", adxl_block.replace("# [adxl345]", ""),
                         "Active [adxl345] header must not appear in the passthrough block")

    def test_adxl345_block_contains_preserved_pin_data(self):
        """The cs_pin and spi_bus values from the profile must be present in
        the commented block so the user can uncomment and use them."""
        parsed = dict(_BARE_BOARD_PARSED)
        parsed["adxl345"] = dict(_ADXL345_SECTION)

        blocks = get_advanced_sections(parsed)
        adxl_block = next((b for b in blocks if "adxl345" in b.lower()), "")

        self.assertIn("PE11", adxl_block,   "cs_pin value must be preserved")
        self.assertIn("spi4", adxl_block,   "spi_bus value must be preserved")

    # ── resonance_tester (passthrough=False) ──────────────────────────────────

    def test_resonance_tester_is_flagged_as_unsupported(self):
        """resonance_tester has passthrough=False — it must be classified as
        an unsupported section, not silently passed through as commented."""
        self.assertTrue(
            is_unsupported_section("resonance_tester"),
            "resonance_tester should be classified as unsupported (passthrough=False)",
        )

    def test_resonance_tester_does_not_produce_passthrough_block(self):
        """Even if resonance_tester is injected into parsed_data, it must NOT
        produce a passthrough block (passthrough=False means it is filtered out)."""
        parsed = dict(_BARE_BOARD_PARSED)
        parsed["resonance_tester"] = dict(_RESONANCE_SECTION)

        blocks = get_advanced_sections(parsed)
        resonance_blocks = [b for b in blocks if "resonance_tester" in b.lower()]

        self.assertEqual(
            resonance_blocks, [],
            "resonance_tester (passthrough=False) must not produce any passthrough block",
        )

    # ── Unknown/custom sections ───────────────────────────────────────────────

    def test_completely_unknown_section_produces_no_advanced_block(self):
        """A section that matches no schema (e.g. [custom_thing]) must be
        silently ignored by the advanced module handler."""
        parsed = dict(_BARE_BOARD_PARSED)
        parsed["custom_thing"] = dict(_UNKNOWN_SECTION)

        blocks = get_advanced_sections(parsed)
        unknown_blocks = [b for b in blocks if "custom_thing" in b.lower()]

        self.assertEqual(
            unknown_blocks, [],
            "Completely unknown sections must produce no advanced passthrough block",
        )

    # ── Board without any advanced sections ───────────────────────────────────

    def test_bare_board_with_no_advanced_sections_returns_empty_list(self):
        """A board config with only standard Klipper sections must produce no
        advanced blocks — get_advanced_sections returns []."""
        blocks = get_advanced_sections(_BARE_BOARD_PARSED)
        self.assertEqual(blocks, [])


# ── Wizard merge injection simulation ────────────────────────────────────────

class TestProfileMergeInjection(unittest.TestCase):
    """Validates the wizard merge loop's behaviour when profile_parsed
    contains sections absent from board_parsed."""

    def _simulate_wizard_merge(self, board_parsed: dict, profile_parsed: dict) -> dict:
        """Mirror the merge loop from core/wizard/__init__.py."""
        import copy
        merged = copy.deepcopy(board_parsed)
        for section, section_data in profile_parsed.items():
            if section not in merged:
                merged[section] = {}
            for key, value in section_data.items():
                merged[section][key] = value
        return merged

    def test_profile_values_update_existing_board_sections(self):
        """Profile values for sections that ALREADY exist in board_parsed
        must override the board values (profiles are authoritative for their keys)."""
        profile_parsed = {
            "extruder": {"sensor_type": "NTC 100K MGB18-104F39050L32"},
        }
        merged = self._simulate_wizard_merge(_BARE_BOARD_PARSED, profile_parsed)

        self.assertEqual(
            merged["extruder"]["sensor_type"],
            "NTC 100K MGB18-104F39050L32",
            "Profile sensor_type should override the board default",
        )

    def test_profile_only_sections_are_injected_into_merged_dict(self):
        """Sections present in the profile but absent from the board must be
        added to the merged dict — this is the injection that advanced_module_handler
        must subsequently route correctly."""
        profile_parsed = {"adxl345": dict(_ADXL345_SECTION)}
        merged = self._simulate_wizard_merge(_BARE_BOARD_PARSED, profile_parsed)

        self.assertIn("adxl345", merged,
                      "Profile-only section should be present in merged board_parsed")
        self.assertEqual(merged["adxl345"]["cs_pin"], "PE11")

    def test_injected_adxl345_is_captured_by_advanced_module_handler(self):
        """After the wizard merge, an injected adxl345 section must be
        correctly captured by get_advanced_sections() — meaning the passthrough
        routing works end-to-end from profile injection to commented output."""
        profile_parsed = {"adxl345": dict(_ADXL345_SECTION)}
        merged = self._simulate_wizard_merge(_BARE_BOARD_PARSED, profile_parsed)

        blocks = get_advanced_sections(merged)
        adxl_blocks = [b for b in blocks if "adxl345" in b.lower()]

        self.assertTrue(
            adxl_blocks,
            "Injected adxl345 from profile merge must be captured by advanced_module_handler",
        )
        self.assertIn("# [adxl345]", adxl_blocks[0])

    def test_injected_resonance_tester_not_in_advanced_blocks(self):
        """resonance_tester injected from a profile must not appear in the
        passthrough block list (passthrough=False)."""
        profile_parsed = {"resonance_tester": dict(_RESONANCE_SECTION)}
        merged = self._simulate_wizard_merge(_BARE_BOARD_PARSED, profile_parsed)

        blocks = get_advanced_sections(merged)
        resonance = [b for b in blocks if "resonance_tester" in b.lower()]

        self.assertEqual(resonance, [],
                         "resonance_tester must not appear in passthrough blocks")


# ── Generation-level injection tests (require jinja2) ─────────────────────────

@_skip_no_jinja2
class TestProfileInjectionInGeneratedConfig(unittest.TestCase):
    """Validates that the generate_config() Jinja2 pipeline does NOT render
    injected advanced sections as active Klipper config entries."""

    def setUp(self):
        from core.generator import generate_config
        self._generate = generate_config

    def _run_generation(self, extra_sections: dict) -> str:
        """Merge extra_sections into board_parsed and run generate_config.
        Returns the rendered config text."""
        import copy
        parsed = copy.deepcopy(_BARE_BOARD_PARSED)
        parsed.update(extra_sections)
        user_data = dict(_USER_DATA)
        result = self._generate(parsed, user_data)
        return result.get("content", "")

    def test_injected_adxl345_not_rendered_as_active_section(self):
        """[adxl345] from a profile injection must NEVER appear as an active
        (uncommented) Klipper section in the generated printer.cfg output."""
        content = self._run_generation({"adxl345": dict(_ADXL345_SECTION)})

        # The active section header must not appear anywhere in the output
        lines = content.splitlines()
        active_headers = [l.strip() for l in lines if l.strip() == "[adxl345]"]
        self.assertEqual(
            active_headers, [],
            "Active [adxl345] section must not appear in generated config — "
            "it should be commented out or absent entirely. "
            "If this fails, the profile injection safety gap is confirmed.",
        )

    def test_injected_adxl345_appears_commented_in_output(self):
        """If adxl345 is injected via a profile, the advanced_module_handler
        should emit it as a '# [adxl345]' commented block."""
        content = self._run_generation({"adxl345": dict(_ADXL345_SECTION)})

        # The commented header is the correct passthrough representation
        self.assertIn(
            "# [adxl345]", content,
            "adxl345 should be preserved as a commented passthrough block in the output",
        )

    def test_injected_resonance_tester_absent_from_output(self):
        """resonance_tester (passthrough=False) must be completely absent
        from the generated output — neither active nor commented."""
        content = self._run_generation({"resonance_tester": dict(_RESONANCE_SECTION)})

        self.assertNotIn(
            "[resonance_tester]", content,
            "resonance_tester must not appear in any form in generated output",
        )

    def test_injected_unknown_section_not_in_output(self):
        """A totally unknown profile section must not appear in the generated
        output — the template must not blindly iterate all of parsed_data."""
        content = self._run_generation({"custom_firmware_plugin": _UNKNOWN_SECTION})

        self.assertNotIn(
            "[custom_firmware_plugin]", content,
            "Unknown injected sections must never appear in generated config",
        )


if __name__ == '__main__':
    unittest.main()
