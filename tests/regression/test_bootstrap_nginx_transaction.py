"""Run bootstrap's embedded transaction with real temporary files, fake services."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

BOOTSTRAP = Path(__file__).resolve().parents[2] / "scripts/bootstrap.sh"
MARKER = "# KACE managed: printer dashboard\n"
pytestmark = pytest.mark.skipif(os.name == "nt", reason="bootstrap publisher requires POSIX symlinks; exercised in Linux")


def transaction(root, candidate, monkeypatch, *, fail="", mutate=None):
    source = BOOTSTRAP.read_text(encoding="utf-8")
    assert "publish_nginx_configuration() {" in source, "missing transactional publisher"
    body = source.split("publish_nginx_configuration() {", 1)[1].split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        if mutate:
            mutate(argv)
        failing = ((fail == "nginx-stage" and argv[:3] == ["nginx", "-t", "-c"])
                   or (fail == "nginx" and argv == ["nginx", "-t"])
                   or (fail == "systemctl" and argv[0] == "systemctl"))
        return subprocess.CompletedProcess(argv, 1 if failing else 0)
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(sys, "argv", ["bootstrap-nginx", str(candidate), str(root), "true"])
    try:
        exec(compile(body, str(BOOTSTRAP), "exec"), {"__name__": "__main__"})
    except SystemExit as exc:
        return exc.code, calls
    return 0, calls


def layout(tmp_path):
    root = tmp_path / "nginx"
    available = root / "sites-available"
    enabled = root / "sites-enabled"
    available.mkdir(parents=True)
    enabled.mkdir()
    (root / "nginx.conf").write_text("events {}\nhttp {\n    include " + str(root / "sites-enabled/*") + ";\n}\n")
    (available / "kace-printer").write_text(MARKER + "old dashboard\n")
    (enabled / "default").write_text("operator default\n")
    (enabled / "kace-printer").write_text("old enabled regular file\n")
    candidate = tmp_path / "candidate"
    candidate.write_text(MARKER + "new dashboard\n")
    return root, candidate


@pytest.mark.parametrize("failure", ["nginx-stage", "nginx", "systemctl"])
def test_validation_or_restart_failure_restores_every_previous_path(tmp_path, monkeypatch, failure):
    root, candidate = layout(tmp_path)
    paths = [root / "sites-available/kace-printer", root / "sites-enabled/default", root / "sites-enabled/kace-printer"]
    before = {p: p.read_bytes() for p in paths}
    code, calls = transaction(root, candidate, monkeypatch, fail=failure)
    assert code != 0
    assert {p: p.read_bytes() for p in paths} == before
    assert not (root / ".kace-nginx-transaction.json").exists()
    if failure.startswith("nginx"):
        assert not any(call[0] == "systemctl" for call in calls)


def test_external_change_during_failure_is_preserved_for_manual_recovery(tmp_path, monkeypatch):
    root, candidate = layout(tmp_path)
    changed = root / "sites-enabled/default"
    def edit(argv):
        if argv == ["nginx", "-t"]:
            changed.write_bytes(b"external writer")
    code, _ = transaction(root, candidate, monkeypatch, fail="nginx", mutate=edit)
    assert code != 0
    assert changed.read_bytes() == b"external writer"
    assert (root / ".kace-nginx-transaction.json").is_file()


def test_success_publishes_candidate_and_removes_conflicts(tmp_path, monkeypatch):
    root, candidate = layout(tmp_path)
    code, calls = transaction(root, candidate, monkeypatch)
    assert code == 0
    assert (root / "sites-available/kace-printer").read_bytes() == candidate.read_bytes()
    assert not (root / "sites-enabled/default").exists()
    assert (root / "sites-enabled/kace-printer").is_symlink()
    assert calls[0][:3] == ["nginx", "-t", "-c"]
    assert calls[1:] == [["nginx", "-t"], ["systemctl", "restart", "nginx"]]


def test_unknown_available_config_is_rejected_before_service_or_write(tmp_path, monkeypatch):
    root, candidate = layout(tmp_path)
    foreign = root / "sites-available/kace-printer"
    foreign.write_bytes(b"operator supplied server block")
    before = foreign.read_bytes()
    code, calls = transaction(root, candidate, monkeypatch)
    assert code != 0
    assert calls == []
    assert foreign.read_bytes() == before


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks, verified separately on Linux")
def test_relative_and_broken_links_are_restored_without_dereferencing(tmp_path, monkeypatch):
    root, candidate = layout(tmp_path)
    default = root / "sites-enabled/default"
    default.unlink()
    default.symlink_to("../sites-available/missing")
    code, _ = transaction(root, candidate, monkeypatch, fail="nginx")
    assert code != 0
    assert default.is_symlink()
    assert os.readlink(default) == "../sites-available/missing"


def test_permissions_and_ownership_survive_failure(tmp_path, monkeypatch):
    root, candidate = layout(tmp_path)
    previous = root / "sites-available/kace-printer"
    previous.chmod(0o640)
    before = previous.stat()
    code, _ = transaction(root, candidate, monkeypatch, fail="nginx")
    after = previous.stat()
    assert code != 0
    assert (after.st_mode, after.st_uid, after.st_gid) == (before.st_mode, before.st_uid, before.st_gid)


def test_interrupted_publication_recovers_before_retry(tmp_path, monkeypatch):
    root, candidate = layout(tmp_path)
    replace = os.replace
    def interrupt(src, dest):
        replace(src, dest)
        if Path(dest) == root / "sites-available/kace-printer":
            raise KeyboardInterrupt("simulated process stop after replacement")
    monkeypatch.setattr(os, "replace", interrupt)
    with pytest.raises(KeyboardInterrupt):
        transaction(root, candidate, monkeypatch)
    assert (root / ".kace-nginx-transaction.json").exists()
    monkeypatch.setattr(os, "replace", replace)
    code, _ = transaction(root, candidate, monkeypatch)
    assert code == 0
    assert (root / "sites-available/kace-printer").read_bytes() == candidate.read_bytes()
    assert not (root / ".kace-nginx-transaction.json").exists()


def test_unknown_main_include_layout_preserves_active_configuration(tmp_path, monkeypatch):
    root, candidate = layout(tmp_path)
    (root / "nginx.conf").write_text("events {}\nhttp {}\n")
    before = (root / "sites-available/kace-printer").read_bytes()
    code, calls = transaction(root, candidate, monkeypatch)
    assert code != 0
    assert calls == []
    assert (root / "sites-available/kace-printer").read_bytes() == before


def test_repeated_success_is_idempotent(tmp_path, monkeypatch):
    root, candidate = layout(tmp_path)
    assert transaction(root, candidate, monkeypatch)[0] == 0
    first = (root / "sites-available/kace-printer").read_bytes()
    assert transaction(root, candidate, monkeypatch)[0] == 0
    assert (root / "sites-available/kace-printer").read_bytes() == first
    assert not (root / "sites-enabled/default").exists()
