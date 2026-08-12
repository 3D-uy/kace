import json
import tempfile
import unittest
from pathlib import Path

from core.power_config import (
    POWER_SCHEMA,
    PowerConfigError,
    load_power_config,
    power_config_from_mapping,
)


def versioned(**overrides):
    data = {
        "schema": POWER_SCHEMA,
        "revision": 3,
        "enabled": True,
        "device": "main_psu",
        "pin": "gpiochip0/gpio20",
        "active_low": True,
        "initial_state": "on",
        "restart_klipper_when_powered": True,
        "off_when_shutdown": False,
    }
    data.update(overrides)
    return data


class TestPowerConfig(unittest.TestCase):
    def test_versioned_power_contract_is_validated(self):
        config = power_config_from_mapping(versioned())
        self.assertEqual(config.schema, POWER_SCHEMA)
        self.assertEqual(config.revision, 3)
        self.assertEqual(config.device, "main_psu")
        self.assertEqual(config.moonraker_pin(), "!gpiochip0/gpio20")

    def test_disabled_contract_cannot_retain_device_or_pin(self):
        with self.assertRaisesRegex(PowerConfigError, "disabled"):
            power_config_from_mapping(versioned(enabled=False))
        disabled = power_config_from_mapping(
            versioned(enabled=False, device=None, pin=None)
        )
        self.assertFalse(disabled.enabled)

    def test_legacy_identity_is_read_only_migration_input(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "power.json"
            target.write_text(
                '{"schema":1,"enabled":true,"device":"printer"}',
                encoding="utf-8",
            )
            previous = load_power_config(target)
            self.assertTrue(previous.legacy)
            self.assertEqual(previous.device, "printer")
            with self.assertRaisesRegex(PowerConfigError, "legacy"):
                previous.validated()

    def test_malformed_legacy_enabled_does_not_silently_become_disabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "power.json"
            target.write_text(
                '{"schema":1,"enabled":"true","device":"printer"}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(PowerConfigError, "boolean"):
                load_power_config(target)

    def test_malformed_versioned_contract_fails_closed(self):
        mutations = (
            {"revision": 0},
            {"pin": "!gpiochip0/gpio20"},
            {"active_low": "true"},
            {"initial_state": "maybe"},
            {"device": "bad name"},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                with self.assertRaises(PowerConfigError):
                    power_config_from_mapping(versioned(**mutation))

    def test_missing_power_json_maps_to_explicit_disabled_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_power_config(Path(tmpdir) / "missing.json")
        self.assertFalse(config.enabled)
        self.assertEqual(
            json.loads(json.dumps(config.to_mapping()))["schema"],
            POWER_SCHEMA,
        )


if __name__ == "__main__":
    unittest.main()
