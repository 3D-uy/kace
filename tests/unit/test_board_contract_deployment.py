"""Phase 3 BoardContract artifact and non-executing deployment-plan tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from firmware.artifacts import BuildArtifact, BuildProvenance, FirmwareFormat
from firmware.boards.catalog import load_default_catalog
from firmware.boards.deployment import (
    ContractArtifactError,
    ContractIdentityMismatch,
    DeploymentStepId,
    FilenamePolicyError,
    build_artifact_from_proof,
    create_deployment_plan,
)
from firmware.boards.kconfig import BuildProof, CommandProof, VerificationProof
from firmware.identity import ToolchainIdentity


TARGETS = (
    ("creality.v4.2.7", "stm32f103-ret6", "uart-usart1-pa10-pa9", None),
    ("btt.skr-mini-e3.v3.0", "stm32g0b1", "usb-pa11-pa12", "firmware.bin"),
    ("mks.robin-nano.v3", "stm32f407", "usb-pa11-pa12", "Robin_nano_v3.bin"),
    ("btt.skr-pico.v1.0", "rp2040", "usb-native", "klipper.uf2"),
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class BoardContractDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_default_catalog(refresh=True)
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def _contract_parts(self, board_id, variant_id, target_id):
        contract = self.catalog.by_id(board_id)
        variant = contract.variant(variant_id)
        target = variant.target(target_id)
        return contract, variant, target

    def _artifact(self, board_id, variant_id, target_id, *, filename=None):
        contract, variant, target = self._contract_parts(board_id, variant_id, target_id)
        native_filename = filename or target.artifact.native_filename
        directory = self.root / f"native-{board_id}-{target_id}-{len(list(self.root.iterdir()))}"
        directory.mkdir()
        path = directory / native_filename
        payload = f"real firmware:{board_id}:{variant_id}:{target_id}".encode("utf-8")
        path.write_bytes(payload)
        return contract, BuildArtifact(
            build_id="a" * 32,
            path=str(path),
            native_filename=native_filename,
            format={"BIN": FirmwareFormat.BIN, "UF2": FirmwareFormat.UF2}[target.artifact.format.value],
            sha256=_sha(payload),
            size_bytes=len(payload),
            mcu=variant.processor.resolved_mcu,
            firmware_fingerprint="kace-board-contract-test",
            provenance=BuildProvenance.REAL,
            flashable=False,
            board_id=board_id,
            hardware_variant_id=variant_id,
            build_target_id=target_id,
            board_contract_digest=contract.contract_digest,
            klipper_commit=contract.upstream.validated_commit,
            build_proof_digest="b" * 64,
        )

    def _proof(self, board_id, variant_id, target_id):
        contract, variant, target = self._contract_parts(board_id, variant_id, target_id)
        evidence = self.root / "proof-evidence"
        evidence.mkdir(exist_ok=True)
        requested = evidence / "requested.config"
        resolved = evidence / "resolved.config"
        artifact = evidence / target.artifact.native_filename
        requested_bytes = b"CONFIG_MACH_STM32=y\n"
        resolved_bytes = (
            f'CONFIG_MCU="{variant.processor.resolved_mcu}"\n'
            f"CONFIG_CLOCK_FREQ={target.resolved_assertions['CONFIG_CLOCK_FREQ']}\n"
        ).encode("utf-8")
        build_id = "c" * 32
        fingerprint = f"kace-b1-{build_id}"
        artifact_bytes = (b"verified real artifact" * 1024) + fingerprint.encode()
        requested.write_bytes(requested_bytes)
        resolved.write_bytes(resolved_bytes)
        artifact.write_bytes(artifact_bytes)
        command = CommandProof(
            ("make", f"KLIPPER_VERSION={fingerprint}"),
            0, _sha(b"ok"), _sha(b""), "ok", "",
        )
        verification = VerificationProof(True, ("CONFIG_MCU",))
        proof = BuildProof(
            schema="kace-board-build-proof/v3",
            board_id=board_id,
            hardware_variant_id=variant_id,
            build_target_id=target_id,
            contract_digest=contract.contract_digest,
            klipper_commit=contract.upstream.validated_commit,
            requested_config_path=str(requested),
            requested_config_sha256=_sha(requested_bytes),
            resolved_config_path=str(resolved),
            resolved_config_sha256=_sha(resolved_bytes),
            artifact_path=str(artifact),
            artifact_sha256=_sha(artifact_bytes),
            artifact_size=len(artifact_bytes),
            olddefconfig=command,
            requested_selections=verification,
            resolved_assertions=verification,
            build=command,
            build_attempts=(command,),
            lto_retry_used=False,
            toolchain=ToolchainIdentity(
                "make", "GNU Make 4.4", "arm-none-eabi-gcc", "gcc 13.2"
            ),
            requested_flags=("-O2", "-flto"),
            effective_flags=("-O2", "-flto"),
            lto_requested=True,
            lto_effective=True,
            fallback_used=False,
            fallback_reason="",
            build_id=build_id,
            firmware_fingerprint=fingerprint,
            embedded_fingerprint_verified=True,
        )
        return contract, proof

    def test_build_proof_creates_fully_linked_additive_artifact(self):
        contract, proof = self._proof(*TARGETS[0][:3])
        artifact = build_artifact_from_proof(proof, contract)
        self.assertEqual(contract.board_id, artifact.board_id)
        self.assertEqual(proof.hardware_variant_id, artifact.hardware_variant_id)
        self.assertEqual(proof.build_target_id, artifact.build_target_id)
        self.assertEqual(proof.digest, artifact.build_proof_digest)
        self.assertEqual(proof.artifact_sha256, artifact.sha256)
        self.assertFalse(artifact.flashable)
        self.assertIsNotNone(artifact.firmware_identity)
        self.assertEqual(proof.firmware_fingerprint, artifact.firmware_identity.reported_version)

    def test_positive_plans_apply_exact_filename_and_rename_only(self):
        for board_id, variant_id, target_id, expected_filename in TARGETS:
            with self.subTest(board=board_id):
                contract, artifact = self._artifact(board_id, variant_id, target_id)
                plan = create_deployment_plan(
                    contract, artifact, output_directory=str(self.root / "prepared")
                )
                if expected_filename is None:
                    self.assertRegex(plan.transformation.final_filename, r"^kace-[0-9a-f]{12}\.bin$")
                else:
                    self.assertEqual(expected_filename, plan.transformation.final_filename)
                self.assertEqual(artifact.sha256, plan.transformation.native_sha256)
                self.assertEqual(artifact.sha256, plan.transformation.final_sha256)
                self.assertFalse(plan.transformation.content_changed)
                self.assertTrue(Path(plan.transformation.final_path).is_file())
                self.assertEqual(DeploymentStepId.VALIDATE_ARTIFACT, plan.steps[0].id)
                self.assertEqual(
                    DeploymentStepId.VERIFY_KLIPPER_BUILD_ID, plan.steps[-1].id
                )
                with self.assertRaises(FrozenInstanceError):
                    plan.plan_digest = "0" * 64

    def test_artifact_from_another_board_is_rejected(self):
        contract, artifact = self._artifact(*TARGETS[0][:3])
        with self.assertRaisesRegex(ContractIdentityMismatch, "board_id"):
            create_deployment_plan(
                self.catalog.by_id("btt.skr-mini-e3.v3.0"),
                artifact,
                output_directory=str(self.root / "prepared"),
            )

    def test_wrong_variant_is_rejected(self):
        contract, artifact = self._artifact(*TARGETS[0][:3])
        artifact = replace(artifact, hardware_variant_id="stm32f103-wrong")
        with self.assertRaisesRegex(ContractIdentityMismatch, "variant"):
            create_deployment_plan(contract, artifact, output_directory=str(self.root / "prepared"))

    def test_wrong_target_is_rejected(self):
        contract, artifact = self._artifact(*TARGETS[0][:3])
        artifact = replace(artifact, build_target_id="uart-does-not-exist")
        with self.assertRaisesRegex(ContractIdentityMismatch, "target"):
            create_deployment_plan(contract, artifact, output_directory=str(self.root / "prepared"))

    def test_wrong_contract_digest_is_rejected(self):
        contract, artifact = self._artifact(*TARGETS[0][:3])
        artifact = replace(artifact, board_contract_digest="0" * 64)
        with self.assertRaisesRegex(ContractIdentityMismatch, "board_contract_digest"):
            create_deployment_plan(contract, artifact, output_directory=str(self.root / "prepared"))

    def test_wrong_klipper_commit_is_rejected(self):
        contract, artifact = self._artifact(*TARGETS[0][:3])
        artifact = replace(artifact, klipper_commit="0" * 40)
        with self.assertRaisesRegex(ContractIdentityMismatch, "klipper_commit"):
            create_deployment_plan(contract, artifact, output_directory=str(self.root / "prepared"))

    def test_creality_repeated_filename_is_rejected(self):
        contract, artifact = self._artifact(*TARGETS[0][:3])
        first = create_deployment_plan(
            contract, artifact, output_directory=str(self.root / "prepared")
        )
        with self.assertRaisesRegex(FilenamePolicyError, "last successful"):
            create_deployment_plan(
                contract,
                artifact,
                output_directory=str(self.root / "prepared"),
                last_successful_filename=first.transformation.final_filename.upper(),
            )

    def test_wrong_extension_is_rejected(self):
        contract, artifact = self._artifact(*TARGETS[1][:3], filename="klipper.uf2")
        with self.assertRaises(ContractArtifactError):
            create_deployment_plan(contract, artifact, output_directory=str(self.root / "prepared"))

    def test_absent_artifact_is_rejected(self):
        contract, artifact = self._artifact(*TARGETS[1][:3])
        Path(artifact.path).unlink()
        with self.assertRaisesRegex(ContractArtifactError, "absent"):
            create_deployment_plan(contract, artifact, output_directory=str(self.root / "prepared"))

    def test_altered_native_hash_is_rejected(self):
        contract, artifact = self._artifact(*TARGETS[1][:3])
        Path(artifact.path).write_bytes(b"tampered")
        with self.assertRaisesRegex(ContractArtifactError, "hash"):
            create_deployment_plan(contract, artifact, output_directory=str(self.root / "prepared"))

    def test_rename_only_transformation_cannot_change_content(self):
        contract, artifact = self._artifact(*TARGETS[1][:3])

        def corrupt(_source, destination):
            destination.write_bytes(b"changed by invalid transformer")

        with patch("firmware.boards.deployment._copy_artifact_bytes", side_effect=corrupt):
            with self.assertRaisesRegex(ContractArtifactError, "changed content"):
                create_deployment_plan(
                    contract, artifact, output_directory=str(self.root / "prepared")
                )

    def test_legacy_data_cannot_create_contract_deployment_plan(self):
        _contract, artifact = self._artifact(*TARGETS[1][:3])
        legacy_profile = {"board_ids": ["skr-mini-e3-v3.0"], "final_filename": "firmware.bin"}
        with self.assertRaisesRegex(ContractIdentityMismatch, "legacy"):
            create_deployment_plan(
                legacy_profile, artifact, output_directory=str(self.root / "prepared")
            )


if __name__ == "__main__":
    unittest.main()
