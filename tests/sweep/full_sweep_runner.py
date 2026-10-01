#!/usr/bin/env python3
"""
KACE Full Klipper Config Sweep — Extended Runner
=================================================
Clones the Klipper config/ directory (sparse, shallow) using a discovered
git binary, then runs parse + generate against every generic-*.cfg and
printer-*.cfg config, then validates generated files with pinned Klipper in
Docker. Reports distinguish generation, loader, and infrastructure failures.

Usage:
    python tests/sweep/full_sweep_runner.py [--verbose]
"""

import os
import re
import sys
import subprocess
import time
import argparse
import json
import hashlib
import tempfile
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, '..', '..'))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ── Normalize stdout to UTF-8 on Windows ─────────────────────────────────────
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except (AttributeError, OSError):
    pass

from tests.sweep.result_codes import SweepResult, SweepSummary
from tests.sweep.scope_inventory import InventoryError, verify_source_inventory
from tests.klipper_contract import KLIPPER_REF, KLIPPER_REPO_URL
from core.workspace import CLONE_MINIMUM_FREE_BYTES, ensure_free_space, heavy_workspace
from core.scraper import parse_config, extract_profile_defaults
from core.generator import generate_config
from core.advanced_module_handler import is_unsupported_section
from core.capabilities import supported_kinematics
from tests.matrix.run_matrix import run_docker_validation

CONFIG_SUBDIR    = "config"
REPORT_PATH      = os.path.join(_HERE, "last_sweep_report.txt")

# ── Git binary discovery ──────────────────────────────────────────────────────
_GIT_CANDIDATES = [
    "git",
    r"C:\Program Files\Git\cmd\git.exe",
    r"C:\Program Files (x86)\Git\cmd\git.exe",
    "/usr/bin/git",
    "/usr/local/bin/git",
]

def _find_git():
    for candidate in _GIT_CANDIDATES:
        try:
            r = subprocess.run(
                [candidate, "--version"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5
            )
            if r.returncode == 0:
                return candidate
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue
    return None

GIT = _find_git()

_TODO_RE = re.compile(r'\bTODO\b', re.IGNORECASE)


# ── Git helpers ────────────────────────────────────────────────────────────────
def _run(cmd, cwd=None):
    return subprocess.run(
        cmd, cwd=cwd, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120,
    )

def _clone_klipper(target_dir):
    """Shallow sparse clone — config/ only. Returns True on success."""
    print(f"  Using git: {GIT}")
    print("  Cloning Klipper (shallow, sparse: config/ only)...")
    try:
        _run([GIT, "init", target_dir])
        _run([GIT, "remote", "add", "origin", KLIPPER_REPO_URL], cwd=target_dir)
        _run([GIT, "config", "core.sparseCheckout", "true"], cwd=target_dir)
        sparse = os.path.join(target_dir, ".git", "info", "sparse-checkout")
        with open(sparse, "w") as f:
            f.write(f"{CONFIG_SUBDIR}/\n")
        _run([GIT, "fetch", "--depth=1", "origin", KLIPPER_REF], cwd=target_dir)
        _run([GIT, "checkout", "--detach", "FETCH_HEAD"], cwd=target_dir)
        checked_out = _run([GIT, "rev-parse", "HEAD"], cwd=target_dir).stdout.strip()
        if checked_out != KLIPPER_REF:
            raise RuntimeError(
                f"Klipper checkout mismatch: expected {KLIPPER_REF}, got {checked_out}"
            )
        return True
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        subprocess.TimeoutExpired,
        RuntimeError,
    ) as exc:
        print(f"\n  \033[91m[ERROR]\033[0m Could not clone Klipper: {exc}")
        return False


# ── Config classification ──────────────────────────────────────────────────────
def _has_active_todo(parsed):
    for section, fields in parsed.items():
        if not isinstance(fields, dict):
            continue
        for val in fields.values():
            if isinstance(val, str) and _TODO_RE.search(val):
                return True
    return False

def _has_unsupported_sections(parsed):
    """Return True if any section is still gated as UNSUPPORTED.

    Delegates to advanced_module_handler.is_unsupported_section() —
    data/advanced_modules.yaml is the single source of truth.
    Sections with passthrough=True are handled by the generator.
    """
    return any(is_unsupported_section(s) for s in parsed)

