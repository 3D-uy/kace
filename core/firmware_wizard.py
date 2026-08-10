import sys
from core.menu import simple_input, yes_no, numbered_select
from core.validators import (
    questionary_arch_validator,
    questionary_hex_offset_validator,
    questionary_processor_validator,
)
from core.translations import t
from core.terminal import BOLD, INFO, RESET, WARNING
from core.exceptions import DerivationAmbiguityError
from core.capabilities import validate_firmware_processor_for_architecture
from firmware.derivation import derive_config
from firmware.configuration import (
    BootloaderOffset,
    FirmwareConfigurationError,
    bootloader_offset_from_config,
    render_config_diff,
    validate_firmware_configuration,
)
from firmware.builder import build_firmware_orchestrator, BuildContext
from firmware.artifacts import BuildArtifact
from firmware.deployment import (
    DeploymentMethodId,
    DeploymentTarget,
    FirmwareDeploymentService,
    deployment_artifact_blockers,
)


def _read_deployment_usb_identity(device_path):
    """Best-effort current USB facts; absence disables automatic flashing."""
    if not device_path:
        return {}
    from core.mcu_monitor import McuIdentityReader, McuMonitorError

    try:
        identity = McuIdentityReader().read(device_path)
    except (McuMonitorError, OSError):
        return {}
    if identity is None:
        return {}
    return {
        "usb_vid": identity.vendor_id,
        "usb_pid": identity.model_id,
        "usb_path": identity.physical_path,
    }


def _cancel_firmware_configuration():
    print(f"\n\033[93m{t('kace.cancelled')}\033[0m")
    sys.exit(0)


def _is_back(value):
    return str(value or "").strip().lower() in ("<", "back", "volver")


def _processor_validator_for_architecture(architecture: str):
    def _validate(value):
        text = str(value or "").strip()
        if _is_back(text):
            return True
        if not text:
            return "Processor is required after changing architecture."
        try:
            validate_firmware_processor_for_architecture(text, architecture)
            return True
        except ValueError as exc:
            return str(exc)

    return _validate


def _resolve_firmware_configuration(current_mcu, current_hint, resolved_flash=None):
    """Resolve every dependent field and return one validated configuration."""
    while True:
        try:
            config = derive_config(
                current_mcu,
                current_hint,
                flash_start=resolved_flash,
            )
            validate_firmware_configuration(config, processor=current_mcu)
            return config, current_mcu, current_hint
        except DerivationAmbiguityError as ambig:
            if ambig.param == "mcu_family":
                choices = ambig.options + ["Enter manually"]
                answer = numbered_select(
                    f"Select MCU architecture family for {current_mcu if current_mcu else 'Board'}:",
                    choices=choices,
                )
                if answer == "Enter manually" or answer is None:
                    answer = simple_input(
                        "Enter Klipper ARCH (e.g. stm32)",
                        validate=questionary_arch_validator,
                    )
                if not answer:
                    _cancel_firmware_configuration()
                current_mcu = answer
                resolved_flash = None
            elif ambig.param == "bootloader_offset":
                options = ambig.options
                choices = list(options.keys()) + ["No bootloader (0x0)", "Enter manually"]
                answer = numbered_select(
                    f"Select bootloader offset for {current_mcu.upper()}:",
                    choices=choices,
                )
                if answer == "Enter manually":
                    answer = simple_input(
                        "Enter HEX offset (e.g. 0x8000)",
                        validate=questionary_hex_offset_validator,
                    )
                elif answer == "No bootloader (0x0)" or answer is None:
                    answer = "0x0"
                else:
                    answer = options.get(answer, "0x0")
                resolved_flash = BootloaderOffset.from_value(answer)
            elif ambig.param == "comm_interface":
                answer = numbered_select(
                    f"Select the communication interface for {(current_mcu or 'Board').upper()}:",
                    choices=ambig.options,
                )
                if not answer:
                    _cancel_firmware_configuration()
                current_hint = answer.lower()

