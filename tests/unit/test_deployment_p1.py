"""Hardware-free regressions for firmware identity and rollback ownership."""

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.firmware_workflow import (
    CheckpointIncompatible, FirmwareWorkflowState as State, _with_integrity,
    artifact_evidence,
    transition_checkpoint, verify_reappeared_mcu, write_checkpoint, load_checkpoint,
)
from core.mcu_monitor import McuIdentity
from core.snapshot import create_snapshot, restore_snapshot
from core.workflow_outcome import WorkflowOutcome
from tests.unit.test_config_transaction import FakeTransport, GENERATED
from tests.unit.test_firmware_workflow import awaiting_flash, physical_identity
from tests.unit import test_moonraker_deployer as physical_tests


class TransactionIdentityTests(unittest.TestCase):
    def test_fingerprint_failure_or_unavailable_response_requires_recovery_before_done(self):
        for error in (RuntimeError("wrong fingerprint"), TimeoutError("version unavailable")):
            with self.subTest(error=str(error)), tempfile.TemporaryDirectory() as root:
                transport = FakeTransport({"printer.cfg": b"# original\n"})
                events = []
                verifier = Mock(side_effect=error)
                result = ConfigDeploymentTransaction(
                    transport, GENERATED, None, activation="firmware", snapshot_root=root,
                    verify_firmware=verifier, poll_interval=0,
                    state_sink=lambda state, _detail: events.append(state),
                ).run()
                self.assertEqual(result.state, ConfigTransactionState.ROLLBACK_FAILED)
                self.assertFalse(result.rollback_succeeded)
                self.assertIn("firmware verification error", result.detail)
                self.assertIn("manual recovery", result.detail)
                self.assertEqual(result.snapshot.config_files, {"printer.cfg": b"# original\n"})
                self.assertNotIn("DONE", events)
                self.assertEqual(transport.calls.count(("restart", "firmware")), 1)

    def test_matching_and_idempotent_deployments_verify_before_done(self):
        with tempfile.TemporaryDirectory() as root:
            transport = FakeTransport()
            for repeat in range(2):
                order = []
                transport.calls.clear()
                result = ConfigDeploymentTransaction(
                    transport, GENERATED, None, activation="firmware", snapshot_root=root,
                    verify_firmware=lambda: order.append("fingerprint"), poll_interval=0,
                    state_sink=lambda state, _detail: order.append(state),
                ).run()
                self.assertTrue(result.ok)
                self.assertLess(order.index("fingerprint"), order.index("DONE"))
                if repeat:
                    self.assertFalse(any(c[0] == "upload" for c in transport.calls))
                    self.assertIn(("restart", "firmware"), transport.calls)
            before = dict(transport.files)
            events = []
            result = ConfigDeploymentTransaction(
                transport, GENERATED, None, activation="firmware", snapshot_root=root,
                verify_firmware=Mock(side_effect=RuntimeError("wrong fingerprint")),
                poll_interval=0, state_sink=lambda s, _: events.append(s),
            ).run()
            self.assertEqual(result.state, ConfigTransactionState.FIRMWARE_FAILED)
            self.assertEqual(transport.files, before)
            self.assertIsNone(result.rollback_succeeded)
            self.assertNotIn("DONE", events)

    def test_pending_activation_does_not_verify_inactive_firmware(self):
        with tempfile.TemporaryDirectory() as root:
            verifier = Mock()
            result = ConfigDeploymentTransaction(
                FakeTransport(), GENERATED, None, activation="none", snapshot_root=root,
                verify_firmware=verifier,
            ).run()
        self.assertTrue(result.pending)
        verifier.assert_not_called()

    def test_both_live_adapters_keep_fingerprint_inside_real_transaction(self):
        from contextlib import ExitStack
        from core import deployer

        for route in ("moonraker", "sftp"):
            with self.subTest(route=route), tempfile.TemporaryDirectory() as root, ExitStack() as stack:
                checkpoint = awaiting_flash(Path(root))
                checkpoint = transition_checkpoint(checkpoint, State.VERIFYING_MCU)
                checkpoint = transition_checkpoint(
                    checkpoint, State.MCU_VERIFIED, verified_serial_path="/dev/serial/by-id/test",
                    flash_evidence_recorded_at=1,
                )
                for state in (State.CONFIG_GENERATED, State.READY_TO_DEPLOY, State.DEPLOYING):
                    checkpoint = transition_checkpoint(checkpoint, state)
                transport = FakeTransport({"printer.cfg": b"# original\n"})
                transport.host, transport.port, transport.api_key = "pi.local", 7125, None
                user = {"workflow_checkpoint": checkpoint, "host": "pi.local",
                        "user": "kace", "dest_path": "~/printer_data/config/"}
                def snapshot(*args, **kwargs):
                    kwargs["persist_root"] = root
                    return create_snapshot(*args, **kwargs)
                stack.enter_context(patch("core.config_transaction.create_snapshot", side_effect=snapshot))
                stack.enter_context(patch.object(deployer, "_generated_config_bytes", return_value=("unused", GENERATED, None)))
                stack.enter_context(patch.object(deployer, "_preflight_check", return_value=True))
                stack.enter_context(patch.object(deployer, "_interactive_configuration_review", return_value=True))
                stack.enter_context(patch.object(deployer, "_select_config_activation", return_value="firmware"))
                stack.enter_context(patch.object(deployer._MoonrakerClient, "get_mcu_versions", return_value={"mcu": "old-firmware"}))
                stack.enter_context(patch("core.config_transaction.time.sleep"))
                if route == "moonraker":
                    stack.enter_context(patch("core.menu.simple_input", side_effect=["pi.local", "7125", ""]))
                    stack.enter_context(patch("core.moonraker.check_moonraker", return_value=(True, "ok")))
                    stack.enter_context(patch("core.config_transaction.MoonrakerConfigTransport", return_value=transport))
                    result = deployer.deploy_moonraker(user)
                else:
                    stack.enter_context(patch.object(deployer, "_require_paramiko", return_value=SimpleNamespace(AuthenticationException=RuntimeError)))
                    stack.enter_context(patch.object(deployer, "_connect_ssh_client", return_value=Mock()))
                    stack.enter_context(patch("core.config_transaction.SftpConfigTransport", return_value=transport))
                    result = deployer.deploy_config(user)
                self.assertEqual(result.outcome, WorkflowOutcome.DEPLOYMENT_FAILED, result.detail)
                self.assertIn("firmware verification error", result.detail)
                self.assertIn("manual recovery", result.detail)
                self.assertEqual(transport.calls.count(("restart", "firmware")), 1)


