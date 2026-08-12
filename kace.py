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
    success,
)

# print_summary has been refactored into core.summary to improve testability.




def _finish(result: WorkflowResult) -> None:
    """Emit the stable machine-readable outcome and terminate the CLI."""
    print(result.marker(), flush=True)
    raise SystemExit(result.exit_code)


def main():
    print_kace_banner("Klipper Automated Configuration Ecosystem", __version__)
    
    # ── Dashboard (bypassed in CI / auto / dev modes) ─────────
    _bypassed = os.environ.get("KACE_AUTO") == "1"
    if not _bypassed:
        # Deferred import to optimize startup performance on slow Raspberry Pi hardware
        from core.dashboard import detect_system_state, run_dashboard
        try:
            _state = detect_system_state()
            _action = run_dashboard(_state)
        except WizardExit:
            print(f"\n\033[93m{t('kace.cancelled')}\033[0m")
            _finish(cancelled("Dashboard cancelled."))
        if _action == "quit":
            _finish(cancelled("Dashboard closed by the user."))
    
    # Interactive Wizard & Phase 1 Execution Loop
    user_data = {"make_command": _make_command}
    
    try:
        user_data = run_wizard(user_data)
    except WizardExit:
        print(f"\n\033[93m{t('kace.cancelled')}\033[0m")
        _finish(cancelled("Wizard cancelled."))
    except (KeyboardInterrupt, EOFError):
        print(f"\n\033[93m{t('kace.cancelled')}\033[0m")
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
                print(f"\n\033[93m{t('kace.cancelled')}\033[0m")
                _finish(cancelled("Display compatibility warning was declined."))

    time.sleep(0.5)
    print(f"\033[92m[*]\033[0m {t('kace.fetching_cfg_done', board=user_data['board'])}")

    # ==========================================
    # PHASE 2: FIRMWARE COMPILATION & DEPLOYMENT
    # ==========================================
    mcu = user_data.get('mcu_type')
    hint = user_data.get('mcu_hint')
    if mcu or hint == "manual":
        prompt_mcu = mcu if mcu else "manually selected board"

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
        else:
            # Deferred import to optimize startup performance on slow Raspberry Pi hardware
            from core.firmware_wizard import run_firmware_wizard
            run_firmware_wizard(user_data)

    generate_macros = yes_no(
        f"\n{t('kace.generate_macros_prompt')}",
        default=True
    )
    user_data["macros_generated"] = generate_macros

    # ==========================================
    # PHASE 3: CONFIGURATION GENERATION
    # ==========================================
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
    print(f"\n\033[92mSUCCESS:\033[0m {t('kace.cfg_success', path=cfg_path)}")

    # Print Configuration Summary before deployment
    print_summary(user_data, parsed_data)

    # Firmware build and deployment are separate. Once config exists, execute
    # the prepared strategy. When physical identity and a build fingerprint are
    # available, compose it with the verified configuration transaction.
    if user_data.get("pending_firmware_deployment"):
        from core.moonraker_deployer import DeployState
        artifact = user_data.get("firmware_artifact")
        if getattr(artifact, "firmware_identity", None) and user_data.get("mcu_path"):
            result = deploy_firmware_installation(user_data)
            if result.state is DeployState.DONE:
                print("\n\033[92m[OK] Installation completed and validated.\033[0m")
                _finish(success("Firmware and configuration installation validated."))
            print(f"\n\033[91m[!] Installation did not complete: {result.state.name}: {result.detail}\033[0m")
            if result.state in (DeployState.CANCELLED, DeployState.ABORTED):
                _finish(cancelled(result.detail or "Firmware installation cancelled."))
            if result.state is DeployState.FAILED_PRECONDITION:
                _finish(failed(WorkflowOutcome.PRECONDITION_FAILED, result.detail))
            _finish(failed(WorkflowOutcome.FIRMWARE_FAILED, result.detail or result.state.name))

        # A firmware artifact remains useful without a connected MCU or a
        # fingerprint. Execute its delivery method, then let the user choose a
        # separate configuration destination; do not claim verification.
        deployment_result = execute_firmware_deployment(user_data)
        if deployment_result is None:
            _finish(failed(
                WorkflowOutcome.PRECONDITION_FAILED,
                "Firmware deployment was requested but no prepared strategy exists.",
            ))
        if deployment_result.status.value == "CANCELLED":
            _finish(cancelled(deployment_result.detail or "Firmware deployment cancelled."))
        if not deployment_result.ok:
            print(f"\n\033[91m[!] Firmware deployment did not complete: {deployment_result.detail}\033[0m")
            _finish(failed(WorkflowOutcome.FIRMWARE_FAILED, deployment_result.detail))

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
        print(f"\n\033[93m{t('kace.cancelled')}\033[0m")
        _finish(cancelled("Configuration deployment selection cancelled."))

    deployment_result = None
    if deploy_cfg == "usb":
        deployment_result = deploy_usb(user_data, artifact_type="config")
    elif deploy_cfg == "local":
        deployment_result = deploy_local(user_data, artifact_type="config")
    elif deploy_cfg == "ssh":
        host = simple_input(t("kace.ssh_host_prompt"))
        if host is None or not host:
            print(f"\n\033[93m{t('kace.cancelled')}\033[0m")
            _finish(cancelled("SSH host entry cancelled."))
        # Default SSH user is overridable via KACE_SSH_USER (e.g. "kace" for
        # KACE-installed Klipper). Falls back to the historical default "pi".
        user = simple_input(
            t("kace.ssh_user_prompt"),
            default=os.environ.get("KACE_SSH_USER", "kace")
        )
        if user is None or not user:
            print(f"\n\033[93m{t('kace.cancelled')}\033[0m")
            _finish(cancelled("SSH user entry cancelled."))
        password = password_input(t("kace.ssh_pass_prompt"))
        if password is None:
            print(f"\n\033[93m{t('kace.cancelled')}\033[0m")
            _finish(cancelled("SSH password entry cancelled."))
        dest_path = simple_input(t("kace.ssh_dest_prompt"), default="~/printer_data/config/")
        if dest_path is None or not dest_path:
            print(f"\n\033[93m{t('kace.cancelled')}\033[0m")
            _finish(cancelled("SSH destination entry cancelled."))

        user_data['host'] = host
        user_data['user'] = user
        user_data['password'] = password
        user_data['dest_path'] = dest_path
        if host and user and dest_path:
            deployment_result = deploy_config(user_data)
            # Q2-04: Zero/remove password from user_data after deployment completes
            user_data.pop('password', None)
            password = None
    elif deploy_cfg == "moonraker":
        deployment_result = deploy_moonraker(user_data)

    if deploy_cfg == "none":
        _finish(success("Configuration generated; deployment intentionally skipped."))
    if not isinstance(deployment_result, WorkflowResult):
        _finish(failed(
            WorkflowOutcome.DEPLOYMENT_FAILED,
            "Deployment returned no terminal result.",
        ))
    _finish(deployment_result)

if __name__ == "__main__":
    main()
