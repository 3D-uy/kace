"""Hardware-free end-to-end qualification of the physical deployment flow."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

from core.deployer import _MoonrakerClient
from core.mcu_monitor import McuPresenceMonitor
from core.moonraker_deployer import (
    ConfigArtifact,
    Deployer,
    DeploymentManifest,
    DeployState,
    JsonEventSink,
    McuTarget,
)
from core.power_controller import MoonrakerPowerController
from core.snapshot import DeploymentSnapshot
from firmware.artifacts import BuildArtifact
from firmware.deployment import (
    DeploymentExecutionContext,
    DeploymentMethodId,
    DeploymentStatus,
    DeploymentTarget,
    FirmwareDeploymentService,
)
from firmware.identity import FirmwareBuildInputs, ToolchainIdentity
from tests.integration.simulated_hardware import MoonrakerLab


class SimulatedFirmwareLabTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.output_dir = os.path.join(self.tmp.name, "output")
        self.media_dir = os.path.join(self.tmp.name, "media")
        os.makedirs(self.output_dir)
        os.makedirs(self.media_dir)
        self.printer_cfg = os.path.join(self.tmp.name, "printer.cfg")
        with open(self.printer_cfg, "wb") as target:
            target.write(b"[printer]\nnew: true\n")
        self.snapshot = DeploymentSnapshot(
            "simulation",
            "now",
            "simulated-board",
            "test",
            "mcu=previous-firmware",
            ("mcu",),
            False,
            {"printer.cfg": b"[printer]\nold: true\n"},
        )

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _build_inputs(*, commit: str, config: str, build_id: str):
        return FirmwareBuildInputs.create(
            klipper_commit=commit,
            canonical_config=config,
            toolchain=ToolchainIdentity(
                "make", "GNU Make 4.4", "gcc", "gcc 13.2"
            ),
            build_id=build_id,
        )

    def _artifact(
        self,
        *,
        filename="klipper.bin",
        payload=b"simulated-real-firmware",
        mcu="stm32g0b1",
        config='CONFIG_MCU="stm32"\nCONFIG_FLASH_START=0x2000\n',
        commit="2" * 40,
        build_id="b" * 32,
    ):
        path = os.path.join(self.tmp.name, filename)
        with open(path, "wb") as target:
            target.write(payload)
        return BuildArtifact.create(
            path=path,
            native_filename=filename,
            size_bytes=len(payload),
            mcu=mcu,
            firmware_fingerprint="",
            mock_build=False,
            size_warning=False,
            build_identity=self._build_inputs(
                commit=commit, config=config, build_id=build_id
            ),
        )

    def _runtime(
        self,
        lab,
        artifact,
        *,
        candidate_confirmation=None,
        expected_vid_pids=("1d50:614e",),
        bootloader_vid_pids=("0483:df11",),
    ):
        monitor = McuPresenceMonitor(
            "/dev/serial/by-id/usb-KACE-LAB-MCU",
            reader=lab.physical_mcu.reader,
            event_source=lab.physical_mcu.events,
            expected_vid_pids=expected_vid_pids,
            bootloader_vid_pids=bootloader_vid_pids,
        )
        client = _MoonrakerClient(lab.host, lab.port, api_key=lab.api_key)
        power = MoonrakerPowerController(
            "printer",
            host=lab.host,
            port=lab.port,
            api_key=lab.api_key,
            poll_interval=0.001,
        )
        manifest = DeploymentManifest(
            [
                McuTarget(
                    "mcu",
                    artifact.firmware_identity.reported_version,
                    artifact.firmware_identity.to_dict(),
                )
            ],
            self.printer_cfg,
            config_artifacts=[ConfigArtifact(self.printer_cfg, "printer.cfg")],
        )
        transcript = io.StringIO()
        common = {
            "client": client,
            "manifest": manifest,
            "snapshot": self.snapshot,
            "mcu_monitor": monitor,
            "identity_confirmation_prompt": candidate_confirmation,
            "event_sink": JsonEventSink(transcript),
        }
        return common, power, transcript

    @staticmethod
    def _events(transcript: io.StringIO) -> list[dict]:
        events = []
        for line in transcript.getvalue().splitlines():
            payload = line.split("=== KACE_WORKFLOW_EVENT: ", 1)[1].rsplit(" ===", 1)[0]
            events.append(json.loads(payload))
        return events

    def _manual_sd_deployer(self, lab, artifact, *, confirmation=None):
        service = FirmwareDeploymentService(
            output_dir=self.output_dir, event_sink=lambda _event: None
        )
        prepared = service.prepare(
            service.plan(
                artifact,
                DeploymentTarget(
                    "generic-bigtreetech-skr-mini-e3-v3.0.cfg", "stm32g0b1xx"
                ),
                DeploymentMethodId.MANUAL,
            )
        )
        common, power, transcript = self._runtime(
            lab, artifact, candidate_confirmation=confirmation
        )
        deployer = Deployer(
            **common,
            firmware_deploy=lambda: service.execute(
                prepared,
                DeploymentExecutionContext(media_path_provider=lambda: self.media_dir),
            ),
            power_cycle_prompt=lambda: True,
            media_installation_prompt=lambda: True,
            power_off=lambda: power.power_off(timeout=0.2),
            power_on=lambda: power.power_on(timeout=0.2),
        )
        deployer.POLL_INTERVAL_S = 0.001
        deployer.POLL_BACKOFF_MAX_S = 0.002
        deployer.WAIT_TIMEOUT_S = 0.2
        return deployer, transcript

    def test_sd_power_cycle_runs_real_contracts_in_safe_order(self):
        artifact = self._artifact()
        with MoonrakerLab() as lab:
            lab.version_after_reconnect = artifact.firmware_identity.reported_version
            deployer, transcript = self._manual_sd_deployer(lab, artifact)

            result = deployer.run()
            events = self._events(transcript)

            self.assertEqual(result.state, DeployState.DONE)
            self.assertEqual(lab.power_history, ["off", "on"])
            self.assertEqual(lab.physical_mcu.history, ["remove", "bootloader", "application"])
            self.assertEqual(lab.files["printer.cfg"], b"[printer]\nnew: true\n")
            self.assertEqual(lab.uploads, ["printer.cfg"])
            self.assertEqual(lab.auth_failures, 0)
            self.assertTrue(os.path.isfile(os.path.join(self.media_dir, "firmware.bin")))
            states = [event["state"] for event in events]
            self.assertLess(states.index("FIRMWARE_VERIFIED"), states.index("APPLYING_CONFIG"))
            self.assertEqual(states[-1], "DONE")
            self.assertEqual(
                [event["sequence"] for event in events],
                list(range(1, len(events) + 1)),
            )

    def test_failed_flash_that_leaves_previous_build_never_uploads_config(self):
        config = 'CONFIG_MCU="stm32"\nCONFIG_FLASH_START=0x2000\n'
        previous = self._build_inputs(
            commit="1" * 40, config=config, build_id="a" * 32
        )
        artifact = self._artifact(config=config, commit="2" * 40, build_id="b" * 32)
        self.assertEqual(previous.config_sha256, artifact.firmware_identity.config_sha256)
        self.assertNotEqual(previous.input_sha256, artifact.firmware_identity.input_sha256)

        with MoonrakerLab() as lab:
            lab.version_after_reconnect = previous.reported_version
            deployer, transcript = self._manual_sd_deployer(lab, artifact)

            result = deployer.run()

            self.assertEqual(result.state, DeployState.FAILED_FLASH)
            self.assertEqual(lab.uploads, [])
            self.assertEqual(lab.files["printer.cfg"], b"[printer]\nold: true\n")
            self.assertNotIn("FIRMWARE_VERIFIED", [e["state"] for e in self._events(transcript)])

    def test_wrong_vid_pid_on_same_port_is_terminal_and_never_uploads(self):
        artifact = self._artifact()
        with MoonrakerLab() as lab:
            lab.physical_mcu.candidate_mode = "wrong_vid_pid"
            lab.version_after_reconnect = artifact.firmware_identity.reported_version
            deployer, _ = self._manual_sd_deployer(lab, artifact)

            result = deployer.run()

            self.assertEqual(result.state, DeployState.FAILED_MONITOR)
            self.assertEqual(lab.uploads, [])
            self.assertIn("not allowed", result.detail)

    def test_expected_vid_pid_on_wrong_port_cannot_be_accepted_automatically(self):
        artifact = self._artifact()
        with MoonrakerLab() as lab:
            lab.physical_mcu.candidate_mode = "wrong_port"
            lab.version_after_reconnect = artifact.firmware_identity.reported_version
            deployer, _ = self._manual_sd_deployer(lab, artifact)

            result = deployer.run()

            self.assertEqual(result.state, DeployState.FAILED_MONITOR)
            self.assertEqual(lab.uploads, [])
            self.assertIn("physical topology", result.detail)

    def test_ambiguous_serial_requires_and_records_physical_confirmation(self):
        artifact = self._artifact()
        assessments = []
        with MoonrakerLab() as lab:
            lab.physical_mcu.candidate_mode = "serial_changed"
            lab.version_after_reconnect = artifact.firmware_identity.reported_version
            deployer, transcript = self._manual_sd_deployer(
                lab,
                artifact,
                confirmation=lambda assessment: assessments.append(assessment) or True,
            )

            result = deployer.run()
            events = self._events(transcript)

            self.assertEqual(result.state, DeployState.DONE)
            self.assertEqual(len(assessments), 1)
            states = [event["state"] for event in events]
            self.assertLess(
                states.index("AWAITING_MCU_CONFIRMATION"),
                states.index("MCU_IDENTITY_CONFIRMED"),
            )
            present = next(event for event in events if event["state"] == "MCU_PRESENT")
            self.assertTrue(present["data"]["manually_confirmed"])

    def test_declined_ambiguous_identity_is_cancelled_without_upload(self):
        artifact = self._artifact()
        with MoonrakerLab() as lab:
            lab.physical_mcu.candidate_mode = "serial_changed"
            deployer, _ = self._manual_sd_deployer(
                lab, artifact, confirmation=lambda _assessment: False
            )

            result = deployer.run()

            self.assertEqual(result.state, DeployState.CANCELLED)
            self.assertEqual(lab.uploads, [])

    def test_upload_corruption_rolls_back_exact_original_bytes(self):
        artifact = self._artifact()
        with MoonrakerLab() as lab:
            lab.version_after_reconnect = artifact.firmware_identity.reported_version
            lab.corrupt_download_once.add("printer.cfg")
            deployer, transcript = self._manual_sd_deployer(lab, artifact)

            result = deployer.run()

            self.assertEqual(result.state, DeployState.FAILED_UPLOAD)
            self.assertTrue(result.rollback_succeeded)
            self.assertEqual(lab.files["printer.cfg"], b"[printer]\nold: true\n")
            self.assertEqual(lab.uploads, ["printer.cfg", "printer.cfg"])
            self.assertNotEqual(self._events(transcript)[-1]["state"], "DONE")

    def test_activation_error_rolls_back_and_never_emits_done(self):
        artifact = self._artifact()
        with MoonrakerLab() as lab:
            lab.version_after_reconnect = artifact.firmware_identity.reported_version
            lab.klippy_states.extend(["ready", "ready", "error", "ready", "ready"])
            deployer, transcript = self._manual_sd_deployer(lab, artifact)

            result = deployer.run()

            self.assertEqual(result.state, DeployState.CONFIG_ERROR)
            self.assertTrue(result.rollback_succeeded)
            self.assertEqual(lab.files["printer.cfg"], b"[printer]\nold: true\n")
            self.assertEqual(self._events(transcript)[-1]["state"], "CONFIG_ERROR")

    def test_usb_strategy_arms_real_monitor_before_avrdude_and_verifies_build(self):
        artifact = self._artifact(
            filename="klipper.elf.hex",
            payload=b":100000000C945C000C946E000C946E00AA\n",
            mcu="atmega2560",
            config='CONFIG_MCU="avr"\n',
        )
        service = FirmwareDeploymentService(
            output_dir=self.output_dir, event_sink=lambda _event: None
        )
        prepared = service.prepare(
            service.plan(
                artifact,
                DeploymentTarget(
                    "generic-ramps.cfg",
                    "atmega2560",
                    "/dev/serial/by-id/usb-KACE-LAB-MCU",
                    usb_vid="2341",
                    usb_pid="0042",
                ),
                DeploymentMethodId.USB,
            )
        )
        with MoonrakerLab() as lab:
            lab.physical_mcu.baseline = lab.physical_mcu.reader.current = replace(
                lab.physical_mcu.baseline,
                vendor_id="2341",
                model_id="0042",
            )
            lab.physical_mcu.emit_bootloader = False
            lab.physical_mcu.application_vendor_id = "2341"
            lab.physical_mcu.application_model_id = "0042"
            lab.version_after_reconnect = artifact.firmware_identity.reported_version
            common, _, transcript = self._runtime(
                lab,
                artifact,
                expected_vid_pids=("2341:0042",),
                bootloader_vid_pids=(),
            )

            def command_runner(_command, *, check, timeout):
                self.assertTrue(check)
                self.assertEqual(timeout, 120)
                self.assertTrue(lab.physical_mcu.events.started)
                lab.simulate_usb_flash()

            deployer = Deployer(
                **common,
                firmware_deploy=lambda: service.execute(
                    prepared,
                    DeploymentExecutionContext(
                        confirm=lambda _prompt: True,
                        command_runner=command_runner,
                    ),
                ),
                monitor_before_firmware=True,
            )
            deployer.POLL_INTERVAL_S = 0.001
            deployer.POLL_BACKOFF_MAX_S = 0.002
            deployer.WAIT_TIMEOUT_S = 0.2

            with patch("firmware.deployment.usb.shutil.which", return_value="/usr/bin/avrdude"):
                result = deployer.run()

            self.assertEqual(result.state, DeployState.DONE)
            states = [event["state"] for event in self._events(transcript)]
            self.assertLess(states.index("MONITOR_ARMED"), states.index("FLASHING"))
            self.assertLess(states.index("FIRMWARE_VERIFIED"), states.index("APPLYING_CONFIG"))

    def test_uf2_prepare_only_cannot_enter_a_physical_transaction(self):
        artifact = self._artifact(
            filename="klipper.uf2",
            mcu="rp2040",
            config='CONFIG_MCU="rp2040"\n',
        )
        service = FirmwareDeploymentService(
            output_dir=self.output_dir, event_sink=lambda _event: None
        )
        prepared = service.prepare(
            service.plan(
                artifact,
                DeploymentTarget("generic-bigtreetech-skr-pico-v1.0.cfg", "rp2040"),
                DeploymentMethodId.MANUAL,
            )
        )
        with MoonrakerLab() as lab:
            common, _, transcript = self._runtime(lab, artifact)
            deployer = Deployer(
                **common,
                firmware_deploy=lambda: service.execute(
                    prepared,
                    DeploymentExecutionContext(
                        media_path_provider=lambda: self.fail(
                            "prepare-only must not request arbitrary media"
                        )
                    ),
                ),
            )

            result = deployer.run()

            self.assertEqual(result.state, DeployState.FAILED_PRECONDITION)
            self.assertEqual(lab.power_history, [])
            self.assertEqual(lab.uploads, [])
            self.assertFalse(lab.physical_mcu.events.started)
            self.assertIn("no safe automatic or removable-media flash", result.detail)
            self.assertEqual(self._events(transcript)[-1]["state"], "FAILED_PRECONDITION")

        direct = service.execute(prepared, DeploymentExecutionContext())
        self.assertEqual(direct.status, DeploymentStatus.ACTION_REQUIRED)
        self.assertFalse(direct.ok)

    def test_moonraker_timeout_is_terminal_and_cannot_upload(self):
        artifact = self._artifact()
        with MoonrakerLab() as lab:
            lab.version_after_reconnect = artifact.firmware_identity.reported_version
            deployer, transcript = self._manual_sd_deployer(lab, artifact)
            lab.moonraker_available = False
            deployer.WAIT_TIMEOUT_S = 0.02

            result = deployer.run()

            self.assertEqual(result.state, DeployState.TIMEOUT)
            self.assertEqual(lab.uploads, [])
            self.assertEqual(self._events(transcript)[-1]["state"], "TIMEOUT")


if __name__ == "__main__":
    unittest.main()