class RollbackOwnershipTests(unittest.TestCase):
    def test_rollback_read_failure_or_late_external_edit_blocks_restoration(self):
        for unreadable in (True, False):
            with self.subTest(unreadable=unreadable), tempfile.TemporaryDirectory() as root:
                transport = FakeTransport({"printer.cfg": b"# original\n"})
                read = transport.read_files
                recovery_reads = []
                recovering = False

                def fail_activation(_mode):
                    nonlocal recovering
                    recovering = True
                    raise RuntimeError("restart failed")

                def read_files(names):
                    if recovering:
                        recovery_reads.append(names)
                        if unreadable:
                            raise ConnectionError("cannot inspect current bytes")
                        # Preflight checked the root; the per-file check must
                        # catch an editor changing it immediately afterwards.
                        if len(recovery_reads) == 1:
                            transport.files["printer.cfg"] = b"external"
                    return read(names)

                transport.restart = Mock(side_effect=fail_activation)
                transport.read_files = read_files
                result = ConfigDeploymentTransaction(
                    transport, GENERATED, None, activation="firmware", snapshot_root=root,
                ).run()
                self.assertEqual(result.state, ConfigTransactionState.ROLLBACK_FAILED)
                self.assertFalse(result.rollback_succeeded)
                self.assertEqual(transport.restart.call_count, 1)
                if unreadable:
                    self.assertIn("cannot inspect current bytes", result.detail)
                    self.assertIn(b"[include", transport.files["printer.cfg"])
                else:
                    self.assertIn("concurrent modification", result.detail)
                    self.assertEqual(transport.files["printer.cfg"], b"external")

    def test_external_edit_or_delete_after_upload_is_preserved_without_restart(self):
        for name in ("printer.cfg", "kace/generated-hardware.cfg"):
            for replacement in (b"# external edit\n", None):
                with self.subTest(name=name, replacement=replacement), tempfile.TemporaryDirectory() as root:
                    transport = FakeTransport({"printer.cfg": b"# original\n"})
                    def fail_activation(mode):
                        transport.calls.append(("restart", mode))
                        if transport.calls.count(("restart", mode)) > 1:
                            return
                        if replacement is None:
                            transport.files.pop(name, None)
                        else:
                            transport.files[name] = replacement
                        raise RuntimeError("restart failed")
                    transport.restart = fail_activation
                    result = ConfigDeploymentTransaction(
                        transport, GENERATED, None, activation="firmware", snapshot_root=root,
                    ).run()
                    self.assertEqual(result.state, ConfigTransactionState.ROLLBACK_FAILED)
                    self.assertIn("manual recovery", result.detail)
                    self.assertEqual(transport.files.get(name), replacement)
                    self.assertEqual(transport.calls.count(("restart", "firmware")), 1)

    def test_failed_upload_does_not_claim_unknown_partial_or_external_bytes(self):
        with tempfile.TemporaryDirectory() as root:
            transport = FakeTransport()
            def upload(name, content):
                transport.files[name] = b"unknown bytes"
                raise OSError("connection lost after possible write")
            transport.upload_bytes = upload
            result = ConfigDeploymentTransaction(
                transport, GENERATED, None, activation="firmware", snapshot_root=root,
            ).run()
            self.assertEqual(result.state, ConfigTransactionState.ROLLBACK_FAILED)
            self.assertIn("concurrent modification", result.detail)
            self.assertEqual(transport.files["kace/generated-hardware.cfg"], b"unknown bytes")

    def test_physical_snapshot_rollback_checks_ownership_and_rechecks_before_write(self):
        for change_during_restore in (False, True):
            with self.subTest(late=change_during_restore), tempfile.TemporaryDirectory() as root:
                snapshot = create_snapshot({"printer.cfg": b"old", "new.cfg": None}, persist_root=root)
                remote = {"printer.cfg": b"written", "new.cfg": b"written-new"}
                reads = []
                def read_files(names):
                    reads.append(names)
                    if not change_during_restore:
                        remote["printer.cfg"] = b"external"
                    captured = {n: remote.get(n) for n in names}
                    if change_during_restore:
                        remote["printer.cfg"] = b"external"
                    return captured
                with patch("core.config_transaction.MoonrakerConfigTransport.read_files", side_effect=read_files), \
                     patch("core.snapshot.upload_printer_cfg") as upload, \
                     patch("core.snapshot.delete_config_file") as delete, \
                     patch("core.snapshot.restart_firmware") as restart:
                    failures = restore_snapshot(snapshot, "pi", 7125, expected_files={
                        "printer.cfg": b"written", "new.cfg": b"written-new",
                    })
                self.assertTrue(failures)
                self.assertIn("manual recovery", " ".join(failures))
                self.assertEqual(remote["printer.cfg"], b"external")
                upload.assert_not_called()
                restart.assert_not_called()

    def test_owned_snapshot_restore_only_touches_attempted_files(self):
        with tempfile.TemporaryDirectory() as root:
            snapshot = create_snapshot({"printer.cfg": b"old", "untouched.cfg": b"keep", "new.cfg": None}, persist_root=root)
            remote = {"printer.cfg": b"written", "untouched.cfg": b"external", "new.cfg": b"written-new"}
            with patch("core.config_transaction.MoonrakerConfigTransport.read_files", side_effect=lambda ns: {n: remote.get(n) for n in ns}), \
                 patch("core.snapshot.upload_printer_cfg", return_value=(True, "ok")) as upload, \
                 patch("core.snapshot.delete_config_file", return_value=(True, "ok")) as delete:
                errors = restore_snapshot(snapshot, "pi", 7125, issue_restart=False,
                                          expected_files={"printer.cfg": b"written", "new.cfg": b"written-new"})
            self.assertIn("manual recovery", " ".join(errors))
            upload.assert_not_called()
            delete.assert_not_called()
            self.assertEqual(remote, {"printer.cfg": b"written", "untouched.cfg": b"external", "new.cfg": b"written-new"})


class ManualIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.checkpoint = awaiting_flash(Path(self.temp.name))
        self.path = "/dev/serial/by-id/usb-Klipper_lpc1769_NEW-if00"

    def verify(self, identity, **kwargs):
        with patch("core.firmware_workflow.os.path.exists", return_value=True):
            return verify_reappeared_mcu(
                self.checkpoint, flash_evidence=True,
                detector=lambda: {"derived_mcu": "lpc1769", "mcu_path": self.path},
                identity_reader=SimpleNamespace(read=lambda _: identity), **kwargs,
            )

    def test_same_model_on_another_port_is_not_automatically_accepted(self):
        with self.assertRaisesRegex(CheckpointIncompatible, "physical identity"):
            self.verify(physical_identity(self.path, port="usb-2", serial="another-board"))

    def test_serial_change_requires_explicit_physical_confirmation_and_is_recorded(self):
        candidate = physical_identity(self.path, serial="changed")
        for confirmation in (None, lambda _: False):
            with self.assertRaises(CheckpointIncompatible):
                self.verify(candidate, ambiguity_resolver=confirmation)
        callback = Mock(return_value=True)
        verified, _ = self.verify(candidate, ambiguity_resolver=callback)
        self.assertTrue(verified["hardware"]["identity_manually_confirmed"])
        self.assertEqual(callback.call_args.args[0].baseline.serial, "original")
        self.assertEqual(verified["hardware"]["identity_assessment"]["candidate"]["serial"], "changed")

    def test_wrong_vid_pid_cannot_be_overridden_by_confirmation(self):
        resolver = Mock(return_value=True)
        with self.assertRaises(CheckpointIncompatible):
            self.verify(McuIdentity(self.path, "/dev/ttyACM1", physical_port="usb-1",
                                    vendor_id="ffff", model_id="ffff"), ambiguity_resolver=resolver)
        resolver.assert_not_called()

    def test_auto_mode_cannot_supply_physical_confirmation(self):
        import kace
        with patch.dict("os.environ", {"KACE_AUTO": "1"}), \
             patch("core.board_contract_deployment._ambiguity_confirmation") as prompt:
            self.assertFalse(kace._confirm_workflow_mcu_identity(None))
        prompt.assert_not_called()

    def test_contract_application_identity_can_differ_from_original_firmware(self):
        self.checkpoint["artifact"]["expected_vid_pids"] = ["1234:5678"]
        self.checkpoint["artifact"]["bootloader_vid_pids"] = ["1234:0001"]
        self.checkpoint = _with_integrity(self.checkpoint)
        resolver = Mock(return_value=True)
        with self.assertRaises(CheckpointIncompatible):
            self.verify(McuIdentity(self.path, "/dev/ttyACM1", physical_port="usb-1",
                                    vendor_id="1234", model_id="0001"), ambiguity_resolver=resolver)
        resolver.assert_not_called()
        verified, _ = self.verify(McuIdentity(
            self.path, "/dev/ttyACM1", physical_port="usb-1", serial="original",
            vendor_id="1234", model_id="5678",
        ))
        self.assertFalse(verified["hardware"]["identity_manually_confirmed"])

    def test_artifact_projection_keeps_contract_and_legacy_usb_expectations(self):
        from firmware.boards.catalog import load_default_catalog
        target = load_default_catalog().by_id("btt.skr-mini-e3.v3.0").variant("stm32g0b1").target("usb-pa11-pa12")
        from tests.unit.test_hardware_readiness import build_artifact
        built = build_artifact(Path(self.temp.name))
        transformation = SimpleNamespace(native_sha256=built.sha256, final_sha256=built.sha256,
                                         size_bytes=built.size_bytes)
        plan = SimpleNamespace(transformation=transformation, board_id="btt.skr-mini-e3.v3.0", hardware_variant_id="stm32g0b1",
                               build_target_id="usb-pa11-pa12")
        evidence = artifact_evidence({"firmware_path": built.path, "firmware_artifact": built,
                                      "board_contract_deployment_plan": plan})
        self.assertEqual(evidence["expected_vid_pids"], [target.transport.endpoint["application_vid_pid"]])
        self.assertEqual(evidence["bootloader_vid_pids"], [])
        usb = SimpleNamespace(application_vid_pids=("2341:0042",), bootloader_vid_pids=("2341:003d",))
        prepared = SimpleNamespace(sha256=built.sha256, plan=SimpleNamespace(artifact=built, profile=SimpleNamespace(usb=usb)))
        evidence = artifact_evidence({"firmware_path": built.path, "firmware_artifact": built,
                                      "prepared_firmware_deployment": prepared})
        self.assertEqual(evidence["expected_vid_pids"], ["2341:0042"])
        self.assertEqual(evidence["bootloader_vid_pids"], ["2341:003d"])

    def test_checkpoint_roundtrip_preserves_original_physical_identity(self):
        filename = str(Path(self.temp.name) / "checkpoint.json")
        write_checkpoint(self.checkpoint, filename)
        self.checkpoint = load_checkpoint(filename)
        verified, _ = self.verify(physical_identity(self.path))
        self.assertEqual(verified["state"], State.MCU_VERIFIED.value)
        self.assertFalse(verified["hardware"]["identity_manually_confirmed"])

    def test_legacy_checkpoint_or_unreadable_identity_requires_confirmation(self):
        with self.assertRaises(CheckpointIncompatible):
            self.verify(None)
        self.checkpoint["hardware"].pop("baseline_identity")
        self.checkpoint = _with_integrity(self.checkpoint)
        with self.assertRaises(CheckpointIncompatible):
            self.verify(physical_identity(self.path))
        verified, _ = self.verify(physical_identity(self.path), ambiguity_resolver=lambda _: True)
        self.assertTrue(verified["hardware"]["identity_manually_confirmed"])

    def test_multiple_same_model_devices_select_original_topology_not_first_path(self):
        other = "/dev/serial/by-id/usb-Klipper_lpc1769_AAA-if00"
        identities = {other: physical_identity(other, port="usb-2", serial="other"), self.path: physical_identity(self.path)}
        with patch("core.firmware_workflow.glob.glob", return_value=[other, self.path]), \
             patch("core.firmware_workflow.os.path.exists", return_value=True):
            verified, observed = verify_reappeared_mcu(
                self.checkpoint, flash_evidence=True,
                identity_reader=SimpleNamespace(read=lambda p: identities[p]),
            )
        self.assertEqual(observed["mcu_path"], self.path)
        self.assertEqual(verified["hardware"]["verified_serial_path"], self.path)

    def test_multiple_ambiguous_devices_do_not_select_the_first_or_prompt_blindly(self):
        other = "/dev/serial/by-id/usb-Klipper_lpc1769_AAA-if00"
        resolver = Mock(return_value=True)
        with patch("core.firmware_workflow.glob.glob", return_value=[other, self.path]), \
             patch("core.firmware_workflow.os.path.exists", return_value=True):
            with self.assertRaisesRegex(CheckpointIncompatible, "multiple devices"):
                verify_reappeared_mcu(self.checkpoint, flash_evidence=True,
                    identity_reader=SimpleNamespace(read=lambda p: physical_identity(p, port="usb-2")),
                    ambiguity_resolver=resolver)
        resolver.assert_not_called()


