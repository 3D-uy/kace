"""Deployment adapters must consume bound XY evidence before physical work."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from core import config_transaction, deployer, snapshot
from core.config_transaction import ConfigConflictError
from core.firmware_workflow import (
    FirmwareWorkflowState, load_checkpoint, transition_checkpoint, write_checkpoint,
)
from core.moonraker_deployer import DeployResult, DeployState
from core.workflow_outcome import WorkflowOutcome
from tests.unit.test_config_transaction import FakeTransport
from tests.unit import test_deployer as firmware_fixtures
from tests.unit.test_effective_xy_geometry import _destination, _generate
from tests.unit.test_firmware_pin_reservations import artifact, resumed_user
from tests.unit.test_generator import _parsed
from tests.unit.test_reserved_pin_review import assert_untouched


@pytest.fixture(autouse=True)
def isolated_snapshots(tmp_path, monkeypatch):
    """Exercise real snapshot persistence without writing to the operator home."""
    create = snapshot.create_snapshot

    def persist(*args, **kwargs):
        kwargs.setdefault("persist_root", str(tmp_path / "snapshots"))
        if kwargs["persist_root"] is None:
            kwargs["persist_root"] = str(tmp_path / "snapshots")
        return create(*args, **kwargs)

    monkeypatch.setattr(snapshot, "create_snapshot", persist)
    monkeypatch.setattr(config_transaction, "create_snapshot", persist)


@pytest.fixture(autouse=True)
def isolated_klipper_preflight(monkeypatch):
    """These cases exercise geometry; preflight has separate integration tests."""
    from core import klipper_preflight
    from tests.fixtures.klipper_preflight import valid_preflight
    monkeypatch.setattr(klipper_preflight, "validate_plan", valid_preflight)


def _source(tmp_path, **values):
    source = tmp_path / "source"
    source.mkdir()
    content = _generate(source, **values)
    return source / "printer.cfg", content


def _damage_evidence(path, damage):
    sidecar = Path(str(path) + ".provenance.json")
    if damage == "missing":
        sidecar.unlink()
        return
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    if damage == "legacy":
        payload.pop("geometry")
    elif damage == "stale":
        payload["geometry"]["source_sha256"] = "0" * 64
    else:
        raise AssertionError(damage)
    sidecar.write_text(json.dumps(payload), encoding="utf-8")


def _firmware_user(tmp_path):
    built = artifact(tmp_path)
    user = firmware_fixtures.FirmwareInstallationPreconditionTests()._user()
    prepared = user["prepared_firmware_deployment"]
    prepared.plan.artifact = built
    prepared.sha256 = built.sha256
    prepared.staged_path = built.path
    return user, built


@pytest.mark.parametrize("override", [
    "[bed_mesh]\nmesh_min: 300,300\nmesh_max: 400,400\n",
    "[safe_z_home]\nhome_xy_position: 999,999\n",
    "[bltouch]\nx_offset: 500\n",
])
def test_combined_xy_failure_precedes_snapshot_power_and_firmware(tmp_path, override):
    path, content = _source(tmp_path)
    user, _built = _firmware_user(tmp_path)
    transport = FakeTransport(_destination(content, override))
    original = dict(transport.files)

    with patch.object(config_transaction, "configuration_transport", return_value=transport), \
            patch.object(deployer, "_generated_config_bytes", return_value=(str(path), content, None)), \
            patch.object(deployer, "_preflight_check", return_value=True), \
            patch.object(deployer, "_interactive_configuration_review", return_value=True) as review, \
            patch("core.snapshot.create_snapshot") as take_snapshot, \
            patch("core.power_controller.configured_power_controller") as power, \
            patch("core.mcu_monitor.McuPresenceMonitor") as monitor, \
            patch("core.moonraker_deployer.Deployer") as physical:
        result = deployer.deploy_firmware_installation(user)

    assert result.state == DeployState.FAILED_PRECONDITION
    assert "semantic configuration validation failed before firmware" in result.detail
    assert any(item.code == "effective-xy-geometry" for item in review.call_args.args[0].validation.errors)
    take_snapshot.assert_not_called()
    power.assert_not_called()
    monitor.assert_not_called()
    physical.assert_not_called()
    user["firmware_deployment_service"].execute.assert_not_called()
    assert_untouched(transport, original)


def test_combined_valid_xy_keeps_firmware_identity_and_final_state_guards(tmp_path):
    path, content = _source(tmp_path)
    override = "[safe_z_home]\nhome_xy_position: 100,110\n"
    user, built = _firmware_user(tmp_path)
    prepared = user["prepared_firmware_deployment"]
    transport = FakeTransport(_destination(content, override))
    original = dict(transport.files)
    captured = {}

    def run_boundary():
        # Stop before physical work but inspect the real staged files and gates.
        manifest = physical.call_args.args[1]
        options = physical.call_args.kwargs
        captured.update(options)
        captured["manifest"] = manifest
        staged = {item.remote_name: Path(item.local_path).read_bytes() for item in manifest.artifacts()}
        assert staged
        baseline = options["before_config_upload"]()
        assert baseline == {name: original.get(name) for name in baseline}
        options["firmware_deploy"]()  # The service itself is an explicit offline mock.
        transport.files.update(staged)
        transport.active_files = dict(transport.files)
        options["verify_config_state"]()
        options["verify_active_configuration"]()
        return DeployResult(DeployState.ABORTED, "offline boundary inspected")

    with patch.object(config_transaction, "configuration_transport", return_value=transport), \
            patch.object(deployer, "_generated_config_bytes", return_value=(str(path), content, None)), \
            patch.object(deployer, "_preflight_check", return_value=True), \
            patch.object(deployer, "_interactive_configuration_review", return_value=True), \
            patch("core.power_controller.configured_power_controller", return_value=None), \
            patch("core.mcu_monitor.McuPresenceMonitor"), \
            patch("core.moonraker_deployer.Deployer") as physical:
        physical.return_value.run.side_effect = run_boundary
        result = deployer.deploy_firmware_installation(user)

    assert result.state == DeployState.ABORTED
    assert result.detail == "offline boundary inspected"
    assert captured["verify_firmware"] is True
    target = captured["manifest"].targets[0]
    assert target.expected_version == built.firmware_identity.reported_version
    assert target.firmware_identity == built.firmware_identity.to_dict()
    assert user["prepared_firmware_deployment"] is prepared
    assert prepared.plan.artifact is built
    assert user["firmware_deployment_service"].execute.call_args.args[0] is prepared
    assert transport.files["nested.cfg"] == override.encode()
    transport.files["nested.cfg"] = b"# edited after review\n"
    with pytest.raises(ConfigConflictError, match="concurrent"):
        captured["verify_config_state"]()
    transport.active_files["printer.cfg"] = b"# stale loaded root\n"
    with pytest.raises(ConfigConflictError, match="loaded configuration"):
        captured["verify_active_configuration"]()


@pytest.mark.parametrize("route", ["config-only", "export"])
@pytest.mark.parametrize("evidence", ["valid", "missing", "legacy", "stale"])
def test_configuration_adapters_read_actual_geometry_sidecar(tmp_path, route, evidence):
    path, content = _source(tmp_path)
    if evidence != "valid":
        _damage_evidence(path, evidence)
    remote = _destination(content, "[safe_z_home]\nhome_xy_position: 100,110\n")
    transport = FakeTransport(remote)
    destination = tmp_path / "destination"
    destination.mkdir()
    with patch.object(deployer, "_generated_config_bytes", return_value=(str(path), content, None)), \
            patch.object(deployer, "_preflight_check", return_value=True), \
            patch.object(deployer, "_interactive_configuration_review", return_value=True), \
            patch.object(deployer, "_review_configuration_export", return_value=True), \
            patch.object(config_transaction, "LocalConfigTransport", return_value=transport):
        if route == "config-only":
            result = deployer._run_config_transaction(transport, {}, "none")
            accepted = result.outcome == WorkflowOutcome.DEPLOYED_PENDING_ACTIVATION
            if not accepted:
                assert result.outcome == WorkflowOutcome.PRECONDITION_FAILED
                assert "geometry" in result.detail
                assert_untouched(transport, remote)
        else:
            accepted = deployer._copy_artifacts({}, str(destination), "config")
            if not accepted:
                assert_untouched(transport, remote)

    assert accepted is (evidence == "valid")


@pytest.mark.parametrize("state", ["CONFIG_GENERATED", "READY_TO_DEPLOY", "DEPLOYING"])
@pytest.mark.parametrize("damage", ["missing", "stale"])
def test_resumed_geometry_failure_preserves_checkpoint_and_mcu_receipts(tmp_path, state, damage):
    path, content = _source(tmp_path, mcu_path="/dev/serial/by-id/test")
    built = artifact(tmp_path)
    user = resumed_user(built)
    user["board_parsed"] = _parsed(bltouch={"sensor_pin": "^PB8", "control_pin": "PB9"})
    checkpoint = user["workflow_checkpoint"]
    for next_state in ("CONFIG_GENERATED", "READY_TO_DEPLOY", "DEPLOYING"):
        checkpoint = transition_checkpoint(checkpoint, FirmwareWorkflowState(next_state), user_data=user)
        if next_state == state:
            break
    checkpoint_path = tmp_path / "firmware-workflow.json"
    write_checkpoint(checkpoint, str(checkpoint_path))
    user["workflow_checkpoint"] = load_checkpoint(str(checkpoint_path))
    before = deepcopy(user["workflow_checkpoint"])
    checkpoint_bytes = checkpoint_path.read_bytes()
    firmware_bytes = Path(built.path).read_bytes()
    _damage_evidence(path, damage)
    transport = FakeTransport(_destination(content, ""))
    original = dict(transport.files)

    with patch.object(deployer, "_generated_config_bytes", return_value=(str(path), content, None)), \
            patch.object(deployer, "_preflight_check", return_value=True), \
            patch.object(deployer, "_interactive_configuration_review", return_value=True), \
            patch.object(deployer, "_require_running_firmware_checkpoint") as verify_running, \
            patch("core.firmware_workflow.write_checkpoint") as persist, \
            patch("core.firmware_workflow.verify_reappeared_mcu") as verify_mcu, \
            patch("core.generator.generate_config") as regenerate:
        result = deployer._run_config_transaction(transport, user, "none")

    assert result.outcome == WorkflowOutcome.PRECONDITION_FAILED
    assert "geometry" in result.detail
    assert user["workflow_checkpoint"] == before
    assert checkpoint_path.read_bytes() == checkpoint_bytes
    assert Path(built.path).read_bytes() == firmware_bytes
    assert path.read_bytes() == content
    persist.assert_not_called()
    verify_running.assert_not_called()
    verify_mcu.assert_not_called()
    regenerate.assert_not_called()
    assert_untouched(transport, original)
