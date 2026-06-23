import questionary
from core.scraper import fetch_config_list, fetch_raw_config, parse_config, get_reusable_driver_sockets, detect_fan_pins, detect_driver_info
from core.style import custom_style
from core.translations import t
from core.exceptions import WizardExit
from core.validators import questionary_pin_validator
from core.wizard.runner import _BACK, _QUIT
from core.wizard.ui import _back_choice, _quit_choice


def _get_parsed(user_data):
    import core.wizard
    return core.wizard.get_current_board_parsed(user_data)



_MCU_SEARCH_TERMS_FALLBACK = {
    "lpc1769":    ["skr-v1.4", "skr-v1.3", "sgen-l"],
    "lpc1768":    ["mks-sgenl", "sbase"],
    "stm32f103":  ["creality-v4.2.2", "creality-v4.2.7", "skr-mini-e3"],
    "stm32f407":  ["mks-robin-nano-v3", "skr-pro"],
    "stm32f429":  ["skr-2", "octopus-pro-v1.0"],
    "stm32f446":  ["octopus", "spider"],
    "stm32g0b1":  ["manta", "skr-mini-e3-v3.0"],
    "stm32h723":  ["octopus-max-ez"],
    "stm32f042":  ["cheetah-v2.0"],
    "rp2040":     ["skr-pico"],
    "atmega2560": ["ramps", "mega2560"],
    "atmega1284p":["melzi"],
    "at90usb1286":["printrboard"],
    "sam4e8e":    ["duet2"],
    "samd51":     ["duet3-mini"],
}

def _load_mcu_search_terms() -> dict:
    try:
        from core.loader import load_boards_yaml
        db = load_boards_yaml()
        result = {}
        for entry in db.get('boards', []):
            mcu = entry.get('mcu')
            terms = entry.get('search_terms', [])
            if mcu and terms:
                result[mcu] = terms
        return result if result else _MCU_SEARCH_TERMS_FALLBACK
    except Exception:
        return _MCU_SEARCH_TERMS_FALLBACK

_MCU_SEARCH_TERMS = None

def _get_mcu_search_terms() -> dict:
    global _MCU_SEARCH_TERMS
    if _MCU_SEARCH_TERMS is None:
        _MCU_SEARCH_TERMS = _load_mcu_search_terms()
    return _MCU_SEARCH_TERMS


def _has_fan_options(user_data: dict) -> bool:
    raw_cfg = user_data.get("board_raw_config")
    if not raw_cfg:
        return False
    return len(detect_fan_pins(raw_cfg)) > 0


def _step_board(user_data, suggested_configs, board_configs):
    """Board selection step.

    Presents MCU-suggested boards at the top of the list.
    After selection, loads and stores the raw board config so subsequent
    wizard steps (Z socket assignment, display) can use it without re-fetching.
    """
    choices = []
    if suggested_configs:
        choices.append(questionary.Separator(f"── {t('wizard.select_board_suggested')} ──"))
        choices.extend(suggested_configs)
        choices.append(questionary.Separator("──────────────────────────────────────────────────"))
    choices.extend([
        {"name": t("choice.search_manually"), "value": "__search__"},
        _back_choice(),
        _quit_choice(),
    ])

    ans = questionary.select(
        t("wizard.select_board"),
        choices=choices,
        style=custom_style
    ).ask()

    if ans == _QUIT or ans is None:
        raise WizardExit()
    if ans == _BACK:
        return _BACK

    if ans == "__search__":
        ans = questionary.autocomplete(
            t("wizard.select_board_manual"),
            choices=board_configs,
            style=custom_style
        ).ask()
        if ans is None:
            return "__retry__"

    user_data["board"] = ans

    # ── Load board config immediately so subsequent steps have it ─────────────
    raw = fetch_raw_config(ans)
    if raw:
        user_data["board_raw_config"] = raw
        user_data["board_parsed"]     = parse_config(raw, ans, keep_comments=True)
    else:
        user_data["board_raw_config"] = None
        user_data["board_parsed"]     = {}

    return ans


