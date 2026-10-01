"""Run the seven existing real-build tests and retain their unmodified results."""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import traceback
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
MODULES = (
    "tests.regression.test_mcu_builds",
    "tests.integration.test_board_contract_real_builds",
    "tests.integration.test_printrboard_real_build",
)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")


def gate_passed(result, artifacts):
    return (result.wasSuccessful() and not result.skipped
            and not result.expectedFailures and result.testsRun == 7
            and len(artifacts) == 12)


class BuildEvidence:
    """Observe real return values; never replace builders or test assertions."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.artifacts = []

    def retain(self, artifact, record, function, resolved_config=None):
        artifact = Path(artifact)
        destination = self.directory / f"artifact-{len(self.artifacts):02d}"
        destination.mkdir()
        shutil.copyfile(artifact, destination / artifact.name)
        for extra in artifact.parent.iterdir():
            if extra.is_file() and extra.suffix in (".json", ".config"):
                shutil.copyfile(extra, destination / extra.name)
        if resolved_config is not None:
            shutil.copyfile(resolved_config, destination / "resolved.config")
        write_json(destination / "return.json", record)
        self.artifacts.append({
            "function": function,
            "file": str((destination / artifact.name).relative_to(self.directory)),
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "size": artifact.stat().st_size,
        })

    def observe(self, frame, event, value):
        if event != "return" or value is None:
            return
        source = Path(frame.f_code.co_filename).resolve()
        if (source == ROOT / "firmware/boards/kconfig.py"
                and frame.f_code.co_name == "build_board_contract_shadow"):
            self.retain(value.artifact_path, dataclasses.asdict(value),
                        "build_board_contract_shadow")
        elif (source == ROOT / "firmware/builder.py"
              and frame.f_code.co_name == "build_firmware_orchestrator"
              and isinstance(value, dict) and value.get("status") == "success"):
            record = dict(value, requested_config=frame.f_locals.get("config_dict"))
            self.retain(value["path"], record, "build_firmware_orchestrator",
                        Path(frame.f_locals["klipper_path"]) / ".config")


class Result(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.events = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.events.append({"test": test.id(), "status": "passed"})

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        self.events.append({"test": subtest.id(), "status": "passed" if err is None else "failed"})

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.events.append({"test": test.id(), "status": "skipped", "reason": reason})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    args.artifacts.mkdir(parents=True, exist_ok=True)
    evidence = BuildEvidence(args.artifacts)
    report = {"success": False, "artifacts": evidence.artifacts}
    try:
        from tests.klipper_contract import KLIPPER_REF, KLIPPER_REPO_URL
        report.update(klipper_commit=KLIPPER_REF, klipper_repository=KLIPPER_REPO_URL,
                      tested_commit=subprocess.check_output(
                          ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                      pr_head=os.environ.get("KACE_CI_HEAD_SHA"),
                      python=sys.version, tools={})
        # Fixed absolute paths exclude the simulator's /usr/local/bin/make.
        for tool in ("/usr/bin/make", "/usr/bin/arm-none-eabi-gcc", "/usr/bin/avr-gcc"):
            if not Path(tool).is_file():
                raise RuntimeError(f"Required real toolchain is unavailable: {tool}")
            report["tools"][tool] = subprocess.check_output(
                [tool, "--version"], text=True).splitlines()[0]
        os.environ.update(KACE_BOARD_CONTRACT_REAL_BUILDS="1",
                          KACE_REAL_MAKE="/usr/bin/make")
        with tempfile.TemporaryDirectory(prefix="kace-ci-klipper-") as source:
            for command in (
                ["git", "init", source],
                ["git", "-C", source, "remote", "add", "origin", KLIPPER_REPO_URL],
                ["git", "-C", source, "fetch", "--depth=1", "origin", KLIPPER_REF],
                ["git", "-C", source, "checkout", "--detach", KLIPPER_REF],
            ):
                subprocess.run(command, check=True)
            revision = subprocess.check_output(
                ["git", "-C", source, "rev-parse", "HEAD"], text=True).strip()
            dirty = subprocess.check_output(
                ["git", "-C", source, "status", "--porcelain"], text=True).strip()
            if revision != KLIPPER_REF or dirty:
                raise RuntimeError("Klipper source is not the clean pinned checkout")
            os.environ["KACE_KLIPPER_SOURCE"] = source
            suite = unittest.defaultTestLoader.loadTestsFromNames(MODULES)
            sys.setprofile(evidence.observe)
            try:
                result = unittest.TextTestRunner(verbosity=2, resultclass=Result).run(suite)
            finally:
                sys.setprofile(None)
            report.update(
                tests_run=result.testsRun, events=result.events,
                failures=[(str(test), error) for test, error in result.failures],
                errors=[(str(test), error) for test, error in result.errors],
                skips=[(str(test), reason) for test, reason in result.skipped],
                expected_failures=[(str(test), error) for test, error in result.expectedFailures],
                success=gate_passed(result, evidence.artifacts),
            )
    except Exception:
        report["gate_error"] = traceback.format_exc()
        print(report["gate_error"], file=sys.stderr)
    finally:
        write_json(args.artifacts / "results.json", report)
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
