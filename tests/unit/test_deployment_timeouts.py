"""Regressions for finite, stage-specific deployment deadlines."""

from __future__ import annotations

import math
import unittest

from core.moonraker_deployer import DeploymentTimeouts


class DeploymentTimeoutTests(unittest.TestCase):
    def test_default_deployment_timeouts_are_all_finite_and_positive(self):
        timeouts = DeploymentTimeouts.from_env({})

        for value in (
            timeouts.mcu_disconnect_s,
            timeouts.mcu_reenumeration_s,
            timeouts.moonraker_s,
            timeouts.klipper_ready_s,
            timeouts.mcu_registration_s,
        ):
            self.assertTrue(math.isfinite(value))
            self.assertGreater(value, 0)

    def test_every_deployment_stage_timeout_is_independently_configurable(self):
        environment = {
            "KACE_TIMEOUT_MCU_DISCONNECT_S": "11",
            "KACE_TIMEOUT_MCU_REENUMERATION_S": "12",
            "KACE_TIMEOUT_MOONRAKER_S": "13",
            "KACE_TIMEOUT_KLIPPER_READY_S": "14",
            "KACE_TIMEOUT_MCU_REGISTRATION_S": "15",
        }

        timeouts = DeploymentTimeouts.from_env(environment)

        self.assertEqual(timeouts.mcu_disconnect_s, 11)
        self.assertEqual(timeouts.mcu_reenumeration_s, 12)
        self.assertEqual(timeouts.moonraker_s, 13)
        self.assertEqual(timeouts.klipper_ready_s, 14)
        self.assertEqual(timeouts.mcu_registration_s, 15)

    def test_invalid_stage_timeout_configuration_fails_closed(self):
        for value in ("0", "-1", "nan", "inf", "invalid"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "KACE_TIMEOUT_MOONRAKER_S"):
                    DeploymentTimeouts.from_env({"KACE_TIMEOUT_MOONRAKER_S": value})
