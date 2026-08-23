#!/usr/bin/env python3

from core.loader import read_version as _read_version
__version__ = _read_version()

import os
import sys
import time

# ── Normalize stdout/stderr to UTF-8 (critical for Windows) ──
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except (AttributeError, OSError):
    # Python < 3.7 or non-reconfigurable streams (e.g., piped output in some CI)
    pass

# ── Early argument handling (no heavy imports needed) ─────────
# Parse the complete public CLI surface before loading heavier modules. Normal
# execution is strict; importing kace for its version/API does not consume the
# embedding process's arguments.
import argparse as _argparse
import json as _json
_ap = _argparse.ArgumentParser(
    prog="kace",
    description="Klipper Automated Configuration Ecosystem",
)
_ap.add_argument("--version", "-v", action="store_true", help="Print version and exit")
_ap.add_argument("--auto", action="store_true", help="Non-interactive mode (CI/auto deploy)")
_ap.add_argument("--dev-deploy", action="store_true", dest="dev_deploy", help="Enable dev-deploy mode")
_ap.add_argument("--debug", action="store_true", help="Enable KACE_DEBUG verbose output")
_ap.add_argument("--real-build", action="store_true", dest="real_build", help="Use the real system make binary")
_ap.add_argument(
    "--board-contract-sd-deploy",
    action="store_true",
    dest="board_contract_sd_deploy",
    help="Explicitly enable the interactive BoardContract SD-card executor",
)
_ap.add_argument(
    "--power",
    choices=("status", "on", "off", "wait"),
    help="Run one non-interactive Moonraker power operation and return JSON",
)
_known = _ap.parse_args() if __name__ == "__main__" else _ap.parse_args([])

if _known.version:
    print(f"KACE {__version__}")
    sys.exit(0)
if _known.auto:
    os.environ["KACE_AUTO"] = "1"
if _known.dev_deploy:
    os.environ["KACE_DEV_DEPLOY"] = "1"
if _known.debug:
    os.environ["KACE_DEBUG"] = "1"
if _known.real_build:
    os.environ["KACE_REAL_BUILD"] = "1"
if _known.board_contract_sd_deploy:
    if _known.auto:
        _ap.error("--board-contract-sd-deploy cannot be combined with --auto")
    os.environ["KACE_BOARD_CONTRACT_SD_DEPLOY"] = "1"

if _known.power:
    from core.power_controller import PowerControllerError, configured_power_controller

    response = {
        "ok": False,
        "available": False,
        "device": None,
        "status": "error",
        "detail": "",
    }
    try:
        controller = configured_power_controller()
        if controller is None:
            response["detail"] = "POWER_RELAY is not enabled for this KACE installation"
        else:
            response["available"] = True
            response["device"] = controller.device
            if _known.power == "status":
                status = controller.get_status()
            elif _known.power == "on":
                status = controller.power_on()
            elif _known.power == "off":
                status = controller.power_off()
            else:
                status = controller.wait_until_ready()
            response.update(ok=status != "error", status=status)
            if status == "error":
                response["detail"] = (
                    f"Moonraker power device '{controller.device}' is in error state"
                )
    except (PowerControllerError, OSError, ValueError) as exc:
        response["detail"] = str(exc)
    print(_json.dumps(response, separators=(",", ":")))
    sys.exit(0 if response["ok"] else 2)
# Resolve make command at the application boundary
_make_command = "make"
if os.environ.get("KACE_REAL_BUILD") == "1":
    if os.path.exists("/usr/bin/make"):
        _make_command = "/usr/bin/make"

from core.menu import simple_input, yes_no, numbered_select, password_input
from core.validators import questionary_pin_validator

if os.environ.get("KACE_AUTO") == "1":
    print("\n\033[93m[AUTO MODE]\033[0m User interactions disabled. Using safe defaults for all prompts.", flush=True)

