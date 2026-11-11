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
from core import klipper_preflight_engine as engine
from core import studio_preflight
from firmware.boards.upstream import load_klipper_source_contract

PIN = "fe4eb8650bd7de4c2100a14eaf09b0965c430e29"
_ROOT = Path(__file__).resolve().parents[1]
_DOCKERFILE = _ROOT / "core/klipper_preflight.Dockerfile"
_WORKER = _ROOT / "core/klipper_preflight_worker.py"
_ENGINE = _ROOT / "core/klipper_preflight_engine.py"
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


_digest = engine._digest


def plan_digest(plan):
    return _digest(_files(plan))


_check_staged = engine._check_staged


def _receipt_path():
    override = os.environ.get("KACE_KLIPPER_PREFLIGHT_RECEIPT")
    return Path(override).expanduser() if override else Path.home() / ".local/share/kace/klipper-preflight.json"


_sha = engine._sha


def _check_pin():
    if load_klipper_source_contract().validated_commit != PIN:
        raise RuntimeError("preflight image recipe does not match the configured Klipper pin")


def _run(args, timeout):
    return subprocess.run(args, text=True, encoding="utf-8", errors="replace",
                          capture_output=True, timeout=timeout, check=False,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def provision():
    """Explicitly build the pinned image and record its immutable local ID."""
    _check_pin()
    return engine.provision(pin=PIN, recipe=_DOCKERFILE, worker=_WORKER,
                            receipt_path=_receipt_path(), run=_run, sha=_sha, which=shutil.which)


_classify = engine._classify


def _studio_identity():
    """Bind the bridge to canonical Git/LF resources, independent of checkout EOL."""
    return {
        "pin": PIN,
        **{key: sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
           for key, path in (("engine_sha256", _ENGINE), ("dockerfile_sha256", _DOCKERFILE),
                             ("worker_sha256", _WORKER))},
    }


def validate_plan(plan):
    """Validate the reviewed bytes; never reinterpret infrastructure failure as invalid."""
    try:
        files = _files(plan)
        digest = _digest(files)
    except Exception as exc:
        return PreflightResult("unverified", f"configuration tree unavailable: {exc}")
    try:
        _check_pin()
        if studio_preflight.configured():
            # Any bridge environment selects Studio, including partial settings.
            # A lost session or malformed receipt must never select Pi Docker.
            result = studio_preflight.validate_files(files, _studio_identity(), digest)
            return PreflightResult(**result)
        result = engine.validate_files(files, pin=PIN, recipe=_DOCKERFILE, worker=_WORKER,
                                       receipt_path=_receipt_path(), run=_run, sha=_sha,
                                       which=shutil.which, check_staged=_check_staged)
        return PreflightResult(**result)
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
