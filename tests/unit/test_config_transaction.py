import os
import tempfile
import unittest
from unittest.mock import patch

from core.config_transaction import (
    ConfigConflictError,
    ConfigDeploymentTransaction,
    ConfigTransactionState,
    LocalConfigTransport,
    MoonrakerConfigTransport,
    configuration_transport,
)


GENERATED = b"""[mcu]
serial: /dev/serial/by-id/test
[printer]
kinematics: cartesian
[stepper_x]
step_pin: PA1
"""


class FakeTransport:
    def validate_activation_target(self):
        pass

    def supports_conditional_write(self, previous):
        return True

    def upload_if_unchanged(self, name, content, previous):
        if self.files.get(name) != previous:
            raise RuntimeError("concurrent modification")
        self.upload_bytes(name, content)

    def __init__(self, files=None):
        self.destination_key = ("simulated-printer", id(self))
        self.files = dict(files or {})
        self.calls = []
        self.fail_upload = None
        self.fail_delete = None
        self.corrupt_download = None
        self.fail_restart = False
        self.fail_moonraker_restart = False

    def read_files(self, names):
        self.calls.append(("read", tuple(names)))
        result = {name: self.files.get(name) for name in names}
        if self.corrupt_download and self.corrupt_download in names:
            result[self.corrupt_download] = b"corrupt"
        return result

    def upload_bytes(self, name, content):
        self.calls.append(("upload", name))
        if name == self.fail_upload:
            raise OSError("synthetic upload failure")
        self.files[name] = content

    def delete_file(self, name):
        self.calls.append(("delete", name))
        if name == self.fail_delete:
            raise OSError("synthetic rollback delete failure")
        self.files.pop(name, None)

    def restart(self, mode):
        self.calls.append(("restart", mode))
        if self.fail_restart:
            raise RuntimeError("synthetic restart failure")

    def restart_moonraker(self):
        self.calls.append(("restart_moonraker",))
        if self.fail_moonraker_restart:
            raise RuntimeError("synthetic Moonraker restart failure")

    def moonraker_online(self):
        return True

    def klipper_state(self):
        return "ready"


class BrokenReadTransport(FakeTransport):
    def read_files(self, names):
        raise ConnectionError("backup unavailable")


