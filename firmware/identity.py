"""Cryptographic identity for one concrete Klipper firmware build."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import asdict, dataclass
from typing import Mapping, Optional


IDENTITY_SCHEMA = "kace-firmware-build/v1"
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_CONFIG_RE = re.compile(r"^(CONFIG_[A-Za-z0-9_]+)=")
_CONFIG_UNSET_RE = re.compile(r"^# (CONFIG_[A-Za-z0-9_]+) is not set$")


class FirmwareIdentityError(RuntimeError):
    """Raised when a real build cannot be given a trustworthy identity."""


@dataclass(frozen=True)
class ToolchainIdentity:
    make_command: str
    make_version: str
    compiler: str
    compiler_version: str


@dataclass(frozen=True)
class FirmwareBuildInputs:
    schema: str
    build_id: str
    reported_version: str
    klipper_commit: str
    canonical_config: str
    config_sha256: str
    toolchain: ToolchainIdentity
    build_options: dict
    input_sha256: str

    @classmethod
    def create(
        cls,
        *,
        klipper_commit: str,
        canonical_config: str,
        toolchain: ToolchainIdentity,
        build_options: Optional[Mapping[str, object]] = None,
        build_id: Optional[str] = None,
    ) -> "FirmwareBuildInputs":
        commit = str(klipper_commit).strip().lower()
        if not _COMMIT_RE.fullmatch(commit):
            raise FirmwareIdentityError("Klipper commit must be an exact 40-character SHA")
        canonical = canonicalize_dot_config(canonical_config)
        options = dict(build_options or {})
        payload = {
            "schema": IDENTITY_SCHEMA,
            "klipper_commit": commit,
            "canonical_config": canonical,
            "toolchain": asdict(toolchain),
            "build_options": options,
        }
        input_sha256 = _json_sha256(payload)
        resolved_build_id = (build_id or uuid.uuid4().hex).replace("-", "").lower()
        if not re.fullmatch(r"[0-9a-f]{32}", resolved_build_id):
            raise FirmwareIdentityError("firmware build_id must contain 128 bits of hexadecimal data")
        return cls(
            schema=IDENTITY_SCHEMA,
            build_id=resolved_build_id,
            reported_version=f"kace-b1-{resolved_build_id}",
            klipper_commit=commit,
            canonical_config=canonical,
            config_sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            toolchain=toolchain,
            build_options=options,
            input_sha256=input_sha256,
        )

    def complete(
        self,
        *,
        artifact_sha256: str,
        artifact_size: int,
        artifact_format: str,
    ) -> "FirmwareBuildIdentity":
        digest = str(artifact_sha256).lower()
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise FirmwareIdentityError("firmware artifact SHA-256 is missing or invalid")
        artifact_build_id = _json_sha256({
            "schema": IDENTITY_SCHEMA,
            "build_id": self.build_id,
            "input_sha256": self.input_sha256,
            "artifact_sha256": digest,
        })
        return FirmwareBuildIdentity(
            schema=self.schema,
            build_id=self.build_id,
            reported_version=self.reported_version,
            klipper_commit=self.klipper_commit,
            canonical_config=self.canonical_config,
            config_sha256=self.config_sha256,
            toolchain=self.toolchain,
            build_options=dict(self.build_options),
            input_sha256=self.input_sha256,
            artifact_sha256=digest,
            artifact_size=int(artifact_size),
            artifact_format=str(artifact_format),
            artifact_build_id=artifact_build_id,
        )


@dataclass(frozen=True)
class FirmwareBuildIdentity:
    schema: str
    build_id: str
    reported_version: str
    klipper_commit: str
    canonical_config: str
    config_sha256: str
    toolchain: ToolchainIdentity
    build_options: dict
    input_sha256: str
    artifact_sha256: str
    artifact_size: int
    artifact_format: str
    artifact_build_id: str

    def to_dict(self) -> dict:
        return asdict(self)


def _json_sha256(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonicalize_dot_config(content: str) -> str:
    """Return a stable, order-independent representation of Kconfig values."""
    if not isinstance(content, str):
        raise FirmwareIdentityError("Klipper .config must be text")
    values: dict[str, str] = {}
    for raw_line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        match = _CONFIG_RE.match(line) or _CONFIG_UNSET_RE.match(line)
        if not match:
            continue
        key = match.group(1)
        if key in values and values[key] != line:
            raise FirmwareIdentityError(f"Klipper .config contains conflicting {key} values")
        values[key] = line
    if not values:
        raise FirmwareIdentityError("Klipper .config has no canonical Kconfig values")
    return "\n".join(values[key] for key in sorted(values)) + "\n"


def _first_version_line(command: list[str], *, cwd: str, env: Mapping[str, str]) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=dict(env),
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise FirmwareIdentityError(f"could not identify build tool {command[0]!r}: {exc}") from exc
    output = (result.stdout or result.stderr or "").strip().splitlines()
    if not output:
        raise FirmwareIdentityError(f"build tool {command[0]!r} returned no version")
    return output[0].strip()


def _compiler_for_config(canonical_config: str) -> str:
    match = re.search(r'^CONFIG_MCU="?([^"\n]+)"?$', canonical_config, re.MULTILINE)
    mcu = match.group(1) if match else ""
    return {
        "avr": "avr-gcc",
        "stm32": "arm-none-eabi-gcc",
        "lpc176x": "arm-none-eabi-gcc",
        "rp2040": "arm-none-eabi-gcc",
        "sam3": "arm-none-eabi-gcc",
        "sam4": "arm-none-eabi-gcc",
        "same70": "arm-none-eabi-gcc",
        "atsamd": "arm-none-eabi-gcc",
        "pru": "pru-gcc",
        "linux": "gcc",
        "host": "gcc",
        "esp32": "xtensa-esp32-elf-gcc",
    }.get(mcu, "gcc")


def create_build_inputs(
    *,
    klipper_path: str,
    config_path: str,
    make_command: str,
    env: Mapping[str, str],
    lto_retry: bool = False,
    build_id: Optional[str] = None,
) -> FirmwareBuildInputs:
    try:
        with open(config_path, "r", encoding="utf-8") as source:
            config_text = source.read()
    except OSError as exc:
        raise FirmwareIdentityError(f"could not read resolved Klipper .config: {exc}") from exc
    canonical = canonicalize_dot_config(config_text)
    try:
        commit_result = subprocess.run(
            ["git", "-C", klipper_path, "rev-parse", "--verify", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            env=dict(env),
        )
        commit = (commit_result.stdout or "").strip().lower()
        dirty_result = subprocess.run(
            ["git", "-C", klipper_path, "status", "--porcelain", "--untracked-files=no"],
            check=True,
            capture_output=True,
            text=True,
            env=dict(env),
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise FirmwareIdentityError(f"could not identify the Klipper source commit: {exc}") from exc
    if not _COMMIT_RE.fullmatch(commit):
        raise FirmwareIdentityError("Klipper checkout did not return an exact commit SHA")
    if (dirty_result.stdout or "").strip():
        raise FirmwareIdentityError("Klipper tracked source files are dirty; refusing ambiguous build identity")

    compiler = _compiler_for_config(canonical)
    compiler_path = shutil.which(compiler, path=env.get("PATH"))
    if not compiler_path:
        raise FirmwareIdentityError(f"required compiler {compiler!r} is unavailable")
    make_path = shutil.which(make_command, path=env.get("PATH")) or make_command
    toolchain = ToolchainIdentity(
        make_command=os.path.basename(make_path),
        make_version=_first_version_line([make_path, "--version"], cwd=klipper_path, env=env),
        compiler=compiler,
        compiler_version=_first_version_line([compiler_path, "--version"], cwd=klipper_path, env=env),
    )
    return FirmwareBuildInputs.create(
        klipper_commit=commit,
        canonical_config=canonical,
        toolchain=toolchain,
        build_options={"lto_retry": bool(lto_retry)},
        build_id=build_id,
    )
