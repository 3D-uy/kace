"""Load every reviewed socket/driver pair through real pinned Klipper.

No MCU connection or motion: fixture currents/mechanics are test choices.
Run with python -m tests.regression.validate_tmc_sockets --artifacts <new-dir>.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from core.configuration_review import validate_configuration_plan
from core.generator import generate_config
from core.managed_config import build_managed_config_plan
from core.tmc_socket import REVIEWED
from core.wizard.steps.hardware import _apply_z_tmc_mappings
from tests.klipper_contract import KLIPPER_REF
from tests.matrix.run_matrix import run_docker_validation
from tests.unit.test_tmc_socket import MODELS, confirm_currents, inputs


def execute(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    cases = []
    report = {"klipper_ref": KLIPPER_REF, "qualified_boards": [], "successful": False,
              "scope": "Reviewed socket wiring; root and preserved-root includes; no MCU IO",
              "cases": cases, "error": None}
    try:
        for board_name in sorted(REVIEWED):
            for model in MODELS:
                identity = board_name.removesuffix(".cfg") + "-" + model.lower()
                directory = folder / identity
                directory.mkdir()
                board, user = inputs(board_name, model)
                _apply_z_tmc_mappings(user)
                confirm_currents(board, user)
                content = generate_config(board, user, output_path=str(directory / "direct.cfg"), verbose=False)["content"]
                cases.append({"id": identity + "-direct", "config_path": identity + "/direct.cfg",
                              "generation": {"status": "generated"}})
                original_root = b"# User-owned configuration\n[gcode_macro USER_MARKER]\ngcode: G4 P0\n"
                plan = build_managed_config_plan(content.encode(), None, {"printer.cfg": original_root})
                assert validate_configuration_plan(plan).valid, identity
                remote = {artifact.remote_name: artifact.content for artifact in plan.artifacts}
                assert original_root in remote["printer.cfg"], identity
                assert b"[include kace/" in remote["printer.cfg"], identity
                assert not build_managed_config_plan(content.encode(), None, remote).changed_artifacts, identity
                for name, data in remote.items():
                    path = directory / "managed" / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                cases.append({"id": identity + "-managed", "config_path": identity + "/managed/printer.cfg",
                              "generation": {"status": "generated"}})
        assert len(cases) == 100
        manifest = folder / "manifest.json"
        manifest.write_text(json.dumps({"klipper_ref": KLIPPER_REF, "cases": cases}, indent=2), encoding="utf-8")
        results, error = run_docker_validation(folder, manifest)
        report["error"] = error
        for case in cases:
            result = results.get(case["id"])
            case["klipper"] = result
            case["result"] = ("INFRA_ERROR" if error or not isinstance(result, dict)
                              else "PASS" if result.get("valid") is True else "KLIPPER_ERROR")
        report["successful"] = not error and set(results) == {case["id"] for case in cases} and all(
            case["result"] == "PASS" for case in cases)
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "detail": str(exc)}
    report["summary"] = dict(Counter(case.get("result", "UNVALIDATED") for case in cases))
    report["sha256"] = {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in folder.rglob("*.cfg")}
    (folder / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    report = execute(args.artifacts)
    print(json.dumps({key: report[key] for key in ("successful", "summary", "error")}))
    raise SystemExit(0 if report["successful"] else 1)