class PhysicalTransactionIdentityTests(unittest.TestCase):
    def test_identity_changed_after_restart_triggers_recovery_without_done(self):
        fixture = physical_tests.InstallationWorkflowTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        client = physical_tests.Client({}, versions=[{"mcu": "kace-good"}, {"mcu": "other-build"}])
        events = []
        result = fixture.make(client=client, events=events).run()
        self.assertFalse(result.ok)
        self.assertTrue(result.rollback_succeeded)
        self.assertTrue(client.rollback)
        self.assertNotIn("DONE", [e["state"] for e in events])

    def test_physical_transaction_preserves_edit_on_fingerprint_failure(self):
        fixture = physical_tests.InstallationWorkflowTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        client = physical_tests.Client({})
        calls = []

        def versions():
            calls.append(True)
            if len(calls) == 1:
                return {"mcu": "kace-good"}
            client.remote["printer.cfg"] = b"external edit"
            return {}

        client.get_mcu_versions = versions
        client.restore_snapshot = lambda snapshot, **kw: restore_snapshot(
            snapshot, "pi", 7125, issue_restart=False, **kw,
        )
        with patch("core.config_transaction.MoonrakerConfigTransport.read_files",
                   side_effect=lambda names: {n: client.remote.get(n) for n in names}), \
             patch("core.snapshot.upload_printer_cfg") as upload, \
             patch("core.snapshot.delete_config_file") as delete:
            result = fixture.make(client=client).run()
        self.assertFalse(result.ok)
        self.assertFalse(result.rollback_succeeded)
        self.assertIn("manual recovery", result.detail)
        self.assertEqual(client.remote["printer.cfg"], b"external edit")
        upload.assert_not_called()
        delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