def _classify_config(filename, raw, output_dir, verbose=False, *, without_display=False):
    """
    Full parse + generate pipeline for one config.
    Returns (SweepResult, generate_ok: bool, warnings: list[str])
    """
    warnings = []
    try:
        parsed = parse_config(raw, filename)
        defaults = extract_profile_defaults(parsed)

        if _has_active_todo(parsed):
            return SweepResult(SweepResult.SAFE_ABORT, filename,
                               "Active TODO placeholder pins detected"), False, warnings

        if _has_unsupported_sections(parsed):
            return SweepResult(SweepResult.UNSUPPORTED, filename,
                               "Unsupported/experimental sections present"), False, warnings

        kinematics = str(defaults.get("kinematics", "cartesian")).strip().lower()
        if kinematics not in supported_kinematics():
            return SweepResult(SweepResult.UNSUPPORTED, filename,
                               f"Unsupported kinematics: {kinematics}"), False, warnings

        # Build a minimal user_data for generation
        user_data = {
            "mcu_path":          parsed.get("mcu", {}).get("serial", "/dev/serial/by-id/TODO"),
            "kinematics":        defaults.get("kinematics", "cartesian"),
            "x_size":            defaults.get("x_size", "235"),
            "y_size":            defaults.get("y_size", "235"),
            "z_size":            defaults.get("z_size", "250"),
            "stepper_drivers":   "None (Standard)",
            "driver_type":       "None (Standard)",
            "driver_mode":       "Standalone",
            "hotend_thermistor": defaults.get("hotend_thermistor", "EPCOS 100K B57560G104F"),
            "bed_thermistor":    defaults.get("bed_thermistor", "EPCOS 100K B57560G104F"),
            "probe":             "None",
            "motors":            "4",
            "z_motors":          "1",
            "extruder":          "1",
            "runout":            "No",
            "language":          "en",
            "web_interface":     "None",
            "board":             filename,
            "printer_profile":   filename,
            "gear_ratio_x":      defaults.get("gear_ratio_x"),
            "gear_ratio_y":      defaults.get("gear_ratio_y"),
            "gear_ratio_z":      defaults.get("gear_ratio_z"),
            "gear_ratio_e":      defaults.get("gear_ratio_e"),
            "rotation_distance_x": defaults.get("rotation_distance_x"),
            "rotation_distance_y": defaults.get("rotation_distance_y"),
            "rotation_distance_z": defaults.get("rotation_distance_z"),
            "rotation_distance_e": defaults.get("rotation_distance_e"),
        }

        # This is an explicit wizard choice, not permission to ignore display
        # evidence for a selected panel. Keep the original auto-detect scenario.
        if without_display:
            user_data["display_choice"] = "none"

        out_file = os.path.join(output_dir, filename.replace(".cfg", ".out.cfg"))
        try:
            generate_config(parsed, user_data, output_path=out_file, include_macros=False)
            if not os.path.isfile(out_file) or os.path.getsize(out_file) == 0:
                raise RuntimeError("Generator did not produce a nonempty config file")
            generate_ok = True
        except Exception as gen_exc:
            generate_ok = False
            detail = f"Generation failed: {gen_exc}"
            warnings.append(detail)
            return SweepResult(SweepResult.FAILURE, filename, detail), False, warnings

        return SweepResult(SweepResult.GENERATED, filename,
                           "Generated; official validation pending"), generate_ok, warnings

    except Exception as exc:
        return SweepResult(SweepResult.FAILURE, filename, str(exc)), False, warnings


