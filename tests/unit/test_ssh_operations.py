"""SFTP transport contract tests for managed configuration deployment."""

import io
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from core.config_transaction import SftpConfigTransport
from core.deployer import deploy_config
from core.workflow_outcome import success


class Attr:
    pass


class MemorySftp:
    def __init__(self):
        self.files = {}
        self.directories = {"/", "/home", "/home/pi", "/home/pi/config"}
        self.calls = []
        self.read_error = None

    def stat(self, path):
        self.calls.append(("stat", path))
        if self.read_error and path.endswith(self.read_error):
            raise PermissionError(13, "denied", path)
        if path in self.files or path in self.directories:
            return Attr()
        raise FileNotFoundError(2, "missing", path)

    def open(self, path, mode):
        self.calls.append(("open", path, mode))
        return io.BytesIO(self.files[path])

    def mkdir(self, path, mode=0o777):
        self.calls.append(("mkdir", path, mode))
        self.directories.add(path)

    def put(self, local, remote):
        self.calls.append(("put", remote))
        with open(local, "rb") as source:
            self.files[remote] = source.read()

    def posix_rename(self, source, destination):
        self.calls.append(("posix_rename", source, destination))
        self.files[destination] = self.files.pop(source)

    def remove(self, path):
        self.calls.append(("remove", path))
        if path not in self.files:
            raise FileNotFoundError(2, "missing", path)
        del self.files[path]


class SftpTransportTests(unittest.TestCase):
    def setUp(self):
        self.sftp = MemorySftp()
        self.transport = SftpConfigTransport(
            self.sftp, "/home/pi/config", "pi.local", 7125
        )

    def test_read_files_reserves_none_for_confirmed_absence(self):
        self.sftp.files["/home/pi/config/printer.cfg"] = b"root"
        result = self.transport.read_files(("printer.cfg", "missing.cfg"))
        self.assertEqual(result, {"printer.cfg": b"root", "missing.cfg": None})

    def test_read_permission_failure_is_not_misreported_as_absence(self):
        self.sftp.read_error = "printer.cfg"
        with self.assertRaises(PermissionError):
            self.transport.read_files(("printer.cfg",))

    def test_upload_replaces_atomically_without_fixed_backup(self):
        self.sftp.files["/home/pi/config/printer.cfg"] = b"old"
        self.transport.upload_bytes("printer.cfg", b"new")
        self.assertEqual(self.sftp.files["/home/pi/config/printer.cfg"], b"new")
        renames = [call for call in self.sftp.calls if call[0] == "posix_rename"]
        self.assertEqual(len(renames), 1)
        self.assertIn(".kace-part-", renames[0][1])
        self.assertFalse(any(".bak" in str(call) for call in self.sftp.calls))

    def test_nested_managed_directory_is_created_before_upload(self):
        self.transport.upload_bytes("kace/generated-hardware.cfg", b"hardware")
        self.assertIn("/home/pi/config/kace", self.sftp.directories)
        self.assertEqual(
            self.sftp.files["/home/pi/config/kace/generated-hardware.cfg"],
            b"hardware",
        )

    def test_missing_atomic_rename_support_fails_closed_and_cleans_temp(self):
        self.sftp.posix_rename = None
        with self.assertRaisesRegex(RuntimeError, "atomic POSIX rename"):
            self.transport.upload_bytes("printer.cfg", b"new")
        self.assertFalse(any(".kace-part-" in name for name in self.sftp.files))

    def test_delete_absent_is_idempotent(self):
        self.transport.delete_file("not-there.cfg")


class DeployConfigPathTests(unittest.TestCase):
    def _run(self, destination):
        sftp = MagicMock()
        ssh = MagicMock()
        ssh.open_sftp.return_value = sftp
        paramiko = MagicMock()
        paramiko.SSHClient.return_value = ssh
        paramiko.AuthenticationException = type("AuthenticationException", (Exception,), {})
        with (
            patch("core.deployer._require_paramiko", return_value=paramiko),
            patch(
                "core.deployer._generated_config_bytes",
                return_value=("generated.cfg", b"[mcu]\n[printer]\n", None),
            ),
            patch("core.menu.numbered_select", return_value="none"),
            patch("core.deployer._run_config_transaction", return_value=success("done")) as run,
        ):
            result = deploy_config({
                "host": "pi.local",
                "user": "pi",
                "password": "secret",
                "dest_path": destination,
            })
        self.assertTrue(result.ok)
        return run.call_args.args[0].config_dir

    def test_file_directory_and_trailing_slash_resolve_to_same_config_root(self):
        values = [
            self._run("~/printer_data/config/printer.cfg"),
            self._run("~/printer_data/config"),
            self._run("~/printer_data/config/"),
        ]
        self.assertEqual(values, ["/home/pi/printer_data/config"] * 3)


if __name__ == "__main__":
    unittest.main()
