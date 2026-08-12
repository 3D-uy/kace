"""Regression coverage for durable, serialized KACE SSH trust storage."""

from contextlib import contextmanager
import os
from pathlib import Path
import stat
import threading
import time
import unittest
from unittest.mock import patch


class TestKnownHostsSafety(unittest.TestCase):
    def setUp(self):
        from tempfile import TemporaryDirectory

        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.expanduser = patch(
            "core.known_hosts.os.path.expanduser", return_value=str(self.home)
        )
        self.expanduser.start()
        self.addCleanup(self.expanduser.stop)

    def test_storage_and_lock_are_private(self):
        from core import known_hosts

        path = Path(known_hosts.get_known_hosts_path())
        lock_path = path.with_name("known_hosts.lock")
        self.assertTrue(path.is_file())
        self.assertTrue(lock_path.is_file())
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode) & 0o077, 0)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode) & 0o077, 0)
            self.assertEqual(stat.S_IMODE(lock_path.stat().st_mode) & 0o077, 0)

    def test_lock_serializes_threads(self):
        from core import known_hosts

        path = known_hosts.get_known_hosts_path()
        active = 0
        maximum = 0
        state_lock = threading.Lock()

        def worker():
            nonlocal active, maximum
            with known_hosts.known_hosts_lock(path):
                with state_lock:
                    active += 1
                    maximum = max(maximum, active)
                time.sleep(0.02)
                with state_lock:
                    active -= 1

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(2)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(maximum, 1)

    def test_atomic_publish_failure_preserves_previous_file(self):
        from core import known_hosts

        path = Path(known_hosts.get_known_hosts_path())
        path.write_text("printer.local ssh-ed25519 AAAATEST\n", encoding="utf-8")
        with patch("core.known_hosts.os.replace", side_effect=OSError("publish failed")):
            with self.assertRaisesRegex(OSError, "publish failed"):
                known_hosts.atomic_write_known_hosts(str(path), "replacement\n")
        self.assertEqual(
            path.read_text(encoding="utf-8"),
            "printer.local ssh-ed25519 AAAATEST\n",
        )
        self.assertEqual(list(path.parent.glob(".known_hosts.*.part")), [])

    def test_trust_transaction_holds_lock_through_connect_and_publish(self):
        from core import deployer

        path = self.home / "known_hosts"
        path.write_text("", encoding="utf-8")
        depth = 0
        events = []

        @contextmanager
        def observed_lock(actual_path):
            nonlocal depth
            self.assertEqual(actual_path, str(path))
            depth += 1
            try:
                yield
            finally:
                depth -= 1

        class Client:
            def load_system_host_keys(self):
                events.append("system")

            def load_host_keys(self, actual_path):
                self.assert_locked(actual_path)
                events.append("load")

            def assert_locked(self, actual_path):
                self_outer.assertEqual(actual_path, str(path))
                self_outer.assertEqual(depth, 1)

            def set_missing_host_key_policy(self, _policy):
                events.append("policy")

            def connect(self, *_args, **_kwargs):
                self_outer.assertEqual(depth, 1)
                events.append("connect")

            def close(self):
                events.append("close")

        self_outer = self

        class Paramiko:
            class SSHException(Exception):
                pass

            @staticmethod
            def SSHClient():
                return Client()

        def observed_persist(_paramiko, _client, actual_path, *, lock_held=False):
            self.assertEqual(actual_path, str(path))
            self.assertTrue(lock_held)
            self.assertEqual(depth, 1)
            events.append("persist")

        with patch("core.deployer.get_known_hosts_path", return_value=str(path)), patch(
            "core.deployer.known_hosts_lock", observed_lock
        ), patch("core.deployer.persist_host_keys_atomically", observed_persist):
            client = deployer._connect_ssh_client(
                Paramiko, "printer.local", username="kace", password="secret", timeout=10
            )

        self.assertIsInstance(client, Client)
        self.assertEqual(events, ["system", "load", "policy", "connect", "persist"])

    def test_deployer_never_uses_paramiko_non_atomic_save(self):
        source = (Path(__file__).resolve().parents[2] / "core" / "deployer.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn(".save_host_keys(", source)

    def test_publish_failure_aborts_connection_and_closes_client(self):
        from core import deployer

        path = self.home / "known_hosts"
        path.write_text("", encoding="utf-8")
        client = unittest.mock.MagicMock()

        class Paramiko:
            class SSHException(Exception):
                pass

            @staticmethod
            def SSHClient():
                return client

        with patch("core.deployer.get_known_hosts_path", return_value=str(path)), patch(
            "core.deployer.persist_host_keys_atomically",
            side_effect=OSError("trust publish failed"),
        ):
            with self.assertRaisesRegex(OSError, "trust publish failed"):
                deployer._connect_ssh_client(
                    Paramiko,
                    "printer.local",
                    username="kace",
                    password="secret",
                    timeout=10,
                )
        client.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
