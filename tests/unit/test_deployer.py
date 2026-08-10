"""Boundary tests for deployment entry points.

The byte-level transaction, rollback, ordering and checksum contracts live in
test_config_transaction.py. These tests verify that each interactive boundary
constructs and closes the correct transport without reimplementing that state
machine.
"""

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.config_transaction import ConfigTransactionState
from core.deployer import (
    _copy_artifacts,
    deploy_config,
    deploy_firmware_installation,
    deploy_moonraker,
)
from core.moonraker_deployer import DeployState
from core.workflow_outcome import WorkflowOutcome, success
from firmware.artifacts import BuildProvenance
from firmware.identity import FirmwareBuildInputs, ToolchainIdentity


class FakeParamiko:
    class AuthenticationException(Exception):
        pass

    class SSHException(Exception):
        pass

    def __init__(self, client):
        self.client = client

    def SSHClient(self):
        return self.client


class SshBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.generated = patch(
            "core.deployer._generated_config_bytes",
            return_value=("generated.cfg", b"[mcu]\n[printer]\n", None),
        )
        self.generated.start()
        self.sftp = MagicMock()
        self.ssh = MagicMock()
        self.ssh.open_sftp.return_value = self.sftp
        self.paramiko = FakeParamiko(self.ssh)
        self.user = {
            "host": "pi.local",
            "user": "kace",
            "password": "secret",
            "dest_path": "~/printer_data/config/printer.cfg",
            "moonraker_port": 8123,
        }

    def tearDown(self):
        self.generated.stop()

    @patch("core.deployer._run_config_transaction", return_value=success("done"))
    @patch("core.menu.numbered_select", return_value="service")
    @patch("core.deployer._require_paramiko")
    def test_ssh_builds_shared_transport_and_closes_resources(self, require, _select, run):
        require.return_value = self.paramiko
        result = deploy_config(self.user)

        self.assertTrue(result.ok)
        self.assertNotIn("password", self.user)
        self.ssh.connect.assert_called_once_with(
            "pi.local", username="kace", password="secret", timeout=10
        )
        transport, passed_user, activation, generated = run.call_args.args
        self.assertEqual(transport.config_dir, "/home/kace/printer_data/config")
        self.assertEqual(transport.port, 8123)
        self.assertIs(passed_user, self.user)
        self.assertEqual(activation, "service")
        self.assertEqual(generated[0], "generated.cfg")
        self.sftp.close.assert_called_once()
        self.ssh.close.assert_called_once()

    @patch("core.deployer._require_paramiko")
    def test_authentication_failure_is_terminal_and_resources_close(self, require):
        require.return_value = self.paramiko
        self.ssh.connect.side_effect = FakeParamiko.AuthenticationException("bad credentials")
        result = deploy_config(self.user)
        self.assertEqual(result.outcome, WorkflowOutcome.DEPLOYMENT_FAILED)
        self.assertIn("authentication", result.detail.lower())
        self.ssh.close.assert_called_once()

    @patch("core.deployer._require_paramiko", return_value=None)
    def test_missing_paramiko_is_precondition_failure(self, _require):
        result = deploy_config(self.user)
        self.assertEqual(result.outcome, WorkflowOutcome.PRECONDITION_FAILED)


class MoonrakerBoundaryTests(unittest.TestCase):
    @patch("core.menu.simple_input", return_value="")
    def test_empty_host_cancels_without_probe(self, _input):
        with patch("core.moonraker.check_moonraker") as check:
            result = deploy_moonraker({})
        self.assertEqual(result.outcome, WorkflowOutcome.CANCELLED)
        check.assert_not_called()

    @patch("core.menu.simple_input", side_effect=["pi.local", "not-a-port"])
    def test_invalid_port_fails_precondition(self, _input):
        result = deploy_moonraker({})
        self.assertEqual(result.outcome, WorkflowOutcome.PRECONDITION_FAILED)

    @patch("core.menu.simple_input", side_effect=["http://pi.local", "7125", "secret"])
    def test_api_key_over_plain_http_is_hard_block(self, _input):
        with patch("core.moonraker.check_moonraker") as check:
            result = deploy_moonraker({})
        self.assertEqual(result.outcome, WorkflowOutcome.PRECONDITION_FAILED)
        check.assert_not_called()

    @patch("core.deployer._run_config_transaction", return_value=success("done"))
    @patch("core.menu.numbered_select", return_value="firmware")
    @patch("core.moonraker.check_moonraker", return_value=(True, "OK"))
    @patch("core.menu.simple_input", side_effect=["pi.local", "7125", ""])
    def test_reachable_host_uses_common_transaction(self, _input, _check, _select, run):
        result = deploy_moonraker({})
        self.assertTrue(result.ok)
        transport, _user, activation = run.call_args.args
        self.assertEqual(transport.host, "pi.local")
        self.assertEqual(transport.port, 7125)
        self.assertEqual(activation, "firmware")

    @patch("core.menu.yes_no", return_value=False)
    @patch("core.moonraker.check_moonraker", return_value=(False, "offline"))
    @patch("core.menu.simple_input", side_effect=["pi.local", "7125", ""])
    def test_unreachable_without_fallback_is_failure(self, _input, _check, _yes):
        result = deploy_moonraker({})
        self.assertEqual(result.outcome, WorkflowOutcome.DEPLOYMENT_FAILED)
        self.assertIn("offline", result.detail)


