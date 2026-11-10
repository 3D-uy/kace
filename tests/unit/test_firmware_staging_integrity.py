"""Firmware staging must still contain the reviewed plan before publication."""
from pathlib import Path
from unittest.mock import patch
import pytest

from core.deployer import deploy_firmware_installation
from core.moonraker_deployer import DeployResult, DeployState
from tests.unit import test_deployer as firmware_fixtures


@pytest.fixture(autouse=True)
def isolated_preflight(monkeypatch):
    """Staging regressions exercise this boundary independently of Docker."""
    from core import klipper_preflight
    monkeypatch.setattr(klipper_preflight, "validate_plan", lambda plan:
                        klipper_preflight.PreflightResult("valid", "fixture", klipper_preflight.plan_digest(plan)))


def test_changed_staged_file_is_rejected_before_upload(tmp_path):
    files = {"printer.cfg": b"# original\n"}
    generated = b"[mcu]\nserial: /dev/serial/by-id/test\n[printer]\nkinematics: cartesian\n"
    user = firmware_fixtures.FirmwareInstallationPreconditionTests()._user()
    uploaded = []
    def inspect_deployment():
        manifest = physical.call_args.args[1]
        artifact = manifest.artifacts()[0]
        Path(artifact.local_path).write_bytes(b"# changed after plan review\n")
        try:
            physical.call_args.kwargs["before_config_upload"]()
        except Exception as exc:
            return DeployResult(DeployState.FAILED_PRECONDITION, str(exc))
        uploaded.append(Path(artifact.local_path).read_bytes())
        return DeployResult(DeployState.DONE, "unreviewed staging accepted")
    from core.snapshot import create_snapshot
    with patch("core.deployer._preflight_check", return_value=True), \
         patch("core.deployer._generated_config_bytes", return_value=("generated.cfg", generated, None)), \
         patch("core.config_transaction.MoonrakerConfigTransport.validate_activation_target"), \
         patch("core.config_transaction.MoonrakerConfigTransport.supports_conditional_write", return_value=True), \
         patch("core.config_transaction.MoonrakerConfigTransport.read_files", side_effect=lambda names: {n: files.get(n) for n in names}), \
         patch("core.deployer._interactive_configuration_review", return_value=True), \
         patch("core.snapshot.create_snapshot", side_effect=lambda originals, **kw: create_snapshot(originals, persist_root=str(tmp_path), **kw)), \
         patch("core.power_controller.configured_power_controller", return_value=None), \
         patch("core.mcu_monitor.McuPresenceMonitor"), \
         patch("core.moonraker_deployer.Deployer") as physical:
        physical.return_value.run.side_effect = inspect_deployment
        result = deploy_firmware_installation(user)
    assert result.state == DeployState.FAILED_PRECONDITION
    assert "staged" in result.detail.lower()
    assert not uploaded


def _real_deployer(tmp_path, callback):
    from core.moonraker_deployer import ConfigArtifact, Deployer, DeploymentManifest, McuTarget
    from core.snapshot import DeploymentSnapshot
    from tests.unit.test_moonraker_deployer import Client

    path = tmp_path / "printer.cfg"
    expected = b"[printer]\nkinematics: cartesian\n"
    path.write_bytes(expected)
    artifact = ConfigArtifact(str(path), "printer.cfg", expected)
    manifest = DeploymentManifest([McuTarget("mcu", "kace-good")], str(path), config_artifacts=[artifact])
    snapshot = DeploymentSnapshot("id", "now", "board", "version", "", ("mcu",), False,
                                  {"printer.cfg": b"[printer]\nold: true\n"})
    client = Client({})
    deployer = Deployer(client, manifest, snapshot=snapshot, verify_firmware=False,
                        before_config_upload=lambda: callback(path, client),
                        verify_active_configuration=lambda: None, event_sink=lambda _event: None)
    deployer.POLL_INTERVAL_S = 0.001
    deployer.POLL_BACKOFF_MAX_S = 0.002
    return path, expected, client, deployer


def test_real_deployer_rejects_staging_mutation_before_first_write(tmp_path):
    def mutate(path, _client):
        path.write_bytes(b"# tampered\n")
    _path, _expected, client, deployer = _real_deployer(tmp_path, mutate)
    result = deployer.run()
    assert result.state == DeployState.FAILED_PRECONDITION
    assert "staged configuration changed" in result.detail
    assert not [call for call in client.calls if isinstance(call, tuple) and call[0] == "upload"]
    assert "rollback" not in client.calls


def test_real_deployer_uploads_checked_buffer_and_verifies_plan_bytes(tmp_path):
    def mutate_after_staging(path, client):
        original_read = client.read_config_files
        def read(names):
            path.write_bytes(b"# changed after the checked read\n")
            return original_read(names)
        client.read_config_files = read
    path, expected, client, deployer = _real_deployer(tmp_path, mutate_after_staging)
    result = deployer.run()
    assert result.state == DeployState.DONE, result.detail
    assert path.read_bytes() != expected
    assert client.remote["printer.cfg"] == expected


