import hashlib
import json
from dataclasses import asdict
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.firmware_workflow import (
    CheckpointCorrupt,
    CheckpointConflict,
    CheckpointIncompatible,
    DeploymentInvariantError,
    FirmwareWorkflowError,
    FirmwareWorkflowState,
    create_checkpoint,
    checkpoint_revision,
    deployment_blockers,
    enforce_deployment_invariants,
    load_checkpoint,
    restore_wizard_data,
    transition_checkpoint,
    verify_reappeared_mcu,
    verify_running_firmware,
    write_checkpoint,
)
from core.mcu_monitor import McuIdentity
from core.custom_probe import (
    CustomProbeConfig, GuidedCustomProbeSettings, parse_custom_probe_config,
)


def physical_identity(path, port="usb-1", serial="original"):
    return McuIdentity(path, "/dev/ttyACM1", physical_port=port,
                       vendor_id="1d50", model_id="614e", serial=serial)


def identity_reader():
    return SimpleNamespace(read=lambda path: physical_identity(path))


def base_user_data():
    return {
        "board": "generic-bigtreetech-skr-v1.4.cfg",
        "mcu_type": "lpc1769",
        "mcu_path": "/dev/serial/by-id/usb-Klipper_lpc1769_BASE-if00",
        "kinematics": "cartesian",
        "x_size": "300",
        "password": "must-not-persist",
    }


def artifact(root: Path, *, strategy="SD_CARD", method="MANUAL", model="lpc1769"):
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
            "mcu": model,
            "firmware_identity": {"reported_version": "kace-b1-" + "2" * 32},
        },
    }


