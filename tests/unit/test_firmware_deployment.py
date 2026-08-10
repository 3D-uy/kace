import hashlib
import json
import os
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

from firmware.artifacts import BuildArtifact, BuildProvenance, FirmwareFormat
from firmware.configuration import BootloaderOffsetKind
from firmware.identity import FirmwareBuildInputs, ToolchainIdentity
from firmware.deployment import (
    DeploymentArtifactError,
    DeploymentExecutionContext,
    DeploymentMethodId,
    DeploymentStatus,
    DeploymentStrategyId,
    DeploymentTarget,
    FirmwareDeploymentService,
    PostFlashVerification,
    UsbTopology,
)
from firmware.deployment.profiles import (
    DeploymentProfileError,
    load_profiles,
)


_DEFAULT = object()


def artifact(
    path,
    *,
    fmt=FirmwareFormat.BIN,
    flashable=True,
    mcu=None,
    config_mcu=None,
    flash_offset=_DEFAULT,
    native_filename=None,
):
    with open(path, "rb") as source:
        payload = source.read()
    defaults = {
        FirmwareFormat.BIN: ("klipper.bin", "stm32g0b1", "stm32", "0x2000"),
        FirmwareFormat.UF2: ("klipper.uf2", "rp2040", "rp2040", None),
        FirmwareFormat.IHEX: ("klipper.elf.hex", "atmega2560", "avr", None),
    }
    default_filename, default_mcu, default_config_mcu, default_offset = defaults[fmt]
    resolved_offset = default_offset if flash_offset is _DEFAULT else flash_offset
    config_lines = [f'CONFIG_MCU="{config_mcu or default_config_mcu}"']
    if resolved_offset is not None:
        config_lines.append(f"CONFIG_FLASH_START={resolved_offset}")
    identity = FirmwareBuildInputs.create(
        klipper_commit="1" * 40,
        canonical_config="\n".join(config_lines) + "\n",
        toolchain=ToolchainIdentity("make", "GNU Make 4.4", "gcc", "gcc 13.2"),
        build_id="a" * 32,
    ).complete(
        artifact_sha256=hashlib.sha256(payload).hexdigest(),
        artifact_size=len(payload),
        artifact_format=fmt.value,
    )
    return BuildArtifact(
        build_id="build-1",
        path=path,
        native_filename=native_filename or default_filename,
        format=fmt,
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        mcu=mcu or default_mcu,
        firmware_fingerprint="kace-deadbeef",
        provenance=BuildProvenance.REAL,
        flashable=flashable,
        firmware_identity=identity,
    )


def write_artifact(root, filename="klipper.bin", payload=b"firmware bytes"):
    path = os.path.join(root, filename)
    with open(path, "wb") as target:
        target.write(payload)
    return path


def write_profile_file(profile):
    source = tempfile.NamedTemporaryFile(
        "w", suffix=".yaml", delete=False, encoding="utf-8"
    )
    with source:
        json.dump({"profiles": [profile]}, source)
    return source.name


def valid_profile_payload(**overrides):
    profile = {
        "id": "exact-sd",
        "method": "MANUAL",
        "strategy": "SD_CARD",
        "board_ids": ["exact-board.cfg"],
        "mcu_patterns": ["stm32g0b1"],
        "exact_match_required": True,
        "formats": ["BIN"],
        "config_mcu": "stm32",
        "native_filenames": ["klipper.bin"],
        "final_filename": "firmware.bin",
        "bootloader_offset": "0x2000",
        "instructions": [],
        "usb": {
            "topology": "NATIVE_USB_CDC",
            "application_vid_pids": ["1d50:614e"],
            "bootloader_vid_pids": [],
        },
        "post_flash_verification": "KLIPPER_BUILD_ID",
    }
    profile.update(overrides)
    return profile


