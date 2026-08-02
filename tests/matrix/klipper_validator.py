#!/usr/bin/env python3
"""Load generated configs with Klipper without connecting to an MCU."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
import traceback


KLIPPER_ROOT = Path(os.environ.get("KLIPPER_ROOT", "/opt/klipper"))
sys.path.insert(0, str(KLIPPER_ROOT / "klippy"))

import klippy  # noqa: E402
import reactor  # noqa: E402


def validate_config(config_path: Path) -> dict:
    """Run Klipper's real object loaders and unused-option validation."""
    started = time.monotonic()
    input_fd = os.open(os.devnull, os.O_RDONLY)
    printer = None
    try:
        start_args = {
            "config_file": str(config_path),
            "gcode_fd": input_fd,
            "debuginput": os.devnull,
            "software_version": os.environ.get("KLIPPER_REF", "matrix"),
            "start_reason": "matrix_validation",
        }
        printer = klippy.Printer(reactor.Reactor(), None, start_args)
        # Deliberately stop before klippy:mcu_identify. _read_config loads every
        # configured module and calls check_unused_options(), but opens no MCU.
        printer._read_config()
        return {
            "valid": True,
            "reason": "Klipper loaded all sections and options",
            "duration_seconds": round(time.monotonic() - started, 6),
        }
    except Exception as exc:  # Klipper uses several config exception classes.
        return {
            "valid": False,
            "reason": str(exc) or exc.__class__.__name__,
            "exception": exc.__class__.__name__,
            "traceback": traceback.format_exc(limit=8),
            "duration_seconds": round(time.monotonic() - started, 6),
        }
    finally:
        if printer is not None:
            try:
                printer.send_event("klippy:disconnect")
            except Exception:
                pass
        os.close(input_fd)


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: klipper_validator.py MANIFEST.json RESULTS.json", file=sys.stderr)
        return 2
    manifest_path = Path(sys.argv[1])
    results_path = Path(sys.argv[2])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    results = {}
    for case in manifest["cases"]:
        if case["generation"]["status"] != "generated":
            continue
        config_path = manifest_path.parent / case["config_path"]
        results[case["id"]] = validate_config(config_path)
    payload = {
        "schema_version": 1,
        "klipper_ref": manifest["klipper_ref"],
        "results": results,
    }
    results_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
