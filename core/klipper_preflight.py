"""Bounded fan-reference preflight using an explicitly provisioned Klipper image.

A successful result covers object loading and fan reference resolution in the
pinned image only. It does not attest the printer's Python environment, custom
extensions, MCU or physical hardware. Infrastructure failures are unverified.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile

from core.managed_config import config_includes
from firmware.boards.upstream import load_klipper_source_contract

PIN = "fe4eb8650bd7de4c2100a14eaf09b0965c430e29"
_ROOT = Path(__file__).resolve().parents[1]
_DOCKERFILE = _ROOT / "core/klipper_preflight.Dockerfile"
_WORKER = _ROOT / "core/klipper_preflight_worker.py"
_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class PreflightResult:
    status: str
    detail: str
    tree_digest: str = ""


def _files(plan):
    files = {}
    for name, content in plan.source_files:
        if content is not None:
            if name in files:
                raise ValueError("duplicate source path")
            files[name] = content
    for artifact in plan.artifacts:
        files[artifact.remote_name] = artifact.content
    if "printer.cfg" not in files:
        raise ValueError("printer.cfg missing from effective plan")
    for name, data in files.items():
        if not isinstance(name, str) or not isinstance(data, bytes):
            raise ValueError("plan file names and content must be text and bytes")
        path = PurePosixPath(name)
        if (not name or path.is_absolute() or name != path.as_posix()
                or "\\" in name or ":" in name or any(ord(c) < 32 for c in name)
                or any(part in ("", ".", "..") for part in name.split("/"))):
            raise ValueError(f"unreviewable configuration path: {name!r}")
    for name in files:
        if any(parent.as_posix() in files for parent in PurePosixPath(name).parents if str(parent) != "."):
            raise ValueError("configuration file/directory collision")
    # Check every reachable explicit include against the same tree submitted to
    # Klipper. Existing config_includes rejects absolute, glob and escaping paths.
    pending, visited = ["printer.cfg"], set()
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        for _, dependency in config_includes(files[name], name):
            if dependency not in files:
                raise ValueError(f"include missing from reviewed tree: {dependency}")
            pending.append(dependency)
    return files


def _digest(files):
    digest = sha256()
    for name, content in sorted(files.items()):
        encoded = name.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(sha256(content).digest())
    return digest.hexdigest()


def plan_digest(plan):
    return _digest(_files(plan))


def _check_staged(root, files):
    """Ensure the mounted inputs are still the exact reviewed regular files."""
    actual = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise RuntimeError("staged configuration contains a symlink")
        if path.is_file():
            actual[path.relative_to(root).as_posix()] = path.read_bytes()
        elif not path.is_dir():
            raise RuntimeError("staged configuration contains a special file")
    if actual != files:
        raise RuntimeError("staged configuration changed during preflight")


def _receipt_path():
    override = os.environ.get("KACE_KLIPPER_PREFLIGHT_RECEIPT")
    return Path(override).expanduser() if override else Path.home() / ".local/share/kace/klipper-preflight.json"


def _sha(path):
    return sha256(path.read_bytes()).hexdigest()


def _check_pin():
    if load_klipper_source_contract().validated_commit != PIN:
        raise RuntimeError("preflight image recipe does not match the configured Klipper pin")


def _run(args, timeout):
    return subprocess.run(args, text=True, encoding="utf-8", errors="replace",
                          capture_output=True, timeout=timeout, check=False)


def provision():
    """Explicitly build the pinned image and record its immutable local ID."""
    _check_pin()
    docker = shutil.which("docker")
    if not docker:
        raise RuntimeError("Docker CLI not available")
    with tempfile.TemporaryDirectory(prefix="kace-preflight-build-") as temporary:
        directory = Path(temporary)
        context = directory / "context"
        (context / "core").mkdir(parents=True)
        recipe_hash, worker_hash = _sha(_DOCKERFILE), _sha(_WORKER)
        shutil.copyfile(_DOCKERFILE, context / "core/klipper_preflight.Dockerfile")
        shutil.copyfile(_WORKER, context / "core/klipper_preflight_worker.py")
        if (_sha(context / "core/klipper_preflight.Dockerfile") != recipe_hash
                or _sha(context / "core/klipper_preflight_worker.py") != worker_hash):
            raise RuntimeError("preflight build resources changed during staging")
        iid = directory / "iid"
        build = _run([docker, "build", "--iidfile", str(iid), "--build-arg", f"KLIPPER_REF={PIN}",
                      "-f", str(context / "core/klipper_preflight.Dockerfile"), str(context)], 1800)
        if build.returncode != 0:
            raise RuntimeError("preflight image build failed: " + (build.stderr or build.stdout)[-2000:])
        image = iid.read_text(encoding="utf-8").strip()
        if not _IMAGE_ID.fullmatch(image):
            raise RuntimeError("Docker did not provide an immutable image ID")
        inspect = _run([docker, "image", "inspect", "--format", "{{.Id}}", image], 30)
        if inspect.returncode or inspect.stdout.strip() != image:
            raise RuntimeError("built image identity could not be verified")
        if _sha(_DOCKERFILE) != recipe_hash or _sha(_WORKER) != worker_hash:
            raise RuntimeError("preflight build resources changed during provisioning")
        receipt = {"schema": 1, "pin": PIN, "image_id": image,
                   "dockerfile_sha256": recipe_hash, "worker_sha256": worker_hash}
        target = _receipt_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(target.name + ".tmp")
        temp.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temp, target)
        return receipt


def _classify(result):
    if not isinstance(result, dict) or result.get("infrastructure_error"):
        return "unverified"
    if result.get("valid") is True and result.get("checks") == ["object_load", "fan_references"]:
        return "valid"
    if (result.get("valid") is False and result.get("stage") == "fan_references"
            and result.get("checks") == ["object_load"] and result.get("exception") == "Error"
            and isinstance(result.get("reason"), str)
            and (result["reason"].startswith("Unknown heater ")
                 or result["reason"].startswith("One or more of these steppers are unknown:"))):
        return "invalid"
    return "unverified"


def validate_plan(plan):
    """Validate the reviewed bytes; never reinterpret infrastructure failure as invalid."""
    try:
        files = _files(plan)
        digest = _digest(files)
    except Exception as exc:
        return PreflightResult("unverified", f"configuration tree unavailable: {exc}")
    try:
        _check_pin()
        docker = shutil.which("docker")
        if not docker:
            raise RuntimeError("Docker CLI not available")
        try:
            receipt = json.loads(_receipt_path().read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise RuntimeError(
                "preflight image is not provisioned; from the KACE directory run "
                "python -m core.klipper_preflight --provision"
            ) from exc
        image = receipt.get("image_id", "")
        if (receipt.get("schema") != 1 or receipt.get("pin") != PIN or not _IMAGE_ID.fullmatch(image)
                or receipt.get("dockerfile_sha256") != _sha(_DOCKERFILE)
                or receipt.get("worker_sha256") != _sha(_WORKER)):
            raise RuntimeError("preflight image receipt does not match runtime resources")
        inspect = _run([docker, "image", "inspect", "--format", "{{.Id}}", image], 30)
        if inspect.returncode or inspect.stdout.strip() != image:
            raise RuntimeError("provisioned image missing or identity mismatch")
        with tempfile.TemporaryDirectory(prefix="kace-preflight-") as temporary:
            stage = Path(temporary)
            for name, content in files.items():
                destination = stage / "tree" / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
            _check_staged(stage / "tree", files)
            manifest = {"klipper_ref": PIN, "cases": [{"id": "plan", "config_path": "tree/printer.cfg",
                                                          "generation": {"status": "generated"}}]}
            (stage / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            command = [docker, "run", "--rm", "--pull", "never", "--network", "none", "--cap-drop", "ALL",
                       "--security-opt", "no-new-privileges", "--read-only", "--pids-limit", "128",
                       "--memory", "512m", "--cpus", "1", "--tmpfs", "/tmp:rw,exec,nosuid,nodev",
                       "--mount", f"type=bind,source={stage.resolve()},target=/matrix,readonly", "--entrypoint", "sh",
                       image, "-c", "echo '" + _sha(_WORKER) + "  /usr/local/bin/kace-klipper-validator' | sha256sum -c >/dev/null && "
                       "cp -a /opt/klipper /tmp/klipper && "
                       "test \"$(git -C /tmp/klipper rev-parse HEAD)\" = " + PIN + " && "
                       "KLIPPER_ROOT=/tmp/klipper python -I /usr/local/bin/kace-klipper-validator "
                       "/matrix/manifest.json /tmp/result.json && cat /tmp/result.json"]
            run = _run(command, 120)
            if run.returncode:
                raise RuntimeError("isolated Klipper failed: " + (run.stderr or run.stdout)[-1000:])
            _check_staged(stage / "tree", files)
            payload = json.loads(run.stdout)
            if payload.get("schema_version") != 1 or payload.get("klipper_ref") != PIN:
                raise RuntimeError("invalid Klipper result envelope")
            results = payload.get("results")
            if not isinstance(results, dict) or set(results) != {"plan"}:
                raise RuntimeError("missing or unexpected Klipper results")
            result = results["plan"]
            status = _classify(result)
            detail = (result.get("infrastructure_error") or result.get("reason", "Klipper result unavailable")) if isinstance(result, dict) else "invalid result"
            if status == "valid":
                detail += "; fan references checked in pinned image, target extensions and hardware unverified"
            return PreflightResult(status, detail, digest)
    except Exception as exc:
        return PreflightResult("unverified", f"isolated Klipper unavailable: {exc}", digest)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provision", action="store_true", help="build the local pinned Klipper preflight image")
    args = parser.parse_args()
    if not args.provision:
        parser.error("select --provision")
    try:
        print(json.dumps(provision(), indent=2))
    except Exception as exc:
        parser.exit(1, f"preflight provisioning failed: {exc}\n")