class TestConfigDeploymentTransaction(unittest.TestCase):
    def run_transaction(self, transport, root, **kwargs):
        return ConfigDeploymentTransaction(
            transport,
            GENERATED,
            kwargs.pop("macros", b"# generated macros\n"),
            activation=kwargs.pop("activation", "firmware"),
            confirm=kwargs.pop("confirm", lambda _diff: True),
            output=kwargs.pop("output", lambda _diff: None),
            snapshot_root=root,
            poll_interval=0,
            **kwargs,
        ).run()

    def test_backup_failure_prevents_every_write(self):
        with tempfile.TemporaryDirectory() as root:
            transport = BrokenReadTransport()
            result = self.run_transaction(transport, root)
        self.assertEqual(result.state, ConfigTransactionState.PRECONDITION_FAILED)
        self.assertFalse(any(call[0] == "upload" for call in transport.calls))

    def test_cancel_after_diff_prevents_snapshot_and_write(self):
        with tempfile.TemporaryDirectory() as root:
            transport = FakeTransport({"printer.cfg": b"# user\n"})
            result = self.run_transaction(transport, root, confirm=lambda _diff: False)
            self.assertEqual(os.listdir(root), [])
        self.assertEqual(result.state, ConfigTransactionState.CANCELLED)
        self.assertFalse(any(call[0] == "upload" for call in transport.calls))

    def test_skip_restart_is_verified_but_non_final(self):
        with tempfile.TemporaryDirectory() as root:
            transport = FakeTransport({"printer.cfg": b"# user\n"})
            result = self.run_transaction(transport, root, activation="none")
        self.assertEqual(result.state, ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION)
        self.assertFalse(any(call[0] == "restart" for call in transport.calls))
        self.assertTrue(result.snapshot.storage_path)

    def test_interrupt_before_writing_cancels_without_rollback(self):
        for phase in ("read", "confirm", "upload"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as root:
                original = {"printer.cfg": b"# original\n"}
                transport = FakeTransport(original)

                def interrupt(*_args):
                    raise KeyboardInterrupt

                kwargs = {}
                if phase == "confirm":
                    kwargs["confirm"] = interrupt
                else:
                    setattr(transport, "read_files" if phase == "read" else "upload_bytes", interrupt)
                with patch.object(ConfigDeploymentTransaction, "_rollback") as rollback:
                    try:
                        result = self.run_transaction(transport, root, **kwargs)
                    except KeyboardInterrupt:
                        self.fail("interruption escaped without a cancellation result")
                self.assertEqual(result.state, ConfigTransactionState.CANCELLED)
                self.assertIsNone(result.rollback_succeeded)
                rollback.assert_not_called()
                self.assertEqual(transport.files, original)
                self.assertFalse(any(c[0] in {"upload", "delete", "restart"} for c in transport.calls))

    def test_interrupt_in_upload_retains_files_and_durable_recovery(self):
        for interrupted_upload in (1, 2):
            with self.subTest(upload=interrupted_upload), tempfile.TemporaryDirectory() as root:
                original = {"printer.cfg": b"# original\n", "kace/generated-hardware.cfg": b"# old hardware\n"}
                transport = FakeTransport(original)
                upload = transport.upload_bytes
                count = 0

                def write_then_interrupt(name, content):
                    nonlocal count
                    upload(name, content)
                    count += 1
                    if count == interrupted_upload:
                        raise KeyboardInterrupt

                transport.upload_bytes = write_then_interrupt
                try:
                    result = self.run_transaction(transport, root)
                except KeyboardInterrupt:
                    self.fail(f"interrupted upload left remote state: {transport.files!r}")
                self.assertEqual(result.state, ConfigTransactionState.ROLLBACK_FAILED)
                self.assertFalse(result.rollback_succeeded)
                self.assertEqual(result.snapshot.config_files, original)
                self.assertIn("manual recovery", result.detail)
                self.assertFalse(any(c[0] == "delete" for c in transport.calls))
                self.assertEqual(count, interrupted_upload)
                self.assertTrue(os.path.isfile(os.path.join(result.snapshot.storage_path, "snapshot.json")))

    def test_interrupt_during_restart_or_verification_requires_manual_recovery(self):
        for phase in ("checksum", "restart", "ready"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as root:
                original = {"printer.cfg": b"# original\n"}
                transport = FakeTransport(original)
                transaction = ConfigDeploymentTransaction(
                    transport, GENERATED, None, activation="firmware",
                    snapshot_root=root, poll_interval=0,
                )
                target, method = (
                    (transaction, "_verify_plan") if phase == "checksum"
                    else (transport, "restart" if phase == "restart" else "klipper_state")
                )
                operation = getattr(target, method)
                interrupted = False

                def interrupt_once(*args):
                    nonlocal interrupted
                    if not interrupted:
                        interrupted = True
                        raise KeyboardInterrupt
                    return operation(*args)

                with patch.object(target, method, side_effect=interrupt_once):
                    try:
                        result = transaction.run()
                    except KeyboardInterrupt:
                        self.fail(f"interruption during {phase} bypassed rollback")
                self.assertEqual(result.state, ConfigTransactionState.ROLLBACK_FAILED)
                self.assertFalse(result.rollback_succeeded)
                self.assertEqual(result.snapshot.config_files, original)
                self.assertIn("manual recovery", result.detail)
                self.assertFalse(any(c[0] == "delete" for c in transport.calls))

    def test_failed_or_interrupted_cancellation_rollback_is_reported(self):
        for failure in (OSError("restore unavailable"), KeyboardInterrupt()):
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as root:
                transport = FakeTransport({"printer.cfg": b"# original\n"})
                upload = transport.upload_bytes

                def write_then_interrupt(name, content):
                    upload(name, content)
                    raise KeyboardInterrupt

                transport.upload_bytes = write_then_interrupt
                with patch.object(transport, "delete_file", side_effect=failure):
                    try:
                        result = self.run_transaction(transport, root)
                    except KeyboardInterrupt:
                        self.fail("cancellation/rollback interruption was not reported")
                self.assertEqual(result.state, ConfigTransactionState.ROLLBACK_FAILED)
                self.assertIs(result.rollback_succeeded, False)
                self.assertIn("cancelled", result.detail)
                self.assertIn("rollback", result.detail)
                self.assertIn("kace/generated-hardware.cfg", transport.files)

    def test_success_uploads_includes_before_root_and_verifies_ready(self):
        with tempfile.TemporaryDirectory() as root:
            transport = FakeTransport({"printer.cfg": b"# user\n"})
            result = self.run_transaction(transport, root)
        uploads = [call[1] for call in transport.calls if call[0] == "upload"]
        self.assertEqual(result.state, ConfigTransactionState.COMMITTED)
        self.assertEqual(uploads[-1], "printer.cfg")
        self.assertIn(("restart", "firmware"), transport.calls)

    def test_restart_state_is_emitted_only_at_actual_activation_boundary(self):
        events = []
        with tempfile.TemporaryDirectory() as root:
            transport = FakeTransport({"printer.cfg": b"# user\n"})
            result = self.run_transaction(
                transport,
                root,
                state_sink=lambda state, detail: events.append((state, detail)),
            )
        states = [state for state, _detail in events]
        self.assertEqual(result.state, ConfigTransactionState.COMMITTED)
        self.assertLess(states.index("APPLYING_CONFIG"), states.index("FIRMWARE_RESTART"))
        self.assertLess(states.index("FIRMWARE_RESTART"), states.index("VERIFYING_CONFIG"))
        self.assertEqual(states[-1], "DONE")

    def test_review_confirmation_precedes_restart_selection_and_upload(self):
        with tempfile.TemporaryDirectory() as root:
            transport = FakeTransport({"printer.cfg": b"# user\n"})

            def review(_review):
                transport.calls.append(("review_and_confirm",))
                return True

            def select_activation():
                transport.calls.append(("select_activation",))
                return "firmware"

            result = self.run_transaction(
                transport,
                root,
                review=review,
                activation_selector=select_activation,
            )
        self.assertEqual(result.state, ConfigTransactionState.COMMITTED)
        self.assertLess(
            transport.calls.index(("review_and_confirm",)),
            transport.calls.index(("select_activation",)),
        )
        first_upload = next(
            index for index, call in enumerate(transport.calls)
            if call[0] == "upload"
        )
        self.assertLess(transport.calls.index(("select_activation",)), first_upload)

    def test_moonraker_change_restarts_moonraker_before_klipper(self):
        with tempfile.TemporaryDirectory() as root:
            transport = FakeTransport({
                "printer.cfg": b"# user\n",
                "moonraker.conf": b"[server]\nport: 7125\n",
            })
            result = self.run_transaction(transport, root, activation="service")
        self.assertEqual(result.state, ConfigTransactionState.COMMITTED)
        self.assertLess(
            transport.calls.index(("restart_moonraker",)),
            transport.calls.index(("restart", "service")),
        )

    def test_second_identical_run_reactivates_without_writing(self):
        with tempfile.TemporaryDirectory() as root:
            transport = FakeTransport({"printer.cfg": b"# user\n"})
            first = self.run_transaction(transport, root)
            first_call_count = len(transport.calls)
            second = self.run_transaction(transport, root)
        self.assertEqual(first.state, ConfigTransactionState.COMMITTED)
        self.assertEqual(second.state, ConfigTransactionState.COMMITTED)
        self.assertIsNone(second.snapshot)
        self.assertEqual(
            [call for call in transport.calls[first_call_count:] if call[0] in {"upload", "restart"}],
            [("restart", "firmware")],
        )

    def test_repeated_deployment_preserves_save_config_without_extra_writes(self):
        saved = (
            b"#*# <---------------------- SAVE_CONFIG ---------------------->\n"
            b"#*# DO NOT EDIT THIS BLOCK OR BELOW. The contents are auto-generated.\n"
            b"#*#\n#*# [input_shaper]\n#*# shaper_freq_x = 42.375\n"
        )
        with tempfile.TemporaryDirectory() as root:
            transport = FakeTransport({"printer.cfg": b"[mcu]\nserial: old\n" + saved})
            first = self.run_transaction(transport, root)
            deployed = dict(transport.files)
            first_call_count = len(transport.calls)
            second = self.run_transaction(transport, root)
        self.assertEqual(first.state, ConfigTransactionState.COMMITTED)
        self.assertEqual(second.state, ConfigTransactionState.COMMITTED)
        deployed_root = deployed["printer.cfg"]
        self.assertEqual(deployed_root[deployed_root.index(b"#*# <"):], saved)
        self.assertEqual(deployed_root.count(b"SAVE_CONFIG"), 1)
        self.assertEqual(transport.files, deployed)
        self.assertFalse(any(
            call[0] == "upload" for call in transport.calls[first_call_count:]
        ))

    def test_resumed_identical_config_requires_klipper_ready_evidence(self):
        events = []
        with tempfile.TemporaryDirectory() as root:
            transport = FakeTransport({"printer.cfg": b"# user\n"})
            self.run_transaction(transport, root)
            before = len(transport.calls)
            resumed = self.run_transaction(
                transport,
                root,
                verify_existing_ready=True,
                state_sink=lambda state, detail: events.append((state, detail)),
            )
        self.assertEqual(resumed.state, ConfigTransactionState.COMMITTED)
        self.assertIn("Klipper Ready", resumed.detail)
        self.assertEqual(events[-1][0], "DONE")
        self.assertFalse(any(
            call[0] == "restart" for call in transport.calls[before:]
        ))

    def test_macros_upload_failure_preserves_files_for_manual_recovery(self):
        old_root = b"# original root\n"
        with tempfile.TemporaryDirectory() as root:
            transport = FakeTransport({"printer.cfg": old_root})
            transport.fail_upload = "kace/generated-macros.cfg"
            result = self.run_transaction(transport, root)
        self.assertEqual(result.state, ConfigTransactionState.ROLLBACK_FAILED)
        self.assertFalse(result.rollback_succeeded)
        self.assertIn("manual recovery", result.detail)
        self.assertEqual(transport.files["printer.cfg"], old_root)
        self.assertIn("kace/generated-hardware.cfg", transport.files)
        self.assertEqual(result.snapshot.config_files["printer.cfg"], old_root)
        self.assertNotIn("kace/generated-macros.cfg", transport.files)
        self.assertNotIn(("delete", "kace/generated-macros.cfg"), transport.calls)

    def test_first_upload_failure_does_not_delete_a_file_that_never_existed(self):
        with tempfile.TemporaryDirectory() as root:
            transport = FakeTransport({"printer.cfg": b"# original root\n"})
            transport.fail_upload = "kace/generated-hardware.cfg"
            result = self.run_transaction(transport, root)
        self.assertEqual(result.state, ConfigTransactionState.UPLOAD_FAILED)
        self.assertIsNone(result.rollback_succeeded)
        self.assertFalse(any(call[0] == "delete" for call in transport.calls))
        self.assertIn("upload error:", result.detail)
        self.assertIn("rollback not required", result.detail)
        self.assertNotIn("rollback error", result.detail)
        self.assertNotIn("delete", result.detail)

    def test_upload_and_rollback_errors_are_reported_separately(self):
        with tempfile.TemporaryDirectory() as root:
            transport = FakeTransport({"printer.cfg": b"# original root\n"})
            transport.fail_upload = "kace/generated-macros.cfg"
            transport.fail_delete = "kace/generated-hardware.cfg"
            result = self.run_transaction(transport, root)
        self.assertEqual(result.state, ConfigTransactionState.ROLLBACK_FAILED)
        self.assertFalse(result.rollback_succeeded)
        self.assertIn("upload error: synthetic upload failure", result.detail)
        self.assertIn("rollback error:", result.detail)
        self.assertIn("no atomic conditional restore", result.detail)
        self.assertFalse(any(c[0] == "delete" for c in transport.calls))

    def test_restart_failure_rolls_back_and_reaches_ready(self):
        with tempfile.TemporaryDirectory() as root:
            transport = FakeTransport({"printer.cfg": b"# original\n"})
            transport.fail_restart = True
            result = self.run_transaction(transport, root)
        # The same synthetic restart failure also prevents rollback activation,
        # so the transaction truthfully reports an incomplete rollback.
        self.assertEqual(result.state, ConfigTransactionState.ROLLBACK_FAILED)
        self.assertFalse(result.rollback_succeeded)

    def test_local_transport_preserves_existing_files_without_conditional_replace(self):
        with tempfile.TemporaryDirectory() as destination, tempfile.TemporaryDirectory() as snapshots:
            with open(os.path.join(destination, "printer.cfg"), "wb") as output:
                output.write(b"[gcode_macro USER]\ngcode: M117 keep\n")
            result = ConfigDeploymentTransaction(
                LocalConfigTransport(destination),
                GENERATED,
                b"# macros\n",
                activation="none",
                confirm=lambda _diff: True,
                snapshot_root=snapshots,
            ).run()
            with open(os.path.join(destination, "printer.cfg"), "rb") as source:
                root = source.read()
            self.assertFalse(os.path.exists(os.path.join(destination, "kace")))
            self.assertTrue(os.listdir(snapshots))
        self.assertEqual(result.state, ConfigTransactionState.PRECONDITION_FAILED)
        self.assertEqual(root, b"[gcode_macro USER]\ngcode: M117 keep\n")
        self.assertIn("manually apply", result.detail)

    def test_local_transport_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as destination:
            transport = LocalConfigTransport(destination)
            with self.assertRaisesRegex(ValueError, "escapes"):
                transport.upload_bytes("../outside.cfg", b"bad")


class ConfigurationTransportSelectionTests(unittest.TestCase):
    def test_remote_fixture_never_discovers_a_local_destination(self):
        for platform in ("nt", "posix"):
            with self.subTest(platform=platform), \
                    patch("core.config_transaction.os.name", platform), \
                    patch("core.moonraker._get") as get:
                transport = configuration_transport("fixture-printer.invalid", 7125)
                self.assertIs(type(transport), MoonrakerConfigTransport)
                self.assertEqual(transport.host, "fixture-printer.invalid")
                get.assert_not_called()

    def test_posix_loopback_requires_active_config_before_selecting_destination(self):
        for host in ("localhost", "127.0.0.1", "[::1]"):
            with self.subTest(host=host), \
                    patch("core.config_transaction.os.name", "posix"), \
                    patch("core.moonraker._get", return_value=(False, "offline", {})) as get:
                with self.assertRaisesRegex(ConfigConflictError, "active Klipper config_file"):
                    configuration_transport(host, 7125, "fixture-api-key")
                get.assert_called_once_with(
                    f"http://{host}:7125/printer/info", api_key="fixture-api-key"
                )


if __name__ == "__main__":
    unittest.main()
