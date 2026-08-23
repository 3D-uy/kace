import json
from pathlib import Path
from unittest.mock import patch

import pytest

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


def artifact(tmp_path: Path, *, strategy="SD_CARD", method="MANUAL"):
    path = tmp_path / ("firmware.bin" if strategy == "SD_CARD" else "klipper.uf2")
    path.write_bytes(b"verified firmware payload")
    import hashlib

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
            "firmware_identity": {
                "reported_version": "kace-b1-" + "2" * 32,
            },
        },
    }


def awaiting_flash(tmp_path: Path):
    checkpoint = create_checkpoint(base_user_data())
    checkpoint = transition_checkpoint(
        checkpoint, FirmwareWorkflowState.ARTIFACT_READY, artifact=artifact(tmp_path)
    )
    return transition_checkpoint(checkpoint, FirmwareWorkflowState.AWAITING_FLASH)


def write_config(path: Path, serial: str | None):
    value = "" if serial is None else serial
    path.write_text(
        f"[mcu]\nserial: {value}\n\n[printer]\nkinematics: cartesian\n",
        encoding="utf-8",
    )


def test_compiled_but_not_flashed_blocks_deploy(tmp_path):
    checkpoint = awaiting_flash(tmp_path)
    config = tmp_path / "printer.cfg"
    write_config(config, "/dev/serial/by-id/usb-Klipper_lpc1769_NEW-if00")

    blockers = deployment_blockers(
        str(config), base_user_data(), checkpoint=checkpoint
    )

    assert any("AWAITING_FLASH" in item for item in blockers)
    with pytest.raises(DeploymentInvariantError):
        enforce_deployment_invariants(
            str(config), base_user_data(), checkpoint=checkpoint
        )


def test_empty_mcu_serial_blocks_even_without_checkpoint(tmp_path):
    config = tmp_path / "printer.cfg"
    write_config(config, "")

    assert deployment_blockers(str(config), {}) == (
        "[mcu].serial is missing or empty",
    )


def test_mcu_reappears_with_valid_serial_and_workflow_continues(tmp_path):
    checkpoint = awaiting_flash(tmp_path)
    serial = "/dev/serial/by-id/usb-Klipper_lpc1769_NEW-if00"
    with patch("core.firmware_workflow.os.path.exists", return_value=True):
        verified, observed = verify_reappeared_mcu(
            checkpoint,
            detector=lambda: {"derived_mcu": "lpc1769", "mcu_path": serial},
            flash_evidence=True,
        )

    assert observed["mcu_path"] == serial
    assert verified["state"] == FirmwareWorkflowState.MCU_VERIFIED.value
    assert verified["hardware"]["verified_serial_path"] == serial

    verified = transition_checkpoint(
        verified, FirmwareWorkflowState.CONFIG_GENERATED
    )
    ready = transition_checkpoint(verified, FirmwareWorkflowState.READY_TO_DEPLOY)
    config = tmp_path / "printer.cfg"
    write_config(config, serial)
    enforce_deployment_invariants(
        str(config), {**base_user_data(), "mcu_path": serial}, checkpoint=ready
    )


def test_present_old_mcu_cannot_bypass_flash_evidence_gate(tmp_path):
    checkpoint = awaiting_flash(tmp_path)
    serial = "/dev/serial/by-id/usb-Klipper_lpc1769_BASE-if00"
    with patch("core.firmware_workflow.os.path.exists", return_value=True):
        with pytest.raises(FirmwareWorkflowError, match="flashing step completed"):
            verify_reappeared_mcu(
                checkpoint,
                detector=lambda: {"derived_mcu": "lpc1769", "mcu_path": serial},
            )


def test_running_klipper_must_report_exact_compiled_build(tmp_path):
    checkpoint = awaiting_flash(tmp_path)
    serial = "/dev/serial/by-id/usb-Klipper_lpc1769_NEW-if00"
    with patch("core.firmware_workflow.os.path.exists", return_value=True):
        checkpoint, _ = verify_reappeared_mcu(
            checkpoint,
            detector=lambda: {"derived_mcu": "lpc1769", "mcu_path": serial},
            flash_evidence=True,
        )
    checkpoint = transition_checkpoint(checkpoint, FirmwareWorkflowState.CONFIG_GENERATED)
    checkpoint = transition_checkpoint(checkpoint, FirmwareWorkflowState.READY_TO_DEPLOY)
    checkpoint = transition_checkpoint(checkpoint, FirmwareWorkflowState.DEPLOYING)
    expected = "kace-b1-" + "2" * 32

    assert verify_running_firmware(checkpoint, {"mcu": expected}) == expected
    with pytest.raises(FirmwareWorkflowError, match="expected compiled build"):
        verify_running_firmware(checkpoint, {"mcu": "old-firmware"})


def test_checkpoint_resume_restores_wizard_without_secrets(tmp_path):
    checkpoint = awaiting_flash(tmp_path)
    path = tmp_path / "workflow.json"
    write_checkpoint(checkpoint, str(path))

    resumed = load_checkpoint(str(path))

    assert resumed["wizard_data"]["board"] == base_user_data()["board"]
    assert resumed["wizard_data"]["x_size"] == "300"
    assert "password" not in resumed["wizard_data"]
    assert resumed["state"] == FirmwareWorkflowState.AWAITING_FLASH.value


def test_corrupt_and_incompatible_checkpoints_are_rejected(tmp_path):
    checkpoint = awaiting_flash(tmp_path)
    path = tmp_path / "workflow.json"
    write_checkpoint(checkpoint, str(path))
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["state"] = FirmwareWorkflowState.COMPLETE.value
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CheckpointCorrupt):
        load_checkpoint(str(path))

    write_checkpoint(checkpoint, str(path))
    with pytest.raises(CheckpointIncompatible):
        load_checkpoint(
            str(path), current_hardware={"derived_mcu": "stm32f103"}
        )
    verified = transition_checkpoint(checkpoint, FirmwareWorkflowState.VERIFYING_MCU)
    verified = transition_checkpoint(
        verified,
        FirmwareWorkflowState.MCU_VERIFIED,
        verified_serial_path="/dev/serial/by-id/usb-Klipper_lpc1769_EXPECTED-if00",
        flash_evidence_recorded_at=1,
    )
    write_checkpoint(verified, str(path))
    with pytest.raises(CheckpointIncompatible, match="serial path"):
        load_checkpoint(
            str(path),
            current_hardware={
                "derived_mcu": "lpc1769",
                "mcu_path": "/dev/serial/by-id/usb-Klipper_lpc1769_OTHER-if00",
            },
        )


@pytest.mark.parametrize(
    ("strategy", "method", "filename"),
    [
        ("SD_CARD", "MANUAL", "firmware.bin"),
        ("AVRDUDE", "USB", "klipper.uf2"),
        ("PREPARE_ONLY", "MANUAL", "klipper.uf2"),
    ],
)
def test_checkpoint_keeps_board_specific_flash_contracts(
    tmp_path, strategy, method, filename
):
    evidence = artifact(tmp_path, strategy=strategy, method=method)
    checkpoint = create_checkpoint(base_user_data())
    checkpoint = transition_checkpoint(
        checkpoint, FirmwareWorkflowState.ARTIFACT_READY, artifact=evidence
    )
    checkpoint = transition_checkpoint(
        checkpoint, FirmwareWorkflowState.AWAITING_FLASH
    )

    assert checkpoint["artifact"]["strategy"] == strategy
    assert checkpoint["artifact"]["method"] == method
    assert checkpoint["artifact"]["final_filename"] == filename
    assert checkpoint["state"] == FirmwareWorkflowState.AWAITING_FLASH.value