from core.scraper import fetch_raw_config, parse_config
from core.wizard import run_wizard, make_pin_validator_with_collision_check, resolve_bltouch_pins
from core.exceptions import WizardExit, GenerationError
from core.style import custom_style
from core.generator import generate_config, has_todo_pins
from core.deployer import (
    deploy_config,
    deploy_usb,
    deploy_local,
    deploy_moonraker,
    deploy_firmware_installation,
    execute_firmware_deployment,
)
from core.banner import print_kace_banner
from core.translations import t
from core.display_checker import check_display_compatibility
from core.summary import print_summary
from core.display_warning import print_display_warning
from core.workflow_outcome import (
    WorkflowOutcome,
    WorkflowResult,
    cancelled,
    failed,
    pending_activation,
    success,
)
from core.outcome_renderer import print_workflow_result
from core.firmware_workflow import (
    CheckpointCorrupt,
    CheckpointIncompatible,
    FirmwareWorkflowError,
    FirmwareWorkflowState,
    artifact_evidence,
    create_checkpoint,
    extract_mcu_serial,
    load_checkpoint,
    transition_checkpoint,
    verify_reappeared_mcu,
    write_checkpoint,
)

# print_summary has been refactored into core.summary to improve testability.




def _finish(result: WorkflowResult) -> None:
    """Render the terminal outcome and preserve its stable exit-code contract."""
    print_workflow_result(result)
    raise SystemExit(result.exit_code)


def _persist_workflow(checkpoint, user_data=None):
    if user_data is not None:
        user_data["workflow_checkpoint"] = checkpoint
    write_checkpoint(checkpoint)
    return checkpoint


def _resume_firmware_workflow():
    """Return ``(checkpoint, action)`` for a valid recoverable workflow."""
    try:
        from firmware.detector import discover_mcu_hardware

        observed_hardware = discover_mcu_hardware(interactive=False)
        checkpoint = load_checkpoint(
            current_hardware=observed_hardware,
            verify_artifact=True,
        )
    except (CheckpointCorrupt, CheckpointIncompatible) as exc:
        print(f"\n\033[91m[!] Saved firmware workflow rejected safely: {exc}\033[0m")
        print("\033[93m    Start a new hardware workflow to replace the invalid checkpoint.\033[0m")
        return None, "new"
    if checkpoint is None or checkpoint["state"] == FirmwareWorkflowState.COMPLETE.value:
        return checkpoint, "new"
    if os.environ.get("KACE_AUTO") == "1":
        return checkpoint, "continue"

    state = FirmwareWorkflowState(checkpoint["state"])
    choices = []
    if state in {
        FirmwareWorkflowState.HARDWARE_SELECTED,
        FirmwareWorkflowState.COMPILE_REQUIRED,
        FirmwareWorkflowState.ARTIFACT_READY,
        FirmwareWorkflowState.AWAITING_FLASH,
        FirmwareWorkflowState.VERIFYING_MCU,
        FirmwareWorkflowState.MCU_VERIFIED,
        FirmwareWorkflowState.CONFIG_GENERATED,
        FirmwareWorkflowState.READY_TO_DEPLOY,
        FirmwareWorkflowState.DEPLOYING,
    }:
        choices.append({"name": "Continue from the last valid step", "value": "continue"})
    if checkpoint.get("artifact"):
        choices.append({"name": "Get/copy the prepared firmware", "value": "obtain"})
        choices.append({"name": "Verify MCU after flashing", "value": "verify"})
    choices.append({"name": "Compile firmware again", "value": "compile"})
    choices.append({"name": "Start a new hardware workflow", "value": "new"})
    action = numbered_select(
        f"\nSaved firmware workflow: {state.value}",
        choices=choices,
    )
    return checkpoint, action or "continue"


