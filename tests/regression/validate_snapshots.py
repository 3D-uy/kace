#!/usr/bin/env python3
"""Load every golden printer config with pinned Klipper, without an MCU."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.klipper_contract import KLIPPER_REF
from tests.matrix.run_matrix import run_docker_validation


def execute(artifact_dir, fixture_dir=ROOT / "tests/fixtures"):
    artifact_dir = Path(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="run-", dir=artifact_dir))
    configs = output / "configs"
    configs.mkdir()
    cases = []
    for source in sorted(Path(fixture_dir).glob("*-expected.txt")):
        target = configs / (source.stem + ".cfg")
        shutil.copyfile(source, target)
        cases.append({"id": source.stem, "config_path": "configs/" + target.name,
                      "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                      "generation": {"status": "generated"}})
    manifest = {"schema_version": 1, "klipper_ref": KLIPPER_REF, "cases": cases}
    manifest_path = output / "manifest.generated.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    validations, error = {}, "No golden config snapshots found"
    if cases:
        try:
            validations, error = run_docker_validation(output, manifest_path)
        except Exception as exc:
            error = str(exc) or type(exc).__name__
        if not isinstance(validations, dict):
            validations, error = {}, "Malformed validator result collection"
    results = []
    for case in cases:
        result = validations.get(case["id"])
        if error:
            status, reason = "INFRA_ERROR", error
        elif not isinstance(result, dict) or type(result.get("valid")) is not bool:
            status, reason = "INFRA_ERROR", "Missing or malformed validator result"
        else:
            status = "PASS" if result["valid"] else "KLIPPER_ERROR"
            reason = result.get("reason", status)
        results.append({**case, "result": status, "reason": reason, "klipper": result})
    summary = {key: sum(row["result"] == key for row in results)
               for key in ("PASS", "KLIPPER_ERROR", "INFRA_ERROR")}
    payload = {"schema_version": 1, "klipper_ref": KLIPPER_REF,
               "successful": bool(cases) and not error and summary["PASS"] == len(cases),
               "summary": {"total": len(cases), **summary},
               "infrastructure_error": error, "results": results}
    (output / "report.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    for row in results:
        print(f"{row['result']}: {row['id']} - {row['reason']}")
    print(json.dumps(payload["summary"]))
    if error:
        print(f"INFRA_ERROR: {error}")
    print(f"Snapshot validation artifacts: {output}")
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, default=ROOT / "tests/results/snapshot-validation")
    args = parser.parse_args()
    return 0 if execute(args.artifacts)["successful"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
