#!/usr/bin/env python3
"""Trusted compiler argv auditor for experimental BoardContract builds."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


_LTO_FLAGS = ("-flto", "-fwhole-program", "-fno-use-linker-plugin")


def _real_compiler(command_name: str, wrapper_directory: Path) -> str:
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        directory = Path(entry).resolve()
        if directory == wrapper_directory:
            continue
        candidate = directory / command_name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    raise RuntimeError(f"real compiler {command_name!r} is unavailable")


def _is_lto_flag(argument: str) -> bool:
    return argument.startswith("-flto") or argument in _LTO_FLAGS


def _record(command: str, requested: list[str], effective: list[str]) -> None:
    destination = os.environ.get("KACE_CC_FLAGS_LOG", "")
    if not destination:
        return
    line = json.dumps(
        {"compiler": command, "requested": requested, "effective": effective},
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(descriptor, line.encode("utf-8"))
    finally:
        os.close(descriptor)


def main() -> int:
    command_name = Path(sys.argv[0]).name
    wrapper_directory = Path(sys.argv[0]).resolve().parent
    requested = list(sys.argv[1:])
    disable_lto = os.environ.get("KACE_CC_DISABLE_LTO", "0") == "1"
    effective = [item for item in requested if not (disable_lto and _is_lto_flag(item))]
    _record(command_name, requested, effective)
    compiler = _real_compiler(command_name, wrapper_directory)
    return subprocess.run([compiler, *effective], check=False).returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        raise SystemExit(f"BoardContract compiler wrapper error: {exc}")
