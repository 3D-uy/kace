#!/usr/bin/env python3
"""Build the real-build BoardContract targets through the opt-in path."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from firmware.boards.kconfig import (  # noqa: E402
    BoardContractBuildContext,
    build_board_contract_shadow,
)
from firmware.boards.catalog import load_default_catalog  # noqa: E402
from firmware.boards.deployment import (  # noqa: E402
    build_artifact_from_proof,
    create_deployment_plan,
)


TARGETS = (
    ("creality.v4.2.7", "stm32f103-ret6", "uart-usart1-pa10-pa9"),
    ("btt.skr-mini-e3.v3.0", "stm32g0b1", "usb-pa11-pa12"),
    ("mks.robin-nano.v3", "stm32f407", "usb-pa11-pa12"),
    ("btt.skr-pico.v1.0", "rp2040", "usb-native"),
    ("btt.skr-v1.4", "lpc1768", "usb-native"),
    ("btt.skr-v1.4", "lpc1769-turbo", "usb-native"),
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Experimental isolated builds for Phase 2 BoardContracts"
    )
    parser.add_argument("--source-checkout", help="Local Klipper git checkout used as clone source")
    parser.add_argument("--output", required=True, help="Directory for configs, artifacts, and proofs")
    parser.add_argument("--staging-parent", help="Parent for disposable checkout directories")
    parser.add_argument(
        "--deployment-output",
        help="Also prepare non-executing Phase-3 artifacts and DeploymentPlans",
    )
    parser.add_argument("--make", default="make", help="Real make executable")
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()

    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    summaries = []
    plans = []
    catalog = load_default_catalog()
    deployment_output = (
        Path(args.deployment_output).resolve() if args.deployment_output else None
    )
    for board_id, variant_id, target_id in TARGETS:
        proof = build_board_contract_shadow(
            board_id,
            variant_id,
            target_id,
            context=BoardContractBuildContext(
                output_directory=str(output),
                staging_parent=args.staging_parent,
                source_checkout=args.source_checkout,
                make_command=(args.make,),
                concurrency=args.jobs,
            ),
        )
        summary = proof.to_mapping()
        summary["proof_path"] = str(Path(proof.artifact_path).parent / "build-proof.json")
        summaries.append(summary)
        print(
            f"{proof.board_id}/{proof.hardware_variant_id}/{proof.build_target_id}: "
            f"{Path(proof.artifact_path).name} {proof.artifact_size} bytes "
            f"sha256={proof.artifact_sha256}",
            flush=True,
        )
        if deployment_output is not None:
            contract = catalog.by_id(proof.board_id)
            artifact = build_artifact_from_proof(proof, contract)
            plan = create_deployment_plan(
                contract,
                artifact,
                output_directory=str(deployment_output),
            )
            plans.append(plan.to_dict())
            print(
                f"  plan: {plan.strategy.value} -> "
                f"{plan.transformation.final_filename} "
                f"sha256={plan.transformation.final_sha256}",
                flush=True,
            )

    manifest = output / "build-proofs.json"
    temporary = output / ".build-proofs.json.tmp"
    temporary.write_text(
        json.dumps(summaries, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, manifest)
    print(f"proof manifest: {manifest}", flush=True)
    if deployment_output is not None:
        deployment_output.mkdir(parents=True, exist_ok=True)
        plan_manifest = deployment_output / "deployment-plans.json"
        plan_temporary = deployment_output / ".deployment-plans.json.tmp"
        plan_temporary.write_text(
            json.dumps(plans, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(plan_temporary, plan_manifest)
        print(f"deployment plan manifest: {plan_manifest}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
