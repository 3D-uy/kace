"""Tests for typed probe strategy resolution and legacy compatibility boundaries."""

import unittest

from core.custom_probe import GuidedCustomProbeSettings, parse_custom_probe_config
from core.exceptions import GenerationError
from core.probe_configuration import (
    PROBE_KIND_BLTOUCH,
    PROBE_KIND_CR_TOUCH,
    PROBE_KIND_CUSTOM,
    PROBE_KIND_INDUCTIVE,
    PROBE_KIND_NONE,
    apply_probe_compatibility_context,
    resolve_probe_configuration,
)


class TestProbeConfigurationStrategies(unittest.TestCase):
    def test_no_probe_strategy_has_no_generation_capabilities(self):
        probe = resolve_probe_configuration({"probe": "None"})
        self.assertEqual(probe.kind, PROBE_KIND_NONE)
        self.assertFalse(probe.uses_virtual_z_endstop)
        self.assertFalse(probe.generates_safe_z_home)
        self.assertFalse(probe.generates_bed_mesh)

    def test_all_predefined_legacy_labels_resolve_to_stable_kinds(self):
        cases = (
            ("BLTouch", PROBE_KIND_BLTOUCH, "bltouch"),
            ("CR-Touch", PROBE_KIND_CR_TOUCH, "bltouch"),
            ("Inductive", PROBE_KIND_INDUCTIVE, "probe"),
        )
        for label, kind, section in cases:
            with self.subTest(label=label):
                probe = resolve_probe_configuration({
                    "probe": label,
                    "probe_x_offset": "-12",
                    "probe_y_offset": "4.5",
                })
                self.assertEqual(probe.kind, kind)
                self.assertEqual(probe.structured_section_name, section)
                self.assertTrue(probe.uses_virtual_z_endstop)
                self.assertTrue(probe.generates_safe_z_home)
                self.assertTrue(probe.generates_bed_mesh)
                self.assertEqual(probe.resolved_offsets.x, -12.0)
                self.assertEqual(probe.resolved_offsets.y, 4.5)

    def test_custom_kind_uses_typed_offsets_and_ignores_display_label_for_selection(self):
        custom = parse_custom_probe_config(
            "[probe]\npin: ^PA1\nx_offset: -7\ny_offset: 3\nz_offset: -0.2\n"
        )
        probe = resolve_probe_configuration({
            "probe_kind": PROBE_KIND_CUSTOM,
            "probe": "legacy display value is not used for strategy selection",
            "custom_probe": custom,
        })
        self.assertEqual(probe.kind, PROBE_KIND_CUSTOM)
        self.assertEqual(probe.resolved_offsets.x, -7.0)
        self.assertEqual(probe.resolved_offsets.y, 3.0)
        self.assertEqual(probe.resolved_offsets.z, -0.2)
        self.assertEqual(probe.render_block(), custom.config_text)

    def test_guided_custom_payload_resolves_through_the_existing_strategy(self):
        custom = GuidedCustomProbeSettings(pin="^PA1", x_offset=-7, y_offset=3).to_config()
        probe = resolve_probe_configuration({
            "probe_kind": PROBE_KIND_CUSTOM,
            "custom_probe": custom,
        })
        self.assertEqual(probe.kind, PROBE_KIND_CUSTOM)
        self.assertEqual(probe.resolved_offsets.x, -7)
        self.assertEqual(probe.resolved_offsets.y, 3)
        self.assertIn("samples: 2", probe.render_block())

    def test_custom_compatibility_context_rejects_offset_drift(self):
        custom = parse_custom_probe_config("[probe]\npin: ^PA1\nx_offset: -7\ny_offset: 3\nz_offset: 0\n")
        probe = resolve_probe_configuration({"probe_kind": PROBE_KIND_CUSTOM, "custom_probe": custom})
        with self.assertRaises(GenerationError):
            apply_probe_compatibility_context(
                {"probe_x_offset": "0", "probe_y_offset": "3"}, probe
            )

    def test_custom_compatibility_context_derives_legacy_offsets_once(self):
        custom = parse_custom_probe_config("[probe]\npin: ^PA1\nx_offset: -7\ny_offset: 3\nz_offset: 0\n")
        probe = resolve_probe_configuration({"probe_kind": PROBE_KIND_CUSTOM, "custom_probe": custom})
        context = {}
        apply_probe_compatibility_context(context, probe)
        self.assertEqual(context["probe"], "Custom Probe")
        self.assertEqual(context["probe_x_offset"], "-7")
        self.assertEqual(context["probe_y_offset"], "3")
        self.assertTrue(context["probe_uses_virtual_z_endstop"])
