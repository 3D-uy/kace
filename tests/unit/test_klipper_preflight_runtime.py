"""Tree identity and conservative outcomes for the pinned fan preflight."""
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from core import klipper_preflight as preflight


def plan(root=b"[include child.cfg]\n", child=b"# child\n", artifacts=()):
    return SimpleNamespace(source_files=(("printer.cfg", root), ("child.cfg", child)),
                           artifacts=tuple(SimpleNamespace(remote_name=n, content=b) for n, b in artifacts))


def test_effective_tree_digest_covers_overrides_and_includes():
    initial = plan()
    changed = plan(child=b"# altered\n")
    replaced = plan(artifacts=(("child.cfg", b"# altered\n"),))
    assert preflight.plan_digest(initial) != preflight.plan_digest(changed)
    assert preflight.plan_digest(changed) == preflight.plan_digest(replaced)


@pytest.mark.parametrize("root", [b"[include missing.cfg]\n", b"[include ../outside.cfg]\n",
                                  b"[include *.cfg]\n"])
def test_incomplete_or_escaping_tree_cannot_be_accepted(root):
    result = preflight.validate_plan(plan(root=root))
    assert result.status == "unverified"
    assert not result.tree_digest


def test_no_docker_is_unverified(monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda _: None)
    result = preflight.validate_plan(plan())
    assert result.status == "unverified"
    assert result.tree_digest == preflight.plan_digest(plan())


def test_missing_receipt_gives_provisioning_instruction(tmp_path, monkeypatch):
    monkeypatch.setenv("KACE_KLIPPER_PREFLIGHT_RECEIPT", str(tmp_path / "missing.json"))
    monkeypatch.setattr(preflight.shutil, "which", lambda _: "docker")
    result = preflight.validate_plan(plan())
    assert result.status == "unverified"
    assert "python -m core.klipper_preflight --provision" in result.detail


@pytest.mark.parametrize("payload,status", [
    ({"valid": True, "checks": ["object_load", "fan_references"]}, "valid"),
    ({"valid": True, "checks": ["object_load"]}, "unverified"),
    ({"valid": True, "checks": ["object_load", "fan_references"], "infrastructure_error": "AIO"}, "unverified"),
    ({"valid": False, "stage": "fan_references", "checks": ["object_load"],
      "exception": "Error", "reason": "Unknown heater 'missing'"}, "invalid"),
    ({"valid": False, "stage": "object_load", "exception": "Error", "reason": "load failed"}, "unverified"),
    ({"valid": False, "stage": "fan_references", "checks": ["object_load"],
      "exception": "RuntimeError", "reason": "Unknown heater 'missing'"}, "unverified"),
    (None, "unverified"),
])
def test_only_explicit_fan_results_are_classified(payload, status):
    assert preflight._classify(payload) == status


def test_invalid_receipt_is_not_accepted(tmp_path, monkeypatch):
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"schema": 1, "pin": preflight.PIN, "image_id": "mutable:tag"}))
    monkeypatch.setenv("KACE_KLIPPER_PREFLIGHT_RECEIPT", str(receipt))
    monkeypatch.setattr(preflight.shutil, "which", lambda _: "docker")
    result = preflight.validate_plan(plan())
    assert result.status == "unverified"
    assert "receipt" in result.detail


def test_pin_mismatch_is_unverified(monkeypatch):
    monkeypatch.setattr(preflight, "load_klipper_source_contract", lambda: SimpleNamespace(validated_commit="0" * 40))
    result = preflight.validate_plan(plan())
    assert result.status == "unverified"
    assert "pin" in result.detail