def _step_fan_assignment(user_data: dict) -> str:
    raw_cfg = user_data.get("board_raw_config", "")
    detected_fans = detect_fan_pins(raw_cfg)
    if not detected_fans:
        return "success"

    # Find board default pin if available
    default_fan_pin = None
    for f in detected_fans:
        if f["section"].lower() == "fan":
            default_fan_pin = f["pin"]
            break

    # ── 1. Part Cooling Fan ──
    part_choices = []
    if default_fan_pin:
        part_choices.append({
            "name": t("wizard.fan_board_default").format(pin=default_fan_pin),
            "value": "default"
        })

    # Add other detected pins
    for f in detected_fans:
        # Avoid duplicating the default fan choice
        if f["pin"] == default_fan_pin:
            continue
        part_choices.append({
            "name": f["label"],
            "value": f["pin"]
        })

    part_choices.extend([
        {"name": t("wizard.fan_custom"), "value": "custom"},
        {"name": t("wizard.fan_none"), "value": "none"},
        _back_choice(),
        _quit_choice()
    ])

    ans_part = questionary.select(
        t("wizard.part_cooling_prompt"),
        choices=part_choices,
        style=custom_style
    ).ask()

    if ans_part is None:
        raise WizardExit()
    if ans_part in [_BACK, _QUIT]:
        return ans_part

    final_part_pin = None
    if ans_part == "custom":
        custom_pin = questionary.text(
            t("wizard.fan_enter_custom"),
            validate=questionary_pin_validator,
            style=custom_style
        ).ask()
        if custom_pin is None:
            raise WizardExit()
        if not custom_pin.strip():
            return "__retry__"
        final_part_pin = custom_pin.strip()
    else:
        final_part_pin = ans_part

    # ── 2. Hotend Heatsink Fan ──
    # Filter choices to remove the selected part cooling pin
    used_part_pin = default_fan_pin if final_part_pin == "default" else final_part_pin

    hotend_choices = [
        {"name": t("wizard.fan_none"), "value": "none"}
    ]

    for f in detected_fans:
        if f["pin"] == used_part_pin:
            continue
        hotend_choices.append({
            "name": f["label"],
            "value": f["pin"]
        })

    hotend_choices.extend([
        {"name": t("wizard.fan_custom"), "value": "custom"},
        _back_choice(),
        _quit_choice()
    ])

    ans_hotend = questionary.select(
        t("wizard.hotend_fan_prompt"),
        choices=hotend_choices,
        style=custom_style
    ).ask()

    if ans_hotend is None:
        raise WizardExit()
    if ans_hotend in [_BACK, _QUIT]:
        return ans_hotend

    final_hotend_pin = None
    if ans_hotend == "custom":
        custom_pin = questionary.text(
            t("wizard.fan_enter_custom"),
            validate=questionary_pin_validator,
            style=custom_style
        ).ask()
        if custom_pin is None:
            raise WizardExit()
        if not custom_pin.strip():
            return "__retry__"
        final_hotend_pin = custom_pin.strip()
    else:
        final_hotend_pin = ans_hotend

    # Save the answers
    user_data["fan_part_cooling_pin"] = final_part_pin
    user_data["fan_hotend_pin"] = final_hotend_pin
    return "success"


def _step_z_motors(user_data):
    ans = questionary.select(
        t("wizard.z_motors"),
        choices=["1", "2", "3", "4", _back_choice(), _quit_choice()],
        default=user_data.get("z_motors") or "1",
        style=custom_style
    ).ask()
    if ans == _QUIT or ans is None:
        raise WizardExit()
    if ans == _BACK:
        return _BACK
    user_data["z_motors"] = ans
    return ans


