"""Tree identity and conservative outcomes for the pinned fan preflight."""
import json
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


def test_container_worker_mismatch_is_unverified_and_isolation_is_requested(tmp_path, monkeypatch):
    image = "sha256:" + "a" * 64
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"schema": 1, "pin": preflight.PIN, "image_id": image,
                                   "dockerfile_sha256": preflight._sha(preflight._DOCKERFILE),
                                   "worker_sha256": preflight._sha(preflight._WORKER)}))
    monkeypatch.setenv("KACE_KLIPPER_PREFLIGHT_RECEIPT", str(receipt))
    monkeypatch.setattr(preflight.shutil, "which", lambda _: "docker")
    commands = []

    def run(command, _timeout):
        commands.append(command)
        if command[1:3] == ["image", "inspect"]:
            return SimpleNamespace(returncode=0, stdout=image + "\n", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="worker checksum mismatch")

    monkeypatch.setattr(preflight, "_run", run)
    result = preflight.validate_plan(plan())
    assert result.status == "unverified"
    assert "worker checksum" in result.detail
    run_command = commands[1]
    assert "--read-only" in run_command and "--network" in run_command
    assert run_command[run_command.index("--network") + 1] == "none"
    assert "--cap-drop" in run_command and "ALL" in run_command
    assert any(value.endswith(",target=/matrix,readonly") for value in run_command)
    assert image in run_command and "sha256sum -c" in run_command[-1]


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
