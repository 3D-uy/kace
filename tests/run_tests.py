#!/usr/bin/env python3
"""
KACE Automated Test Runner
==========================
Single-command entry point for the entire KACE test suite.

Usage:
    python3 tests/run_tests.py                  # all tests
    python3 tests/run_tests.py --verbose        # verbose output
    python3 tests/run_tests.py --update-snapshots
    python3 tests/run_tests.py --yaml-check     # boards.yaml integrity only
    python3 tests/run_tests.py --full-klipper-sweep   # 192+ config sweep (main only)
"""
import unittest
import sys
import os
import time
import argparse
from unittest.mock import MagicMock

os.environ["KACE_TESTING"] = "1"

# Reconfigure stdout/stderr to use UTF-8 on Windows to prevent UnicodeEncodeError with box drawing characters
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# Stub dependencies if not installed on host to allow running the test suite
if 'questionary' not in sys.modules:
    try:
        import questionary  # noqa: F401
    except ImportError:
        sys.modules['questionary'] = MagicMock()

if 'prompt_toolkit' not in sys.modules:
    try:
        import prompt_toolkit  # noqa: F401
    except ImportError:
        sys.modules['prompt_toolkit'] = MagicMock()
        sys.modules['prompt_toolkit.styles'] = MagicMock()


# ── Custom result/runner ───────────────────────────────────────────────────────

class KaceTestResult(unittest.TextTestResult):
    def __init__(self, stream, descriptions, verbosity):
        super().__init__(stream, descriptions, verbosity)
        self.stream       = stream
        self.verbosity    = verbosity
        self.success_count = 0
        self.failure_count = 0
        self.error_count   = 0

    def addSuccess(self, test):
        super().addSuccess(test)
        self.success_count += 1
        if self.verbosity > 0:
            self.stream.writeln(
                f"\033[92m[PASS]\033[0m {test.shortDescription() or str(test)}"
            )

    def addError(self, test, err):
        super().addError(test, err)
        self.error_count += 1
        if self.verbosity > 0:
            self.stream.writeln(
                f"\033[91m[ERROR]\033[0m {test.shortDescription() or str(test)}"
            )

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.failure_count += 1
        if self.verbosity > 0:
            self.stream.writeln(
                f"\033[91m[FAIL]\033[0m {test.shortDescription() or str(test)}"
            )

    def printErrors(self):
        if self.errors or self.failures:
            self.stream.writeln("\n" + "=" * 50)
            self.stream.writeln("\033[91mFAILED TESTS DETAILS\033[0m")
            self.stream.writeln("=" * 50)
            super().printErrors()


class KaceTestRunner(unittest.TextTestRunner):
    def _makeResult(self):
        return KaceTestResult(self.stream, self.descriptions, self.verbosity)

    def run(self, test):
        self.stream.writeln("Running KACE Test Suite...\n")
        start = time.time()
        result = super().run(test)
        elapsed = time.time() - start

        self.stream.writeln("\n" + "=" * 50)
        self.stream.writeln("RESULT:")
        self.stream.writeln(f"\033[92m{result.success_count} PASSED\033[0m")
        if result.failure_count > 0:
            self.stream.writeln(f"\033[91m{result.failure_count} FAILED\033[0m")
            self.stream.writeln("  -> Check KNOWN_FAILURES.md — compare failing test IDs against the documented list.")
            self.stream.writeln("     A new test ID not in that file is a regression, regardless of total count.")
        if result.error_count > 0:
            self.stream.writeln(f"\033[91m{result.error_count} ERRORS\033[0m")
        self.stream.writeln(f"\nTime taken: {elapsed:.2f}s")
        self.stream.writeln("=" * 50)
        return result


# ── YAML integrity check ───────────────────────────────────────────────────────

