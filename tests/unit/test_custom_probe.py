"""Offline tests for custom probe parsing and typed configuration handling."""

import unittest

from core.custom_probe import (
    CustomProbeValidationError,
    GUIDED_PROBE_DEFAULTS,
    GuidedCustomProbeSettings,
    parse_custom_probe_config,
)


class TestCustomProbeParsing(unittest.TestCase):
    def test_guided_defaults_render_a_minimal_valid_probe_section(self):
        settings = GuidedCustomProbeSettings(pin="^PA1", x_offset=-12, y_offset=4)
        config = settings.to_config()

        self.assertIsNone(settings.z_offset)
        self.assertEqual(settings.samples, GUIDED_PROBE_DEFAULTS["samples"])
        self.assertIn("[probe]\npin: ^PA1\nx_offset: -12\ny_offset: 4", config.config_text)
        self.assertNotIn("z_offset:", config.config_text)
        self.assertIn("samples: 2", config.config_text)
        self.assertIn("samples_result: median", config.config_text)

    def test_guided_settings_validate_required_and_conservative_fields(self):
        with self.assertRaises(CustomProbeValidationError):
            GuidedCustomProbeSettings(pin="", x_offset=0, y_offset=0)
        with self.assertRaises(CustomProbeValidationError):
            GuidedCustomProbeSettings(pin="PA1", x_offset=0, y_offset=0, samples=0)
        with self.assertRaises(CustomProbeValidationError):
            GuidedCustomProbeSettings(pin="PA1", x_offset=0, y_offset=0, speed=0)
        with self.assertRaises(CustomProbeValidationError):
            GuidedCustomProbeSettings(pin="PA1", x_offset=0, y_offset=0, samples_result="last")

    def test_guided_settings_include_optional_z_offset_once_when_supplied(self):
        config = GuidedCustomProbeSettings(
            pin="^PC14", x_offset=10, y_offset=-4, z_offset=-0.25
        ).to_config()
        self.assertEqual(config.z_offset, -0.25)
        self.assertEqual(config.config_text.count("z_offset:"), 1)
    def test_valid_probe_extracts_all_offsets_and_preserves_text(self):
        config = """# A user-maintained probe block
[probe]
pin: ^PA1
x_offset: -38.5
y_offset: 2
z_offset: -1.25
samples: 3  # unknown option retained
"""
        model = parse_custom_probe_config(config)

        self.assertEqual(model.primary_section, "probe")
        self.assertEqual(model.x_offset, -38.5)
        self.assertEqual(model.y_offset, 2.0)
        self.assertEqual(model.z_offset, -1.25)
        self.assertEqual(model.config_text, config)

    def test_valid_dockable_probe_and_related_macros_are_preserved(self):
        config = """[dockable_probe]
pin: ^PC14
x_offset: 10
y_offset: -4
dock_position: 245, 15, 20

[gcode_macro ATTACH_PROBE]
gcode:
  # keep this macro exactly as supplied
  G90
  G1 X245 Y15 F6000

[gcode_macro DETACH_PROBE]
gcode:
  G1 X230 Y15 F6000
"""
        model = parse_custom_probe_config(config)

        self.assertEqual(model.primary_section, "dockable_probe")
        self.assertEqual(model.x_offset, 10.0)
        self.assertIn("[gcode_macro ATTACH_PROBE]", model.config_text)
        self.assertIn("# keep this macro exactly as supplied", model.config_text)

    def test_klackender_style_macros_are_not_special_cased_or_rewritten(self):
        config = """[dockable_probe]
pin: ^PC14
x_offset: -17
y_offset: 24
z_offset: 0

[gcode_macro _KLACK_ATTACH]
gcode:
  G1 X10 Y20 F6000

[gcode_macro _KLACK_DOCK]
gcode:
  G1 X5 Y5 F6000
"""
        model = parse_custom_probe_config(config)

        self.assertEqual(model.config_text, config)
        self.assertIn("_KLACK_ATTACH", model.config_text)
        self.assertIn("_KLACK_DOCK", model.config_text)

    def test_missing_offsets_are_added_once_only_after_user_supplies_them(self):
        model = parse_custom_probe_config("[probe]\npin: ^PA1\nx_offset: -5\n")
        self.assertTrue(model.requires_offset_prompt)

        completed = model.with_missing_offsets(y_offset="3.5")
        self.assertEqual(completed.x_offset, -5.0)
        self.assertEqual(completed.y_offset, 3.5)
        self.assertEqual(completed.config_text.count("x_offset:"), 1)
        self.assertEqual(completed.config_text.count("y_offset:"), 1)

    def test_duplicate_offsets_are_rejected(self):
        with self.assertRaises(CustomProbeValidationError):
            parse_custom_probe_config("[probe]\nx_offset: 0\nx_offset: 1\ny_offset: 0\n")

    def test_empty_malformed_and_unrelated_blocks_are_rejected(self):
        invalid_configs = (
            "",
            "[probe\npin: PA1",
            "pin: PA1\n[probe]",
            "[mcu]\nserial: /dev/ttyUSB0",
            "[probe]\npin: PA1\n\n[stepper_x]\nstep_pin: PA2",
            "[gcode_shell_command unsafe]\ncommand: rm -rf /",
            "[probe]\npin: PA1\n\n[safe_z_home]\nhome_xy_position: 0, 0",
            "[probe]\npin: PA1\n\n[bed_mesh]\nmesh_min: 0, 0",
        )
        for config in invalid_configs:
            with self.subTest(config=config):
                with self.assertRaises(CustomProbeValidationError):
                    parse_custom_probe_config(config)
