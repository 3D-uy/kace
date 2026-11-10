"""Legacy folder exports cannot substitute for the firmware deployment authority."""
from unittest.mock import Mock

import pytest

from core import deployer
from core.workflow_outcome import WorkflowOutcome


@pytest.mark.parametrize("artifact_type", ["firmware", "all", "unknown"])
@pytest.mark.parametrize("explicit_path", [False, True])
def test_unverified_folder_handoff_stops_before_reading_or_copying(tmp_path, monkeypatch, artifact_type, explicit_path):
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    firmware = source / "klipper.bin"
    firmware.write_bytes(b"not a verified firmware artifact")
    prior = destination / "klipper.bin"
    prior.write_bytes(b"existing user bytes")
    user = {"firmware_path": str(firmware)} if explicit_path else {}
    reader = Mock(side_effect=AssertionError("No partial configuration handoff"))
    monkeypatch.setattr(deployer, "_generated_config_bytes", reader)
    monkeypatch.setattr(deployer.os.path, "expanduser", lambda p: str(source / p.rsplit("/", 1)[-1]))
    assert deployer._copy_artifacts(user, str(destination), artifact_type) is False
    reader.assert_not_called()
    assert prior.read_bytes() == b"existing user bytes"
    assert firmware.read_bytes() == b"not a verified firmware artifact"
    assert list(destination.iterdir()) == [prior]


@pytest.mark.parametrize("export", [deployer.deploy_usb, deployer.deploy_local])
@pytest.mark.parametrize("artifact_type", ["firmware", "all", "unknown"])
def test_public_legacy_firmware_route_fails_before_prompt(export, artifact_type, monkeypatch):
    import core.menu
    prompt = Mock(return_value=None)
    copy = Mock(return_value=True)
    monkeypatch.setattr(core.menu, "simple_input", prompt)
    monkeypatch.setattr(deployer, "_copy_artifacts", copy)
    result = export({}, artifact_type=artifact_type)
    assert result.outcome is WorkflowOutcome.PRECONDITION_FAILED
    assert "firmware" in result.detail.lower()
    prompt.assert_not_called()
    copy.assert_not_called()


@pytest.mark.parametrize("export", [deployer.deploy_usb, deployer.deploy_local])
def test_legacy_default_does_not_silently_export_only_config(export, monkeypatch):
    import core.menu
    prompt = Mock(return_value=None)
    monkeypatch.setattr(core.menu, "simple_input", prompt)
    assert export({}).outcome is WorkflowOutcome.PRECONDITION_FAILED
    prompt.assert_not_called()