def run_yaml_check(verbose=False):
    """
    Validate data/boards.yaml schema and pattern precedence.
    Returns True on success, False on any error.
    """
    print("\n" + "=" * 50)
    print("  KACE — YAML Integrity Check")
    print("=" * 50)

    test_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(test_dir)
    yaml_path = os.path.join(root_dir, "data", "boards.yaml")

    if not os.path.exists(yaml_path):
        print(f"\033[91m[FAIL]\033[0m boards.yaml not found at: {yaml_path}")
        return False

    try:
        import yaml
    except ImportError:
        print("\033[91m[FAIL]\033[0m PyYAML not installed. Run: pip install PyYAML")
        return False

    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            db = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        print(f"\033[91m[FAIL]\033[0m YAML parse error: {exc}")
        return False

    errors = []

    # ── Check top-level keys ──────────────────────────────────────────────────
    required_keys = {"boards", "mcu_firmware"}
    missing = required_keys - set(db.keys() if db else [])
    if missing:
        errors.append(f"Missing top-level keys: {missing}")

    # ── Validate boards[] entries ─────────────────────────────────────────────
    for i, board in enumerate(db.get("boards", [])):
        if "mcu" not in board:
            errors.append(f"boards[{i}] missing 'mcu' field")
        if "search_terms" not in board:
            errors.append(f"boards[{i}] (mcu={board.get('mcu')}) missing 'search_terms'")
        if "bltouch" not in board:
            errors.append(f"boards[{i}] (mcu={board.get('mcu')}) missing 'bltouch' key")

    # ── Validate mcu_firmware[] precedence ───────────────────────────────────
    entries = db.get("mcu_firmware", [])
    for i, entry in enumerate(entries):
        if "pattern" not in entry:
            errors.append(f"mcu_firmware[{i}] missing 'pattern' field")
            continue
        if "arch" not in entry:
            errors.append(f"mcu_firmware[{i}] (pattern={entry['pattern']}) missing 'arch'")

        # Precedence: no earlier generic pattern should shadow a later specific one
        curr_pat = entry.get("pattern", "")
        for j in range(i + 1, len(entries)):
            later_pat = entries[j].get("pattern", "")
            if curr_pat and later_pat and curr_pat in later_pat:
                errors.append(
                    f"Pattern precedence violation: '{curr_pat}' at index {i} "
                    f"shadows '{later_pat}' at index {j}"
                )

    if errors:
        print(f"\033[91m[FAIL]\033[0m boards.yaml has {len(errors)} error(s):")
        for err in errors:
            print(f"  ✗  {err}")
        return False

    n_boards   = len(db.get("boards", []))
    n_firmware = len(db.get("mcu_firmware", []))
    print(f"\033[92m[PASS]\033[0m boards.yaml is valid.")
    print(f"       {n_boards} board entries, {n_firmware} firmware patterns.")
    print("=" * 50)
    return True


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="KACE Automated Test Runner")
    parser.add_argument("--verbose",            action="store_true",
                        help="Show detailed test output")
    parser.add_argument("--board",              type=str,
                        help="Run validation for a specific board (hardware testing)")
    parser.add_argument("--all-boards",         action="store_true",
                        help="Run validation for all known boards")
    parser.add_argument("--update-snapshots",   action="store_true",
                        help="Update golden regression snapshots")
    parser.add_argument("--yaml-check",         action="store_true",
                        help="Validate data/boards.yaml schema and precedence only")
    parser.add_argument("--full-klipper-sweep", action="store_true",
                        help="Clone Klipper and sweep all 192+ official configs")
    args = parser.parse_args()

    # Propagate flags to test modules via env vars
    if args.update_snapshots:
        os.environ["KACE_UPDATE_SNAPSHOTS"] = "1"
    if args.board:
        os.environ["KACE_TEST_BOARD"] = args.board
    if args.all_boards:
        os.environ["KACE_TEST_ALL_BOARDS"] = "1"

    test_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.dirname(test_dir))

    # ── YAML-only mode ────────────────────────────────────────────────────────
    if args.yaml_check:
        ok = run_yaml_check(verbose=args.verbose)
        sys.exit(0 if ok else 1)

    # ── Full Klipper sweep mode ───────────────────────────────────────────────
    if args.full_klipper_sweep:
        from tests.sweep.klipper_sweep import run_full_sweep
        ok = run_full_sweep(verbose=args.verbose)
        sys.exit(0 if ok else 1)

    # ── Standard test suite ───────────────────────────────────────────────────
    verbosity = 2 if args.verbose else 1
    loader = unittest.TestLoader()
    suite  = loader.discover(start_dir=test_dir, pattern="test_*.py")
    runner = KaceTestRunner(verbosity=verbosity)
    result = runner.run(suite)
    sys.exit(not result.wasSuccessful())


if __name__ == "__main__":
    main()
