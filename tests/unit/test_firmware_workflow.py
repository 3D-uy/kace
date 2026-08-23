import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.firmware_workflow import (
    CheckpointCorrupt,
    CheckpointIncompatible,
    DeploymentInvariantError,
    FirmwareWorkflowError,
    FirmwareWorkflowState,
    create_checkpoint,
    deployment_blockers,
    enforce_deployment_invariants,
    load_checkpoint,
    transition_checkpoint,
    verify_reappeared_mcu,
    verify_running_firmware,
    write_checkpoint,
)


def base_user_data():
    return {
        "board": "generic-bigtreetech-skr-v1.4.cfg",
        "mcu_type": "lpc1769",
        "mcu_path": "/dev/serial/by-id/usb-Klipper_lpc1769_BASE-if00",
        "kinematics": "cartesian",
        "x_size": "300",
        "password": "must-not-persist",
    }


def artifact(root: Path, *, strategy="SD_CARD", method="MANUAL"):
    path = root / ("firmware.bin" if strategy == "SD_CARD" else "klipper.uf2")
    path.write_bytes(b"verified firmware payload")
    return {
        "path": str(path),
        "final_filename": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size_bytes": path.stat().st_size,
        "method": method,
        "strategy": strategy,
        "instructions": [{"id": "copy", "text": f"Copy {path.name}"}],
        "build": {
            "mcu": "lpc1769",
            "firmware_identity": {"reported_version": "kace-b1-" + "2" * 32},
        },
    }


def awaiting_flash(root: Path):
    checkpoint = create_checkpoint(base_user_data())
    checkpoint = transition_checkpoint(
        checkpoint, FirmwareWorkflowState.ARTIFACT_READY, artifact=artifact(root)
    )
    return transition_checkpoint(checkpoint, FirmwareWorkflowState.AWAITING_FLASH)


def write_config(path: Path, serial: str | None):
    value = "" if serial is None else serial
    path.write_text(
        f"[mcu]\nserial: {value}\n\n[printer]\nkinematics: cartesian\n",
        encoding="utf-8",
    )


class FirmwareWorkflowTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)

    def tearDown(self):
        self._temporary.cleanup()

    def test_compiled_but_not_flashed_blocks_deploy(self):
        checkpoint = awaiting_flash(self.root)
        config = self.root / "printer.cfg"
        write_config(config, "/dev/serial/by-id/usb-Klipper_lpc1769_NEW-if00")
        blockers = deployment_blockers(
            str(config), base_user_data(), checkpoint=checkpoint
        )
        self.assertTrue(any("AWAITING_FLASH" in item for item in blockers))
        with self.assertRaises(DeploymentInvariantError):
            enforce_deployment_invariants(
                str(config), base_user_data(), checkpoint=checkpoint
            )

    def test_empty_mcu_serial_blocks_even_without_checkpoint(self):
        config = self.root / "printer.cfg"
        write_config(config, "")
        self.assertEqual(
            deployment_blockers(str(config), {}),
            ("[mcu].serial is missing or empty",),
        )

    def test_mcu_reappears_with_valid_serial_and_workflow_continues(self):
        checkpoint = awaiting_flash(self.root)
        serial = "/dev/serial/by-id/usb-Klipper_lpc1769_NEW-if00"
        with patch("core.firmware_workflow.os.path.exists", return_value=True):
            verified, observed = verify_reappeared_mcu(
                checkpoint,
                detector=lambda: {"derived_mcu": "lpc1769", "mcu_path": serial},
                flash_evidence=True,
            )
        self.assertEqual(observed["mcu_path"], serial)
        self.assertEqual(verified["state"], FirmwareWorkflowState.MCU_VERIFIED.value)
        self.assertEqual(verified["hardware"]["verified_serial_path"], serial)
        verified = transition_checkpoint(
            verified, FirmwareWorkflowState.CONFIG_GENERATED
        )
        ready = transition_checkpoint(verified, FirmwareWorkflowState.READY_TO_DEPLOY)
        config = self.root / "printer.cfg"
        write_config(config, serial)
        enforce_deployment_invariants(
            str(config), {**base_user_data(), "mcu_path": serial}, checkpoint=ready
        )

    def test_present_old_mcu_cannot_bypass_flash_evidence_gate(self):
        checkpoint = awaiting_flash(self.root)
        serial = "/dev/serial/by-id/usb-Klipper_lpc1769_BASE-if00"
        with patch("core.firmware_workflow.os.path.exists", return_value=True):
            with self.assertRaisesRegex(FirmwareWorkflowError, "flashing step completed"):
                verify_reappeared_mcu(
                    checkpoint,
                    detector=lambda: {"derived_mcu": "lpc1769", "mcu_path": serial},
                )

    def test_running_klipper_must_report_exact_compiled_build(self):
        checkpoint = awaiting_flash(self.root)
        serial = "/dev/serial/by-id/usb-Klipper_lpc1769_NEW-if00"
        with patch("core.firmware_workflow.os.path.exists", return_value=True):
            checkpoint, _ = verify_reappeared_mcu(
                checkpoint,
                detector=lambda: {"derived_mcu": "lpc1769", "mcu_path": serial},
                flash_evidence=True,
            )
        checkpoint = transition_checkpoint(
            checkpoint, FirmwareWorkflowState.CONFIG_GENERATED
        )
        checkpoint = transition_checkpoint(
            checkpoint, FirmwareWorkflowState.READY_TO_DEPLOY
        )
        checkpoint = transition_checkpoint(checkpoint, FirmwareWorkflowState.DEPLOYING)
        expected = "kace-b1-" + "2" * 32
        self.assertEqual(verify_running_firmware(checkpoint, {"mcu": expected}), expected)
        with self.assertRaisesRegex(FirmwareWorkflowError, "expected compiled build"):
            verify_running_firmware(checkpoint, {"mcu": "old-firmware"})

    def test_checkpoint_resume_restores_wizard_without_secrets(self):
        checkpoint = awaiting_flash(self.root)
        path = self.root / "workflow.json"
        write_checkpoint(checkpoint, str(path))
        resumed = load_checkpoint(str(path))
        self.assertEqual(resumed["wizard_data"]["board"], base_user_data()["board"])
        self.assertEqual(resumed["wizard_data"]["x_size"], "300")
        self.assertNotIn("password", resumed["wizard_data"])
        self.assertEqual(resumed["state"], FirmwareWorkflowState.AWAITING_FLASH.value)

    def test_corrupt_and_incompatible_checkpoints_are_rejected(self):
        checkpoint = awaiting_flash(self.root)
        path = self.root / "workflow.json"
        write_checkpoint(checkpoint, str(path))
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["state"] = FirmwareWorkflowState.COMPLETE.value
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(CheckpointCorrupt):
            load_checkpoint(str(path))
        write_checkpoint(checkpoint, str(path))
        with self.assertRaises(CheckpointIncompatible):
            load_checkpoint(str(path), current_hardware={"derived_mcu": "stm32f103"})
        verified = transition_checkpoint(checkpoint, FirmwareWorkflowState.VERIFYING_MCU)
        verified = transition_checkpoint(
            verified,
            FirmwareWorkflowState.MCU_VERIFIED,
            verified_serial_path="/dev/serial/by-id/usb-Klipper_lpc1769_EXPECTED-if00",
            flash_evidence_recorded_at=1,
        )
        write_checkpoint(verified, str(path))
        with self.assertRaisesRegex(CheckpointIncompatible, "serial path"):
            load_checkpoint(
                str(path),
                current_hardware={
                    "derived_mcu": "lpc1769",
                    "mcu_path": "/dev/serial/by-id/usb-Klipper_lpc1769_OTHER-if00",
                },
            )

    def test_checkpoint_keeps_board_specific_flash_contracts(self):
        contracts = (
            ("SD_CARD", "MANUAL", "firmware.bin"),
            ("AVRDUDE", "USB", "klipper.uf2"),
            ("PREPARE_ONLY", "MANUAL", "klipper.uf2"),
        )
        for strategy, method, filename in contracts:
            with self.subTest(strategy=strategy, method=method):
                evidence = artifact(self.root, strategy=strategy, method=method)
                checkpoint = create_checkpoint(base_user_data())
                checkpoint = transition_checkpoint(
                    checkpoint, FirmwareWorkflowState.ARTIFACT_READY, artifact=evidence
                )
                checkpoint = transition_checkpoint(
                    checkpoint, FirmwareWorkflowState.AWAITING_FLASH
                )
                self.assertEqual(checkpoint["artifact"]["strategy"], strategy)
                self.assertEqual(checkpoint["artifact"]["method"], method)
                self.assertEqual(checkpoint["artifact"]["final_filename"], filename)
                self.assertEqual(
                    checkpoint["state"], FirmwareWorkflowState.AWAITING_FLASH.value
                )


if __name__ == "__main__":
    unittest.main()