# ── Main sweep ─────────────────────────────────────────────────────────────────
def run_full_sweep(verbose=False, artifact_dir=None, *, without_display=False):
    """Generate every profile and require official validation before PASS."""
    started = time.monotonic()
    base = Path(artifact_dir) if artifact_dir is not None else Path(_HERE) / "out_cfg"
    base.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="run-", dir=base))
    records = []
    fixture = {"z_motors": "1", "probe": "None", "driver_mode": "Standalone",
               "display_choice": "none" if without_display else None,
               "qualified_boards": []}
    infrastructure_error = None
    scope_inventory = None

    try:
        if not GIT:
            raise RuntimeError("git not found; cannot fetch pinned Klipper profiles")
        with heavy_workspace("klipper-sweep-") as workspace:
            ensure_free_space(workspace, CLONE_MINIMUM_FREE_BYTES, "Klipper sweep clone")
            if not _clone_klipper(str(workspace)):
                raise RuntimeError("Could not clone pinned Klipper")
            config_dir = Path(workspace) / CONFIG_SUBDIR
            configs = sorted(path for path in config_dir.glob("*.cfg")
                             if path.name.startswith(("generic-", "printer-")))
            if not configs:
                raise RuntimeError("No official generic/printer configs found")
            scope_inventory = verify_source_inventory(config_dir)
            print(f"Full sweep: {len(configs)} profiles; Klipper {KLIPPER_REF}")
            for path in configs:
                source_digest = None
                try:
                    raw = path.read_text(encoding="utf-8")
                except (OSError, UnicodeError) as exc:
                    result = SweepResult(SweepResult.FAILURE, path.name, f"Could not read: {exc}")
                    generated, warnings = False, []
                else:
                    source_digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()
                    if source_digest != scope_inventory['source_sha256_lf'][path.name]:
                        raise InventoryError(f'Source changed after inventory verification: {path.name}')
                    result, generated, warnings = _classify_config(
                        path.name, raw, str(output), verbose, without_display=without_display)
                records.append({"filename": path.name, "code": result.code,
                                "detail": result.detail, "generated": generated,
                                "source_sha256_lf": source_digest,
                                "warnings": warnings,
                                "config_path": path.name.replace(".cfg", ".out.cfg") if generated else None})

        cases = [{"id": row["filename"], "config_path": row["config_path"],
                  "generation": {"status": "generated"}} for row in records if row["generated"]]
        manifest = {"schema_version": 1, "klipper_ref": KLIPPER_REF, "fixture": fixture,
                    "scope_inventory": scope_inventory, "cases": cases}
        manifest_path = output / "manifest.generated.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        if cases:
            print(f"Validating {len(cases)} generated configs with official Klipper (Docker)...", flush=True)
            validations, infrastructure_error = run_docker_validation(output, manifest_path)
            if not isinstance(validations, dict):
                infrastructure_error = "Malformed validator result collection"
                validations = {}
            for row in records:
                if not row["generated"]:
                    continue
                validation = validations.get(row["filename"])
                row["klipper"] = validation
                if infrastructure_error:
                    row.update(code=SweepResult.INFRA_ERROR, detail=infrastructure_error)
                elif not isinstance(validation, dict) or type(validation.get("valid")) is not bool:
                    row.update(code=SweepResult.INFRA_ERROR,
                               detail="Missing or malformed official validator result")
                elif validation["valid"]:
                    row.update(code=SweepResult.PASS,
                               detail=validation.get("reason", "Klipper loaded config"))
                else:
                    row.update(code=SweepResult.FAILURE,
                               detail="Klipper rejected config: " + validation.get("reason", "unknown error"))
    except Exception as exc:
        infrastructure_error = str(exc) or type(exc).__name__
        for row in records:
            if row["code"] == SweepResult.GENERATED:
                row.update(code=SweepResult.INFRA_ERROR, detail=infrastructure_error)

    summary = SweepSummary()
    for row in records:
        summary.add(SweepResult(row["code"], row["filename"], row["detail"]))
    successful = not infrastructure_error and summary.was_successful()
    counts = {code: summary.count(code) for code in (
        SweepResult.PASS, SweepResult.SAFE_ABORT, SweepResult.UNSUPPORTED,
        SweepResult.FAILURE, SweepResult.INFRA_ERROR, SweepResult.GENERATED)}
    payload = {"schema_version": 1, "klipper_ref": KLIPPER_REF,
               "scope_inventory": scope_inventory,
               "pipeline": "parse-generate-official-loader", "fixture": fixture, "successful": successful,
               "summary": {"total": summary.total, **counts}, "results": records,
               "infrastructure_error": infrastructure_error,
               "duration_seconds": round(time.monotonic() - started, 3)}
    report = ["KACE full sweep: parse + generate + official Klipper loader",
              f"Klipper commit: {KLIPPER_REF}",
              "Fixture: one Z, no probe, standalone drivers; not hardware qualification.",
              "Display choice: " + ("none (explicit wizard selection)" if without_display
                                   else "unspecified (original auto-detect scenario)")]
    report.extend(f"{row['code']}: {row['filename']} - {row['detail']}" for row in records)
    report.append("Summary: " + json.dumps(payload["summary"]))
    if infrastructure_error:
        report.append("INFRA_ERROR: " + infrastructure_error)
    text = "\n".join(report) + "\n"
    try:
        (output / "report.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        (output / "report.txt").write_text(text, encoding="utf-8")
        Path(REPORT_PATH).write_text(text, encoding="utf-8")
    except OSError as exc:
        print(f"Could not save sweep evidence: {exc}")
        return False
    for line in report:
        if verbose or not line.startswith(SweepResult.PASS + ":"):
            print(line)
    print(f"Sweep artifacts: {output}")
    return successful


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KACE Full Klipper Sweep")
    parser.add_argument("--verbose", action="store_true", help="Show all results")
    parser.add_argument("--artifacts", type=Path, help="Base directory for isolated run artifacts")
    parser.add_argument("--without-display", action="store_true",
                        help="Exercise the explicit no-display wizard choice; retain other guards")
    args = parser.parse_args()
    ok = run_full_sweep(verbose=args.verbose, artifact_dir=args.artifacts,
                        without_display=args.without_display)
    sys.exit(0 if ok else 1)