class LocalExportBoundaryTests(unittest.TestCase):
    @patch("core.menu.yes_no", return_value=True)
    def test_config_export_preserves_existing_root_through_real_transaction(self, _yes):
        generated = b"[mcu]\nserial: /dev/serial/by-id/test\n[printer]\nkinematics: cartesian\n"
        with tempfile.TemporaryDirectory() as destination, tempfile.TemporaryDirectory() as home:
            kace_dir = os.path.join(home, "kace")
            os.makedirs(kace_dir)
            with open(os.path.join(kace_dir, "printer.cfg"), "wb") as output:
                output.write(generated)
            with open(os.path.join(destination, "printer.cfg"), "wb") as output:
                output.write(b"[gcode_macro USER]\ngcode: M117 keep\n")
            with patch("core.deployer.os.path.expanduser", side_effect=lambda p: p.replace("~/", home + os.sep)):
                self.assertTrue(_copy_artifacts({}, destination, "config"))
            with open(os.path.join(destination, "printer.cfg"), "rb") as source:
                root = source.read()
        self.assertIn(b"[gcode_macro USER]", root)
        self.assertIn(b"kace/generated-hardware.cfg", root)

    def test_explicit_firmware_path_is_copied(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as destination:
            firmware = os.path.join(source_dir, "firmware.uf2")
            with open(firmware, "wb") as output:
                output.write(b"firmware")
            self.assertTrue(_copy_artifacts({"firmware_path": firmware}, destination, "firmware"))
            with open(os.path.join(destination, "firmware.uf2"), "rb") as copied:
                self.assertEqual(copied.read(), b"firmware")


class FirmwareInstallationPreconditionTests(unittest.TestCase):
    def _user(self):
        digest = "a" * 64
        identity = FirmwareBuildInputs.create(
            klipper_commit="1" * 40,
            canonical_config='CONFIG_MCU="stm32"\n',
            toolchain=ToolchainIdentity("make", "GNU Make 4.4", "gcc", "gcc 13"),
            build_id="2" * 32,
        ).complete(
            artifact_sha256=digest,
            artifact_size=4096,
            artifact_format="bin",
        )
        artifact = SimpleNamespace(
            firmware_identity=identity,
            sha256=digest,
            provenance=BuildProvenance.REAL,
            flashable=True,
        )
        prepared = SimpleNamespace(
            plan=SimpleNamespace(
                method=SimpleNamespace(value="MANUAL"), artifact=artifact
            ),
            sha256=digest,
        )
        return {
            "prepared_firmware_deployment": prepared,
            "firmware_deployment_service": MagicMock(),
            "mcu_path": "/dev/serial/by-id/test",
        }

    def test_legacy_version_string_cannot_replace_typed_build_identity(self):
        user = self._user()
        user["klipper_version"] = "kace-legacy-config-hash"
        user["prepared_firmware_deployment"].plan.artifact.firmware_identity = None

        result = deploy_firmware_installation(user)

        self.assertEqual(result.state, DeployState.FAILED_FLASH)
        self.assertIn("build identity", result.detail)
        user["firmware_deployment_service"].execute.assert_not_called()

    def test_tampered_staged_artifact_cannot_enter_flash_workflow(self):
        user = self._user()
        user["prepared_firmware_deployment"].sha256 = "b" * 64

        result = deploy_firmware_installation(user)

        self.assertEqual(result.state, DeployState.FAILED_FLASH)
        self.assertIn("does not match", result.detail)
        user["firmware_deployment_service"].execute.assert_not_called()

    @patch("core.deployer._preflight_check", return_value=True)
    @patch("core.deployer._generated_config_bytes", return_value=("generated.cfg", b"[mcu]\n[printer]\n", None))
    @patch("core.config_transaction.MoonrakerConfigTransport.read_files", side_effect=ConnectionError("offline"))
    def test_backup_read_failure_prevents_firmware_action(self, _read, _generated, _preflight):
        user = self._user()
        result = deploy_firmware_installation(user)
        self.assertEqual(result.state, DeployState.FAILED_PRECONDITION)
        self.assertIn("before firmware", result.detail)
        user["firmware_deployment_service"].execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
