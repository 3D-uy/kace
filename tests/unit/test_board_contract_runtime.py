"""Phase 4A controlled BoardContract runtime authority tests."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.firmware_wizard import run_firmware_wizard
from core.translations import t
from core.workflow_outcome import WorkflowOutcome
from firmware.boards.catalog import load_default_catalog
from firmware.boards.deployment import build_artifact_from_proof, create_deployment_plan
from firmware.boards.kconfig import BuildProof, CommandProof, VerificationProof
from firmware.boards.models import SupportStatus
from firmware.boards.runtime import (
    BoardContractRuntimeBundle,
    FirmwareAuthority,
    build_board_contract_runtime,
    resolve_firmware_authority,
)
from firmware.identity import ToolchainIdentity


MIGRATED = (
    (
        "generic-creality-v4.2.7.cfg",
        "creality.v4.2.7",
        "stm32f103-ret6",
        "uart-usart1-pa10-pa9",
        "stm32f103",
    ),
    (
        "generic-bigtreetech-skr-mini-e3-v3.0.cfg",
        "btt.skr-mini-e3.v3.0",
        "stm32g0b1",
        "usb-pa11-pa12",
        "stm32g0b1xx",
    ),
    (
        "generic-mks-robin-nano-v3.cfg",
        "mks.robin-nano.v3",
        "stm32f407",
        "usb-pa11-pa12",
        "stm32f407xx",
    ),
    (
        "generic-bigtreetech-skr-pico-v1.0.cfg",
        "btt.skr-pico.v1.0",
        "rp2040",
        "usb-native",
        "rp2040",
    ),
    (
        "generic-bigtreetech-skr-v1.4.cfg",
        "btt.skr-v1.4",
        "lpc1768",
        "usb-native",
        "lpc1768",
    ),
    (
        "generic-bigtreetech-skr-v1.4.cfg",
        "btt.skr-v1.4",
        "lpc1769-turbo",
        "usb-native",
        "lpc1769",
    ),
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class BoardContractRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_default_catalog(refresh=True)
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def _bundle(self, alias=MIGRATED[0][0], detected_mcu=None):
        if detected_mcu is None:
            detected_mcu = next(
                (item[4] for item in MIGRATED if item[0] == alias),
                None,
            )
        decision = resolve_firmware_authority(
            alias, detected_mcu=detected_mcu, catalog=self.catalog
        )
        contract = self.catalog.by_id(decision.board_id)
        variant = contract.variant(decision.hardware_variant_id)
        target = variant.target(decision.build_target_id)
        evidence = self.root / decision.board_id
        evidence.mkdir(exist_ok=True)
        requested = evidence / "requested.config"
        resolved = evidence / "resolved.config"
        artifact_path = evidence / target.artifact.native_filename
        requested_bytes = b"CONFIG_TEST=y\n"
        resolved_bytes = f'CONFIG_MCU="{variant.processor.resolved_mcu}"\n'.encode()
        build_id = "c" * 32
        fingerprint = f"kace-b1-{build_id}"
        artifact_bytes = (
            (decision.board_id.encode() + b" firmware") * 256
            + fingerprint.encode()
        )
        requested.write_bytes(requested_bytes)
        resolved.write_bytes(resolved_bytes)
        artifact_path.write_bytes(artifact_bytes)
        command = CommandProof(
            ("make", f"KLIPPER_VERSION={fingerprint}"),
            0, _sha(b"ok"), _sha(b""), "ok", "",
        )
        verification = VerificationProof(True, ("CONFIG_MCU",))
        proof = BuildProof(
            schema="kace-board-build-proof/v3",
            board_id=decision.board_id,
            hardware_variant_id=decision.hardware_variant_id,
            build_target_id=decision.build_target_id,
            contract_digest=contract.contract_digest,
            klipper_commit=contract.upstream.validated_commit,
            requested_config_path=str(requested),
            requested_config_sha256=_sha(requested_bytes),
            resolved_config_path=str(resolved),
            resolved_config_sha256=_sha(resolved_bytes),
            artifact_path=str(artifact_path),
            artifact_sha256=_sha(artifact_bytes),
            artifact_size=len(artifact_bytes),
            olddefconfig=command,
            requested_selections=verification,
            resolved_assertions=verification,
            build=command,
            build_attempts=(command,),
            lto_retry_used=False,
            toolchain=ToolchainIdentity(
                "make", "GNU Make test", "arm-none-eabi-gcc", "gcc test"
            ),
            requested_flags=("-O2",),
            effective_flags=("-O2",),
            lto_requested=False,
            lto_effective=False,
            fallback_used=False,
            fallback_reason="",
            build_id=build_id,
            firmware_fingerprint=fingerprint,
            embedded_fingerprint_verified=True,
        )
        artifact = build_artifact_from_proof(proof, contract)
        plan = create_deployment_plan(
            contract,
            artifact,
            output_directory=str(self.root / "plans"),
        )
        return BoardContractRuntimeBundle(decision, proof, artifact, plan)

    def test_only_the_declared_exact_targets_are_runtime_supported(self):
        observed = set()
        for contract in self.catalog.contracts:
            for variant in contract.hardware_variants:
                for target in variant.build_targets:
                    if target.support_status is SupportStatus.RUNTIME_SUPPORTED:
                        observed.add((contract.board_id, variant.id, target.id))
        self.assertEqual(
            {(board, variant, target) for _, board, variant, target, _ in MIGRATED},
            observed,
        )

    def test_migrated_aliases_resolve_to_one_exact_runtime_target(self):
        for alias, board_id, variant_id, target_id, detected_mcu in MIGRATED:
            with self.subTest(alias=alias, detected_mcu=detected_mcu):
                result = resolve_firmware_authority(
                    alias, detected_mcu=detected_mcu, catalog=self.catalog
                )
                self.assertIs(result.authority, FirmwareAuthority.BOARD_CONTRACT)
                self.assertEqual((board_id, variant_id, target_id), (
                    result.board_id,
                    result.hardware_variant_id,
                    result.build_target_id,
                ))
                self.assertEqual("RUNTIME_SUPPORTED", result.support_status)

    def test_existing_mcu_detection_resolves_each_skr_v14_variant_exactly(self):
        expected = {
            "lpc1768": "lpc1768",
            "lpc1769": "lpc1769-turbo",
        }
        for detected_mcu, variant_id in expected.items():
            with self.subTest(detected_mcu=detected_mcu):
                decision = resolve_firmware_authority(
                    "generic-bigtreetech-skr-v1.4.cfg",
                    detected_mcu=detected_mcu,
                    catalog=self.catalog,
                )
                self.assertEqual(variant_id, decision.hardware_variant_id)
                self.assertEqual("usb-native", decision.build_target_id)

    def test_known_skr_v14_mcu_does_not_trigger_an_mcu_question(self):
        with patch("core.menu.simple_input") as text_prompt, patch(
            "core.menu.numbered_select"
        ) as choice_prompt:
            decision = resolve_firmware_authority(
                "generic-bigtreetech-skr-v1.4.cfg",
                detected_mcu="lpc1769",
                catalog=self.catalog,
            )
        self.assertEqual("lpc1769-turbo", decision.hardware_variant_id)
        text_prompt.assert_not_called()
        choice_prompt.assert_not_called()

    def test_ambiguous_skr_v14_detection_blocks_without_arbitrary_selection(self):
        for detected_mcu in (None, "", "lpc176x", "lpc17"):
            with self.subTest(detected_mcu=detected_mcu):
                with self.assertRaisesRegex(
                    Exception, "did not identify|does not identify exactly one"
                ):
                    resolve_firmware_authority(
                        "generic-bigtreetech-skr-v1.4.cfg",
                        detected_mcu=detected_mcu,
                        catalog=self.catalog,
                    )

    def test_substrings_and_contracts_not_activated_remain_legacy(self):
        for alias in (
            "prefix-generic-creality-v4.2.7.cfg",
            "creality-v4.2.7-extra",
            "skr-mini-e3-v3",
            ".*skr-pico.*",
            "my-generic-bigtreetech-skr-v1.4.cfg",
            "skr-v1.4-turbo",
            "octopus-pro-v1.0",
            "printrboard",
        ):
            with self.subTest(alias=alias):
                self.assertIs(
                    resolve_firmware_authority(alias, catalog=self.catalog).authority,
                    FirmwareAuthority.LEGACY,
                )

    def test_bundle_rejects_evidence_from_a_different_contract(self):
        bundle = self._bundle()
        wrong_plan = replace(bundle.deployment_plan, board_id="another.board")
        with self.assertRaisesRegex(Exception, "do not share"):
            BoardContractRuntimeBundle(
                bundle.decision, bundle.proof, bundle.artifact, wrong_plan
            )

    @patch("firmware.boards.runtime.BoardContractKconfigBuilder.build")
    def test_runtime_build_wires_exact_proof_artifact_and_plan(self, build):
        source = self._bundle(MIGRATED[2][0])
        build.return_value = source.proof
        result = build_board_contract_runtime(
            source.decision,
            {
                "board_contract_output_directory": str(self.root / "runtime-build"),
                "board_contract_plan_directory": str(self.root / "runtime-plan"),
                "make_command": ("make",),
            },
            catalog=self.catalog,
        )
        build.assert_called_once()
        self.assertEqual(
            (
                source.decision.board_id,
                source.decision.hardware_variant_id,
                source.decision.build_target_id,
            ),
            build.call_args.args,
        )
        build_context = build.call_args.kwargs["context"]
        self.assertIsNone(build_context.concurrency)
        self.assertTrue(callable(build_context.progress_reporter))
        self.assertEqual(source.proof.digest, result.artifact.build_proof_digest)
        self.assertEqual(source.proof.digest, result.deployment_plan.build_proof_digest)

    @patch("core.firmware_wizard.FirmwareDeploymentService")
    @patch("core.firmware_wizard.build_firmware_orchestrator")
    @patch("core.firmware_wizard._resolve_firmware_configuration")
    @patch("core.firmware_wizard.derive_config")
    @patch("firmware.deployment.profiles.load_profiles")
    @patch("core.loader.load_boards_yaml")
    @patch("core.firmware_wizard.yes_no", return_value=True)
    def test_migrated_workflows_never_consult_legacy_firmware_decisions(
        self,
        _confirm,
        legacy_boards,
        legacy_profiles,
        generic_derivation,
        legacy_derivation,
        legacy_builder,
        legacy_deployment,
    ):
        legacy_boards.side_effect = AssertionError("legacy boards metadata read")
        legacy_profiles.side_effect = AssertionError("legacy deployment metadata read")
        for alias, board_id, variant_id, target_id, detected_mcu in MIGRATED:
            with self.subTest(alias=alias, detected_mcu=detected_mcu):
                bundle = self._bundle(alias, detected_mcu)
                user_data = {
                    "board": alias,
                    "mcu_type": detected_mcu,
                    "mcu_hint": "usb",
                }
                with patch(
                    "core.firmware_wizard.build_board_contract_runtime",
                    return_value=bundle,
                ):
                    result = run_firmware_wizard(user_data)
                self.assertEqual(WorkflowOutcome.SUCCESS, result.outcome)
                self.assertEqual("board_contract", user_data["firmware_authority"])
                self.assertEqual(board_id, user_data["firmware_artifact"].board_id)
                self.assertEqual(variant_id, bundle.proof.hardware_variant_id)
                self.assertEqual(target_id, bundle.deployment_plan.build_target_id)
                self.assertFalse(user_data["pending_firmware_deployment"])
                self.assertNotIn("firmware_deployment_plan", user_data)
        legacy_derivation.assert_not_called()
        generic_derivation.assert_not_called()
        legacy_builder.assert_not_called()
        legacy_deployment.assert_not_called()
        legacy_boards.assert_not_called()
        legacy_profiles.assert_not_called()

    @patch("core.firmware_wizard.build_board_contract_runtime")
    @patch("core.firmware_wizard.yes_no", return_value=False)
    def test_contract_target_is_fully_reviewed_before_build_confirmation(
        self, _confirm, contract_build
    ):
        user_data = {
            "board": "generic-creality-v4.2.7.cfg",
            "mcu_type": "stm32f103",
            "mcu_hint": "uart",
        }

        with patch("sys.stdout", new_callable=io.StringIO) as output:
            result = run_firmware_wizard(user_data)

        self.assertEqual(WorkflowOutcome.SUCCESS, result.outcome)
        contract_build.assert_not_called()
        rendered = output.getvalue()
        self.assertIn("creality.v4.2.7", rendered)
        self.assertIn("stm32f103-ret6", rendered)
        self.assertIn("28KiB bootloader", rendered)
        self.assertIn("uart-usart1-pa10-pa9", rendered)
        self.assertIn("kace-{build_id_short}.bin", rendered)
        self.assertIn("CONFIG_MACH_STM32=y", rendered)

    @patch("core.firmware_wizard.FirmwareDeploymentService")
    @patch("core.firmware_wizard.build_firmware_orchestrator")
    @patch("core.firmware_wizard._resolve_firmware_configuration")
    @patch("core.firmware_wizard.derive_config")
    @patch("core.firmware_wizard.build_board_contract_runtime")
    @patch("core.firmware_wizard.yes_no", return_value=True)
    def test_contract_error_blocks_without_legacy_fallback(
        self,
        _confirm,
        contract_build,
        generic_derivation,
        legacy_derivation,
        legacy_builder,
        legacy_deployment,
    ):
        contract_build.side_effect = RuntimeError("resolved assertion changed")
        user_data = {
            "board": MIGRATED[0][0],
            "mcu_type": "stm32f103",
            "mcu_hint": "uart",
        }
        result = run_firmware_wizard(user_data)
        self.assertEqual(WorkflowOutcome.FIRMWARE_FAILED, result.outcome)
        self.assertIn("resolved assertion changed", result.detail)
        self.assertEqual("board_contract", user_data["firmware_authority"])
        self.assertEqual(
            "board_contract",
            user_data["firmware_authority_event"]["firmware_authority"],
        )
        generic_derivation.assert_not_called()
        legacy_derivation.assert_not_called()
        legacy_builder.assert_not_called()
        legacy_deployment.assert_not_called()

    @patch("core.firmware_wizard.FirmwareDeploymentService")
    @patch("core.firmware_wizard.build_firmware_orchestrator")
    @patch("core.firmware_wizard._resolve_firmware_configuration")
    @patch("core.firmware_wizard.validate_firmware_configuration")
    @patch("core.firmware_wizard.numbered_select")
    @patch("core.firmware_wizard.yes_no", return_value=True)
    def test_non_migrated_board_keeps_legacy_authority(
        self, _confirm, select, _validate, legacy_derivation, legacy_builder, deployment
    ):
        legacy_derivation.return_value = (
            {"CONFIG_MCU": '"rpxxxx"', "CONFIG_RPXXXX_USB": "y"},
            "rp2040",
            "usb",
        )
        select.side_effect = [t("builder.compile_now"), "none"]
        legacy_builder.return_value = {
            "status": "success",
            "mcu": "rp2040",
            "firmware": "klipper.uf2",
            "path": "/fake/kace/klipper.uf2",
        }
        deployment.return_value.available_methods.return_value = ()
        user_data = {
            "board": "octopus-pro-v1.0",
            "mcu_type": "rp2040",
            "mcu_hint": "usb",
        }
        with patch("sys.stdout", new_callable=io.StringIO):
            result = run_firmware_wizard(user_data)
        self.assertEqual(WorkflowOutcome.SUCCESS, result.outcome)
        self.assertEqual("legacy", user_data["firmware_authority"])
        self.assertEqual(
            "legacy", user_data["firmware_authority_event"]["firmware_authority"]
        )
        legacy_derivation.assert_called_once()
        legacy_builder.assert_called_once()

if __name__ == "__main__":
    unittest.main()