def awaiting_flash(root: Path):
    checkpoint = create_checkpoint(base_user_data(), identity_reader=identity_reader())
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
                identity_reader=identity_reader(),
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
                identity_reader=identity_reader(),
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
        full_version = "v0.13.0-734-gfe4eb865-20260917-host-" + expected
        self.assertEqual(verify_running_firmware(checkpoint, {"mcu": full_version}), full_version)
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

    def test_custom_probe_source_survives_durable_resume_verbatim(self):
        source = ("# Keep spacing and macro body\n[probe]\npin: ^P1.27\n"
                  "x_offset: -9\ny_offset: -11\nz_offset: 0\n"
                  "custom_option: keep this\n\n[gcode_macro PROBE_HELPER]\n"
                  "gcode:\n    RESPOND MSG=\"unchanged\"\n")
        user_data = {**base_user_data(), "probe": "Custom Probe",
                     "custom_probe": parse_custom_probe_config(source)}
        checkpoint = create_checkpoint(user_data, identity_reader=identity_reader())
        path = self.root / "custom-workflow.json"
        write_checkpoint(checkpoint, str(path))
        loaded = load_checkpoint(str(path))
        before = path.read_bytes()
        restored = restore_wizard_data(loaded["wizard_data"])
        self.assertEqual(loaded["wizard_data"]["custom_probe"], {"config_text": source})
        self.assertIsInstance(restored["custom_probe"], CustomProbeConfig)
        self.assertEqual(restored["custom_probe"].config_text, source)
        self.assertEqual(restored["custom_probe"].x_offset, -9)
        self.assertEqual(restored["custom_probe"].y_offset, -11)
        self.assertEqual(restored["custom_probe"].z_offset, 0)
        self.assertEqual(path.read_bytes(), before)
        self.assertNotIn("password", restored)
        self.assertEqual(loaded["state"], FirmwareWorkflowState.HARDWARE_SELECTED.value)
        self.assertIsNone(loaded["artifact"])

    def test_legacy_guided_custom_probe_can_resume_without_raw_payload(self):
        settings = GuidedCustomProbeSettings(pin="^P1.27", x_offset=-9,
                                             y_offset=-11, z_offset=0)
        user_data = {**base_user_data(), "probe": "Custom Probe",
                     "custom_probe_settings": asdict(settings)}
        checkpoint = create_checkpoint(user_data, identity_reader=identity_reader())
        checkpoint = transition_checkpoint(checkpoint, FirmwareWorkflowState.ARTIFACT_READY,
                                           artifact=artifact(self.root))
        checkpoint = transition_checkpoint(checkpoint, FirmwareWorkflowState.AWAITING_FLASH)
        path = self.root / "legacy-custom-workflow.json"
        write_checkpoint(checkpoint, str(path))
        loaded = load_checkpoint(str(path))
        restored = restore_wizard_data(loaded["wizard_data"])
        self.assertEqual(restored["custom_probe"].config_text, settings.to_config().config_text)
        self.assertEqual(restored["custom_probe_settings"], settings)
        updated = transition_checkpoint(loaded, FirmwareWorkflowState.AWAITING_FLASH,
                                        user_data=restored)
        write_checkpoint(updated, str(path))
        reloaded = load_checkpoint(str(path))
        self.assertEqual(reloaded["sequence"], loaded["sequence"] + 1)
        self.assertEqual(reloaded["wizard_data"]["custom_probe"],
                         {"config_text": settings.to_config().config_text})
        self.assertEqual(reloaded["hardware"], loaded["hardware"])
        self.assertEqual(reloaded["artifact"], loaded["artifact"])
        self.assertEqual(reloaded["state"], FirmwareWorkflowState.AWAITING_FLASH.value)

    def test_resume_probe_kind_matches_generator_precedence(self):
        source = "[probe]\npin: P1.27\nx_offset: -9\ny_offset: -11\nz_offset: 0\n"
        saved = {"probe_kind": "custom", "probe": "None",
                 "custom_probe": {"config_text": source}}
        self.assertIsInstance(restore_wizard_data(saved)["custom_probe"], CustomProbeConfig)
        saved.update(probe_kind="none", probe="Custom Probe")
        self.assertEqual(restore_wizard_data(saved)["custom_probe"], {"config_text": source})

    def test_custom_probe_resume_derives_offsets_and_policy_from_raw_source(self):
        source = "[probe]\npin: P1.27\nx_offset: -9\ny_offset: -11\nz_offset: 0\n"
        saved = {"probe": "Custom Probe", "custom_probe": {
            "config_text": source, "primary_section": "anything", "x_offset": 100,
            "y_offset": 200, "z_offset": 300, "policy": {"primary_sections": ["printer"]},
        }}
        restored = restore_wizard_data(saved)
        self.assertEqual(restored["custom_probe"].primary_section, "probe")
        self.assertEqual(restored["custom_probe"].x_offset, -9)
        self.assertEqual(restored["custom_probe"].y_offset, -11)
        self.assertEqual(restored["custom_probe"].z_offset, 0)
        self.assertEqual(saved["custom_probe"]["x_offset"], 100)

    def test_invalid_custom_probe_resume_never_falls_back_to_guided_settings(self):
        guided = asdict(GuidedCustomProbeSettings(pin="P1.27", x_offset=0, y_offset=0))
        for raw in ({}, {"config_text": "[printer]\nkinematics: cartesian"},
                    {"config_text": "[probe]\nz_offset: nan"}, "not an object"):
            with self.subTest(raw=raw), self.assertRaisesRegex(
                FirmwareWorkflowError, "Saved custom probe rejected"
            ):
                restore_wizard_data({"probe": "Custom Probe", "custom_probe": raw,
                                     "custom_probe_settings": guided})

    def test_invalid_legacy_guided_probe_is_refused(self):
        settings = asdict(GuidedCustomProbeSettings(pin="P1.27", x_offset=0, y_offset=0))
        for changes in ({"x_offset": float("inf")}, {"samples": 0},
                        {"samples_result": "invalid"}, {"unexpected": "value"},
                        {"pin": "P1.27\n[printer]\nkinematics: cartesian"}):
            with self.subTest(changes=changes), self.assertRaisesRegex(
                FirmwareWorkflowError, "Saved custom probe rejected"
            ):
                restore_wizard_data({"probe": "Custom Probe",
                                     "custom_probe_settings": {**settings, **changes}})
        with self.assertRaisesRegex(FirmwareWorkflowError, "unavailable"):
            restore_wizard_data({"probe": "Custom Probe"})

    def test_rehydrated_custom_probe_preserves_checkpoint_integrity_and_stale_writer_guard(self):
        settings = GuidedCustomProbeSettings(pin="P1.27", x_offset=0, y_offset=0)
        checkpoint = create_checkpoint({**base_user_data(), "probe": "Custom Probe",
                                        "custom_probe": settings.to_config()})
        path = self.root / "custom-cas.json"
        write_checkpoint(checkpoint, str(path))
        first = load_checkpoint(str(path))
        stale = load_checkpoint(str(path))
        fresh = transition_checkpoint(first, FirmwareWorkflowState.HARDWARE_SELECTED,
                                      user_data=restore_wizard_data(first["wizard_data"]))
        write_checkpoint(fresh, str(path))
        with self.assertRaises(CheckpointConflict):
            write_checkpoint(transition_checkpoint(stale, FirmwareWorkflowState.HARDWARE_SELECTED,
                user_data=restore_wizard_data(stale["wizard_data"])), str(path))
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["wizard_data"]["custom_probe"]["config_text"] += "\n# tampered"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(CheckpointCorrupt):
            load_checkpoint(str(path))

    def test_cli_rejects_invalid_resumed_probe_before_generation_or_deployment(self):
        import kace

        checkpoint = create_checkpoint(base_user_data())
        checkpoint["wizard_data"].update(probe="Custom Probe", custom_probe={"config_text": ""})
        with patch.object(kace, "_resume_firmware_workflow", return_value=(checkpoint, "continue")), \
                patch.object(kace, "checkpoint_revision", return_value=("unused", None)), \
                patch.object(kace, "print_kace_banner"), \
                patch.object(kace, "print_workflow_result") as outcome, \
                patch.object(kace, "fetch_raw_config") as fetch, \
                patch.object(kace, "generate_config") as generate, \
                patch.object(kace, "deploy_firmware_installation") as deploy:
            with self.assertRaises(SystemExit) as raised:
                kace.main()
        self.assertNotEqual(raised.exception.code, 0)
        self.assertIn("Saved custom probe rejected", outcome.call_args.args[0].detail)
        fetch.assert_not_called()
        generate.assert_not_called()
        deploy.assert_not_called()

    def test_corrupt_and_incompatible_checkpoints_are_rejected(self):
        checkpoint = awaiting_flash(self.root)
        path = self.root / "workflow.json"
        write_checkpoint(checkpoint, str(path))
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["state"] = FirmwareWorkflowState.COMPLETE.value
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(CheckpointCorrupt):
            load_checkpoint(str(path))
        with self.assertRaises(FirmwareWorkflowError):
            write_checkpoint(checkpoint, str(path))
        write_checkpoint(checkpoint, str(path), expected_revision=checkpoint_revision(str(path)))
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