def _step_z_socket_assignment(user_data):
    """Z motor socket assignment step — runs inside the wizard.

    Uses user_data['board_parsed'] (already loaded in _step_board).
    Modifies board_parsed in place so kace.py can use it directly.
    Returns '__skip__' when only 1 Z motor is configured.
    """
    z_motors = int(user_data.get('z_motors', 1))
    if z_motors <= 1:
        return "__skip__"

    raw_cfg   = user_data.get('board_raw_config') or fetch_raw_config(user_data['board'])
    parsed_data = user_data.get('board_parsed')
    if parsed_data is None:
        parsed_data = parse_config(raw_cfg, user_data.get('board', ''), keep_comments=True)
        user_data['board_parsed'] = parsed_data

    available_driver_sockets = list(get_reusable_driver_sockets(raw_cfg, user_data.get('board', '')))

    _parsed_full   = None
    z_idx          = 2
    assigned_drivers = {}

    while z_idx <= z_motors:
        motor_name = f"stepper_z{z_idx - 1}"

        if motor_name in parsed_data:
            z_idx += 1
            continue

        driver_choices = []
        from core.translations import get_mode
        is_beginner = get_mode() == "Beginner"
        for idx_s, (sock_key, sock_label) in enumerate(available_driver_sockets):
            if idx_s == 0 and is_beginner:
                display_label = f"{sock_label}  ✓ Recommended"
            else:
                display_label = sock_label
            driver_choices.append({"name": display_label, "value": sock_key})

        driver_choices.append({"name": t("choice.custom_pins"),  "value": "custom"})
        driver_choices.append({"name": t("choice.back") or "Back", "value": "back"})
        driver_choices.append({"name": t("choice.quit_setup"),   "value": "quit"})

        print(f"\n\033[96m{t('wizard.mapping_pins', motor=motor_name)}\033[0m")
        selected_driver = questionary.select(
            t("wizard.select_driver_z", motor=motor_name.upper()),
            choices=driver_choices,
            style=custom_style
        ).ask()

        if selected_driver == "quit" or selected_driver is None:
            raise WizardExit()

        if selected_driver == "back":
            if z_idx > 2:
                z_idx -= 1
                prev_motor = f"stepper_z{z_idx - 1}"
                if prev_motor in assigned_drivers:
                    prev_key = assigned_drivers[prev_motor]
                    if prev_key != "custom":
                        _label = prev_key.replace("extruder_stepper ", "").upper() \
                            if prev_key.startswith("extruder_stepper ") \
                            else f"E{prev_key.replace('extruder', '')}"
                        available_driver_sockets.append((prev_key, _label))
                        available_driver_sockets.sort(key=lambda t_: t_[0])
                        parsed_data.pop(prev_motor, None)
                continue
            else:
                return _BACK

        if selected_driver == "custom":
            print(t("wizard.assign_custom_pins_header", motor=motor_name))
            step_pin = questionary.text(t("wizard.custom_step_pin"), validate=questionary_pin_validator, style=custom_style).ask()
            dir_pin  = questionary.text(t("wizard.custom_dir_pin"),  validate=questionary_pin_validator, style=custom_style).ask()
            en_pin   = questionary.text(t("wizard.custom_en_pin"),   validate=questionary_pin_validator, style=custom_style).ask()
            if not step_pin or not dir_pin or not en_pin:
                print(f"\n\033[91m{t('kace.abort_valid_pins')}\033[0m")
                raise WizardExit()
            parsed_data[motor_name] = {"step_pin": step_pin, "dir_pin": dir_pin, "enable_pin": en_pin}
            assigned_drivers[motor_name] = "custom"
        else:
            src_data = parsed_data.get(selected_driver)
            if src_data is None:
                if _parsed_full is None:
                    _parsed_full = parse_config(raw_cfg, user_data.get('board', ''), keep_comments=True)
                src_data = _parsed_full.get(selected_driver, {})
            parsed_data[motor_name] = {
                "step_pin":   src_data.get("step_pin",   ""),
                "dir_pin":    src_data.get("dir_pin",    ""),
                "enable_pin": src_data.get("enable_pin", ""),
            }
            parsed_data.pop(selected_driver, None)
            available_driver_sockets = [(k, l) for k, l in available_driver_sockets if k != selected_driver]
            assigned_drivers[motor_name] = selected_driver

        z_idx += 1

    user_data["z_socket_assignments"] = assigned_drivers
    return "done"


def _step_driver_type(user_data):
    base_choices = ["None (Standard)", "TMC2208", "TMC2209", "TMC2225", "TMC2130", "TMC5160", "A4988", "DRV8825"]
    parsed_board = _get_parsed(user_data)
    driver_info = detect_driver_info(parsed_board, user_data.get("board") or "")
    detected_type = driver_info.get("driver_type")
    is_integrated = driver_info.get("integrated")
    is_socketed = driver_info.get("is_socketed")
    
    formatted_choices = []
    preselected_index = 0
    from core.translations import get_mode
    is_beginner = get_mode() == "Beginner"
    for idx, choice in enumerate(base_choices):
        name = choice
        value = choice
        if is_integrated and choice == detected_type:
            if is_beginner:
                name = f"{choice}  ✓ Recommended (Detected from board profile)"
            preselected_index = idx
        elif is_integrated and choice == "None (Standard)":
            if is_beginner:
                name = f"{choice}  (Not Recommended for integrated TMC)"
        formatted_choices.append(questionary.Choice(title=name, value=value))
        
    back_ch = _back_choice()
    quit_ch = _quit_choice()
    formatted_choices.append(questionary.Choice(title=back_ch["name"], value=back_ch["value"]))
    formatted_choices.append(questionary.Choice(title=quit_ch["name"], value=quit_ch["value"]))
    
    default_choice = formatted_choices[preselected_index].value
    
    ans = questionary.select(
        t("wizard.select_driver") or "Select Stepper Driver Type:",
        choices=formatted_choices,
        default=default_choice,
        style=custom_style
    ).ask()
    
    if ans == _QUIT or ans is None: raise WizardExit()
    if ans == _BACK: return _BACK
    
    if not is_integrated and not is_socketed and ans == "None (Standard)":
        confirm_standalone = questionary.confirm(
            t("wizard.confirm_standalone"),
            default=False,
            style=custom_style
        ).ask()
        if not confirm_standalone:
            return "__retry__"

    user_data["driver_type"] = ans
    return ans


