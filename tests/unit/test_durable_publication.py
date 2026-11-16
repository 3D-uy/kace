"""Publication is acknowledged only after directory metadata is synchronized."""
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import durable_storage, firmware_workflow, reconciler
from tests.unit.test_firmware_workflow import base_user_data, identity_reader


@pytest.mark.parametrize("kind", ["text", "checkpoint"])
def test_directory_sync_precedes_publication_acknowledgement(tmp_path, monkeypatch, kind):
    events = []
    destination = tmp_path / "state.json"
    checkpoint = firmware_workflow.create_checkpoint(base_user_data(), identity_reader=identity_reader())
    owner = reconciler if kind == "text" else firmware_workflow
    replace = os.replace

    def replace_file(source, target):
        replace(source, target)
        if Path(target) == destination:
            events.append("replace")

    def sync_directory(directory):
        assert Path(directory) == destination.parent
        assert destination.is_file()
        assert events == ["replace"]
        assert "_storage_revision" not in checkpoint
        events.append("directory-sync")

    monkeypatch.setattr(owner, "fsync_directory", sync_directory, raising=False)
    monkeypatch.setattr(os, "replace", replace_file)
    monkeypatch.setenv("KACE_MACHINE_OUTPUT", "1")
    monkeypatch.setattr("core.moonraker_deployer.JsonEventSink", lambda: lambda event: events.append("event"))
    if kind == "text":
        reconciler.write_text_atomically(destination, "new receipt\n")
        assert events == ["replace", "directory-sync"]
    else:
        firmware_workflow.write_checkpoint(checkpoint, str(destination))
        assert events == ["replace", "directory-sync", "event"]
        assert checkpoint["_storage_revision"] == firmware_workflow.checkpoint_revision(str(destination))


@pytest.mark.parametrize("kind", ["text", "checkpoint"])
def test_post_replace_sync_error_never_acknowledges_durability(tmp_path, monkeypatch, kind):
    destination = tmp_path / "state.json"
    checkpoint = firmware_workflow.create_checkpoint(base_user_data(), identity_reader=identity_reader())
    owner = reconciler if kind == "text" else firmware_workflow
    emitted = []

    def fail_sync(directory):
        assert destination.is_file()  # Replacement already happened; do not claim rollback.
        raise OSError("synthetic directory fsync failure")

    monkeypatch.setattr(owner, "fsync_directory", fail_sync, raising=False)
    monkeypatch.setenv("KACE_MACHINE_OUTPUT", "1")
    monkeypatch.setattr("core.moonraker_deployer.JsonEventSink", lambda: emitted.append)
    with pytest.raises(OSError, match="durability.*not confirmed"):
        if kind == "text":
            reconciler.write_text_atomically(destination, "new receipt\n")
        else:
            firmware_workflow.write_checkpoint(checkpoint, str(destination))
    assert destination.is_file()
    assert not emitted
    assert "_storage_revision" not in checkpoint
    assert not list(tmp_path.glob("*.part"))
    assert not list(tmp_path.glob("firmware-workflow-*.json"))


@pytest.mark.parametrize("failure", ["file-sync", "replace"])
@pytest.mark.parametrize("kind", ["text", "checkpoint"])
def test_prepublication_failure_preserves_existing_state(tmp_path, monkeypatch, failure, kind):
    destination = tmp_path / "receipt.json"
    checkpoint = firmware_workflow.create_checkpoint(base_user_data(), identity_reader=identity_reader())
    if kind == "text":
        destination.write_text("old receipt\n", encoding="utf-8")
    else:
        firmware_workflow.write_checkpoint(checkpoint, str(destination))
    previous = destination.read_bytes()
    revision = checkpoint.get("_storage_revision")
    events = []
    monkeypatch.setenv("KACE_MACHINE_OUTPUT", "1")
    monkeypatch.setattr("core.moonraker_deployer.JsonEventSink", lambda: events.append)
    # This case isolates the file barrier/rename; parent barrier failures have
    # their own coverage and must not intercept the injected file-fsync error.
    owner = reconciler if kind == "text" else firmware_workflow
    monkeypatch.setattr(owner, "ensure_durable_directory", lambda path: None)
    def fail(*args):
        raise OSError("synthetic prepublication failure")
    monkeypatch.setattr(os, "fsync" if failure == "file-sync" else "replace", fail)
    with pytest.raises(OSError, match="prepublication"):
        if kind == "text":
            reconciler.write_text_atomically(destination, "new receipt\n")
        else:
            firmware_workflow.write_checkpoint(checkpoint, str(destination))
    assert destination.read_bytes() == previous
    assert checkpoint.get("_storage_revision") == revision
    assert not events
    assert not list(tmp_path.glob("*.part"))
    assert not list(tmp_path.glob("firmware-workflow-*.json"))


