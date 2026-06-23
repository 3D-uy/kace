"""
KACE Full Klipper Config Sweep
==============================
Clones Klipper (shallow + sparse, config/ only), iterates every
generic-*.cfg and printer-*.cfg, classifies each result, and reports.

Usage:
    python3 tests/run_tests.py --full-klipper-sweep
"""

import os
import re
import sys
import subprocess
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, '..', '..'))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tests.sweep.result_codes import SweepResult, SweepSummary
from core.advanced_module_handler import is_unsupported_section

KLIPPER_REPO_URL = "https://github.com/Klipper3d/klipper.git"
CONFIG_SUBDIR    = "config"

_TODO_RE = re.compile(r'\bTODO\b', re.IGNORECASE)


def _run(cmd, cwd=None):
    return subprocess.run(
        cmd, cwd=cwd, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def _clone_klipper(target_dir):
    """Shallow sparse clone — config/ only. Returns True on success."""
    print("  Cloning Klipper (shallow, sparse: config/ only)...")
    try:
        _run(["git", "init", target_dir])
        _run(["git", "remote", "add", "origin", KLIPPER_REPO_URL], cwd=target_dir)
        _run(["git", "config", "core.sparseCheckout", "true"], cwd=target_dir)
        sparse = os.path.join(target_dir, ".git", "info", "sparse-checkout")
        with open(sparse, "w") as f:
            f.write(f"{CONFIG_SUBDIR}/\n")
        _run(["git", "fetch", "--depth=1", "origin", "master"], cwd=target_dir)
        _run(["git", "checkout", "master"], cwd=target_dir)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"\n  \033[91m[ERROR]\033[0m Could not clone Klipper: {exc}")
        return False


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


def _classify_config(filename, raw):
    """Classify a single config file. Returns SweepResult."""
    try:
        from core.scraper import parse_config
        parsed = parse_config(raw, filename)

        if _has_active_todo(parsed):
            return SweepResult(SweepResult.SAFE_ABORT, filename,
                               "Active TODO placeholder pins detected")
        if _has_unsupported_sections(parsed):
            return SweepResult(SweepResult.UNSUPPORTED, filename,
                               "Unsupported/experimental sections present")
        return SweepResult(SweepResult.PASS, filename)

    except Exception as exc:
        return SweepResult(SweepResult.FAILURE, filename, str(exc))


def run_full_sweep(verbose=False):
    """
    Run the full Klipper config sweep. Returns True if no FAILUREs recorded.
    """
    summary = SweepSummary()

    print("\n" + "=" * 60)
    print("  KACE — Full Klipper Config Sweep")
    print("=" * 60)

    with tempfile.TemporaryDirectory(prefix="kace_sweep_") as tmpdir:
        if not _clone_klipper(tmpdir):
            print("\n\033[91mSweep aborted — could not clone Klipper.\033[0m")
            return False

        config_dir = os.path.join(tmpdir, CONFIG_SUBDIR)
        if not os.path.isdir(config_dir):
            print("\n\033[91mSweep aborted — config/ dir not found in clone.\033[0m")
            return False

        cfg_files = sorted(
            f for f in os.listdir(config_dir)
            if f.endswith(".cfg") and (
                f.startswith("generic-") or f.startswith("printer-")
            )
        )

        if not cfg_files:
            print("\n\033[91mSweep aborted — no config files found.\033[0m")
            return False

        print(f"\n  Found {len(cfg_files)} config files. Processing...\n")

        for i, fname in enumerate(cfg_files, 1):
            fpath = os.path.join(config_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    raw = f.read()
            except OSError as exc:
                result = SweepResult(SweepResult.FAILURE, fname,
                                     f"Could not read: {exc}")
            else:
                result = _classify_config(fname, raw)

            summary.add(result)

            bar = f"[{i:>3}/{len(cfg_files)}]"
            if verbose or result.code != SweepResult.PASS:
                detail = f"  ({result.detail})" if result.detail else ""
                print(f"  {bar} {result.coloured_code():<32} {fname}{detail}")
            else:
                print(".", end=("\n" if i % 10 == 0 else ""), flush=True)

        if not verbose:
            print()

    summary.print_report(verbose=verbose)
    return summary.was_successful()
