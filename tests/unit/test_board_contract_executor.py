"""Phase 4B fail-closed SD executor tests (no real media or hardware)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.mcu_monitor import McuIdentity, McuIdentityAmbiguous, McuIdentityMismatch
from firmware.artifacts import BuildArtifact, BuildProvenance, FirmwareFormat
from firmware.boards.catalog import load_default_catalog
from firmware.boards.deployment import create_deployment_plan
from firmware.boards.executor import (
    ArtifactExecutionError,
    ContractDeploymentExecutionError,
    ContractDeploymentState,
    FirmwareVerificationResult,
    MediaCandidate,
    MediaSelectionError,
    MediaVerificationError,
    PowerObservation,
    SafeEjectResult,
    SafeEjectStatus,
    SdCardDeploymentExecutor,
    UnsupportedContractStrategy,
)
from firmware.boards.promotion import (
    DeploymentPromotionError,
    create_deployment_promotion_request,
    write_deployment_promotion_request,
)
from firmware.identity import FirmwareBuildInputs, ToolchainIdentity
from firmware.deployment.models import (
    DeploymentMethodId, DeploymentProfile, DeploymentStrategyId,
    PostFlashVerification, UsbIdentityExpectation, UsbTopology,
)
from core.power_controller import ManualPowerResult, PrinterPowerState
from core.board_contract_deployment import run_sd_card_contract_deployment


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class FakeMediaProvider:
    def __init__(self, candidates=(), refreshes=None):
        self.candidates = tuple(candidates)
        self.refreshes = list(refreshes or ())
        self.list_calls = 0
        self.refresh_calls = 0

    def list_candidates(self):
        self.list_calls += 1
        return self.candidates

    def refresh(self, selected):
        self.refresh_calls += 1
        if self.refreshes:
            value = self.refreshes.pop(0)
            return selected if value == "same" else value
        return next(
            (item for item in self.candidates if item.stable_id == selected.stable_id),
            None,
        )


class FakeEjector:
    def __init__(self, status=SafeEjectStatus.EJECTED):
        self.status = status
        self.devices = []

    def eject(self, selected):
        self.devices.append(selected.device_path)
        return SafeEjectResult(
            self.status, selected.device_path, self.status.value.lower(),
            "2026-01-01T00:00:00Z",
        )


class FakeMonitor:
    def __init__(self, result=None, error=None):
        self.result = result or McuIdentity(
            "/dev/serial/by-id/kace", "/dev/ttyACM1",
            serial="MCU1", physical_path="pci-usb-1", physical_port="1-1",
            vendor_id="1d50", model_id="614e",
        )
        self.error = error
        self.arm_calls = 0
        self.wait_calls = 0
        self.close_calls = 0

    def arm(self):
        self.arm_calls += 1

    def wait_for_present(self, **_kwargs):
        self.wait_calls += 1
        if self.error:
            raise self.error
        return self.result

    def close(self):
        self.close_calls += 1


class FakeFirmwareVerifier:
    def __init__(self, result=None):
        self.result = result
        self.calls = []

    def wait_for_firmware(self, **kwargs):
        self.calls.append(kwargs)
        if self.result is not None:
            return self.result
        expected = kwargs["expected_fingerprint"]
        return FirmwareVerificationResult(True, expected, {"mcu": expected}, "ready")


class CorruptingWriter:
    def __init__(self, *, omit=False):
        self.omit = omit

    def copy(self, source, destination, deployment_id):
        if not self.omit:
            destination.write_bytes(source.read_bytes() + b"corruption")


class FakeManualRelay:
    def __init__(self):
        self.on_calls = 0
        self.off_calls = 0
        self.refresh_calls = 0
        self.state = PrinterPowerState.UNKNOWN

    def _result(self, action="", confirmed=False):
        return ManualPowerResult(
            self.state, "2026-01-01T00:00:00Z", "simulated",
            requested_action=action, confirmed=confirmed,
        )

    def refresh(self):
        self.refresh_calls += 1
        return self._result()

    def request_on(self):
        self.on_calls += 1
        self.state = PrinterPowerState.ON
        return self._result("ON", True)

    def request_off(self):
        self.off_calls += 1
        self.state = PrinterPowerState.OFF
        return self._result("OFF", True)


class BoardContractExecutorTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_default_catalog(refresh=True)
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.media_root = self.root / "media"
        self.media_root.mkdir()
        self.plan = self._make_plan("creality.v4.2.7", "stm32f103-ret6", "uart-usart1-pa10-pa9")

    def tearDown(self):
        self.temporary.cleanup()

    def _make_plan(self, board_id, variant_id, target_id):
        contract = self.catalog.by_id(board_id)
        variant = contract.variant(variant_id)
        target = variant.target(target_id)
        payload = f"firmware:{board_id}:{target_id}".encode() * 64
        native_dir = self.root / f"native-{board_id}-{target_id}"
        native_dir.mkdir(exist_ok=True)
        native = native_dir / target.artifact.native_filename
        native.write_bytes(payload)
        build_id = hashlib.md5(payload).hexdigest()
        identity = FirmwareBuildInputs.create(
            klipper_commit=contract.upstream.validated_commit,
            canonical_config='CONFIG_MCU="stm32"\n',
            toolchain=ToolchainIdentity("make", "GNU Make", "gcc", "gcc test"),
            build_id=build_id,
        ).complete(
            artifact_sha256=_sha(payload), artifact_size=len(payload),
            artifact_format=target.artifact.format.value.lower(),
        )
        artifact = BuildArtifact(
            build_id=build_id,
            path=str(native),
            native_filename=native.name,
            format={"BIN": FirmwareFormat.BIN, "UF2": FirmwareFormat.UF2}[target.artifact.format.value],
            sha256=_sha(payload),
            size_bytes=len(payload),
            mcu=variant.processor.resolved_mcu,
            firmware_fingerprint=identity.reported_version,
            provenance=BuildProvenance.REAL,
            flashable=False,
            firmware_identity=identity,
            board_id=board_id,
            hardware_variant_id=variant_id,
            build_target_id=target_id,
            board_contract_digest=contract.contract_digest,
            klipper_commit=contract.upstream.validated_commit,
            build_proof_digest="b" * 64,
        )
        return create_deployment_plan(
            contract, artifact, output_directory=str(self.root / "plans")
        )

    def _medium(self, **changes):
        values = dict(
            stable_id="partuuid:card-1", device_path="/dev/sdz1",
            parent_device="/dev/sdz", mount_path=str(self.media_root.resolve()),
            filesystem="vfat", size_bytes=16_000_000, free_bytes=8_000_000,
            removable=True, system_disk=False, read_only=False,
            label="KACE TEST", model="Fake SD", serial="CARD1",
        )
        values.update(changes)
        return MediaCandidate(**values)

    def _executor(self, *, provider=None, ejector=None, monitor=None, verifier=None, writer=None):
        medium = self._medium()
        return SdCardDeploymentExecutor(
            media_provider=provider or FakeMediaProvider((medium,)),
            ejector=ejector or FakeEjector(),
            mcu_monitor=monitor or FakeMonitor(),
            firmware_verifier=verifier or FakeFirmwareVerifier(),
            media_writer=writer,
            catalog=self.catalog,
        )

    def test_valid_copy_is_rehashed_ejected_and_waits_at_manual_gate(self):
        executor = self._executor()
        session = executor.prepare_media(self.plan)
        self.assertEqual(ContractDeploymentState.WAITING_FOR_MANUAL_POWER_CYCLE, session.state)
        copied = self.media_root / self.plan.transformation.final_filename
        self.assertEqual(Path(self.plan.transformation.final_path).read_bytes(), copied.read_bytes())
        proof = session.proof()
        self.assertEqual(self.plan.transformation.final_sha256, proof.media_readback_hash)
        self.assertEqual(SafeEjectStatus.EJECTED, proof.safe_eject.status)
        self.assertEqual(64, len(proof.digest))
        self.assertFalse(proof.manual_confirmation)
        self.assertEqual(proof.digest, session.proof().digest)
        with self.assertRaises(FrozenInstanceError):
            proof.final_state = ContractDeploymentState.FAILED
        with self.assertRaises(FrozenInstanceError):
            proof.selected_media.stable_id = "changed"

    def test_skr_v14_plans_are_directly_compatible_with_phase_4b_sd_executor(self):
        for variant_id in ("lpc1768", "lpc1769-turbo"):
            with self.subTest(variant=variant_id):
                plan = self._make_plan("btt.skr-v1.4", variant_id, "usb-native")
                self.assertEqual("SD_CARD", plan.strategy.value)
                self.assertEqual("firmware.bin", plan.transformation.final_filename)
                self.assertFalse(plan.transformation.content_changed)
                self.assertEqual(
                    plan.artifact.sha256, plan.transformation.final_sha256
                )
                self.assertEqual(
                    (
                        "VALIDATE_ARTIFACT", "ASSIGN_FINAL_FILENAME",
                        "VERIFY_FILENAME_POLICY", "PREPARE_MEDIA",
                        "COPY_TO_MEDIA", "VERIFY_MEDIA_CHECKSUM", "SAFE_EJECT",
                        "REQUIRE_POWER_OFF", "REQUIRE_MEDIA_INSERTED",
                        "REQUIRE_POWER_ON", "WAIT_FOR_MCU_REENUMERATION",
                        "VERIFY_KLIPPER_BUILD_ID",
                    ),
                    tuple(step.id.value for step in plan.steps),
                )
                session = self._executor().prepare_media(plan)
                self.assertEqual(
                    ContractDeploymentState.WAITING_FOR_MANUAL_POWER_CYCLE,
                    session.state,
                )

    def test_explicit_selection_resolves_multiple_candidates(self):
        other_root = self.root / "other"
        other_root.mkdir()
        first = self._medium()
        second = self._medium(
            stable_id="partuuid:card-2", device_path="/dev/sdy1",
            parent_device="/dev/sdy", mount_path=str(other_root.resolve()), serial="CARD2",
        )
        provider = FakeMediaProvider((first, second))
        session = self._executor(provider=provider).prepare_media(
            self.plan, selected_media_id=second.stable_id
        )
        self.assertEqual(second.stable_id, session.selected_media.stable_id)

    def test_no_media_and_ambiguous_media_fail_closed(self):
        with self.assertRaises(MediaSelectionError) as none:
            self._executor(provider=FakeMediaProvider()).prepare_media(self.plan)
        self.assertEqual("NO_MEDIA", none.exception.code)
        second_root = self.root / "second"
        second_root.mkdir()
        second = self._medium(
            stable_id="partuuid:card-2", device_path="/dev/sdy1",
            parent_device="/dev/sdy", mount_path=str(second_root.resolve()), serial="CARD2",
        )
        with self.assertRaises(MediaSelectionError) as ambiguous:
            self._executor(provider=FakeMediaProvider((self._medium(), second))).prepare_media(self.plan)
        self.assertEqual("MEDIA_AMBIGUOUS", ambiguous.exception.code)

    def test_media_policy_rejections(self):
        cases = (
            (dict(filesystem="ext4"), "FILESYSTEM_MISMATCH"),
            (dict(free_bytes=1), "INSUFFICIENT_SPACE"),
            (dict(system_disk=True), "SYSTEM_DISK_REJECTED"),
            (dict(removable=False), "MEDIA_NOT_REMOVABLE"),
            (dict(read_only=True), "MEDIA_READ_ONLY"),
        )
        for changes, code in cases:
            with self.subTest(code=code):
                medium = self._medium(**changes)
                with self.assertRaises(MediaVerificationError) as caught:
                    self._executor(provider=FakeMediaProvider((medium,))).prepare_media(self.plan)
                self.assertEqual(code, caught.exception.code)

    def test_medium_disappearance_and_identity_change_are_detected(self):
        medium = self._medium()
        with self.assertRaises(MediaVerificationError) as disappeared:
            self._executor(
                provider=FakeMediaProvider((medium,), refreshes=[None])
            ).prepare_media(self.plan)
        self.assertEqual("MEDIA_DISAPPEARED", disappeared.exception.code)
        changed = replace(medium, device_path="/dev/sdy1", parent_device="/dev/sdy")
        with self.assertRaises(MediaVerificationError) as identity:
            self._executor(
                provider=FakeMediaProvider((medium,), refreshes=[changed])
            ).prepare_media(self.plan)
        self.assertEqual("MEDIA_IDENTITY_CHANGED", identity.exception.code)
        changed_after_copy = replace(
            medium, device_path="/dev/sdy1", parent_device="/dev/sdy"
        )
        with self.assertRaises(MediaVerificationError) as during_copy:
            self._executor(provider=FakeMediaProvider(
                (medium,), refreshes=["same", "same", changed_after_copy]
            )).prepare_media(self.plan)
        self.assertEqual("MEDIA_IDENTITY_CHANGED", during_copy.exception.code)
        with self.assertRaises(MediaVerificationError) as gone_during_copy:
            self._executor(provider=FakeMediaProvider(
                (medium,), refreshes=["same", "same", None]
            )).prepare_media(self.plan)
        self.assertEqual("MEDIA_DISAPPEARED", gone_during_copy.exception.code)

    def test_artifact_tampering_and_absence_block_before_media_discovery(self):
        provider = FakeMediaProvider((self._medium(),))
        staged = Path(self.plan.transformation.final_path)
        staged.write_bytes(staged.read_bytes() + b"changed")
        with self.assertRaises(ArtifactExecutionError) as changed:
            self._executor(provider=provider).prepare_media(self.plan)
        self.assertIn(changed.exception.code, {"ARTIFACT_SIZE_MISMATCH", "ARTIFACT_HASH_MISMATCH"})
        self.assertEqual(0, provider.list_calls)
        staged.unlink()
        with self.assertRaises(ArtifactExecutionError) as absent:
            self._executor(provider=provider).prepare_media(self.plan)
        self.assertEqual("ARTIFACT_ABSENT", absent.exception.code)
        self.assertEqual(0, provider.list_calls)

    def test_corrupt_or_absent_media_copy_is_not_success(self):
        with self.assertRaises(ArtifactExecutionError) as corrupt:
            self._executor(writer=CorruptingWriter()).prepare_media(self.plan)
        self.assertIn(corrupt.exception.code, {"MEDIA_SIZE_MISMATCH", "MEDIA_HASH_MISMATCH"})
        (self.media_root / self.plan.transformation.final_filename).unlink()
        with self.assertRaises(ArtifactExecutionError) as absent:
            self._executor(writer=CorruptingWriter(omit=True)).prepare_media(self.plan)
        self.assertEqual("MEDIA_FILE_ABSENT", absent.exception.code)

    def test_eject_success_unsupported_and_failure_are_explicit_and_exact(self):
        for status, success in (
            (SafeEjectStatus.EJECTED, True),
            (SafeEjectStatus.UNSUPPORTED, False),
            (SafeEjectStatus.FAILED, False),
        ):
            with self.subTest(status=status):
                ejector = FakeEjector(status)
                executor = self._executor(ejector=ejector)
                if success:
                    executor.prepare_media(self.plan)
                else:
                    with self.assertRaises(MediaVerificationError):
                        executor.prepare_media(self.plan)
                self.assertEqual(["/dev/sdz1"], ejector.devices)

    def test_manual_gate_never_advances_from_observed_power_or_early_mcu(self):
        monitor = FakeMonitor()
        executor = self._executor(monitor=monitor)
        session = executor.prepare_media(self.plan)
        executor.record_power_observation(
            session, PowerObservation("OFF", "now", "observed")
        )
        executor.record_power_observation(
            session, PowerObservation("ON", "later", "observed")
        )
        proof = executor.confirm_manual_power_cycle(session, confirmed=False)
        self.assertEqual(ContractDeploymentState.WAITING_FOR_MANUAL_POWER_CYCLE, proof.final_state)
        self.assertEqual(0, monitor.wait_calls)
        self.assertFalse(proof.manual_confirmation)

    def test_explicit_confirmation_and_exact_fingerprint_are_required_for_verified(self):
        executor = self._executor()
        session = executor.prepare_media(self.plan)
        proof = executor.confirm_manual_power_cycle(session, confirmed=True)
        self.assertEqual(ContractDeploymentState.VERIFIED, proof.final_state)
        self.assertTrue(proof.manual_confirmation)
        self.assertEqual(proof.expected_fingerprint, proof.observed_fingerprint)
        self.assertEqual("MCU1", proof.observed_mcu_identity.serial)

    def test_post_flash_failures_never_verify(self):
        cases = (
            (FakeMonitor(error=TimeoutError("gone")), FakeFirmwareVerifier(), "MCU_REENUMERATION_TIMEOUT"),
            (FakeMonitor(error=McuIdentityMismatch("wrong")), FakeFirmwareVerifier(), "MCU_IDENTITY_REJECTED"),
            (FakeMonitor(error=McuIdentityAmbiguous("many")), FakeFirmwareVerifier(), "MCU_IDENTITY_REJECTED"),
            (FakeMonitor(), FakeFirmwareVerifier(FirmwareVerificationResult(False, "", {}, "offline")), "KLIPPER_NOT_READY"),
            (FakeMonitor(), FakeFirmwareVerifier(FirmwareVerificationResult(True, "wrong", {"mcu": "wrong"}, "ready")), "FIRMWARE_FINGERPRINT_MISMATCH"),
        )
        for monitor, verifier, code in cases:
            with self.subTest(code=code):
                executor = self._executor(monitor=monitor, verifier=verifier)
                session = executor.prepare_media(self.plan)
                with self.assertRaises(ContractDeploymentExecutionError) as caught:
                    executor.confirm_manual_power_cycle(session, confirmed=True)
                self.assertEqual(code, caught.exception.code)
                self.assertEqual(ContractDeploymentState.FAILED, caught.exception.proof.final_state)

    def test_contract_identity_and_plan_digest_tampering_block_before_media(self):
        changes = (
            {"board_id": "btt.skr-mini-e3.v3.0"},
            {"hardware_variant_id": "wrong"},
            {"build_target_id": "wrong"},
            {"board_contract_digest": "0" * 64},
            {"klipper_commit": "0" * 40},
            {"build_proof_digest": "0" * 64},
            {"plan_digest": "0" * 64},
        )
        for fields in changes:
            with self.subTest(fields=fields):
                provider = FakeMediaProvider((self._medium(),))
                with self.assertRaises(ContractDeploymentExecutionError):
                    self._executor(provider=provider).prepare_media(replace(self.plan, **fields))
                self.assertEqual(0, provider.list_calls)

    def test_filename_and_extension_tampering_are_rejected(self):
        for filename in ("wrong.bin", "firmware.hex"):
            transformation = replace(self.plan.transformation, final_filename=filename)
            with self.assertRaises(ContractDeploymentExecutionError):
                self._executor().prepare_media(replace(self.plan, transformation=transformation))

    def test_legacy_raw_and_unsupported_strategies_never_fallback(self):
        legacy_profile = DeploymentProfile(
            id="legacy", method=DeploymentMethodId.MANUAL,
            board_patterns=("Creality",), formats=(FirmwareFormat.BIN,),
            config_mcu="stm32", native_filenames=("klipper.bin",),
            final_filename="firmware.bin", instruction_keys=("copy",),
            strategy=DeploymentStrategyId.SD_CARD, bootloader_offset=None,
            usb=UsbIdentityExpectation(UsbTopology.NOT_APPLICABLE),
            post_flash_verification=PostFlashVerification.KLIPPER_BUILD_ID,
        )
        for invalid in ({}, "strategy: SD_CARD", object(), legacy_profile):
            with self.subTest(invalid=type(invalid).__name__):
                with self.assertRaises(ContractDeploymentExecutionError) as caught:
                    self._executor().prepare_media(invalid)
                self.assertEqual("INVALID_PLAN_TYPE", caught.exception.code)
        pico = self._make_plan("btt.skr-pico.v1.0", "rp2040", "usb-native")
        with self.assertRaises(UnsupportedContractStrategy) as unsupported:
            self._executor().prepare_media(pico)
        self.assertEqual("UNSUPPORTED_STRATEGY", unsupported.exception.code)

    def test_executor_has_no_power_api_and_emits_contract_authority(self):
        events = []
        executor = SdCardDeploymentExecutor(
            media_provider=FakeMediaProvider((self._medium(),)),
            ejector=FakeEjector(), mcu_monitor=FakeMonitor(),
            firmware_verifier=FakeFirmwareVerifier(), catalog=self.catalog,
            event_sink=events.append,
        )
        self.assertFalse(hasattr(executor, "power_on"))
        self.assertFalse(hasattr(executor, "power_off"))
        executor.prepare_media(self.plan)
        self.assertTrue(events)
        self.assertTrue(all(
            event["schema"] == 2
            and event["data"]["firmware_authority"] == "board_contract"
            for event in events
        ))

    def test_verified_proof_creates_review_request_without_editing_contract(self):
        contract_path = Path("data/board_contracts/v1/creality-v4.2.7.yaml")
        before = contract_path.read_bytes()
        executor = self._executor()
        session = executor.prepare_media(self.plan)
        proof = executor.confirm_manual_power_cycle(session, confirmed=True)
        request = create_deployment_promotion_request(proof, catalog=self.catalog)
        self.assertTrue(request.review_required)
        self.assertEqual("DEPLOYMENT_VERIFIED", request.requested_status.value)
        self.assertEqual(proof.digest, request.deployment_proof_digest)
        self.assertEqual(64, len(request.digest))
        path = write_deployment_promotion_request(request, str(self.root / "promotions"))
        self.assertTrue(Path(path).is_file())
        self.assertEqual(before, contract_path.read_bytes())

    def test_unverified_proof_cannot_create_promotion_request(self):
        session = self._executor().prepare_media(self.plan)
        with self.assertRaises(DeploymentPromotionError):
            create_deployment_promotion_request(session.proof(), catalog=self.catalog)

    def test_cli_relay_actions_only_follow_explicit_operator_choices(self):
        medium = self._medium()
        relay = FakeManualRelay()
        user_data = {
            "mcu_path": "/dev/serial/by-id/kace-test",
            "board_contract_deployment_proof_directory": str(self.root / "proofs"),
        }
        with patch(
            "core.board_contract_deployment.numbered_select",
            side_effect=[medium.stable_id, "off", "on", "confirm"],
        ), patch(
            "core.board_contract_deployment.yes_no", return_value=True
        ):
            proof = run_sd_card_contract_deployment(
                user_data, self.plan,
                provider=FakeMediaProvider((medium,)),
                ejector=FakeEjector(), monitor=FakeMonitor(),
                verifier=FakeFirmwareVerifier(), relay_control=relay,
                event_sink=lambda _event: None,
            )
        self.assertEqual(1, relay.off_calls)
        self.assertEqual(1, relay.on_calls)
        self.assertEqual(ContractDeploymentState.VERIFIED, proof.final_state)
        self.assertTrue(Path(user_data["board_contract_deployment_proof_path"]).is_file())

    def test_cli_refresh_and_confirmation_never_switch_relay(self):
        medium = self._medium()
        relay = FakeManualRelay()
        user_data = {
            "mcu_path": "/dev/serial/by-id/kace-test",
            "board_contract_deployment_proof_directory": str(self.root / "proofs"),
        }
        with patch(
            "core.board_contract_deployment.numbered_select",
            side_effect=[medium.stable_id, "refresh", "confirm"],
        ), patch(
            "core.board_contract_deployment.yes_no", return_value=True
        ):
            proof = run_sd_card_contract_deployment(
                user_data, self.plan,
                provider=FakeMediaProvider((medium,)),
                ejector=FakeEjector(), monitor=FakeMonitor(),
                verifier=FakeFirmwareVerifier(), relay_control=relay,
                event_sink=lambda _event: None,
            )
        self.assertEqual(0, relay.off_calls)
        self.assertEqual(0, relay.on_calls)
        self.assertGreaterEqual(relay.refresh_calls, 2)
        self.assertEqual(ContractDeploymentState.VERIFIED, proof.final_state)


if __name__ == "__main__":
    unittest.main()