@pytest.mark.parametrize("host_umask", [0o022, 0o077])
def test_container_worker_mismatch_is_unverified_and_isolation_is_requested(tmp_path, monkeypatch, host_umask):
    image = "sha256:" + "a" * 64
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"schema": 1, "pin": preflight.PIN, "image_id": image,
                                   "dockerfile_sha256": preflight._sha(preflight._DOCKERFILE),
                                   "worker_sha256": preflight._sha(preflight._WORKER)}))
    monkeypatch.setenv("KACE_KLIPPER_PREFLIGHT_RECEIPT", str(receipt))
    monkeypatch.setattr(preflight.shutil, "which", lambda _: "docker")
    commands = []
    staged_paths = []

    def run(command, _timeout):
        commands.append(command)
        if command[1:3] == ["image", "inspect"]:
            return SimpleNamespace(returncode=0, stdout=image + "\n", stderr="")
        mount = command[command.index("--mount") + 1]
        stage = Path(mount.split("source=", 1)[1].split(",target=", 1)[0])
        staged_paths.append(stage)
        assert stage.name == "input"
        assert (stage / "manifest.json").is_file()
        assert (stage / "tree/printer.cfg").read_bytes() == b"[include child.cfg]\n"
        assert (stage / "tree/child.cfg").read_bytes() == b"# child\n"
        if os.name == "posix":
            # Effective host privacy comes from the unmounted parent. The
            # container can read copies without assuming a host/container UID.
            assert stat.S_IMODE(stage.parent.stat().st_mode) == 0o700
            assert stat.S_IMODE(stage.stat().st_mode) == 0o755
            for path in stage.rglob("*"):
                assert stat.S_IMODE(path.stat().st_mode) == (0o755 if path.is_dir() else 0o644)
        return SimpleNamespace(returncode=1, stdout="", stderr="worker checksum mismatch")

    monkeypatch.setattr(preflight, "_run", run)
    original_umask = os.umask(host_umask)
    try:
        result = preflight.validate_plan(plan())
    finally:
        os.umask(original_umask)
    assert result.status == "unverified"
    assert "worker checksum" in result.detail
    run_command = commands[1]
    assert "--read-only" in run_command and "--network" in run_command
    assert run_command[run_command.index("--network") + 1] == "none"
    assert "--cap-drop" in run_command and "ALL" in run_command
    assert "--privileged" not in run_command and "--cap-add" not in run_command
    assert "--user" not in run_command
    assert run_command[run_command.index("--security-opt") + 1] == "no-new-privileges"
    assert run_command[run_command.index("--memory") + 1] == "512m"
    assert run_command[run_command.index("--cpus") + 1] == "1"
    assert run_command[run_command.index("--pids-limit") + 1] == "128"
    assert any(value.endswith(",target=/matrix,readonly") for value in run_command)
    assert image in run_command and "sha256sum -c" in run_command[-1]
    assert len(staged_paths) == 1 and not staged_paths[0].parent.exists()


def test_changed_worker_invalidates_receipt_before_container(tmp_path, monkeypatch):
    image = "sha256:" + "b" * 64
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"schema": 1, "pin": preflight.PIN, "image_id": image,
                                   "dockerfile_sha256": preflight._sha(preflight._DOCKERFILE),
                                   "worker_sha256": "0" * 64}))
    monkeypatch.setenv("KACE_KLIPPER_PREFLIGHT_RECEIPT", str(receipt))
    monkeypatch.setattr(preflight.shutil, "which", lambda _: "docker")
    monkeypatch.setattr(preflight, "_run", lambda *_: pytest.fail("must not invoke Docker"))
    assert preflight.validate_plan(plan()).status == "unverified"