@pytest.mark.parametrize("fail_sync", [False, True])
def test_posix_directory_descriptor_is_closed_even_when_sync_fails(monkeypatch, fail_sync):
    calls = []
    def sync(descriptor):
        calls.append(("sync", descriptor))
        if fail_sync:
            raise OSError("directory sync rejected")
    monkeypatch.setattr(durable_storage, "os", SimpleNamespace(
        name="posix", O_RDONLY=0, O_DIRECTORY=65536,
        open=lambda path, flags: calls.append(("open", path, flags)) or 19,
        fsync=sync, close=lambda fd: calls.append(("close", fd)),
    ))
    if fail_sync:
        with pytest.raises(OSError, match="sync rejected"):
            durable_storage.fsync_directory("state-directory")
    else:
        durable_storage.fsync_directory("state-directory")
    assert calls == [("open", "state-directory", 65536), ("sync", 19), ("close", 19)]


def test_windows_directory_sync_does_not_claim_posix_syscalls(monkeypatch):
    monkeypatch.setattr(durable_storage, "os", SimpleNamespace(name="nt"))
    durable_storage.fsync_directory("unused")


def test_new_parents_are_committed_before_creating_descendants(tmp_path, monkeypatch):
    destination = tmp_path / "operations" / "operation-id"
    calls = []
    def sync(directory):
        directory = Path(directory)
        assert directory.is_dir()
        if directory == tmp_path and (tmp_path / "operations").exists():
            assert not destination.exists()
        calls.append(directory)
    monkeypatch.setattr(durable_storage, "fsync_directory", sync)
    durable_storage.ensure_durable_directory(destination, exist_ok=False)
    assert calls == [tmp_path.parent, destination.parent, tmp_path, destination, destination.parent]
    assert destination.is_dir()
    with pytest.raises(FileExistsError):
        durable_storage.ensure_durable_directory(destination, exist_ok=False)


def test_retry_commits_ancestor_left_by_failed_parent_barrier(tmp_path, monkeypatch):
    destination = tmp_path / "operations" / "operation-id"
    def fail_parent(directory):
        if Path(directory) == tmp_path:
            raise OSError("parent barrier failed")
    monkeypatch.setattr(durable_storage, "fsync_directory", fail_parent)
    with pytest.raises(OSError, match="parent barrier"):
        durable_storage.ensure_durable_directory(destination)
    assert destination.parent.is_dir()
    assert not destination.exists()
    calls = []
    monkeypatch.setattr(durable_storage, "fsync_directory", lambda path: calls.append(Path(path)))
    durable_storage.ensure_durable_directory(destination)
    assert calls == [tmp_path, destination, destination.parent]


def test_text_permissions_are_set_before_final_file_sync(tmp_path, monkeypatch):
    destination = tmp_path / "receipt.json"
    events = []
    chmod, fsync, replace = os.chmod, os.fsync, os.replace
    def set_mode(path, mode):
        events.append(("mode", mode))
        chmod(path, mode)
    def sync(fd):
        events.append(("sync",))
        fsync(fd)
    def replace_file(source, target):
        events.append(("replace",))
        replace(source, target)
    monkeypatch.setattr(reconciler, "ensure_durable_directory", lambda path: None)
    monkeypatch.setattr(reconciler, "fsync_directory", lambda path: events.append(("directory",)))
    monkeypatch.setattr(os, "chmod", set_mode)
    monkeypatch.setattr(os, "fsync", sync)
    monkeypatch.setattr(os, "replace", replace_file)
    reconciler.write_text_atomically(destination, "receipt\n")
    assert events == [("mode", 0o644), ("sync",), ("replace",), ("directory",)]
