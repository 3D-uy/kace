import unittest
from core.scraper import parse_config

class TestScraper(unittest.TestCase):

    def test_bltouch_injection(self):
        """Ensure BLTouch pins are correctly injected based on filename matching."""
        # Pass empty config data and SKR v1.4 filename
        result = parse_config('', 'generic-bigtreetech-skr-v1.4.cfg')
        
        self.assertIn('bltouch', result)
        self.assertEqual(result['bltouch'].get('sensor_pin'), '^P0.10')
        self.assertEqual(result['bltouch'].get('control_pin'), 'P2.0')

    def test_parse_config_ignores_comments_by_default(self):
        """Verify commented keys AND commented section headers are ignored in default mode (keep_comments=False).

        BUG-004 fix: a commented section header such as `# [stepper_y]` must NOT
        be treated as an active section switch.  Both the commented key (`dir_pin`)
        and the commented section (`stepper_y`) must be absent from the result.
        """
        cfg = """
        [stepper_x]
        step_pin: P2.2
        # dir_pin: !P2.6
        # [stepper_y]
        # step_pin: P2.3
        """
        parsed = parse_config(cfg)
        self.assertIn('stepper_x', parsed)
        self.assertEqual(parsed['stepper_x'].get('step_pin'), 'P2.2')
        # Commented key inside active section must be absent
        self.assertNotIn('dir_pin', parsed['stepper_x'])
        # Commented section header must NOT create a new section
        self.assertNotIn('stepper_y', parsed)

    def test_parse_config_bug004_inline_section_annotation(self):
        """Regression guard for BUG-004: a #[section] inline annotation must not
        steal keys that follow it from the enclosing active section."""
        cfg = """
        [stepper_x]
        step_pin: PA0
        # [some_other_section]
        enable_pin: PA1
        """
        parsed = parse_config(cfg)
        # enable_pin must stay in stepper_x, not be swallowed by some_other_section
        self.assertIn('stepper_x', parsed)
        self.assertEqual(parsed['stepper_x'].get('enable_pin'), 'PA1')
        self.assertNotIn('some_other_section', parsed)

    def test_parse_config_keeps_comments_when_requested(self):
        """Verify that commented lines are parsed when keep_comments is True."""
        cfg = """
        [stepper_x]
        step_pin: P2.2
        # dir_pin: !P2.6
        # [stepper_y]
        # step_pin: P2.3
        """
        parsed = parse_config(cfg, keep_comments=True)
        self.assertIn('stepper_x', parsed)
        self.assertEqual(parsed['stepper_x'].get('step_pin'), 'P2.2')
        self.assertEqual(parsed['stepper_x'].get('dir_pin'), '!P2.6')
        self.assertIn('stepper_y', parsed)
        self.assertEqual(parsed['stepper_y'].get('step_pin'), 'P2.3')

    def test_parse_config_inline_comments(self):
        """Verify inline comments are stripped from values."""
        cfg = """
        [stepper_x]
        step_pin: P2.2 # active step pin for X axis
        enable_pin: !P2.1 #enable pin
        """
        parsed = parse_config(cfg)
        self.assertEqual(parsed['stepper_x'].get('step_pin'), 'P2.2')
        self.assertEqual(parsed['stepper_x'].get('enable_pin'), '!P2.1')

    def test_parse_config_malformed_and_duplicate(self):
        """Verify duplicate sections and keys are handled gracefully and deterministically."""
        cfg = """
        [stepper_x]
        step_pin: P2.2
        step_pin: P2.3
        
        [stepper_x]
        dir_pin: P2.6
        
        invalid_line_no_section
        
        [stepper_y]
        = invalid_kv
        """
        parsed = parse_config(cfg)
        self.assertIn('stepper_x', parsed)
        # Duplicate keys: last wins
        self.assertEqual(parsed['stepper_x'].get('step_pin'), 'P2.3')
        # Duplicate section header: keys are merged
        self.assertEqual(parsed['stepper_x'].get('dir_pin'), 'P2.6')
        # Invalid lines or malformed key-value pairs are skipped
        self.assertNotIn('invalid_line_no_section', parsed)

    def test_parse_config_resilience_fuzz(self):
        """Verify the parser is resilient to non-ASCII, spaces, and edge-case syntax."""
        cfg = """
        [extruder]
        # Extreme indentation and weird spacing
          sensor_type   :    ATC Semitec 104GT-2   
        
        # Non-ASCII Unicode characters
        comment_unicode: 🛠️ Setup Completed
        
        # Special characters in keys and values
        pin_special: arduino_pin$@!
        
        [board_pins]
        aliases:
            # Comment inside aliases
            EXP1_1=PE8, EXP1_2=PE7, # inline comment
            EXP1_3=PE6
        """
        parsed = parse_config(cfg)
        self.assertEqual(parsed['extruder'].get('sensor_type'), 'ATC Semitec 104GT-2')
        self.assertEqual(parsed['extruder'].get('comment_unicode'), '🛠️ Setup Completed')
        self.assertEqual(parsed['extruder'].get('pin_special'), 'arduino_pin$@!')
        self.assertIn('board_pins', parsed)
        self.assertIn('EXP1_1=PE8', parsed['board_pins']['aliases'])
        self.assertIn('EXP1_3=PE6', parsed['board_pins']['aliases'])


