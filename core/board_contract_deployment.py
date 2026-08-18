"""Interactive adapter for the typed Phase-4B SD deployment executor.

This module owns prompts only.  It cannot turn power on/off except from the
two direct operator menu actions, and the executor never receives the relay
controller.
"""

from __future__ import annotations

import os
from pathlib import Path

from core.mcu_monitor import McuPresenceMonitor
from core.menu import numbered_select, yes_no
from core.moonraker_deployer import JsonEventSink
from core.power_controller import (
    PowerControllerError,
    configured_manual_relay_control,
)
from firmware.boards.catalog import load_default_catalog
from firmware.boards.deployment import DeploymentPlan
from firmware.boards.executor import (
    ContractDeploymentExecutionError,
    ContractDeploymentState,
    LinuxRemovableMediaProvider,
    LinuxSafeEjector,
    MoonrakerFirmwareVerifier,
    PowerObservation,
    SdCardDeploymentExecutor,
    write_deployment_proof,
)
from firmware.boards.models import FlashStrategy


class BoardContractPhysicalDeploymentError(RuntimeError):
    def __init__(self, message, *, proof=None):
        super().__init__(message)
        self.proof = proof


def _power_observation(result) -> PowerObservation:
    return PowerObservation(
        state=result.state.value,
        timestamp=result.timestamp,
        detail=result.detail,
        requested_action=result.requested_action,
        confirmed=result.confirmed,
    )


def _show_power(result) -> None:
    print(f"\n{result.display}")
    if result.detail:
        print(f"  {result.detail}")


def _ambiguity_confirmation(assessment) -> bool:
    print("\nKACE cannot automatically prove the reenumerated MCU identity.")
    for reason in assessment.reasons:
        print(f"  - {reason}")
    print(
        "  Candidate: "
        f"{assessment.candidate.device_node}; "
        f"VID:PID={assessment.candidate.vid_pid or 'unavailable'}; "
        f"serial={assessment.candidate.serial or 'unavailable'}"
    )
    return bool(yes_no(
        "Did you physically trace the cable and verify this is the intended MCU?",
        default=False,
    ))


def _select_medium(provider: LinuxRemovableMediaProvider) -> str:
    candidates = tuple(provider.list_candidates())
    safe = tuple(item for item in candidates if not item.system_disk)
    if not safe:
        raise BoardContractPhysicalDeploymentError(
            "No non-system removable media candidate is available."
        )
    choices = []
    for item in safe:
        gib = item.size_bytes / (1024 ** 3)
        flags = []
        if not item.removable:
            flags.append("NOT REMOVABLE")
        if item.read_only:
            flags.append("READ ONLY")
        suffix = f" [{' / '.join(flags)}]" if flags else ""
        choices.append({
            "name": (
                f"{item.label or item.model or item.device_path} | {item.device_path} | "
                f"{item.filesystem or 'unknown fs'} | {gib:.2f} GiB | {item.stable_id}{suffix}"
            ),
            "value": item.stable_id,
        })
    selected = numbered_select(
        "Select the exact SD card to receive the contractual firmware:",
        choices=choices,
    )
    if not selected:
        raise BoardContractPhysicalDeploymentError("SD-card selection was cancelled")
    return str(selected)


