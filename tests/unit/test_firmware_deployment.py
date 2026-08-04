import hashlib
import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from firmware.artifacts import BuildArtifact, BuildProvenance, FirmwareFormat
from firmware.deployment import (
    DeploymentExecutionContext,
    DeploymentMethodId,
    DeploymentProfile,
    DeploymentStatus,
    DeploymentTarget,
    FirmwareDeploymentService,
)
from firmware.deployment.profiles import (
    DeploymentProfileError,
    DeploymentProfileResolver,
    load_profiles,
)


def artifact(path, *, fmt=FirmwareFormat.BIN, flashable=True):
    with open(path, "rb") as source:
        payload = source.read()
    return BuildArtifact(
        build_id="build-1",
        path=path,
        native_filename={
            FirmwareFormat.BIN: "klipper.bin",
            FirmwareFormat.UF2: "klipper.uf2",
            FirmwareFormat.IHEX: "klipper.elf.hex",
        }[fmt],
        format=fmt,
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        mcu="atmega2560" if fmt is FirmwareFormat.IHEX else "stm32f103",
        firmware_fingerprint="kace-deadbeef",
        provenance=BuildProvenance.REAL,
        flashable=flashable,
    )


class FirmwareDeploymentTests(unittest.TestCase):
    def test_shipped_profiles_are_valid_and_expose_manual_fallbacks(self):
        profiles = load_profiles()
        self.assertTrue(any(item.method is DeploymentMethodId.MANUAL for item in profiles))
        self.assertTrue(any(item.method is DeploymentMethodId.USB for item in profiles))

    def test_manual_preparation_renames_without_mutating_build_artifact(self):
        events = []
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, "klipper.bin")
            with open(source, "wb") as target:
                target.write(b"firmware bytes")
            build = artifact(source)
            service = FirmwareDeploymentService(output_dir=root, event_sink=events.append)
            target = DeploymentTarget("generic-unknown.cfg", "stm32f103")

            plan = service.plan(build, target, DeploymentMethodId.MANUAL)
            prepared = service.prepare(plan)

            self.assertEqual(plan.final_filename, "firmware.bin")
            self.assertEqual(os.path.basename(prepared.staged_path), "firmware.bin")
            with open(source, "rb") as source_file:
                self.assertEqual(source_file.read(), b"firmware bytes")
            with open(prepared.staged_path, "rb") as staged_file:
                self.assertEqual(staged_file.read(), b"firmware bytes")
            with open(os.path.join(root, "deployment-manifest.json"), encoding="utf-8") as manifest_file:
                manifest = json.load(manifest_file)
            self.assertEqual(manifest["deployment"]["final_filename"], "firmware.bin")
            self.assertEqual(events[-1]["workflow_kind"], "firmware_deployment")
            self.assertEqual(events[-1]["state"], "ARTIFACT_READY")

    def test_manual_execute_copies_only_the_prepared_final_name(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as media:
            source = os.path.join(root, "klipper.bin")
            with open(source, "wb") as target_file:
                target_file.write(b"payload")
            service = FirmwareDeploymentService(output_dir=root, event_sink=lambda _event: None)
            plan = service.plan(
                artifact(source), DeploymentTarget("unknown.cfg", "stm32"), DeploymentMethodId.MANUAL
            )
            prepared = service.prepare(plan)
            result = service.execute(
                prepared,
                DeploymentExecutionContext(media_path_provider=lambda: media),
            )

            self.assertEqual(result.status, DeploymentStatus.ACTION_REQUIRED)
            self.assertTrue(os.path.isfile(os.path.join(media, "firmware.bin")))
            self.assertFalse(os.path.exists(os.path.join(media, "klipper.bin")))

    def test_usb_automatic_flash_uses_allowlisted_argv_without_shell(self):
        usb_profile = DeploymentProfile(
            id="usb-test",
            method=DeploymentMethodId.USB,
            board_patterns=("generic-ramps.cfg",),
            formats=(FirmwareFormat.IHEX,),
            final_filename="firmware.hex",
            instruction_keys=(),
            exact_match_required=True,
            auto_flash=True,
            backend="avrdude",
            backend_options={"part": "atmega2560", "programmer": "wiring", "baud": 115200},
        )
        resolver = DeploymentProfileResolver([usb_profile])
        runner = Mock()
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, "klipper.elf.hex")
            with open(source, "wb") as target_file:
                target_file.write(b":100000000C945C000C946E000C946E00AA\n")
            service = FirmwareDeploymentService(
                resolver=resolver, output_dir=root, event_sink=lambda _event: None
            )
            plan = service.plan(
                artifact(source, fmt=FirmwareFormat.IHEX),
                DeploymentTarget(
                    "generic-ramps.cfg",
                    "atmega2560",
                    "/dev/serial/by-id/usb-Arduino_Mega-if00",
                ),
                DeploymentMethodId.USB,
            )
            prepared = service.prepare(plan)
            with patch("firmware.deployment.usb.shutil.which", return_value="/usr/bin/avrdude"):
                result = service.execute(
                    prepared,
                    DeploymentExecutionContext(confirm=lambda _prompt: True, command_runner=runner),
                )

        self.assertEqual(result.status, DeploymentStatus.FLASHED)
        command = runner.call_args.args[0]
        self.assertIsInstance(command, list)
        self.assertEqual(command[:5], ["avrdude", "-p", "atmega2560", "-c", "wiring"])
        self.assertNotIn("shell", runner.call_args.kwargs)
        self.assertEqual(runner.call_args.kwargs["timeout"], 120)

    def test_usb_refuses_non_flashable_or_ambiguous_device(self):
        profile = DeploymentProfile(
            id="usb-blocked",
            method=DeploymentMethodId.USB,
            board_patterns=("board.cfg",),
            formats=(FirmwareFormat.IHEX,),
            final_filename="firmware.hex",
            instruction_keys=(),
            exact_match_required=True,
            auto_flash=True,
            backend="avrdude",
            backend_options={"part": "atmega2560", "programmer": "wiring", "baud": 115200},
        )
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, "klipper.elf.hex")
            with open(source, "wb") as target_file:
                target_file.write(b"payload")
            service = FirmwareDeploymentService(
                resolver=DeploymentProfileResolver([profile]),
                output_dir=root,
                event_sink=lambda _event: None,
            )
            plan = service.plan(
                artifact(source, fmt=FirmwareFormat.IHEX, flashable=False),
                DeploymentTarget("board.cfg", "atmega2560", "/dev/ttyUSB0"),
                DeploymentMethodId.USB,
            )
            prepared = service.prepare(plan)
            runner = Mock()
            result = service.execute(
                prepared,
                DeploymentExecutionContext(confirm=lambda _prompt: True, command_runner=runner),
            )

        self.assertEqual(result.status, DeploymentStatus.ACTION_REQUIRED)
        self.assertIn("not marked flashable", result.detail)
        self.assertIn("/dev/serial/by-id", result.detail)
        runner.assert_not_called()

    def test_profile_rejects_path_traversal_filename(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as source:
            source.write(
                "profiles:\n"
                "  - id: unsafe\n"
                "    method: MANUAL\n"
                "    formats: [BIN]\n"
                "    final_filename: ../firmware.bin\n"
            )
            path = source.name
        try:
            with self.assertRaises(DeploymentProfileError):
                load_profiles(path)
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
