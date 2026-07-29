"""Offline tests for the SD-card firmware verification follow-up."""

import unittest
from unittest.mock import patch

from core.firmware_flash import verify_sd_card_flash
from core.moonraker_deployer import DeployState


class TestSdCardFirmwareVerification(unittest.TestCase):
    @patch("core.firmware_flash.get_mcu_versions")
    @patch("core.firmware_flash.get_klipper_state")
    def test_disconnect_reconnect_and_matching_fingerprint_succeeds(
        self, mock_state, mock_versions
    ):
        mock_state.side_effect = ["disconnected", "shutdown", "ready"]
        mock_versions.return_value = {"mcu": "kace-new123"}

        result = verify_sd_card_flash(
            expected_version="kace-new123",
            disconnect_cooldown_s=0,
            disconnect_timeout_s=0.01,
            reconnect_timeout_s=0.05,
            poll_interval_s=0.001,
        )

        self.assertEqual(result.state, DeployState.DONE)
        self.assertEqual(result.mcu_versions, {"mcu": "kace-new123"})

    @patch("core.firmware_flash.get_mcu_versions")
    @patch("core.firmware_flash.get_klipper_state")
    def test_reconnect_with_old_firmware_is_not_accepted(self, mock_state, mock_versions):
        mock_state.side_effect = ["disconnected", "ready"]
        mock_versions.return_value = {"mcu": "kace-old123"}

        result = verify_sd_card_flash(
            expected_version="kace-new123",
            disconnect_cooldown_s=0,
            disconnect_timeout_s=0.01,
            reconnect_timeout_s=0.05,
            poll_interval_s=0.001,
        )

        self.assertEqual(result.state, DeployState.FAILED_FLASH)
        self.assertIn("running old firmware", result.detail)

    @patch("core.firmware_flash.get_klipper_state", return_value="ready")
    def test_missing_disconnect_times_out_with_recovery_state(self, _mock_state):
        result = verify_sd_card_flash(
            expected_version="kace-new123",
            disconnect_cooldown_s=0,
            disconnect_timeout_s=0.01,
            reconnect_timeout_s=0.05,
            poll_interval_s=0.001,
        )

        self.assertEqual(result.state, DeployState.TIMEOUT)
        self.assertIn("disconnect was not detected", result.detail)
