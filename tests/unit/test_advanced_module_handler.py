import unittest
from unittest.mock import patch
from core.advanced_module_handler import get_advanced_sections, is_unsupported_section, _render_block

class TestAdvancedModuleHandler(unittest.TestCase):
    def test_get_advanced_sections(self):
        # Test custom parsed_data
        parsed_data = {
            "neopixel my_led": {
                "pin": "PA1",
                "chain_count": "10",
                "new_field_not_in_schema": "some_value"
            },
            "stepper_x": {
                "step_pin": "PC2"
            }
        }
        blocks = get_advanced_sections(parsed_data)
        self.assertEqual(len(blocks), 1)
        # Verify known fields are preserved and order is correct
        self.assertIn("# pin: PA1", blocks[0])
        self.assertIn("# chain_count: 10", blocks[0])
        
        # Verify unknown fields survive (wildcard preservation TD-001)
        self.assertIn("# new_field_not_in_schema: some_value", blocks[0])

        # Verify deterministic order: pin, chain_count, color_order, initial_red, initial_green, initial_blue, initial_white, then new_field_not_in_schema
        # Let's extract the order of fields emitted in the output block
        lines = [line.strip() for line in blocks[0].split('\n') if line.startswith("# ") and ":" in line]
        keys = [line.split(":")[0][2:].strip() for line in lines]
        self.assertEqual(keys, ["pin", "chain_count", "new_field_not_in_schema"])

    def test_schema_without_wildcard(self):
        # Verify wildcard support does not alter current behavior for modules without "*"
        schema = {
            "section_prefix": "custom_module",
            "passthrough": True,
            "banner": "Custom Module Banner",
            "note": "Custom note",
            "fields": ["pin", "chain_count"] # NO wildcard "*"
        }
        fields = {
            "pin": "PC5",
            "chain_count": "5",
            "unknown_field": "discard_me"
        }
        block = _render_block("custom_module", fields, schema)
        self.assertIn("# pin: PC5", block)
        self.assertIn("# chain_count: 5", block)
        self.assertNotIn("unknown_field", block)

    def test_is_unsupported_section(self):
        self.assertTrue(is_unsupported_section("resonance_tester"))
        self.assertFalse(is_unsupported_section("neopixel"))
        self.assertFalse(is_unsupported_section("unknown_section"))

if __name__ == "__main__":
    unittest.main()