def run_sd_card_contract_deployment(
    user_data: dict,
    plan: DeploymentPlan,
    *,
    provider=None,
    ejector=None,
    monitor=None,
    verifier=None,
    relay_control=None,
    event_sink=None,
):
    """Execute one typed plan and return its immutable DeploymentProof."""
    if not isinstance(plan, DeploymentPlan):
        raise BoardContractPhysicalDeploymentError(
            "physical BoardContract deployment requires a typed DeploymentPlan"
        )
    if plan.strategy is not FlashStrategy.SD_CARD:
        raise BoardContractPhysicalDeploymentError(
            f"strategy {plan.strategy.value} is unsupported by Phase 4B"
        )
    if os.environ.get("KACE_AUTO") == "1":
        raise BoardContractPhysicalDeploymentError(
            "physical SD deployment is forbidden in non-interactive auto mode"
        )
    mcu_path = str(user_data.get("mcu_path") or "")
    if not mcu_path:
        raise BoardContractPhysicalDeploymentError(
            "a stable configured MCU path is required before physical deployment"
        )
    catalog = load_default_catalog()
    contract = catalog.by_id(plan.board_id)
    variant = contract.variant(plan.hardware_variant_id) if contract else None
    target = variant.target(plan.build_target_id) if variant else None
    if target is None:
        raise BoardContractPhysicalDeploymentError("plan target is absent from the catalog")
    application_id = target.transport.endpoint.get("application_vid_pid", "")
    bootloader_id = target.transport.endpoint.get("bootloader_vid_pid", "")
    expected_vid_pids = (application_id,) if application_id else ()
    bootloader_vid_pids = (bootloader_id,) if bootloader_id else ()

    active_provider = provider or LinuxRemovableMediaProvider()
    selected_id = _select_medium(active_provider)
    active_monitor = monitor or McuPresenceMonitor(
        mcu_path,
        expected_vid_pids=expected_vid_pids,
        bootloader_vid_pids=bootloader_vid_pids,
        ambiguity_resolver=_ambiguity_confirmation,
    )
    host = str(user_data.get("moonraker_host") or "localhost")
    port = int(user_data.get("moonraker_port") or 7125)
    api_key = user_data.get("moonraker_api_key") or None
    executor = SdCardDeploymentExecutor(
        media_provider=active_provider,
        ejector=ejector or LinuxSafeEjector(),
        mcu_monitor=active_monitor,
        firmware_verifier=verifier or MoonrakerFirmwareVerifier(host, port, api_key),
        mcu_name=str(user_data.get("mcu_name") or "mcu"),
        catalog=catalog,
        event_sink=event_sink or JsonEventSink(),
    )
    proof_directory = str(
        user_data.get("board_contract_deployment_proof_directory")
        or Path("~/kace/deployment-proofs").expanduser()
    )
    session = None
    try:
        session = executor.prepare_media(plan, selected_media_id=selected_id)
        print("\nSD firmware copied, SHA-256 verified and safely ejected.")
        print("The workflow is WAITING_FOR_MANUAL_POWER_CYCLE.")
        print("  1. Turn the printer OFF.")
        print("  2. Insert the prepared SD card.")
        print("  3. Turn the printer ON.")
        print("  4. Explicitly confirm continuation here.")

        if relay_control is None:
            try:
                relay_control = configured_manual_relay_control(
                    host=host, port=port, api_key=api_key
                )
            except (PowerControllerError, OSError, ValueError) as exc:
                print(f"\nPrinter power: UNKNOWN\n  {exc}")
                relay_control = None

        while session.state is ContractDeploymentState.WAITING_FOR_MANUAL_POWER_CYCLE:
            if relay_control is not None:
                observed = relay_control.refresh()
                _show_power(observed)
                executor.record_power_observation(session, _power_observation(observed))
                choices = [
                    {"name": "Refresh printer power", "value": "refresh"},
                    {"name": "Turn printer OFF (manual action)", "value": "off"},
                    {"name": "Turn printer ON (manual action)", "value": "on"},
                    {"name": "I completed OFF → insert SD → ON", "value": "confirm"},
                    {"name": "Cancel this physical deployment", "value": "cancel"},
                ]
            else:
                print("\nPrinter power: UNKNOWN")
                choices = [
                    {"name": "I completed OFF → insert SD → ON", "value": "confirm"},
                    {"name": "Cancel this physical deployment", "value": "cancel"},
                ]
            action = numbered_select("Manual power-cycle control:", choices=choices)
            if action == "refresh":
                continue
            if action in {"on", "off"}:
                # These are the only two call sites which can mutate relay state,
                # and both are direct consequences of this menu choice.
                result = (
                    relay_control.request_on() if action == "on"
                    else relay_control.request_off()
                )
                _show_power(result)
                executor.record_power_observation(session, _power_observation(result))
                continue
            if action == "confirm" and yes_no(
                "Continue with MCU/Klipper verification now?", default=False
            ):
                proof = executor.confirm_manual_power_cycle(session, confirmed=True)
                path = write_deployment_proof(proof, proof_directory)
                user_data["board_contract_deployment_proof"] = proof
                user_data["board_contract_deployment_proof_path"] = path
                return proof
            if action in {"cancel", None}:
                proof = executor.cancel_at_manual_gate(
                    session, reason="physical deployment cancelled by the user"
                )
                path = write_deployment_proof(proof, proof_directory)
                user_data["board_contract_deployment_proof"] = proof
                user_data["board_contract_deployment_proof_path"] = path
                raise BoardContractPhysicalDeploymentError(
                    "physical deployment was cancelled", proof=proof
                )
    except ContractDeploymentExecutionError as exc:
        proof = getattr(exc, "proof", None)
        if proof is not None:
            path = write_deployment_proof(proof, proof_directory)
            user_data["board_contract_deployment_proof"] = proof
            user_data["board_contract_deployment_proof_path"] = path
        raise BoardContractPhysicalDeploymentError(str(exc), proof=proof) from exc