def test_staging_mutation_blocks_power_and_firmware(tmp_path):
    from core.moonraker_deployer import ConfigArtifact
    from core.snapshot import create_snapshot
    files = {"printer.cfg": b"# original\n"}
    generated = b"[mcu]\nserial: /dev/serial/by-id/test\n[printer]\nkinematics: cartesian\n"
    user = firmware_fixtures.FirmwareInstallationPreconditionTests()._user()
    original_read = ConfigArtifact.read_content
    def corrupt(artifact):
        Path(artifact.local_path).write_bytes(b"# modified before power\n")
        return original_read(artifact)
    with patch("core.deployer._preflight_check", return_value=True), \
         patch("core.deployer._generated_config_bytes", return_value=("generated.cfg", generated, None)), \
         patch("core.config_transaction.MoonrakerConfigTransport.validate_activation_target"), \
         patch("core.config_transaction.MoonrakerConfigTransport.supports_conditional_write", return_value=True), \
         patch("core.config_transaction.MoonrakerConfigTransport.read_files", side_effect=lambda names: {n: files.get(n) for n in names}), \
         patch("core.deployer._interactive_configuration_review", return_value=True), \
         patch("core.snapshot.create_snapshot", side_effect=lambda originals, **kw: create_snapshot(originals, persist_root=str(tmp_path), **kw)), \
         patch("core.power_controller.configured_power_controller") as power_factory, \
         patch.object(ConfigArtifact, "read_content", autospec=True, side_effect=corrupt), \
         patch("core.moonraker_deployer.Deployer") as physical:
        result = deploy_firmware_installation(user)
    assert result.state == DeployState.FAILED_PRECONDITION
    assert "staged configuration changed" in result.detail
    power_factory.return_value.power_on.assert_not_called()
    physical.assert_not_called()
    user["firmware_deployment_service"].execute.assert_not_called()


def test_all_staged_files_checked_before_any_upload(tmp_path):
    from dataclasses import replace
    from core.moonraker_deployer import ConfigArtifact
    _path, _expected, client, deployer = _real_deployer(tmp_path, lambda *_args: None)
    other = tmp_path / "second.cfg"
    other.write_bytes(b"# altered\n")
    deployer.manifest.config_artifacts.insert(0, ConfigArtifact(str(other), "second.cfg", b"# reviewed\n"))
    deployer.snapshot = replace(deployer.snapshot, missing_files=("second.cfg",))
    result = deployer.run()
    assert result.state == DeployState.FAILED_PRECONDITION
    assert "second.cfg" in result.detail
    assert not [call for call in client.calls if isinstance(call, tuple) and call[0] == "upload"]


def test_staging_changed_after_power_blocks_firmware_service(tmp_path):
    from core.moonraker_deployer import ConfigArtifact
    from core.snapshot import create_snapshot
    files = {"printer.cfg": b"# original\n"}
    generated = b"[mcu]\nserial: /dev/serial/by-id/test\n[printer]\nkinematics: cartesian\n"
    user = firmware_fixtures.FirmwareInstallationPreconditionTests()._user()
    original_read = ConfigArtifact.read_content
    seen = []
    def remember(artifact):
        seen.append(Path(artifact.local_path))
        return original_read(artifact)
    def firmware_boundary():
        try:
            physical.call_args.kwargs["firmware_deploy"]()
        except ValueError as exc:
            return DeployResult(DeployState.FAILED_PRECONDITION, str(exc))
        return DeployResult(DeployState.DONE, "unexpected firmware action")
    with patch("core.deployer._preflight_check", return_value=True), \
         patch("core.deployer._generated_config_bytes", return_value=("generated.cfg", generated, None)), \
         patch("core.config_transaction.MoonrakerConfigTransport.validate_activation_target"), \
         patch("core.config_transaction.MoonrakerConfigTransport.supports_conditional_write", return_value=True), \
         patch("core.config_transaction.MoonrakerConfigTransport.read_files", side_effect=lambda names: {n: files.get(n) for n in names}), \
         patch("core.deployer._interactive_configuration_review", return_value=True), \
         patch("core.snapshot.create_snapshot", side_effect=lambda originals, **kw: create_snapshot(originals, persist_root=str(tmp_path), **kw)), \
         patch("core.power_controller.configured_power_controller") as power_factory, \
         patch.object(ConfigArtifact, "read_content", autospec=True, side_effect=remember), \
         patch("core.mcu_monitor.McuPresenceMonitor"), \
         patch("core.moonraker_deployer.Deployer") as physical:
        power_factory.return_value.power_on.side_effect = lambda: seen[0].write_bytes(b"# altered after power\n")
        physical.return_value.run.side_effect = firmware_boundary
        result = deploy_firmware_installation(user)
    assert result.state == DeployState.FAILED_PRECONDITION
    assert "staged configuration changed" in result.detail
    power_factory.return_value.power_on.assert_called_once()
    user["firmware_deployment_service"].execute.assert_not_called()
