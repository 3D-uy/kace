#!/usr/bin/env python3
"""
KACE Full Klipper Config Sweep — Extended Runner
=================================================
Clones the Klipper config/ directory (sparse, shallow) using a discovered
git binary, then runs parse + generate against every generic-*.cfg and
printer-*.cfg config. Saves a full report to tests/sweep/last_sweep_report.txt.

Usage:
    python tests/sweep/full_sweep_runner.py [--verbose]
"""

import os
import re
import sys
import subprocess
import tempfile
import time
import datetime
import argparse

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
from core.scraper import parse_config, extract_profile_defaults
from core.generator import generate_config

KLIPPER_REPO_URL = "https://github.com/Klipper3d/klipper.git"
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

# ── Sections KACE doesn't support yet (generates UNSUPPORTED rather than FAIL) 
_UNSUPPORTED_SECTIONS = {
    "resonance_tester", "adxl345", "lis2dw", "mpu9250",
    "sx1509", "pca9685", "dotstar", "neopixel", "palette2",
}

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
        _run([GIT, "fetch", "--depth=1", "origin", "master"], cwd=target_dir)
        _run([GIT, "checkout", "master"], cwd=target_dir)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
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
    for section in parsed:
        for unsup in _UNSUPPORTED_SECTIONS:
            if unsup in section.lower():
                return True
    return False

def _classify_config(filename, raw, output_dir, verbose=False):
    """
    Full parse + generate pipeline for one config.
    Returns (SweepResult, generate_ok: bool, warnings: list[str])
    """
    warnings = []
    try:
        parsed = parse_config(raw, filename)
        extract_profile_defaults(parsed)

        if _has_active_todo(parsed):
            return SweepResult(SweepResult.SAFE_ABORT, filename,
                               "Active TODO placeholder pins detected"), False, warnings

        if _has_unsupported_sections(parsed):
            return SweepResult(SweepResult.UNSUPPORTED, filename,
                               "Unsupported/experimental sections present"), False, warnings

        # Build a minimal user_data for generation
        defaults = extract_profile_defaults(parsed)
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

        out_file = os.path.join(output_dir, filename.replace(".cfg", ".out.cfg"))
        try:
            generate_config(parsed, user_data, output_path=out_file, include_macros=False)
            generate_ok = True
        except SystemExit:
            generate_ok = False
            warnings.append("generate_config hit sys.exit (TODO pins in output)")
        except Exception as gen_exc:
            generate_ok = False
            warnings.append(f"generate_config error: {gen_exc}")

        return SweepResult(SweepResult.PASS, filename), generate_ok, warnings

    except SystemExit:
        return SweepResult(SweepResult.SAFE_ABORT, filename, "sys.exit during parse"), False, warnings
    except Exception as exc:
        return SweepResult(SweepResult.FAILURE, filename, str(exc)), False, warnings


# ── Main sweep ─────────────────────────────────────────────────────────────────
def run_full_sweep(verbose=False):
    summary   = SweepSummary()
    gen_fails = []
    lines     = []  # for the saved report

    def log(msg="", end="\n"):
        print(msg, end=end, flush=True)
        lines.append(msg + end)

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log(f"\n{'=' * 64}")
    log(f"  KACE — Full Klipper Config Sweep")
    log(f"  Run at: {timestamp}")
    log(f"{'=' * 64}")

    if not GIT:
        log("\033[91m[ERROR]\033[0m git not found. Cannot clone Klipper.")
        log("Install Git for Windows from https://git-scm.com/")
        return False

    with tempfile.TemporaryDirectory(prefix="kace_sweep_") as tmpdir:
        output_dir = os.path.join(tmpdir, "generated")
        os.makedirs(output_dir, exist_ok=True)

        if not _clone_klipper(tmpdir):
            log("\n\033[91mSweep aborted — could not clone Klipper.\033[0m")
            return False

        config_dir = os.path.join(tmpdir, CONFIG_SUBDIR)
        if not os.path.isdir(config_dir):
            log("\n\033[91mSweep aborted — config/ dir not found in clone.\033[0m")
            return False

        cfg_files = sorted(
            f for f in os.listdir(config_dir)
            if f.endswith(".cfg") and (
                f.startswith("generic-") or f.startswith("printer-")
            )
        )

        if not cfg_files:
            log("\n\033[91mSweep aborted — no config files found.\033[0m")
            return False

        n = len(cfg_files)
        log(f"\n  Found {n} config files. Processing...\n")
        start = time.time()

        for i, fname in enumerate(cfg_files, 1):
            fpath = os.path.join(config_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    raw = f.read()
            except OSError as exc:
                result = SweepResult(SweepResult.FAILURE, fname, f"Could not read: {exc}")
                gen_ok, warns = False, []
            else:
                result, gen_ok, warns = _classify_config(fname, raw, output_dir, verbose)

            summary.add(result)
            if result.code == SweepResult.PASS and not gen_ok:
                gen_fails.append((fname, warns))

            bar    = f"[{i:>3}/{n}]"
            detail = f"  ({result.detail})" if result.detail else ""
            gen_tag = "" if gen_ok else "  [!gen]"
            line = f"  {bar} {result.coloured_code():<32} {fname}{detail}{gen_tag}"

            if verbose or result.code != SweepResult.PASS or not gen_ok:
                log(line)
            else:
                print(".", end=("\n" if i % 10 == 0 else ""), flush=True)
                lines.append(".")

        if not verbose:
            log()

        elapsed = time.time() - start
        log(f"\n  Sweep completed in {elapsed:.1f}s")

    # ── Final report ─────────────────────────────────────────────────────────
    log(f"\n{'=' * 64}")
    log("  KACE — Full Klipper Config Sweep Report")
    log(f"{'=' * 64}")
    log(f"  Total configs processed  : {summary.total}")
    log(f"  \033[92m[PASS]       \033[0m           : {summary.passes}")
    log(f"  \033[93m[SAFE_ABORT] \033[0m           : {summary.safe_aborts}")
    log(f"  \033[96m[UNSUPPORTED]\033[0m           : {summary.unsupported}")
    log(f"  \033[91m[FAILURE]    \033[0m           : {summary.failures}")
    log(f"  Generation warnings      : {len(gen_fails)}")
    log(f"{'=' * 64}")

    if summary.failures > 0:
        log("\n\033[91mFAILED CONFIGS (crashes — bugs to fix):\033[0m")
        for r in summary.results:
            if r.code == SweepResult.FAILURE:
                log(f"  [FAIL] {r.filename}")
                if r.detail:
                    log(f"         {r.detail}")

    if gen_fails:
        log("\n[WARN] GENERATION WARNINGS (parsed OK but output had issues):")
        for fname, warns in gen_fails:
            log(f"  [!]  {fname}")
            for w in warns:
                log(f"       {w}")

    # Save clean report (strip ANSI)
    ansi_re = re.compile(r'\033\[[0-9;]*m')
    clean_lines = [ansi_re.sub("", l) for l in lines]
    try:
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            f.writelines(clean_lines)
        print(f"\n  Report saved → {REPORT_PATH}")
    except Exception as e:
        print(f"\n  (Could not save report: {e})")

    return summary.failures == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KACE Full Klipper Sweep")
    parser.add_argument("--verbose", action="store_true", help="Show all results")
    args = parser.parse_args()
    ok = run_full_sweep(verbose=args.verbose)
    sys.exit(0 if ok else 1)
