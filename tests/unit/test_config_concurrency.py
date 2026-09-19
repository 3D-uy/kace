"""Hardware-free regressions for reviewed configuration and destination locking."""

import os
import tempfile
import threading
import unittest
from unittest.mock import patch

from core.config_transaction import (
    ConfigDeploymentTransaction, ConfigTransactionState, LocalConfigTransport,
    MoonrakerConfigTransport, SftpConfigTransport, config_destination_lock, LocalMoonrakerConfigTransport,
)
from core.snapshot import create_snapshot
from tests.unit.test_config_transaction import FakeTransport, GENERATED


class TestConfigConcurrency(unittest.TestCase):
    def make(self, transport, snapshots, **kwargs):
        return ConfigDeploymentTransaction(
            transport, GENERATED, None, activation="firmware",
            output=lambda _line: None, snapshot_root=snapshots,
            timeout=1, poll_interval=0, **kwargs,
        )

    def assert_no_remote_mutation(self, transport):
        self.assertFalse(any(call[0] in {"upload", "delete", "restart", "restart_moonraker"}
                             for call in transport.calls))

    def start(self, action, name):
        result, errors = [], []

        def run():
            try:
                result.append(action())
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=run, name=name, daemon=True)
        thread.start()
        return thread, result, errors

    def finish(self, worker):
        thread, result, errors = worker
        thread.join(3)
        self.assertFalse(thread.is_alive(), "destination lock was not released")
        if errors:
            raise errors[0]
        return result[0]

    def test_edit_during_confirmation_is_not_overwritten_or_snapshotted_as_old(self):
        original = b"# user configuration\n"
        concurrent = b"# edited in Mainsail during confirmation\n"
        transport = FakeTransport({"printer.cfg": original})

        def approve(_diff):
            transport.files["printer.cfg"] = concurrent
            return True

        with tempfile.TemporaryDirectory() as snapshots:
            transaction = ConfigDeploymentTransaction(
                transport, GENERATED, None, activation="firmware",
                confirm=approve, output=lambda _line: None,
                snapshot_root=snapshots, poll_interval=0,
            )
            result = transaction.run()

        self.assertEqual(
            transport.files["printer.cfg"], concurrent,
            f"state={result.state.name}; snapshot={result.snapshot.config_files if result.snapshot else None}",
        )
        self.assertEqual(result.state, ConfigTransactionState.PRECONDITION_FAILED)
        self.assertIn("concurrent", result.detail.lower())
        self.assertIsNone(result.snapshot)
        self.assertFalse(any(call[0] in {"upload", "delete", "restart", "restart_moonraker"}
                             for call in transport.calls))

    def test_review_detects_edits_deletions_and_creations_in_every_candidate(self):
        for name in ConfigDeploymentTransaction.CANDIDATES:
            for change in ("edit", "delete", "create-empty"):
                with self.subTest(name=name, change=change), tempfile.TemporaryDirectory() as root:
                    files = {n: b"# initial\n" for n in ConfigDeploymentTransaction.CANDIDATES}
                    if change == "create-empty":
                        del files[name]
                    transport = FakeTransport(files)

                    def review(_review):
                        if change == "delete":
                            del transport.files[name]
                        else:
                            transport.files[name] = b"# edited!\n" if change == "edit" else b""
                        return True

                    with patch("core.config_transaction.create_snapshot", wraps=create_snapshot) as snapshot:
                        result = self.make(transport, root, review=review).run()
                    self.assertEqual(result.state, ConfigTransactionState.PRECONDITION_FAILED)
                    self.assertIn(name, result.detail)
                    self.assertIn("concurrent", result.detail)
                    snapshot.assert_called_once()
                    self.assertTrue(snapshot.call_args.kwargs["deployment_id"].endswith("-proposed"))
                    self.assertEqual(len(os.listdir(root)), 1)
                    self.assert_no_remote_mutation(transport)

    def test_edit_first_observed_by_reread_is_preserved(self):
        transport = FakeTransport({"printer.cfg": b"# initial\n"})
        read = transport.read_files
        calls = 0

        def read_with_edit(names):
            nonlocal calls
            calls += 1
            if calls == 2:
                transport.files["printer.cfg"] = b"# changed during reread\n"
            return read(names)

        transport.read_files = read_with_edit
        with tempfile.TemporaryDirectory() as root:
            result = self.make(transport, root).run()
        self.assertEqual(result.state, ConfigTransactionState.PRECONDITION_FAILED)
        self.assertEqual(transport.files["printer.cfg"], b"# changed during reread\n")
        self.assertIsNone(result.snapshot)
        self.assert_no_remote_mutation(transport)

    def test_activation_prompt_cannot_reopen_the_confirmation_window(self):
        transport = FakeTransport({"printer.cfg": b"# original\n"})

        def select_activation():
            transport.files["printer.cfg"] = b"# edited while choosing restart\n"
            return "service"

        with tempfile.TemporaryDirectory() as root:
            result = self.make(transport, root, activation_selector=select_activation).run()
        self.assertEqual(result.state, ConfigTransactionState.PRECONDITION_FAILED)
        self.assert_no_remote_mutation(transport)

    def test_same_size_edit_with_unchanged_mtime_is_detected(self):
        with tempfile.TemporaryDirectory() as destination, tempfile.TemporaryDirectory() as snapshots:
            path = os.path.join(destination, "printer.cfg")
            with open(path, "wb") as file:
                file.write(b"# before\n")
            metadata = os.stat(path)

            def approve(_diff):
                with open(path, "wb") as file:
                    file.write(b"# edited\n")
                os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
                return True

            transport = LocalMoonrakerConfigTransport(destination)
            transport.validate_activation_target = lambda: None
            result = self.make(transport, snapshots, confirm=approve).run()
            self.assertEqual(result.state, ConfigTransactionState.PRECONDITION_FAILED)
            self.assertEqual(os.stat(path).st_size, metadata.st_size)
            self.assertEqual(os.stat(path).st_mtime_ns, metadata.st_mtime_ns)
            with open(path, "rb") as file:
                self.assertEqual(file.read(), b"# edited\n")
            self.assertEqual(set(os.listdir(destination)), {"printer.cfg", ".kace-deploy.lock"})
            self.assertTrue(os.listdir(snapshots)[0].endswith("-proposed"))

    def test_read_failure_missing_entry_or_non_bytes_cannot_be_treated_as_absence(self):
        for failure in ("exception", "missing-entry", "non-bytes"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as root:
                transport = FakeTransport({"printer.cfg": b"# original\n"})
                read = transport.read_files

                def reread(names):
                    if failure == "exception":
                        raise ConnectionError("read unavailable")
                    result = read(names)
                    if failure == "missing-entry":
                        del result["printer.cfg"]
                    else:
                        result["printer.cfg"] = "not bytes"
                    return result

                def approve(_diff):
                    transport.read_files = reread
                    return True

                result = self.make(transport, root, confirm=approve).run()
                self.assertEqual(result.state, ConfigTransactionState.PRECONDITION_FAILED)
                self.assertIn("revalidation failed", result.detail)
                self.assertIsNone(result.snapshot)
                self.assert_no_remote_mutation(transport)

    def test_review_baseline_is_not_aliased_to_transport_mapping(self):
        transport = FakeTransport({n: None for n in ConfigDeploymentTransaction.CANDIDATES})
        transport.files["printer.cfg"] = b"# initial\n"
        transport.read_files = lambda _names: transport.files

        def approve(_diff):
            transport.files["printer.cfg"] = b"# changed\n"
            return True

        with tempfile.TemporaryDirectory() as root:
            result = self.make(transport, root, confirm=approve).run()
        self.assertEqual(result.state, ConfigTransactionState.PRECONDITION_FAILED)
        self.assert_no_remote_mutation(transport)

    def test_snapshot_uses_freshly_revalidated_bytes_and_is_rechecked_before_write(self):
        transport = FakeTransport({"printer.cfg": b"# initial\n"})
        read = transport.read_files
        reads = []

        def copy_read(names):
            values = {n: bytes(bytearray(v)) if v is not None else None for n, v in read(names).items()}
            reads.append(values)
            return values

        def snapshot(originals, **kwargs):
            self.assertEqual(len(reads), 2)
            self.assertIs(originals["printer.cfg"], reads[1]["printer.cfg"])
            self.assertIsNot(originals["printer.cfg"], reads[0]["printer.cfg"])
            return create_snapshot(originals, **kwargs)

        transport.read_files = copy_read
        with tempfile.TemporaryDirectory() as root, patch("core.config_transaction.create_snapshot", side_effect=snapshot):
            result = self.make(transport, root).run()
        self.assertEqual(result.state, ConfigTransactionState.COMMITTED)
        first_upload = next(i for i, call in enumerate(transport.calls) if call[0] == "upload")
        self.assertEqual(sum(call[0] == "read" for call in transport.calls[:first_upload]), 4)
        self.assertEqual(transport.calls[first_upload - 1], ("read", ("kace/generated-hardware.cfg",)))
        self.assertEqual(result.snapshot.config_files["printer.cfg"], b"# initial\n")

    def test_edit_while_snapshot_is_persisted_aborts_before_first_write(self):
        transport = FakeTransport({"printer.cfg": b"# initial\n"})

        def snapshot(originals, **kwargs):
            result = create_snapshot(originals, **kwargs)
            transport.files["printer.cfg"] = b"# newer than snapshot\n"
            return result

        with tempfile.TemporaryDirectory() as root, patch("core.config_transaction.create_snapshot", side_effect=snapshot):
            result = self.make(transport, root).run()
        self.assertEqual(result.state, ConfigTransactionState.PRECONDITION_FAILED)
        self.assertIn("no configuration files were written", result.detail)
        self.assertEqual(transport.files["printer.cfg"], b"# newer than snapshot\n")
        self.assert_no_remote_mutation(transport)

    def test_same_destination_instances_are_serialized_through_snapshot_and_restart(self):
        first = FakeTransport({"printer.cfg": b"# initial\n"})
        second = FakeTransport()
        second.files = first.files
        second.destination_key = first.destination_key
        entered, release, attempted = threading.Event(), threading.Event(), threading.Event()
        order = []
        second_read = second.read_files

        def read_second(names):
            order.append("second read")
            return second_read(names)

        def snapshot(originals, **kwargs):
            entered.set()
            if not release.wait(3):
                raise AssertionError("test did not release snapshot")
            return create_snapshot(originals, **kwargs)

        def observed_lock(transport):
            lock = config_destination_lock(transport)

            class ObservedLock:
                def __enter__(self):
                    if transport is second:
                        attempted.set()
                    lock.acquire()

                def __exit__(self, *_args):
                    lock.release()

            return ObservedLock()

        second.read_files = read_second
        with tempfile.TemporaryDirectory() as root, \
                patch("core.config_transaction.create_snapshot", side_effect=snapshot), \
                patch("core.config_transaction.config_destination_lock", side_effect=observed_lock):
            a = self.start(lambda: self.make(first, root, state_sink=lambda state, _detail: order.append(state)).run(), "first")
            b = None
            try:
                self.assertTrue(entered.wait(2))
                b = self.start(lambda: self.make(second, root).run(), "second")
                self.assertTrue(attempted.wait(2))
                self.assertEqual(second.calls, [])
                self.assertTrue(config_destination_lock(first).locked())
            finally:
                release.set()
            result_a = self.finish(a)
            result_b = self.finish(b)
        self.assertEqual(result_a.state, ConfigTransactionState.COMMITTED)
        self.assertEqual(result_b.state, ConfigTransactionState.COMMITTED)
        self.assertLess(order.index("DONE"), order.index("second read"))
        self.assertFalse(any(c[0] in {"upload", "delete"} for c in second.calls))
        self.assertIn(("restart", "firmware"), second.calls)

    def test_different_destinations_can_finish_while_first_snapshot_is_blocked(self):
        first = FakeTransport({"printer.cfg": b"# first\n"})
        second = FakeTransport({"printer.cfg": b"# second\n"})
        entered, release = threading.Event(), threading.Event()

        def snapshot(originals, **kwargs):
            if threading.current_thread().name == "first":
                entered.set()
                if not release.wait(3):
                    raise AssertionError("test did not release snapshot")
            return create_snapshot(originals, **kwargs)

        with tempfile.TemporaryDirectory() as root, patch("core.config_transaction.create_snapshot", side_effect=snapshot):
            a = self.start(lambda: self.make(first, root).run(), "first")
            try:
                self.assertTrue(entered.wait(2))
                b = self.start(lambda: self.make(second, root).run(), "second")
                self.assertEqual(self.finish(b).state, ConfigTransactionState.COMMITTED)
                self.assertFalse(release.is_set())
            finally:
                release.set()
            self.assertEqual(self.finish(a).state, ConfigTransactionState.COMMITTED)

    def test_lock_is_released_after_success_cancel_failure_and_exception(self):
        for scenario in ("success", "cancel", "conflict", "snapshot", "upload", "restart", "exception"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as root:
                transport = FakeTransport({"printer.cfg": b"# initial\n"})
                lock = config_destination_lock(transport)
                transaction = self.make(transport, root, confirm=lambda _diff: scenario != "cancel")
                if scenario == "conflict":
                    def approve(_diff):
                        transport.files["printer.cfg"] = b"# concurrent edit\n"
                        return True
                    transaction.confirm = approve
                if scenario == "upload":
                    transport.fail_upload = "kace/generated-hardware.cfg"
                if scenario == "restart":
                    transport.fail_restart = True
                if scenario == "snapshot":
                    with patch("core.config_transaction.create_snapshot", side_effect=OSError("full disk")):
                        self.assertEqual(transaction.run().state, ConfigTransactionState.SNAPSHOT_FAILED)
                elif scenario == "exception":
                    with patch.object(transport, "read_files", side_effect=KeyboardInterrupt):
                        self.assertEqual(transaction.run().state, ConfigTransactionState.CANCELLED)
                else:
                    result = transaction.run()
                    self.assertEqual(result.ok, scenario == "success")
                self.assertTrue(lock.acquire(blocking=False), "destination lock leaked")
                lock.release()
                transport.fail_upload = None
                transport.fail_restart = False
                self.assertEqual(self.make(transport, root).run().state, ConfigTransactionState.COMMITTED)

    def test_unchanged_plan_is_revalidated_before_noop_success(self):
        transport = FakeTransport({"printer.cfg": b"# initial\n"})
        with tempfile.TemporaryDirectory() as root:
            self.assertTrue(self.make(transport, root).run().ok)
            transport.calls.clear()

            def review(_review):
                transport.files["printer.cfg"] += b"# concurrent\n"
                return True

            result = self.make(transport, root, review=review).run()
        self.assertEqual(result.state, ConfigTransactionState.PRECONDITION_FAILED)
        self.assert_no_remote_mutation(transport)

    def test_missing_destination_identity_fails_before_reading(self):
        transport = FakeTransport()
        del transport.destination_key
        with tempfile.TemporaryDirectory() as root:
            result = self.make(transport, root).run()
        self.assertEqual(result.state, ConfigTransactionState.PRECONDITION_FAILED)
        self.assertEqual(transport.calls, [])


class TestDestinationIdentity(unittest.TestCase):
    def test_moonraker_sftp_and_credentials_share_endpoint_lock(self):
        moonraker = MoonrakerConfigTransport("http://Printer.LOCAL.:7125/", 80, "first-key")
        sftp = SftpConfigTransport(object(), "/home/kace/printer_data/config", "printer.local", 7125, "second-key")
        self.assertEqual(moonraker.destination_key, sftp.destination_key)
        self.assertIs(config_destination_lock(moonraker), config_destination_lock(sftp))
        other = MoonrakerConfigTransport("printer.local", 7126)
        self.assertNotEqual(moonraker.destination_key, other.destination_key)

    def test_local_aliases_share_destination_but_other_directories_do_not(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as other:
            first = LocalConfigTransport(root)
            alias = LocalConfigTransport(os.path.join(root, "unused", ".."))
            self.assertIs(config_destination_lock(first), config_destination_lock(alias))
            self.assertNotEqual(first.destination_key, LocalConfigTransport(other).destination_key)


if __name__ == "__main__":
    unittest.main()