def run_firmware_wizard(user_data: dict):
    """Interactively configure, compile and deploy Klipper firmware for the target MCU."""
    mcu = user_data.get('mcu_type')
    hint = user_data.get('mcu_hint')
    if not (mcu or hint == "manual"):
        print(f"\n\033[93m{t('kace.skip_firmware')}\033[0m")
        return

    prompt_mcu = mcu if mcu else "manually selected board"
    ans = yes_no(t("kace.compile_prompt", mcu=prompt_mcu))
    if not ans:
        print(f"\n\033[93m{t('kace.skip_firmware')}\033[0m")
        return

    # ── 1. Resolve firmware configuration interactively (derivation prompts) ──
    current_mcu = mcu
    current_hint = hint
    config_dict, current_mcu, current_hint = _resolve_firmware_configuration(
        current_mcu, current_hint
    )
    initial_config = dict(config_dict)

    # ── 2. Run the interactive compile summary wizard ──
    def format_flash(f):
        if f is None:
            return "N/A"
        mapping = {
            "0x0": t("builder.boot_no"),
            "0x2000": t("builder.boot_8k"),
            "0x4000": t("builder.boot_16k"),
            "0x7000": t("builder.boot_28k"),
            "0x8000": t("builder.boot_32k"),
            "0x10000": t("builder.boot_64k"),
            "0x20000": t("builder.boot_128k")
        }
        return f"{mapping[f]} ({f})" if f in mapping else f

    _B = BOLD
    _C = INFO
    _Y = WARNING
    _R = RESET
    _M = INFO

    while True:
        arch = config_dict.get("CONFIG_MCU", "Unknown").replace('"', '')
        model = current_mcu if current_mcu else "Unknown"
        flash = config_dict.get("CONFIG_FLASH_START")
        comm = "USB" if config_dict.get("CONFIG_USB") == "y" else \
               "CAN" if config_dict.get("CONFIG_CANBUS") == "y" else \
               "UART" if config_dict.get("CONFIG_SERIAL") == "y" else \
               "SPI" if config_dict.get("CONFIG_SPI") == "y" else "Unknown"

        _SEP = "═" * 47
        def _fw_row(label, value):
            pad = " " * max(0, 30 - len(label))
            return f"  {_B}{_C}{label}{_R}{pad}: {_Y}{value}{_R}"

        print(f"\n  {_C}{_SEP}{_R}")
        print(f"  {_B}{_M}  {t('builder.summary_title')}{_R}")
        print(f"  {_C}{_SEP}{_R}")
        print(_fw_row(t("builder.architecture"),           arch.upper()))
        print(_fw_row(t("builder.processor"),              model.upper()))
        print(_fw_row(t("builder.bootloader"),             format_flash(flash)))
        print(_fw_row(t("builder.comm_interface"),         comm))

        clock = config_dict.get("CONFIG_CLOCK_FREQ")
        if clock:
            print(_fw_row(t("builder.clock"), f"{int(clock)//1000000} MHz"))

        mcu_path = user_data.get('mcu_path')
        print(_fw_row(t("builder.usb_path"),    mcu_path if mcu_path else t("builder.not_detected")))
        print(f"  {_C}{_SEP}{_R}\n")

        choices = [
            t("builder.compile_now"),
            t("builder.edit_arch"),
            t("builder.edit_proc"),
        ]
        if flash is not None:
            choices.append(t("builder.edit_boot"))
        choices.append(t("builder.edit_comm"))
        if clock:
            choices.append(t("builder.edit_clock"))
        choices.append(t("builder.abort"))

        ans_summary = numbered_select(t("builder.config_correct"), choices=choices)

        if ans_summary == t("builder.compile_now"):
            try:
                validate_firmware_configuration(config_dict, processor=current_mcu)
            except FirmwareConfigurationError as exc:
                print(f"\n\033[91mERROR:\033[0m {exc}")
                continue
            diff = render_config_diff(initial_config, config_dict)
            print("\n\033[96m[*]\033[0m Firmware configuration diff:")
            print(diff or "(no changes from derived configuration)")
            break
        elif ans_summary == t("builder.abort") or ans_summary is None:
            print(f"\n\033[93m{t('kace.cancelled')}\033[0m")
            sys.exit(0)
        elif ans_summary == t("builder.edit_arch"):
            new_arch = simple_input(t("builder.enter_arch"), default=arch, validate=questionary_arch_validator)
            if not _is_back(new_arch) and new_arch and new_arch != arch:
                new_model = simple_input(
                    t("builder.enter_proc"),
                    default="",
                    validate=_processor_validator_for_architecture(new_arch),
                )
                if not _is_back(new_model) and new_model:
                    try:
                        validate_firmware_processor_for_architecture(new_model, new_arch)
                        config_dict, current_mcu, current_hint = _resolve_firmware_configuration(
                            new_model, current_hint, None
                        )
                    except (FirmwareConfigurationError, ValueError) as exc:
                        print(f"\n\033[91mERROR:\033[0m {exc}")
        elif ans_summary == t("builder.edit_proc"):
            new_model = simple_input(
                t("builder.enter_proc"), default=model, validate=questionary_processor_validator
            )
            if not _is_back(new_model) and new_model and new_model != current_mcu:
                try:
                    config_dict, current_mcu, current_hint = _resolve_firmware_configuration(
                        new_model, current_hint, None
                    )
                except (FirmwareConfigurationError, ValueError) as exc:
                    print(f"\n\033[91mERROR:\033[0m {exc}")
        elif ans_summary == t("builder.edit_boot"):
            opts = [
                f"{t('builder.boot_no')} (0x0)", f"{t('builder.boot_8k')} (0x2000)", f"{t('builder.boot_16k')} (0x4000)",
                f"{t('builder.boot_28k')} (0x7000)", f"{t('builder.boot_32k')} (0x8000)", f"{t('builder.boot_64k')} (0x10000)",
                f"{t('builder.boot_128k')} (0x20000)", t("builder.enter_manual")
            ]
            f_ans = numbered_select(t("builder.select_boot"), choices=opts)
            if f_ans == t("builder.enter_manual"):
                f_ans = simple_input(t("builder.enter_hex"), default=flash, validate=questionary_hex_offset_validator)
            elif f_ans:
                f_ans = f_ans.split(" (")[1].replace(")", "")
            if not _is_back(f_ans) and f_ans:
                try:
                    offset = BootloaderOffset.from_value(f_ans)
                    config_dict, current_mcu, current_hint = _resolve_firmware_configuration(
                        current_mcu, current_hint, offset
                    )
                except (FirmwareConfigurationError, ValueError) as exc:
                    print(f"\n\033[91mERROR:\033[0m {exc}")
        elif ans_summary == t("builder.edit_comm"):
            c_ans = numbered_select(t("builder.select_interface"), choices=["USB", "UART", "CAN", "SPI"])
            if c_ans:
                try:
                    offset = bootloader_offset_from_config(config_dict, current_mcu)
                    config_dict, current_mcu, current_hint = _resolve_firmware_configuration(
                        current_mcu, c_ans.lower(), offset
                    )
                except (FirmwareConfigurationError, ValueError) as exc:
                    print(f"\n\033[91mERROR:\033[0m {exc}")
        elif ans_summary == t("builder.edit_clock"):
            clk = simple_input(t("builder.enter_clock"), default=clock)
            if clk:
                candidate = dict(config_dict)
                candidate["CONFIG_CLOCK_FREQ"] = clk
                try:
                    validate_firmware_configuration(candidate, processor=current_mcu)
                    config_dict = candidate
                except FirmwareConfigurationError as exc:
                    print(f"\n\033[91mERROR:\033[0m {exc}")

    # ── 3. Invoke Headless Compiler Orchestrator ──
    print(f"\n\033[92m[*]\033[0m {t('kace.compiling')}", flush=True)
    result = build_firmware_orchestrator(
        mcu_path=user_data.get('mcu_path'),
        derived_mcu=current_mcu,
        hint=current_hint,
        output_dir="~/kace",
        config_dict=config_dict,
        build_context=BuildContext(make_command=user_data.get('make_command', 'make'))
    )

    if result.get("status") == "success":
        print(f"\033[92mSUCCESS:\033[0m {t('kace.firmware_success', path=result.get('path'))}")
        user_data['mcu_type'] = result.get('mcu')
        user_data['firmware_path'] = result.get('path')
        artifact = result.get('artifact')
        if artifact is None:
            # Compatibility for custom/test builders that still return the
            # historical dictionary without the typed artifact.
            artifact = BuildArtifact.create(
                path=result.get('path') or "",
                native_filename=result.get('firmware') or "klipper.bin",
                size_bytes=result.get('size_bytes', 0),
                mcu=result.get('mcu') or current_mcu or "",
                firmware_fingerprint=result.get('klipper_version') or "",
                mock_build=bool(result.get('size_warning', False)),
                size_warning=bool(result.get('size_warning', False)),
            )
        user_data['firmware_artifact'] = artifact
        identity = getattr(artifact, "firmware_identity", None)
        if identity is not None:
            user_data['firmware_identity'] = identity
            user_data['klipper_version'] = identity.reported_version
            user_data['mcu_name'] = result.get('mcu_name', 'mcu')
        elif result.get('klipper_version'):
            # Compatibility metadata may still be displayed/exported, but it
            # cannot authorize the integrated post-flash verification path.
            user_data['klipper_version'] = result.get('klipper_version')
            user_data['mcu_name'] = result.get('mcu_name', 'mcu')

        # Surface size warning if the builder flagged a suspiciously small artifact.
        # build_mode already printed a detailed block; this adds a concise inline note
        # with a clear recovery hint so the user doesn't have to scroll back up.
        if result.get("size_warning"):
            from firmware.build_mode import _human_size
            _sz = _human_size(result.get("size_bytes", 0))
            print(
                f"\n  \033[93m[!] Firmware is only {_sz} — likely a placeholder from the mock compiler.\033[0m"
                f"\n  \033[93m    To produce real firmware, re-run with:\033[0m"
                f"\n  \033[93m      KACE_REAL_BUILD=1 python3 kace.py   or   python3 kace.py --real-build\033[0m"
            )

        service = FirmwareDeploymentService(output_dir="~/kace")
        mcu_path = user_data.get('mcu_path') or ""
        target = DeploymentTarget(
            board=user_data.get('board') or "",
            mcu=result.get('mcu') or current_mcu or "",
            device_path=mcu_path,
            mcu_name=user_data.get('mcu_name', 'mcu'),
            **_read_deployment_usb_identity(mcu_path),
        )
        available = service.available_methods(target, artifact)
        artifact_blockers = deployment_artifact_blockers(artifact)
        if artifact_blockers:
            print("\n\033[93m[!] Firmware deployment is disabled for this artifact:\033[0m")
            for blocker in artifact_blockers:
                print(f"    - {blocker}")
        elif not available:
            print("\n\033[93m[!] The exact board strategy rejected this build:\033[0m")
            for blocker in service.profile_blockers(target, artifact):
                print(f"    - {blocker}")
        deploy_options = [
            {"name": f"✅  {t('kace.deploy_none')}", "value": "none"},
        ]
        if DeploymentMethodId.MANUAL in available:
            deploy_options.append({
                "name": f"💾  {t('deployment.method_manual')}",
                "value": DeploymentMethodId.MANUAL.value,
            })
        if DeploymentMethodId.USB in available:
            deploy_options.append({
                "name": f"⚡  {t('deployment.method_usb')}",
                "value": DeploymentMethodId.USB.value,
            })

        deploy_fw = numbered_select(
            f"\n{t('kace.deploy_firmware_prompt')}",
            choices=deploy_options
        )

        if deploy_fw in (DeploymentMethodId.MANUAL.value, DeploymentMethodId.USB.value):
            try:
                plan = service.plan(artifact, target, DeploymentMethodId(deploy_fw))
                prepared = service.prepare(plan)
            except Exception as exc:
                print(f"\n\033[91mERROR:\033[0m {t('deployment.prepare_failed', error=exc)}")
                return {"status": "deployment_prepare_failed", "error": str(exc)}

            user_data['firmware_deployment_service'] = service
            user_data['firmware_deployment_plan'] = plan
            user_data['prepared_firmware_deployment'] = prepared
            user_data['pending_firmware_deployment'] = True
            user_data['firmware_path'] = prepared.staged_path

            print(f"\n\033[92m[OK]\033[0m {t('deployment.artifact_ready', path=prepared.staged_path)}")
            print(f"\033[96m[*]\033[0m {t('deployment.final_filename', filename=plan.final_filename)}")
            for index, instruction in enumerate(plan.instructions, 1):
                print(f"  {index}. {instruction.text}")
            if plan.automation_blockers and plan.automation_supported:
                print(f"\033[93m[!] {t('deployment.automation_blocked')}\033[0m")
                for blocker in plan.automation_blockers:
                    print(f"    - {blocker}")
            return {"status": "deployment_prepared", "method": deploy_fw}

    else:
        print(f"\n\033[91mERROR:\033[0m {t('kace.firmware_error', message=result.get('message'))}")