@pytest.mark.parametrize("platform", ["posix", "nt"])
def test_input_permissions_fail_closed_on_posix_and_preserve_windows_acls(tmp_path, monkeypatch, platform):
    image = "sha256:" + "d" * 64
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"schema": 1, "pin": preflight.PIN, "image_id": image,
                                   "dockerfile_sha256": preflight._sha(preflight._DOCKERFILE),
                                   "worker_sha256": preflight._sha(preflight._WORKER)}))
    monkeypatch.setenv("KACE_KLIPPER_PREFLIGHT_RECEIPT", str(receipt))
    monkeypatch.setattr(preflight.shutil, "which", lambda _: "docker")
    # Replace only this engine's platform view, not pathlib/the host OS.
    monkeypatch.setattr(preflight.engine, "os", SimpleNamespace(name=platform))
    chmod_paths, commands = [], []

    def reject_chmod(path, mode, **kwargs):
        chmod_paths.append(path)
        raise PermissionError("input permissions unavailable")

    def run(command, _timeout):
        commands.append(command)
        if command[1:3] == ["image", "inspect"]:
            return SimpleNamespace(returncode=0, stdout=image + "\n", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="explicit Docker test double")

    monkeypatch.setattr(Path, "chmod", reject_chmod)
    monkeypatch.setattr(preflight, "_run", run)
    result = preflight.validate_plan(plan())
    assert result.status == "unverified"
    if platform == "posix":
        assert chmod_paths and "input permissions unavailable" in result.detail
        assert len(commands) == 1  # Image inspection only; no container started.
    else:
        assert not chmod_paths and "explicit Docker test double" in result.detail
        assert len(commands) == 2


def test_changed_staging_cannot_produce_valid_result(tmp_path, monkeypatch):
    image = "sha256:" + "c" * 64
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"schema": 1, "pin": preflight.PIN, "image_id": image,
                                   "dockerfile_sha256": preflight._sha(preflight._DOCKERFILE),
                                   "worker_sha256": preflight._sha(preflight._WORKER)}))
    monkeypatch.setenv("KACE_KLIPPER_PREFLIGHT_RECEIPT", str(receipt))
    monkeypatch.setattr(preflight.shutil, "which", lambda _: "docker")

    def run(command, _timeout):
        if command[1:3] == ["image", "inspect"]:
            return SimpleNamespace(returncode=0, stdout=image + "\n", stderr="")
        mount = next(arg for arg in command if arg.startswith("type=bind,source="))
        stage = mount.split("source=", 1)[1].split(",target=", 1)[0]
        from pathlib import Path
        (Path(stage) / "tree" / "child.cfg").write_bytes(b"changed")
        payload = {"schema_version": 1, "klipper_ref": preflight.PIN,
                   "results": {"plan": {"valid": True, "checks": ["object_load", "fan_references"]}}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(preflight, "_run", run)
    result = preflight.validate_plan(plan())
    assert result.status == "unverified"
    assert "staged configuration changed" in result.detail


@pytest.mark.parametrize("worker_result,status,detail", [
    ({"valid": False, "stage": "object_load", "reason": "Unable to parse existing variable file",
      "infrastructure_error": "Constructor requires an active reactor; offline validation is incomplete"},
     "unverified", "Constructor requires an active reactor; offline validation is incomplete"),
    ({"valid": True, "checks": ["object_load", "fan_references"], "reason": "looks good",
      "infrastructure_error": "reactor unavailable"}, "unverified", "reactor unavailable"),
    ({"valid": False, "stage": "fan_references", "checks": ["object_load"],
      "exception": "Error", "reason": "Unknown heater 'missing'"}, "invalid", "Unknown heater 'missing'"),
])
def test_worker_infrastructure_detail_is_not_hidden(tmp_path, monkeypatch, worker_result, status, detail):
    image = "sha256:" + "a" * 64
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"schema": 1, "pin": preflight.PIN, "image_id": image,
                                   "dockerfile_sha256": preflight._sha(preflight._DOCKERFILE),
                                   "worker_sha256": preflight._sha(preflight._WORKER)}))
    monkeypatch.setenv("KACE_KLIPPER_PREFLIGHT_RECEIPT", str(receipt))
    monkeypatch.setattr(preflight.shutil, "which", lambda _: "docker")

    def run(command, _timeout):
        if command[1:3] == ["image", "inspect"]:
            return SimpleNamespace(returncode=0, stdout=image + "\n", stderr="")
        payload = {"schema_version": 1, "klipper_ref": preflight.PIN,
                   "results": {"plan": worker_result}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(preflight, "_run", run)
    result = preflight.validate_plan(plan())
    assert result.status == status
    assert result.detail == detail