def _step_driver_mode(user_data):
    base_modes = ["UART", "SPI", "Standalone"]
    parsed_board = _get_parsed(user_data)
    driver_info = detect_driver_info(parsed_board, user_data.get("board") or "")
    is_integrated = driver_info.get("integrated")
    detected_mode = driver_info.get("driver_mode")
    preselected_mode_index = 0
    
    formatted_modes = []
    from core.translations import get_mode
    is_beginner = get_mode() == "Beginner"
    for idx, mode in enumerate(base_modes):
        name = mode
        value = mode
        if is_integrated and mode == detected_mode:
            if is_beginner:
                name = f"{mode}  ✓ Recommended (Detected from board profile)"
            preselected_mode_index = idx
        formatted_modes.append(questionary.Choice(title=name, value=value))
        
    back_ch = _back_choice()
    quit_ch = _quit_choice()
    formatted_modes.append(questionary.Choice(title=back_ch["name"], value=back_ch["value"]))
    formatted_modes.append(questionary.Choice(title=quit_ch["name"], value=quit_ch["value"]))
    
    default_mode = formatted_modes[preselected_mode_index].value
    
    ans = questionary.select(
        t("wizard.select_driver_mode", driver=user_data["driver_type"]) or f"Select communication mode for {user_data['driver_type']}:",
        choices=formatted_modes,
        default=default_mode,
        style=custom_style
    ).ask()
    
    if ans == _QUIT or ans is None: raise WizardExit()
    if ans == _BACK: return _BACK
    user_data["driver_mode"] = ans
    return ans



def _apply_z_tmc_mappings(user_data: dict) -> None:
    """Post-processing step: maps Z stepper TMC configurations."""
    z_motors = int(user_data.get('z_motors') or 1)
    if z_motors <= 1:
        return

    assignments = user_data.get("z_socket_assignments")
    if not assignments:
        return

    parsed_data = user_data.get("board_parsed")
    if parsed_data is None:
        return

    raw_cfg = user_data.get("board_raw_config")
    if not raw_cfg:
        return

    driver_type = user_data.get("driver_type") or "None (Standard)"
    driver_mode = user_data.get("driver_mode") or ""

    if "TMC" not in driver_type:
        return

    # Parse full config with comments to find source TMC configuration blocks
    _parsed_full = parse_config(raw_cfg, user_data.get('board', ''), keep_comments=True)

    for motor_name, selected_driver in assignments.items():
        dest_tmc = f"{driver_type.lower()} {motor_name}"

        if selected_driver == "custom":
            if driver_mode in ["UART", "SPI"]:
                # Prompt for custom pin
                pin_key = "uart_pin" if driver_mode == "UART" else "cs_pin"
                if dest_tmc not in parsed_data or pin_key not in parsed_data[dest_tmc]:
                    uart_pin = questionary.text(
                        t("wizard.custom_uart_pin", mode=driver_mode.lower(), motor=motor_name),
                        validate=questionary_pin_validator,
                        style=custom_style
                    ).ask()
                    if not uart_pin:
                        print(f"\n\033[91m{t('kace.abort_no_uart', mode=driver_mode)}\033[0m")
                        raise WizardExit()
                    parsed_data[dest_tmc] = {pin_key: uart_pin, "run_current": "0.650"}
        else:
            # Socketed driver: copy TMC details from board config
            found_tmc = False
            for possible_tmc in ["tmc2209", "tmc2208", "tmc2130", "tmc5160", "tmc2225", "tmc2240"]:
                src_tmc = f"{possible_tmc} {selected_driver}"
                tmc_src_data = parsed_data.get(src_tmc) or _parsed_full.get(src_tmc)
                if tmc_src_data is not None:
                    parsed_data[dest_tmc] = tmc_src_data.copy()
                    parsed_data.pop(src_tmc, None)
                    found_tmc = True
                    break

            if not found_tmc and driver_mode in ["UART", "SPI"]:
                print(f"\n\033[91m{t('kace.abort_no_tmc_map', mode=driver_mode, driver=selected_driver)}\033[0m")
                print(f"\033[93m{t('kace.abort_generation')}\033[0m")
                raise WizardExit()