class FirmwareDeploymentTests(unittest.TestCase):
    def test_shipped_profiles_are_exact_board_strategies(self):
        profiles = load_profiles()
        self.assertEqual(len(profiles), 4)
        self.assertEqual(
            {item.strategy for item in profiles},
            {
                DeploymentStrategyId.PREPARE_ONLY,
                DeploymentStrategyId.SD_CARD,
                DeploymentStrategyId.AVRDUDE,
            },
        )
        for profile in profiles:
            with self.subTest(profile=profile.id):
                self.assertTrue(profile.board_patterns)
                self.assertTrue(profile.exact_match_required)
                self.assertEqual(len(profile.formats), 1)
                self.assertTrue(profile.native_filenames)
                self.assertTrue(profile.mcu_patterns)
                self.assertIs(
                    profile.post_flash_verification,
                    PostFlashVerification.KLIPPER_BUILD_ID,
                )

    def test_unknown_board_falls_back_to_prepare_only_with_native_name(self):
        events = []
        with tempfile.TemporaryDirectory() as root:
            source = write_artifact(root)
            build = artifact(source)
            service = FirmwareDeploymentService(output_dir=root, event_sink=events.append)
            target = DeploymentTarget("generic-unknown.cfg", "stm32g0b1")

            self.assertEqual(
                service.available_methods(target, build),
                (DeploymentMethodId.MANUAL,),
            )
            plan = service.plan(build, target, DeploymentMethodId.MANUAL)
            prepared = service.prepare(plan)

            self.assertTrue(plan.profile.fallback)
            self.assertIs(plan.profile.strategy, DeploymentStrategyId.PREPARE_ONLY)
            self.assertEqual(plan.final_filename, "klipper.bin")
            self.assertEqual(os.path.basename(prepared.staged_path), "klipper.bin")
            with open(os.path.join(root, "deployment-manifest.json"), encoding="utf-8") as stream:
                manifest = json.load(stream)
            self.assertEqual(
                manifest["deployment"]["profile"]["strategy"], "PREPARE_ONLY"
            )
            self.assertTrue(manifest["deployment"]["profile"]["fallback"])
            self.assertEqual(events[-1]["state"], "ARTIFACT_READY")

    def test_prepare_only_never_copies_to_arbitrary_media_or_reports_success(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as media:
            source = write_artifact(root)
            service = FirmwareDeploymentService(output_dir=root, event_sink=lambda _event: None)
            prepared = service.prepare(
                service.plan(
                    artifact(source),
                    DeploymentTarget("unknown.cfg", "stm32g0b1"),
                    DeploymentMethodId.MANUAL,
                )
            )
            provider = Mock(return_value=media)

            result = service.execute(
                prepared,
                DeploymentExecutionContext(media_path_provider=provider),
            )

            self.assertEqual(result.status, DeploymentStatus.ACTION_REQUIRED)
            self.assertFalse(result.ok)
            self.assertEqual(result.error_code, "PREPARE_ONLY")
            provider.assert_not_called()
            self.assertEqual(os.listdir(media), [])

    def test_skr_mini_sd_strategy_renames_and_copies_exact_file(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as media:
            source = write_artifact(root)
            service = FirmwareDeploymentService(output_dir=root, event_sink=lambda _event: None)
            plan = service.plan(
                artifact(source),
                DeploymentTarget(
                    "generic-bigtreetech-skr-mini-e3-v3.0.cfg", "stm32g0b1xx"
                ),
                DeploymentMethodId.MANUAL,
            )
            prepared = service.prepare(plan)
            result = service.execute(
                prepared,
                DeploymentExecutionContext(media_path_provider=lambda: media),
            )

            self.assertIs(plan.profile.strategy, DeploymentStrategyId.SD_CARD)
            self.assertEqual(plan.profile.bootloader_offset.kconfig_value, "0x2000")
            self.assertEqual(plan.final_filename, "firmware.bin")
            self.assertEqual(result.status, DeploymentStatus.MEDIA_PREPARED)
            self.assertFalse(result.ok)
            self.assertTrue(os.path.isfile(os.path.join(media, "firmware.bin")))
            self.assertFalse(os.path.exists(os.path.join(media, "klipper.bin")))

    def test_sd_destination_prompt_cancellation_is_terminal_cancelled(self):
        with tempfile.TemporaryDirectory() as root:
            source = write_artifact(root)
            service = FirmwareDeploymentService(output_dir=root, event_sink=lambda _event: None)
            prepared = service.prepare(
                service.plan(
                    artifact(source),
                    DeploymentTarget(
                        "generic-bigtreetech-skr-mini-e3-v3.0.cfg", "stm32g0b1"
                    ),
                    DeploymentMethodId.MANUAL,
                )
            )

            result = service.execute(
                prepared,
                DeploymentExecutionContext(media_path_provider=lambda: ""),
            )

            self.assertEqual(result.status, DeploymentStatus.CANCELLED)
            self.assertFalse(result.ok)

    def test_skr_pico_is_exact_prepare_only_not_generic_uf2_copy(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as media:
            source = write_artifact(root, "klipper.uf2")
            service = FirmwareDeploymentService(output_dir=root, event_sink=lambda _event: None)
            plan = service.plan(
                artifact(source, fmt=FirmwareFormat.UF2),
                DeploymentTarget("generic-bigtreetech-skr-pico-v1.0.cfg", "rp2040"),
                DeploymentMethodId.MANUAL,
            )
            prepared = service.prepare(plan)
            provider = Mock(return_value=media)
            result = service.execute(
                prepared,
                DeploymentExecutionContext(media_path_provider=provider),
            )

            self.assertEqual(plan.final_filename, "klipper.uf2")
            self.assertIs(plan.profile.strategy, DeploymentStrategyId.PREPARE_ONLY)
            self.assertIs(
                plan.profile.bootloader_offset.kind,
                BootloaderOffsetKind.NOT_APPLICABLE,
            )
            self.assertIs(
                plan.profile.usb.topology,
                UsbTopology.RP2040_BOOTSEL_MASS_STORAGE,
            )
            self.assertEqual(plan.profile.usb.bootloader_vid_pids, ("2e8a:0003",))
            self.assertEqual(result.status, DeploymentStatus.ACTION_REQUIRED)
            provider.assert_not_called()
            self.assertEqual(os.listdir(media), [])

    def test_ramps_automatic_flash_uses_exact_profile_and_safe_argv(self):
        runner = Mock()
        with tempfile.TemporaryDirectory() as root:
            source = write_artifact(
                root,
                "klipper.elf.hex",
                b":100000000C945C000C946E000C946E00AA\n",
            )
            service = FirmwareDeploymentService(output_dir=root, event_sink=lambda _event: None)
            plan = service.plan(
                artifact(source, fmt=FirmwareFormat.IHEX),
                DeploymentTarget(
                    "generic-ramps.cfg",
                    "atmega2560",
                    "/dev/serial/by-id/usb-Arduino_Mega-if00",
                    usb_vid="2341",
                    usb_pid="0042",
                ),
                DeploymentMethodId.USB,
            )
            prepared = service.prepare(plan)
            with patch("firmware.deployment.usb.shutil.which", return_value="/usr/bin/avrdude"):
                result = service.execute(
                    prepared,
                    DeploymentExecutionContext(confirm=lambda _prompt: True, command_runner=runner),
                )

        self.assertIs(plan.profile.strategy, DeploymentStrategyId.AVRDUDE)
        self.assertEqual(result.status, DeploymentStatus.FLASHED)
        command = runner.call_args.args[0]
        self.assertEqual(command[:5], ["avrdude", "-p", "atmega2560", "-c", "wiring"])
        self.assertIn("klipper.elf.hex:i", command[-1])
        self.assertNotIn("shell", runner.call_args.kwargs)
        self.assertEqual(runner.call_args.kwargs["timeout"], 120)

    def test_ramps_confirmation_decline_is_terminal_cancelled(self):
        with tempfile.TemporaryDirectory() as root:
            source = write_artifact(root, "klipper.elf.hex", b"payload")
            service = FirmwareDeploymentService(output_dir=root, event_sink=lambda _event: None)
            prepared = service.prepare(
                service.plan(
                    artifact(source, fmt=FirmwareFormat.IHEX),
                    DeploymentTarget(
                        "generic-ramps.cfg",
                        "atmega2560",
                        "/dev/serial/by-id/usb-Arduino_Mega-if00",
                        usb_vid="2341",
                        usb_pid="0042",
                    ),
                    DeploymentMethodId.USB,
                )
            )
            runner = Mock()
            result = service.execute(
                prepared,
                DeploymentExecutionContext(confirm=lambda _prompt: False, command_runner=runner),
            )

            self.assertEqual(result.status, DeploymentStatus.CANCELLED)
            runner.assert_not_called()

    def test_ramps_usb_requires_stable_path_and_allowed_vid_pid(self):
        cases = (
            ("/dev/ttyUSB0", "2341", "0042", "/dev/serial/by-id"),
            ("/dev/serial/by-id/clone", "1a86", "7523", "VID:PID"),
            ("/dev/serial/by-id/unknown", "", "", "could not be verified"),
        )
        for device, vid, pid, message in cases:
            with self.subTest(device=device, vid=vid, pid=pid), tempfile.TemporaryDirectory() as root:
                source = write_artifact(root, "klipper.elf.hex", b"payload")
                service = FirmwareDeploymentService(output_dir=root, event_sink=lambda _event: None)
                plan = service.plan(
                    artifact(source, fmt=FirmwareFormat.IHEX),
                    DeploymentTarget(
                        "generic-ramps.cfg",
                        "atmega2560",
                        device,
                        usb_vid=vid,
                        usb_pid=pid,
                    ),
                    DeploymentMethodId.USB,
                )
                prepared = service.prepare(plan)
                runner = Mock()
                result = service.execute(
                    prepared,
                    DeploymentExecutionContext(confirm=lambda _prompt: True, command_runner=runner),
                )

                self.assertEqual(result.status, DeploymentStatus.ACTION_REQUIRED)
                self.assertIn(message, result.detail)
                runner.assert_not_called()

    def test_known_board_rejects_wrong_offset_without_generic_fallback(self):
        with tempfile.TemporaryDirectory() as root:
            source = write_artifact(root)
            wrong = artifact(source, flash_offset="0x8000")
            service = FirmwareDeploymentService(output_dir=root, event_sink=lambda _event: None)
            target = DeploymentTarget(
                "generic-bigtreetech-skr-mini-e3-v3.0.cfg", "stm32g0b1"
            )

            self.assertEqual(service.available_methods(target, wrong), ())
            with self.assertRaisesRegex(DeploymentProfileError, "bootloader offset"):
                service.plan(wrong, target, DeploymentMethodId.MANUAL)

    def test_known_board_rejects_wrong_native_artifact_name(self):
        with tempfile.TemporaryDirectory() as root:
            source = write_artifact(root, "renamed.bin")
            wrong = artifact(source, native_filename="renamed.bin")
            service = FirmwareDeploymentService(output_dir=root, event_sink=lambda _event: None)
            target = DeploymentTarget(
                "generic-bigtreetech-skr-mini-e3-v3.0.cfg", "stm32g0b1"
            )

            with self.assertRaisesRegex(DeploymentProfileError, "native artifact"):
                service.plan(wrong, target, DeploymentMethodId.MANUAL)

    def test_known_board_rejects_mcu_substring_that_is_not_a_canonical_prefix(self):
        with tempfile.TemporaryDirectory() as root:
            source = write_artifact(root)
            build = artifact(source, mcu="not-stm32g0b1")
            service = FirmwareDeploymentService(output_dir=root, event_sink=lambda _event: None)
            target = DeploymentTarget(
                "generic-bigtreetech-skr-mini-e3-v3.0.cfg", "not-stm32g0b1"
            )

            self.assertEqual(service.available_methods(target, build), ())
            with self.assertRaisesRegex(DeploymentProfileError, "MCU"):
                service.plan(build, target, DeploymentMethodId.MANUAL)

    def test_unknown_board_has_no_usb_strategy(self):
        with tempfile.TemporaryDirectory() as root:
            source = write_artifact(root, "klipper.elf.hex", b"payload")
            build = artifact(source, fmt=FirmwareFormat.IHEX)
            service = FirmwareDeploymentService(output_dir=root, event_sink=lambda _event: None)
            target = DeploymentTarget("unknown-avr.cfg", "atmega2560")

            self.assertEqual(
                service.available_methods(target, build),
                (DeploymentMethodId.MANUAL,),
            )
            with self.assertRaisesRegex(DeploymentProfileError, "no exact automatic"):
                service.plan(build, target, DeploymentMethodId.USB)

    def test_mock_or_nonflashable_artifact_is_rejected_by_every_method(self):
        with tempfile.TemporaryDirectory() as root:
            source = write_artifact(root, "klipper.elf.hex", b"payload")
            unsafe = replace(
                artifact(source, fmt=FirmwareFormat.IHEX),
                provenance=BuildProvenance.MOCK,
                flashable=False,
            )
            service = FirmwareDeploymentService(output_dir=root, event_sink=lambda _event: None)
            target = DeploymentTarget(
                "generic-ramps.cfg",
                "atmega2560",
                "/dev/serial/by-id/test",
                usb_vid="2341",
                usb_pid="0042",
            )

            self.assertEqual(service.available_methods(target, unsafe), ())
            for method in (DeploymentMethodId.MANUAL, DeploymentMethodId.USB):
                with self.subTest(method=method), self.assertRaises(DeploymentArtifactError):
                    service.plan(unsafe, target, method)

    def test_tampered_prepared_media_is_rejected_before_sd_copy(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as media:
            source = write_artifact(root, payload=b"original")
            service = FirmwareDeploymentService(output_dir=root, event_sink=lambda _event: None)
            prepared = service.prepare(
                service.plan(
                    artifact(source),
                    DeploymentTarget(
                        "generic-bigtreetech-skr-mini-e3-v3.0.cfg", "stm32g0b1"
                    ),
                    DeploymentMethodId.MANUAL,
                )
            )
            with open(prepared.staged_path, "wb") as target_file:
                target_file.write(b"tampered")

            result = service.execute(
                prepared,
                DeploymentExecutionContext(media_path_provider=lambda: media),
            )

            self.assertEqual(result.status, DeploymentStatus.FAILED)
            self.assertEqual(result.error_code, "ARTIFACT_UNSAFE")
            self.assertFalse(os.path.exists(os.path.join(media, "firmware.bin")))

    def test_profile_rejects_path_traversal_filename(self):
        path = write_profile_file(
            valid_profile_payload(id="unsafe", final_filename="../firmware.bin")
        )
        try:
            with self.assertRaises(DeploymentProfileError):
                load_profiles(path)
        finally:
            os.remove(path)

    def test_profile_rejects_format_global_board_claim(self):
        path = write_profile_file(valid_profile_payload(board_ids=[]))
        try:
            with self.assertRaisesRegex(DeploymentProfileError, "board_ids must not be empty"):
                load_profiles(path)
        finally:
            os.remove(path)

    def test_avrdude_profile_requires_application_vid_pid_allowlist(self):
        path = write_profile_file(
            valid_profile_payload(
                id="unsafe-avrdude",
                method="USB",
                strategy="AVRDUDE",
                mcu_patterns=["atmega2560"],
                formats=["IHEX"],
                config_mcu="avr",
                native_filenames=["klipper.elf.hex"],
                final_filename="klipper.elf.hex",
                bootloader_offset="NOT_APPLICABLE",
                usb={
                    "topology": "USB_SERIAL_BRIDGE",
                    "application_vid_pids": [],
                    "bootloader_vid_pids": ["2341:0042"],
                },
                auto_flash=True,
                backend="avrdude",
                backend_options={
                    "part": "atmega2560",
                    "programmer": "wiring",
                    "baud": 115200,
                },
            )
        )
        try:
            with self.assertRaisesRegex(DeploymentProfileError, "application VID:PID"):
                load_profiles(path)
        finally:
            os.remove(path)

    def test_sd_profile_requires_post_flash_application_vid_pid_allowlist(self):
        path = write_profile_file(
            valid_profile_payload(
                usb={
                    "topology": "NATIVE_USB_CDC",
                    "application_vid_pids": [],
                    "bootloader_vid_pids": ["0483:df11"],
                }
            )
        )
        try:
            with self.assertRaisesRegex(DeploymentProfileError, "post-flash application"):
                load_profiles(path)
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