def _show_prepared_firmware(checkpoint):
    artifact = checkpoint.get("artifact") or {}
    print("\n\033[93m[!] Firmware flashing is still required.\033[0m")
    print(f"    Artifact: {artifact.get('path') or 'unavailable'}")
    print(f"    Final filename: {artifact.get('final_filename') or 'board-specific'}")
    for index, instruction in enumerate(artifact.get("instructions") or (), 1):
        text = instruction.get("text") if isinstance(instruction, dict) else str(instruction)
        if text:
            print(f"    {index}. {text}")
    print("    Copy the artifact using the board-specific method, power-cycle the board,")
    print("    then resume with 'Verify MCU after flashing'.")


def main():
    # ── Dashboard (bypassed in CI / auto / dev modes) ─────────
    _bypassed = os.environ.get("KACE_AUTO") == "1"
    if not _bypassed:
        # The interactive dashboard owns the complete landing-screen render,
        # including the sole banner for this execution.
        # Deferred import to optimize startup performance on slow Raspberry Pi hardware
        from core.dashboard import detect_system_state, run_dashboard
        try:
            _state = detect_system_state()
            _action = run_dashboard(_state)
        except WizardExit:
            _finish(cancelled("Dashboard cancelled."))
        if _action == "quit":
            _finish(cancelled("Dashboard closed by the user."))
    else:
        # Headless/automatic execution has no dashboard renderer.
        print_kace_banner("Klipper Automated Configuration Ecosystem")
    
    # Interactive Wizard & durable resume selection.  A compatible checkpoint
    # restores decisions after SSH/Studio/process loss; runtime objects are
    # always reconstructed or revalidated.
    workflow_checkpoint, resume_action = _resume_firmware_workflow()
    if resume_action == "obtain" and workflow_checkpoint is not None:
        _show_prepared_firmware(workflow_checkpoint)
        _finish(pending_activation("Firmware is ready to copy/flash; MCU verification is pending."))

    user_data = {"make_command": _make_command}
    if workflow_checkpoint is not None and resume_action != "new":
        user_data.update(workflow_checkpoint.get("wizard_data") or {})
        user_data["make_command"] = _make_command
        user_data["workflow_checkpoint"] = workflow_checkpoint
        if resume_action == "compile":
            workflow_checkpoint = transition_checkpoint(
                workflow_checkpoint,
                FirmwareWorkflowState.COMPILE_REQUIRED,
                user_data=user_data,
            )
            _persist_workflow(workflow_checkpoint, user_data)
        elif resume_action == "continue" and FirmwareWorkflowState(
            workflow_checkpoint["state"]
        ) is FirmwareWorkflowState.DEPLOYING:
            # A process/SSH loss during deploy leaves the remote result
            # uncertain.  Re-enter READY and let the idempotent transaction
            # verify existing files, Klipper Ready, and the firmware identity.
            workflow_checkpoint = transition_checkpoint(
                workflow_checkpoint,
                FirmwareWorkflowState.READY_TO_DEPLOY,
                user_data=user_data,
                last_error="resuming verification after an interrupted deployment",
            )
            _persist_workflow(workflow_checkpoint, user_data)
        elif resume_action == "verify" and FirmwareWorkflowState(
            workflow_checkpoint["state"]
        ) in {
            FirmwareWorkflowState.ARTIFACT_READY,
            FirmwareWorkflowState.AWAITING_FLASH,
            FirmwareWorkflowState.VERIFYING_MCU,
        }:
            if FirmwareWorkflowState(workflow_checkpoint["state"]) is FirmwareWorkflowState.ARTIFACT_READY:
                workflow_checkpoint = transition_checkpoint(
                    workflow_checkpoint, FirmwareWorkflowState.AWAITING_FLASH
                )
                _persist_workflow(workflow_checkpoint, user_data)
            try:
                workflow_checkpoint, observed = verify_reappeared_mcu(
                    workflow_checkpoint, flash_evidence=True
                )
            except FirmwareWorkflowError as exc:
                workflow_checkpoint = transition_checkpoint(
                    workflow_checkpoint,
                    FirmwareWorkflowState.AWAITING_FLASH,
                    last_error=str(exc),
                )
                _persist_workflow(workflow_checkpoint, user_data)
                _show_prepared_firmware(workflow_checkpoint)
                _finish(pending_activation(f"MCU verification is still pending: {exc}"))
            user_data["mcu_path"] = observed["mcu_path"]
            user_data["mcu_type"] = observed["derived_mcu"]
            _persist_workflow(workflow_checkpoint, user_data)
    else:
        workflow_checkpoint = None
        try:
            user_data = run_wizard(user_data)
        except WizardExit:
            _finish(cancelled("Wizard cancelled."))
        except (KeyboardInterrupt, EOFError):
            _finish(cancelled("Wizard interrupted."))
        except ImportError as e:
            print(f"\n\033[91mERROR:\033[0m {t('kace.missing_dep', error=e)}")
            print(f"\033[93m{t('kace.missing_dep_hint')}\033[0m")
            _finish(failed(WorkflowOutcome.PRECONDITION_FAILED, f"Missing dependency: {e}"))

    # ==========================================
    # PHASE 1: CONFIGURATION FETCH & DRIVER SETUP
    # ==========================================
    parsed_data = user_data.get("board_parsed")
    if not parsed_data:
        raw_cfg = fetch_raw_config(user_data['board'])
        if not raw_cfg:
            print(f"\n\033[91m[!] Board configuration could not be fetched for: '{user_data['board']}'\033[0m")
            print(f"\033[93m    This may indicate an invalid board selection or a network error.\033[0m")
            print(f"\033[93m    Please re-run KACE and select a valid board configuration.\033[0m")
            print(f"\033[2m[!] Aborting — cannot generate a configuration without board data.\033[0m")
            _finish(failed(
                WorkflowOutcome.PRECONDITION_FAILED,
                f"Board configuration could not be fetched: {user_data['board']}",
            ))
        parsed_data = parse_config(raw_cfg, user_data['board'], keep_comments=True)
        user_data["board_parsed"] = parsed_data

    # ── Validation Gate 1b: BLTouch pin resolution ──────────────────────
    # When the user selected BLTouch/CR-Touch but the board has no mapped
    # pins in the database, the template would emit '^TODO'/'TODO' into
    # active config lines and trigger a GenerationError.  Catch this early
    # and ask for the pins interactively so the workflow succeeds.
    _probe_choice = user_data.get("probe", "None")
    if _probe_choice in ("BLTouch", "CR-Touch"):
        resolve_bltouch_pins(user_data, parsed_data)

    # ── Display Compatibility Check ───────────────────────────────────────────
    # Run before generation so users can make an informed decision about
    # their display. Non-invasive: never modifies the parsed config.
    #
    # Conditional logic:
    #   display_choice == "none"         → skip entirely (user opted out of display)
    #   display_choice starts with "recommended:" and risk_accepted → skip
    #     (user already saw board-aware recommendations in the wizard)
    #   display_choice starts with "manual:" or "override:" → run check, but
    #     the wizard already showed the full risk panel; confirm only if new findings
    #   display_choice is None (auto/CI) → run full check as before
    _display_choice      = user_data.get("display_choice")
    _display_risk_accepted = user_data.get("display_risk_accepted", False)

    _skip_display_check = (
        _display_choice == "none"
        or (
            _display_choice is not None
            and _display_choice.startswith("recommended:")
            and _display_risk_accepted
        )
    )

    if not _skip_display_check:
        _display_findings = check_display_compatibility(
            parsed_data,
            printer_filename=user_data.get('printer_profile', ''),
            board_filename=user_data.get('board', ''),
        )

        # If the user made a manual/override selection in the wizard, filter findings
        # to only show truly new issues not already covered by the wizard risk panel.
        if _display_choice and (_display_choice.startswith("manual:") or _display_choice.startswith("override:")):
            chosen_section = _display_choice.split(":", 1)[1] if ":" in _display_choice else None
            if chosen_section:
                # Suppress findings for the chosen section if risk was already accepted
                _display_findings = [
                    f for f in _display_findings
                    if not (f.get("section") == chosen_section and _display_risk_accepted)
                ]

        if _display_findings:
            _should_continue = print_display_warning(_display_findings)
            if not _should_continue:
                _finish(cancelled("Display compatibility warning was declined."))

    time.sleep(0.5)
    print(f"\033[92m[*]\033[0m {t('kace.fetching_cfg_done', board=user_data['board'])}")

    # ==========================================
    # PHASE 2: FIRMWARE COMPILATION & DEPLOYMENT
    # ==========================================
    mcu = user_data.get('mcu_type')
    hint = user_data.get('mcu_hint')
    firmware_required = bool(mcu or hint == "manual")
    if firmware_required and workflow_checkpoint is None:
        try:
            workflow_checkpoint = create_checkpoint(user_data)
        except FirmwareWorkflowError as exc:
            _finish(failed(WorkflowOutcome.PRECONDITION_FAILED, str(exc)))
        _persist_workflow(workflow_checkpoint, user_data)

    workflow_state = (
        FirmwareWorkflowState(workflow_checkpoint["state"])
        if workflow_checkpoint is not None else None
    )
    run_firmware_phase = firmware_required and workflow_state in {
        FirmwareWorkflowState.HARDWARE_SELECTED,
        FirmwareWorkflowState.COMPILE_REQUIRED,
    }
    if run_firmware_phase:

        # ── Validation Gate 2: Pre-compilation TODO scan ──────────────────
        # If the parsed config already has unresolved TODO pins, compilation
        # would produce a broken printer.cfg anyway. Skip the prompt entirely
        # and explain why instead of wasting the user's time on a compile
        # that is guaranteed to fail at the generation step.
        _early_todos = has_todo_pins(parsed_data)
        if _early_todos:
            print(f"\n\033[91m[!] Firmware compilation skipped.\033[0m")
            print(f"\033[93m    Board mapping incomplete — the following required pins could not be resolved:\033[0m")
            for section, key in _early_todos:
                print(f"\033[93m      • [{section}] → {key}\033[0m")
            print(f"\033[93m    Select a specific board config instead of the stock profile, or\033[0m")
            print(f"\033[93m    configure the missing pins manually in the generated printer.cfg.\033[0m")
            print(f"\033[2m[!] Skipping firmware compilation — configuration has unresolved TODO pins.\033[0m")
            workflow_checkpoint = transition_checkpoint(
                workflow_checkpoint,
                FirmwareWorkflowState.COMPILE_REQUIRED,
                user_data=user_data,
                last_error="firmware compilation is blocked by unresolved board pins",
            )
            _persist_workflow(workflow_checkpoint, user_data)
            _finish(pending_activation(
                "Resolve the board pins, then compile firmware from the saved checkpoint."
            ))
        else:
            # Deferred import to optimize startup performance on slow Raspberry Pi hardware
            from core.firmware_wizard import run_firmware_wizard
            try:
                firmware_result = run_firmware_wizard(user_data)
            except WizardExit:
                _finish(cancelled("Firmware workflow cancelled."))
            except (KeyboardInterrupt, EOFError):
                _finish(cancelled("Firmware workflow interrupted."))
            if not isinstance(firmware_result, WorkflowResult):
                _finish(failed(
                    WorkflowOutcome.FIRMWARE_FAILED,
                    "Firmware wizard returned no typed terminal result.",
                ))
            if not firmware_result.ok:
                workflow_checkpoint = transition_checkpoint(
                    workflow_checkpoint,
                    FirmwareWorkflowState.COMPILE_REQUIRED,
                    user_data=user_data,
                    last_error=firmware_result.detail,
                )
                _persist_workflow(workflow_checkpoint, user_data)
                _finish(firmware_result)

            evidence = artifact_evidence(user_data)
            if evidence is None:
                workflow_checkpoint = transition_checkpoint(
                    workflow_checkpoint,
                    FirmwareWorkflowState.COMPILE_REQUIRED,
                    user_data=user_data,
                    last_error="firmware compilation produced no revalidatable artifact",
                )
                _persist_workflow(workflow_checkpoint, user_data)
                _finish(pending_activation(
                    "Firmware must be compiled and verified before configuration can continue."
                ))

            workflow_checkpoint = transition_checkpoint(
                workflow_checkpoint,
                FirmwareWorkflowState.ARTIFACT_READY,
                user_data=user_data,
                artifact=evidence,
            )
            _persist_workflow(workflow_checkpoint, user_data)

            physical_verified = bool(user_data.get("board_contract_deployment_proof"))
            if user_data.get("pending_firmware_deployment"):
                deployment_result = execute_firmware_deployment(user_data)
                if deployment_result is None:
                    _finish(failed(
                        WorkflowOutcome.PRECONDITION_FAILED,
                        "Firmware deployment was requested but no prepared strategy exists.",
                    ))
                if deployment_result.status.value == "CANCELLED":
                    workflow_checkpoint = transition_checkpoint(
                        workflow_checkpoint,
                        FirmwareWorkflowState.AWAITING_FLASH,
                        last_error=deployment_result.detail,
                    )
                    _persist_workflow(workflow_checkpoint, user_data)
                    _finish(cancelled(deployment_result.detail or "Firmware deployment cancelled."))
                if deployment_result.status.value in ("ACTION_REQUIRED", "MEDIA_PREPARED"):
                    workflow_checkpoint = transition_checkpoint(
                        workflow_checkpoint, FirmwareWorkflowState.AWAITING_FLASH
                    )
                    _persist_workflow(workflow_checkpoint, user_data)
                    _show_prepared_firmware(workflow_checkpoint)
                    _finish(pending_activation(
                        deployment_result.detail or "Flash the prepared firmware, then verify the MCU."
                    ))
                if not deployment_result.ok:
                    workflow_checkpoint = transition_checkpoint(
                        workflow_checkpoint,
                        FirmwareWorkflowState.AWAITING_FLASH,
                        last_error=deployment_result.detail,
                    )
                    _persist_workflow(workflow_checkpoint, user_data)
                    _finish(failed(WorkflowOutcome.FIRMWARE_FAILED, deployment_result.detail))
                physical_verified = True

            if physical_verified:
                workflow_checkpoint = transition_checkpoint(
                    workflow_checkpoint, FirmwareWorkflowState.VERIFYING_MCU
                )
                _persist_workflow(workflow_checkpoint, user_data)
                try:
                    workflow_checkpoint, observed = verify_reappeared_mcu(
                        workflow_checkpoint, flash_evidence=True
                    )
                except FirmwareWorkflowError as exc:
                    workflow_checkpoint = transition_checkpoint(
                        workflow_checkpoint,
                        FirmwareWorkflowState.AWAITING_FLASH,
                        last_error=str(exc),
                    )
                    _persist_workflow(workflow_checkpoint, user_data)
                    _finish(pending_activation(f"MCU verification is pending: {exc}"))
                user_data["mcu_path"] = observed["mcu_path"]
                user_data["mcu_type"] = observed["derived_mcu"]
                _persist_workflow(workflow_checkpoint, user_data)
            else:
                workflow_checkpoint = transition_checkpoint(
                    workflow_checkpoint, FirmwareWorkflowState.AWAITING_FLASH
                )
                _persist_workflow(workflow_checkpoint, user_data)
                _show_prepared_firmware(workflow_checkpoint)
                _finish(pending_activation(
                    "Firmware is compiled and verified, but flashing and MCU verification are pending."
                ))

    if workflow_checkpoint is not None:
        workflow_state = FirmwareWorkflowState(workflow_checkpoint["state"])
        if workflow_state not in {
            FirmwareWorkflowState.MCU_VERIFIED,
            FirmwareWorkflowState.CONFIG_GENERATED,
            FirmwareWorkflowState.READY_TO_DEPLOY,
            FirmwareWorkflowState.DEPLOYING,
            FirmwareWorkflowState.COMPLETE,
        }:
            _show_prepared_firmware(workflow_checkpoint)
            _finish(pending_activation(
                f"Firmware workflow is {workflow_state.value}; configuration deployment remains blocked."
            ))

    existing_state = FirmwareWorkflowState(workflow_checkpoint["state"]) if workflow_checkpoint else None
    if existing_state in {
        FirmwareWorkflowState.CONFIG_GENERATED,
        FirmwareWorkflowState.READY_TO_DEPLOY,
        FirmwareWorkflowState.DEPLOYING,
    } and os.path.isfile(os.path.expanduser("~/kace/printer.cfg")):
        generate_macros = bool(user_data.get("macros_generated"))
    else:
        generate_macros = yes_no(
            f"\n{t('kace.generate_macros_prompt')}",
            default=True
        )
        user_data["macros_generated"] = generate_macros

    # ==========================================
    # PHASE 3: CONFIGURATION GENERATION
    # ==========================================
    needs_generation = existing_state not in {
        FirmwareWorkflowState.CONFIG_GENERATED,
        FirmwareWorkflowState.READY_TO_DEPLOY,
        FirmwareWorkflowState.DEPLOYING,
    }
    if needs_generation:
        print(f"\033[91m[*]\033[0m {t('kace.generating_cfg')}", end="", flush=True)
        try:
            generate_config(parsed_data, user_data, include_macros=generate_macros)
        except GenerationError as gen_err:
            print(f"\r\033[91m[!]\033[0m {t('kace.generating_cfg')} FAILED")
            print(f"\n\033[91mERROR:\033[0m {gen_err}")
            if gen_err.todos:
                print("\033[93m    Unresolved TODO pins:\033[0m")
                for section, key in gen_err.todos:
                    print(f"\033[93m      • {section} → {key}\033[0m")
            print("\033[93m    Resolve the missing pins and re-run KACE.\033[0m")
            _finish(failed(WorkflowOutcome.GENERATION_FAILED, str(gen_err)))
        time.sleep(0.5)
        print(f"\r\033[92m[*]\033[0m {t('kace.generating_cfg_done')}")
    
    cfg_path = os.path.expanduser('~/kace/printer.cfg')
    generated_serial = extract_mcu_serial(cfg_path)
    if not generated_serial:
        _finish(failed(
            WorkflowOutcome.PRECONDITION_FAILED,
            "Generated printer.cfg has no active [mcu].serial; deployment is blocked.",
        ))
    if workflow_checkpoint is not None:
        verified_serial = workflow_checkpoint["hardware"].get("verified_serial_path") or ""
        if not verified_serial or generated_serial != verified_serial:
            _finish(failed(
                WorkflowOutcome.PRECONDITION_FAILED,
                "Generated [mcu].serial does not match the MCU validated after flashing.",
            ))
        state = FirmwareWorkflowState(workflow_checkpoint["state"])
        if state is FirmwareWorkflowState.MCU_VERIFIED:
            workflow_checkpoint = transition_checkpoint(
                workflow_checkpoint,
                FirmwareWorkflowState.CONFIG_GENERATED,
                user_data=user_data,
            )
            _persist_workflow(workflow_checkpoint, user_data)
            state = FirmwareWorkflowState.CONFIG_GENERATED
        if state is FirmwareWorkflowState.CONFIG_GENERATED:
            workflow_checkpoint = transition_checkpoint(
                workflow_checkpoint,
                FirmwareWorkflowState.READY_TO_DEPLOY,
                user_data=user_data,
            )
            _persist_workflow(workflow_checkpoint, user_data)
    print(f"\n\033[92mSUCCESS:\033[0m {t('kace.cfg_success', path=cfg_path)}")

    # Print Configuration Summary before deployment
    print_summary(user_data, parsed_data)

    # ==========================================
    # PHASE 4: CONFIGURATION DEPLOYMENT
    # ==========================================
    deploy_cfg = numbered_select(
        f"\n{t('kace.deploy_cfg_prompt')}",
        choices=[
            {"name": f"✅  {t('kace.deploy_none')}",       "value": "none"},
            {"name": f"📁  {t('kace.deploy_local')}",       "value": "local"},
            {"name": f"💾  {t('kace.deploy_usb')}",         "value": "usb"},
            {"name": f"🔗  {t('kace.deploy_ssh')}",         "value": "ssh"},
            {"name": f"🌐  {t('kace.deploy_moonraker')}",   "value": "moonraker"},
        ]
    )

    if deploy_cfg is None:
        _finish(cancelled("Configuration deployment selection cancelled."))

    deployment_result = None
    live_deployment = deploy_cfg in {"ssh", "moonraker"}
    if live_deployment and workflow_checkpoint is not None and FirmwareWorkflowState(
        workflow_checkpoint["state"]
    ) is not FirmwareWorkflowState.READY_TO_DEPLOY:
        _finish(failed(
            WorkflowOutcome.PRECONDITION_FAILED,
            f"Firmware workflow is {workflow_checkpoint['state']}; live deployment is blocked.",
        ))
    if deploy_cfg == "usb":
        deployment_result = deploy_usb(user_data, artifact_type="config")
    elif deploy_cfg == "local":
        deployment_result = deploy_local(user_data, artifact_type="config")
    elif deploy_cfg == "ssh":
        host = simple_input(t("kace.ssh_host_prompt"))
        if host is None or not host:
            _finish(cancelled("SSH host entry cancelled."))
        # Default SSH user is overridable via KACE_SSH_USER (e.g. "kace" for
        # KACE-installed Klipper). Falls back to the historical default "pi".
        user = simple_input(
            t("kace.ssh_user_prompt"),
            default=os.environ.get("KACE_SSH_USER", "kace")
        )
        if user is None or not user:
            _finish(cancelled("SSH user entry cancelled."))
        password = password_input(t("kace.ssh_pass_prompt"))
        if password is None:
            _finish(cancelled("SSH password entry cancelled."))
        dest_path = simple_input(t("kace.ssh_dest_prompt"), default="~/printer_data/config/")
        if dest_path is None or not dest_path:
            _finish(cancelled("SSH destination entry cancelled."))

        user_data['host'] = host
        user_data['user'] = user
        user_data['password'] = password
        user_data['dest_path'] = dest_path
        if host and user and dest_path:
            if workflow_checkpoint is not None:
                workflow_checkpoint = transition_checkpoint(
                    workflow_checkpoint, FirmwareWorkflowState.DEPLOYING
                )
                _persist_workflow(workflow_checkpoint, user_data)
            deployment_result = deploy_config(user_data)
            # Q2-04: Zero/remove password from user_data after deployment completes
            user_data.pop('password', None)
            password = None
    elif deploy_cfg == "moonraker":
        if workflow_checkpoint is not None:
            workflow_checkpoint = transition_checkpoint(
                workflow_checkpoint, FirmwareWorkflowState.DEPLOYING
            )
            _persist_workflow(workflow_checkpoint, user_data)
        deployment_result = deploy_moonraker(user_data)

    if deploy_cfg == "none":
        _finish(success("Configuration generated; deployment intentionally skipped."))
    if not isinstance(deployment_result, WorkflowResult):
        _finish(failed(
            WorkflowOutcome.DEPLOYMENT_FAILED,
            "Deployment returned no terminal result.",
        ))
    if live_deployment and workflow_checkpoint is not None:
        if deployment_result.ok:
            workflow_checkpoint = transition_checkpoint(
                workflow_checkpoint, FirmwareWorkflowState.COMPLETE
            )
        else:
            workflow_checkpoint = transition_checkpoint(
                workflow_checkpoint,
                FirmwareWorkflowState.READY_TO_DEPLOY,
                last_error=deployment_result.detail,
            )
        _persist_workflow(workflow_checkpoint, user_data)
    _finish(deployment_result)

if __name__ == "__main__":
    main()
