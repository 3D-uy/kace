import os
import tempfile
import unittest

from core.config_transaction import (
    ConfigDeploymentTransaction,
    ConfigTransactionState,
    LocalConfigTransport,
)


GENERATED = b"""[mcu]
serial: /dev/serial/by-id/test
[printer]
kinematics: cartesian
[stepper_x]
step_pin: PA1
"""


class FakeTransport:
    def __init__(self, files=None):
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

    def test_success_uploads_includes_before_root_and_verifies_ready(self):
        with tempfile.TemporaryDirectory() as root:
            transport = FakeTransport({"printer.cfg": b"# user\n"})
            result = self.run_transaction(transport, root)
        uploads = [call[1] for call in transport.calls if call[0] == "upload"]
        self.assertEqual(result.state, ConfigTransactionState.COMMITTED)
        self.assertEqual(uploads[-1], "printer.cfg")
        self.assertIn(("restart", "firmware"), transport.calls)

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

    def test_second_identical_run_does_not_snapshot_write_or_restart(self):
        with tempfile.TemporaryDirectory() as root:
            transport = FakeTransport({"printer.cfg": b"# user\n"})
            first = self.run_transaction(transport, root)
            first_call_count = len(transport.calls)
            second = self.run_transaction(transport, root)
        self.assertEqual(first.state, ConfigTransactionState.COMMITTED)
        self.assertEqual(second.state, ConfigTransactionState.COMMITTED)
        self.assertEqual(second.detail, "configuration is already reconciled; no files were written")
        self.assertEqual(
            [call for call in transport.calls[first_call_count:] if call[0] in {"upload", "restart"}],
            [],
        )

    def test_macros_upload_failure_restores_old_bytes_and_deletes_new_files(self):
        old_root = b"# original root\n"
        with tempfile.TemporaryDirectory() as root:
            transport = FakeTransport({"printer.cfg": old_root})
            transport.fail_upload = "kace/generated-macros.cfg"
            result = self.run_transaction(transport, root)
        self.assertEqual(result.state, ConfigTransactionState.UPLOAD_FAILED)
        self.assertTrue(result.rollback_succeeded)
        self.assertEqual(transport.files["printer.cfg"], old_root)
        self.assertNotIn("kace/generated-hardware.cfg", transport.files)
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
        self.assertIn("delete kace/generated-hardware.cfg", result.detail)

    def test_restart_failure_rolls_back_and_reaches_ready(self):
        with tempfile.TemporaryDirectory() as root:
            transport = FakeTransport({"printer.cfg": b"# original\n"})
            transport.fail_restart = True
            result = self.run_transaction(transport, root)
        # The same synthetic restart failure also prevents rollback activation,
        # so the transaction truthfully reports an incomplete rollback.
        self.assertEqual(result.state, ConfigTransactionState.ROLLBACK_FAILED)
        self.assertFalse(result.rollback_succeeded)

    def test_local_transport_preserves_user_root_and_is_atomic(self):
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
            with open(os.path.join(destination, "kace", "generated-hardware.cfg"), "rb") as source:
                hardware = source.read()
        self.assertEqual(result.state, ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION)
        self.assertIn(b"[gcode_macro USER]", root)
        self.assertIn(b"[mcu]", hardware)

    def test_local_transport_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as destination:
            transport = LocalConfigTransport(destination)
            with self.assertRaisesRegex(ValueError, "escapes"):
                transport.upload_bytes("../outside.cfg", b"bad")


if __name__ == "__main__":
    unittest.main()