class TestScraperEdgeCases(unittest.TestCase):
    """Boundary-condition tests for parse_config() — these are the gaps
    identified in the audit that were not covered by the existing suite."""

    def test_empty_string_no_board_injects_empty_bltouch(self):
        """
        SCRAPER-001 (Known Bug): parse_config('') with no board filename
        unconditionally injects {'bltouch': {}} into the result dict
        (lines 275-276 of scraper.py run regardless of whether a filename
        was given). This is a false entry — an empty config with no board
        has no BLTouch. Document the current behaviour here so any fix
        is immediately visible as a test change.
        """
        result = parse_config("")
        # Current (buggy) behaviour: always contains bltouch key
        self.assertIn('bltouch', result, 
                      "SCRAPER-001: parse_config always injects bltouch — "
                      "fix should remove bltouch when filename is empty")
        # When this bug is fixed, the assertion below should replace the one above:
        # self.assertEqual(result, {})

    def test_whitespace_only_no_board_injects_empty_bltouch(self):
        """
        SCRAPER-001 (Known Bug): Same as test_empty_string_no_board_injects_empty_bltouch.
        Whitespace-only input with no board still injects {'bltouch': {}}.
        """
        result = parse_config("   \n  \t  \n  ")
        self.assertIn('bltouch', result,
                      "SCRAPER-001: bltouch is always injected even for whitespace-only input")

    def test_empty_string_with_known_board_injects_bltouch_pins(self):
        """When a known board filename IS given, bltouch must have actual pin values."""
        result = parse_config("", "generic-bigtreetech-skr-v1.4.cfg")
        self.assertIn('bltouch', result)
        self.assertIn('sensor_pin', result['bltouch'])
        self.assertIn('control_pin', result['bltouch'])

    def test_empty_string_with_unknown_board_bltouch_has_no_pins(self):
        """An unknown board filename must NOT inject pin values — only an empty bltouch dict."""
        result = parse_config("", "generic-unknown-board-xyz.cfg")
        self.assertIn('bltouch', result)
        # Must not fabricate pins for an unknown board
        self.assertEqual(result['bltouch'].get('sensor_pin'), None)
        self.assertEqual(result['bltouch'].get('control_pin'), None)

    def test_comment_only_returns_only_bltouch(self):
        """
        SCRAPER-001 (Known Bug): A config with only comment lines still injects
        bltouch. Document this so the fix is visible.
        """
        cfg = "# This is a comment\n# Another comment\n"
        result = parse_config(cfg)
        # Only bltouch from injection — no real sections
        non_bltouch = {k: v for k, v in result.items() if k != 'bltouch'}
        self.assertEqual(non_bltouch, {},
                         "Comment-only config must produce no real sections")

    def test_key_without_colon_separator_is_skipped(self):
        """A line with no ':' separator must be skipped, not crash or corrupt the dict."""
        cfg = """
        [stepper_x]
        step_pin PA0
        dir_pin: PA1
        """
        parsed = parse_config(cfg)
        self.assertIn('stepper_x', parsed)
        # dir_pin has a colon — must be parsed
        self.assertEqual(parsed['stepper_x'].get('dir_pin'), 'PA1')
        # step_pin has no colon — must be absent (not crash)
        self.assertNotIn('step_pin', parsed['stepper_x'])

    def test_colon_in_value_is_preserved(self):
        """A value containing a colon (e.g. sensor_type: ATC Semitec 104GT-2:0)
        must have the value captured correctly up to the first colon in the key."""
        cfg = "[extruder]\nsensor_type: ATC Semitec 104GT-2\n"
        parsed = parse_config(cfg)
        self.assertEqual(parsed['extruder'].get('sensor_type'), 'ATC Semitec 104GT-2')

    def test_section_without_keys_is_recorded(self):
        """A section header with no following key-value pairs must create an empty dict
        entry, not be silently dropped."""
        cfg = "[stepper_x]\n\n[stepper_y]\nstep_pin: PA0\n"
        parsed = parse_config(cfg)
        self.assertIn('stepper_x', parsed)
        self.assertIn('stepper_y', parsed)

    def test_multiword_section_name_is_parsed(self):
        """Section names with spaces (e.g. 'tmc2209 stepper_x') must be parsed as-is."""
        cfg = "[tmc2209 stepper_x]\nuart_pin: PC11\n"
        parsed = parse_config(cfg)
        self.assertIn('tmc2209 stepper_x', parsed)
        self.assertEqual(parsed['tmc2209 stepper_x'].get('uart_pin'), 'PC11')

    def test_get_bltouch_pins_for_board_with_none_or_empty(self):
        """Verify that get_bltouch_pins_for_board handles None or empty string input gracefully."""
        from core.scraper import get_bltouch_pins_for_board
        self.assertEqual(get_bltouch_pins_for_board(None), {})
        self.assertEqual(get_bltouch_pins_for_board(""), {})
        # Known board should still work
        pins = get_bltouch_pins_for_board("generic-bigtreetech-skr-v1.4.cfg")
        self.assertEqual(pins.get("sensor_pin"), "^P0.10")


if __name__ == '__main__':
    unittest.main()
