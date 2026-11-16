"""Diagnostic storage failure must not hide files already published."""
import errno

import pytest

from core import config_transaction, klipper_preflight
from core.deployer import _config_result_to_workflow
from core.snapshot import create_snapshot
from tests.unit.test_config_transaction import FakeTransport, GENERATED


@pytest.fixture
def valid_preflight(monkeypatch):
    monkeypatch.setattr(klipper_preflight, "validate_plan", lambda plan:
        klipper_preflight.PreflightResult("valid", "explicit unit loader double", klipper_preflight.plan_digest(plan)))


@pytest.mark.parametrize("failure_type,error_number", [(OSError, errno.ENOSPC), (PermissionError, errno.EACCES)])
@pytest.mark.parametrize("failed_name", ["kace/generated-hardware.cfg", "kace/generated-macros.cfg", "printer.cfg"])
@pytest.mark.parametrize("failed_after_write", [False, True])
def test_proposal_snapshot_failure_preserves_primary_error_and_partial_state(
    tmp_path, monkeypatch, valid_preflight, failure_type, error_number, failed_name, failed_after_write,
):
    transport = FakeTransport({"printer.cfg": b"# old root\n"})
    upload = transport.upload_bytes
    def failing_upload(name, content):
        if name == failed_name:
            transport.calls.append(("upload", name))
            if failed_after_write:
                transport.files[name] = content
            raise OSError("synthetic upload failure")
        upload(name, content)
    transport.upload_bytes = failing_upload
    snapshot_calls = []
    def snapshot(originals, **kwargs):
        snapshot_calls.append(kwargs["deployment_id"])
        if kwargs["deployment_id"].endswith("-proposed"):
            raise failure_type(error_number, "synthetic proposal storage failure")
        return create_snapshot(originals, **kwargs)
    monkeypatch.setattr(config_transaction, "create_snapshot", snapshot)
    events = []
    transaction = config_transaction.ConfigDeploymentTransaction(
        transport, GENERATED, b"# macros\n", activation="firmware", confirm=lambda _: True,
        output=lambda _: None, snapshot_root=str(tmp_path / "snapshots"), poll_interval=0,
        state_sink=lambda state, detail: events.append((state, detail)),
    )
    result = transaction.run()
    partial = failed_name != "kace/generated-hardware.cfg" or failed_after_write
    assert result.state is (config_transaction.ConfigTransactionState.ROLLBACK_FAILED if partial
                            else config_transaction.ConfigTransactionState.UPLOAD_FAILED)
    assert result.rollback_succeeded is (False if partial else None)
    assert "synthetic upload failure" in result.detail
    assert "synthetic proposal storage failure" in result.detail
    assert result.snapshot is not None
    assert result.snapshot.config_files["printer.cfg"] == b"# old root\n"
    expected_files = {"printer.cfg": b"# old root\n"}
    for artifact in sorted(transaction.plan.changed_artifacts,
                           key=lambda item: (item.remote_name == "printer.cfg", item.remote_name)):
        if artifact.remote_name == failed_name:
            if failed_after_write:
                expected_files[artifact.remote_name] = artifact.content
            break
        expected_files[artifact.remote_name] = artifact.content
    assert transport.files == expected_files
    assert not any(call[0] == "restart" for call in transport.calls)
    assert ("CONFIG_ERROR", "synthetic upload failure") in events
    assert not any(state == "DONE" for state, _ in events)
    assert len(snapshot_calls) == 2
    workflow = _config_result_to_workflow(result)
    assert workflow.exit_code == 40
    assert workflow.detail == result.detail


@pytest.mark.parametrize("conflict_after_snapshot", [False, True])
def test_proposal_failure_preserves_prepublication_conflict(
    tmp_path, monkeypatch, valid_preflight, conflict_after_snapshot,
):
    transport = FakeTransport({"printer.cfg": b"# original\n"})
    external = b"# concurrent edit\n"
    def confirm(_):
        if not conflict_after_snapshot:
            transport.files["printer.cfg"] = external
        return True
    def snapshot(originals, **kwargs):
        if kwargs["deployment_id"].endswith("-proposed"):
            raise OSError(errno.ENOSPC, "proposal disk full")
        result = create_snapshot(originals, **kwargs)
        transport.files["printer.cfg"] = external
        return result
    monkeypatch.setattr(config_transaction, "create_snapshot", snapshot)
    result = config_transaction.ConfigDeploymentTransaction(
        transport, GENERATED, b"# macros\n", activation="firmware", confirm=confirm,
        output=lambda _: None, snapshot_root=str(tmp_path / "snapshots"), poll_interval=0,
    ).run()
    assert result.state is config_transaction.ConfigTransactionState.PRECONDITION_FAILED
    assert "concurrent configuration modification" in result.detail
    assert "no configuration files were written" in result.detail
    assert "proposal disk full" in result.detail
    assert (result.snapshot is not None) is conflict_after_snapshot
    assert transport.files == {"printer.cfg": external}
    assert not any(call[0] in {"upload", "delete", "restart"} for call in transport.calls)
    assert _config_result_to_workflow(result).exit_code == 10


def test_proposal_failure_does_not_authorize_overwriting_external_edit(tmp_path, monkeypatch, valid_preflight):
    transport = FakeTransport({"printer.cfg": b"# original\n"})
    upload = transport.upload_bytes
    external = b"# concurrent hardware edit\n"
    def failing_upload(name, content):
        if name == "printer.cfg":
            transport.files["kace/generated-hardware.cfg"] = external
            raise OSError("primary upload failed")
        upload(name, content)
    transport.upload_bytes = failing_upload
    def snapshot(originals, **kwargs):
        if kwargs["deployment_id"].endswith("-proposed"):
            raise PermissionError(errno.EACCES, "proposal access denied")
        return create_snapshot(originals, **kwargs)
    monkeypatch.setattr(config_transaction, "create_snapshot", snapshot)
    result = config_transaction.ConfigDeploymentTransaction(
        transport, GENERATED, b"# macros\n", activation="firmware", confirm=lambda _: True,
        output=lambda _: None, snapshot_root=str(tmp_path / "snapshots"), poll_interval=0,
    ).run()
    assert result.state is config_transaction.ConfigTransactionState.ROLLBACK_FAILED
    assert result.rollback_succeeded is False
    assert "primary upload failed" in result.detail
    assert "proposal access denied" in result.detail
    assert "rollback conflict" in result.detail
    assert "manual recovery" in result.detail
    assert transport.files["kace/generated-hardware.cfg"] == external
    assert transport.files["printer.cfg"] == b"# original\n"
    assert result.snapshot.config_files["printer.cfg"] == b"# original\n"
    assert not any(call[0] in {"delete", "restart"} for call in transport.calls)
