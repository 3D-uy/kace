import sys
from core.menu import simple_input, yes_no, numbered_select, Choice
from core.style import custom_style
from core.translations import t
from core.exceptions import DerivationAmbiguityError
from firmware.derivation import derive_config
from firmware.builder import build_firmware_orchestrator
from core.deployer import deploy_usb, deploy_local, deploy_avrdude

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
    config_dict = None
    current_mcu = mcu
    current_hint = hint
    resolved_flash = None

    while config_dict is None:
        try:
            config_dict = derive_config(current_mcu, current_hint, flash_start=resolved_flash)
        except DerivationAmbiguityError as ambig:
            if ambig.param == "mcu_family":
                choices = ambig.options + ["Enter manually"]
                ans_family = numbered_select(
                    f"Select MCU architecture family for {current_mcu if current_mcu else 'Board'}:",
                    choices=choices
                )
                if ans_family == "Enter manually" or ans_family is None:
                    ans_family = simple_input("Enter Klipper ARCH (e.g. stm32)")
                if not ans_family:
                    print(f"\n\033[93m{t('kace.cancelled')}\033[0m")
                    sys.exit(0)
                current_mcu = ans_family
            elif ambig.param == "bootloader_offset":
                options = ambig.options
                choices = list(options.keys()) + ["No bootloader (0x0)", "Enter manually"]
                ans_boot = numbered_select(
                    f"Select bootloader offset for {current_mcu.upper()}:",
                    choices=choices
                )
                if ans_boot == "Enter manually":
                    ans_boot = simple_input("Enter HEX offset (e.g. 0x8000)")
                elif ans_boot == "No bootloader (0x0)" or ans_boot is None:
                    ans_boot = "0x0"
                else:
                    ans_boot = options.get(ans_boot, "0x0")
                resolved_flash = ans_boot
            elif ambig.param == "comm_interface":
                ans_comm = numbered_select(
                    f"Select the communication interface for {(current_mcu or 'Board').upper()}:",
                    choices=ambig.options
                )
                if not ans_comm:
                    print(f"\n\033[93m{t('kace.cancelled')}\033[0m")
                    sys.exit(0)
                current_hint = ans_comm.lower()

    # ── 2. Run the interactive compile summary wizard ──
    def format_flash(f):
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

    _B = "\033[1m"
    _C = "\033[96m"
    _Y = "\033[93m"
    _R = "\033[0m"
    _M = "\033[96m"

    while True:
        arch = config_dict.get("CONFIG_MCU", "Unknown").replace('"', '')
        model = current_mcu if current_mcu else "Unknown"
        flash = config_dict.get("CONFIG_FLASH_START", "0x0")
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
            t("builder.edit_boot"),
            t("builder.edit_comm"),
        ]
        if clock:
            choices.append(t("builder.edit_clock"))
        choices.append(t("builder.abort"))

        ans_summary = numbered_select(t("builder.config_correct"), choices=choices)

        if ans_summary == t("builder.compile_now"):
            break
        elif ans_summary == t("builder.abort") or ans_summary is None:
            print(f"\n\033[93m{t('kace.cancelled')}\033[0m")
            sys.exit(0)
        elif ans_summary == t("builder.edit_arch"):
            new_arch = simple_input(t("builder.enter_arch"), default=arch)
            if new_arch: config_dict["CONFIG_MCU"] = f'"{new_arch}"'
        elif ans_summary == t("builder.edit_proc"):
            new_model = simple_input(t("builder.enter_proc"), default=model)
            if new_model: current_mcu = new_model
        elif ans_summary == t("builder.edit_boot"):
            opts = [
                f"{t('builder.boot_no')} (0x0)", f"{t('builder.boot_8k')} (0x2000)", f"{t('builder.boot_16k')} (0x4000)",
                f"{t('builder.boot_28k')} (0x7000)", f"{t('builder.boot_32k')} (0x8000)", f"{t('builder.boot_64k')} (0x10000)",
                f"{t('builder.boot_128k')} (0x20000)", t("builder.enter_manual")
            ]
            f_ans = numbered_select(t("builder.select_boot"), choices=opts)
            if f_ans == t("builder.enter_manual"):
                f_ans = simple_input(t("builder.enter_hex"), default=flash)
                if f_ans: config_dict["CONFIG_FLASH_START"] = f_ans
            elif f_ans:
                config_dict["CONFIG_FLASH_START"] = f_ans.split(" (")[1].replace(")", "")
        elif ans_summary == t("builder.edit_comm"):
            c_ans = numbered_select(t("builder.select_interface"), choices=["USB", "UART", "CAN", "SPI"])
            if c_ans:
                config_dict["CONFIG_USB"]    = "y" if c_ans == "USB"  else "n"
                config_dict["CONFIG_SERIAL"] = "y" if c_ans == "UART" else "n"
                config_dict["CONFIG_CANBUS"] = "y" if c_ans == "CAN"  else "n"
                config_dict["CONFIG_SPI"]    = "y" if c_ans == "SPI"  else "n"
        elif ans_summary == t("builder.edit_clock"):
            clk = simple_input(t("builder.enter_clock"), default=clock)
            if clk: config_dict["CONFIG_CLOCK_FREQ"] = clk

    # ── 3. Invoke Headless Compiler Orchestrator ──
    print(f"\n\033[92m[*]\033[0m {t('kace.compiling')}", flush=True)
    result = build_firmware_orchestrator(
        mcu_path=user_data.get('mcu_path'),
        derived_mcu=current_mcu,
        hint=current_hint,
        output_dir="~/kace",
        config_dict=config_dict,
        make_command=user_data.get('make_command', 'make')
    )

    if result.get("status") == "success":
        print(f"\033[92mSUCCESS:\033[0m {t('kace.firmware_success', path=result.get('path'))}")
        user_data['mcu_type'] = result.get('mcu')
        user_data['firmware_path'] = result.get('path')

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

        deploy_options = [
            {"name": f"✅  {t('kace.deploy_none')}",   "value": "none"},
            {"name": f"📁  {t('kace.deploy_local')}",  "value": "local"},
            {"name": f"💾  {t('kace.deploy_usb')}",    "value": "usb"},
        ]
        if result.get('firmware') == 'klipper.elf.hex':
            deploy_options.insert(1, {"name": f"⚡  {t('kace.deploy_avrdude')}", "value": "avrdude"})

        deploy_fw = numbered_select(
            f"\n{t('kace.deploy_firmware_prompt')}",
            choices=deploy_options
        )

        if deploy_fw == "usb":
            deploy_usb(user_data, artifact_type="firmware")
        elif deploy_fw == "local":
            deploy_local(user_data, artifact_type="firmware")
        elif deploy_fw == "avrdude":
            deploy_avrdude(user_data, result.get("path"), result.get("mcu"))

    else:
        print(f"\n\033[91mERROR:\033[0m {t('kace.firmware_error', message=result.get('message'))}")
