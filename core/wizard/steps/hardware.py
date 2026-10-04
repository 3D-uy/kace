import copy
import os

from core.menu import simple_input, yes_no, numbered_select, autocomplete_select, Separator, Choice
from core.scraper import fetch_raw_config, parse_config, get_reusable_driver_sockets, detect_fan_pins, detect_driver_info
from core.translations import t
from core.terminal import ERROR, INFO, RESET, WARNING, SECTION
from core.exceptions import GenerationError, WizardExit
from core.profile_values import canonical_tmc_model, mark_user_override, resolve_generation_values, tmc_setting_value
from core.validators import questionary_pin_validator, questionary_fan_pin_validator
from core.wizard.runner import _BACK, _QUIT
from core.wizard.ui import _back_choice, _quit_choice


def _get_parsed(user_data):
    import core.wizard
    return core.wizard.get_current_board_parsed(user_data)



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
        if not result:
            raise RuntimeError("[KACE] boards.yaml has no MCU search terms")
        return result
    except Exception as exc:
        raise RuntimeError(
            f"[KACE] failed to load authoritative boards.yaml: {exc}"
        ) from exc

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
        choices.append(Separator(f"── {t('wizard.select_board_suggested')} ──"))
        choices.extend(suggested_configs)
        choices.append(Separator("──────────────────────────────────────────────────"))
    choices.extend([
        {"name": t("choice.search_manually"), "value": "__search__"},
        _back_choice(),
        _quit_choice(),
    ])

    ans = numbered_select(
        t("wizard.select_board"),
        choices=choices
    )

    if ans == _QUIT or ans is None:
        raise WizardExit()
    if ans == _BACK:
        return _BACK

    if ans == "__search__":
        ans = autocomplete_select(
            t("wizard.select_board_manual"),
            choices=board_configs
        )
        if ans is None:
            return "__retry__"

    user_data["board"] = ans

    # Phase 4A authority classification is exact and additive.  It does not
    # build here; it makes the later firmware branch explicit and observable.
    from firmware.boards.runtime import (
        record_board_contract_authority_failure,
        record_firmware_authority,
        resolve_firmware_authority,
    )
    try:
        authority = resolve_firmware_authority(
            ans,
            detected_mcu=user_data.get("mcu_type"),
        )
        record_firmware_authority(user_data, authority)
    except Exception as exc:
        record_board_contract_authority_failure(user_data, ans, exc)
        raise

    # Preserve the earlier shadow diagnostic while legacy boards remain in
    # service. It observes an existing selection and never makes a decision.
    try:
        from firmware.boards.resolver import capture_shadow_comparison
        capture_shadow_comparison(user_data, ans)
    except Exception as exc:
        user_data["board_contract_shadow"] = {
            "legacy_board": str(ans or ""),
            "legacy_mcu": str(user_data.get("mcu_type") or ""),
            "board_contract_id": "",
            "matching_variant_ids": (),
            "divergence": "SHADOW_ERROR",
            "detail": str(exc),
        }

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
    from core.board_cooling import REVIEWED, required_board_fans
    required_cooling = {}
    if user_data.get("board") in REVIEWED:
        required_cooling = required_board_fans(parse_config(raw_cfg, user_data["board"]), user_data["board"])
    from core.board_bx_panel import PROFILE as BX_PROFILE, selected_bx_cooling
    if user_data.get("board") == BX_PROFILE:
        required_cooling.update(selected_bx_cooling(parse_config(raw_cfg, BX_PROFILE)))
    if required_cooling:
        print(f"{INFO}{t('wizard.required_cooling').format(names=', '.join(required_cooling))}{RESET}")
    required_pins = {fields["pin"] for fields in required_cooling.values()}
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
    from core.part_fan import selected_part_fan
    fan_source = parse_config(raw_cfg, keep_comments=False)
    for f in detected_fans:
        # Avoid duplicating the default fan choice
        if f["pin"] == default_fan_pin or f["pin"] in required_pins:
            continue
        try:
            selected_part_fan(fan_source, f["pin"])
        except GenerationError:
            # Automatic/tuned resources cannot become a manual part fan merely
            # because their connector is selectable. Custom input is rechecked
            # against the same source contract during generation.
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

    ans_part = numbered_select(
        t("wizard.part_cooling_prompt"),
        choices=part_choices,
        require_explicit=True,
    )

    if ans_part is None:
        raise WizardExit()
    if ans_part in [_BACK, _QUIT]:
        return ans_part

    final_part_pin = None
    if ans_part == "custom":
        custom_pin = simple_input(
            t("wizard.fan_enter_custom"),
            validate=questionary_fan_pin_validator,
            back_value=_BACK,
        )
        if custom_pin == _BACK:
            return _BACK
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
    from core.pin_validator import PinAliases
    used_part_identity = PinAliases.split_pin(used_part_pin or "")

    hotend_choices = [
        {"name": t("wizard.fan_no_additional" if required_cooling else "wizard.fan_none"), "value": "none"}
    ]

    for f in detected_fans:
        if PinAliases.split_pin(f["pin"]) == used_part_identity:
            continue
        if f["pin"] in required_pins and not f["section"].lower().startswith("heater_fan "):
            # A mandatory controller fan already retains its motor/heater
            # triggers; it cannot be reassigned as an optional thermal fan.
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

    ans_hotend = numbered_select(
        t("wizard.hotend_fan_prompt"),
        choices=hotend_choices,
        require_explicit=True,
    )

    if ans_hotend is None:
        raise WizardExit()
    if ans_hotend in [_BACK, _QUIT]:
        return ans_hotend

    final_hotend_pin = None
    if ans_hotend == "custom":
        custom_pin = simple_input(
            t("wizard.fan_enter_custom"),
            validate=questionary_fan_pin_validator,
            back_value=_BACK,
        )
        if custom_pin == _BACK:
            return _BACK
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
    choices = ["1", "2", "3", "4", _back_choice(), _quit_choice()]
    default_val = user_data.get("z_motors") or "1"
    default_idx = 0
    for idx, choice in enumerate(choices):
        if isinstance(choice, dict) and choice.get("value") == default_val:
            default_idx = idx
            break
        elif choice == default_val:
            default_idx = idx
            break

    ans = numbered_select(
        t("wizard.z_motors"),
        choices=choices,
        default=default_idx
    )
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
                display_label = f"{sock_label} {WARNING}{t('choice.recommended')}{RESET}"
            else:
                display_label = sock_label
            driver_choices.append({"name": display_label, "value": sock_key})

        driver_choices.append({"name": t("choice.custom_pins"),  "value": "custom"})
        driver_choices.append({"name": t("choice.back") or "Back", "value": "back"})
        driver_choices.append({"name": t("choice.quit_setup"),   "value": "quit"})

        print(f"\n{INFO}{t('wizard.mapping_pins', motor=motor_name)}{RESET}")
        selected_driver = numbered_select(
            t("wizard.select_driver_z", motor=motor_name.upper()),
            choices=driver_choices
        )

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
            step_pin = simple_input(t("wizard.custom_step_pin"), validate=questionary_pin_validator, back_value=_BACK)
            if step_pin == _BACK:
                return _BACK
            dir_pin  = simple_input(t("wizard.custom_dir_pin"),  validate=questionary_pin_validator, back_value=_BACK)
            if dir_pin == _BACK:
                return _BACK
            en_pin   = simple_input(t("wizard.custom_en_pin"),   validate=questionary_pin_validator, back_value=_BACK)
            if en_pin == _BACK:
                return _BACK
            if not step_pin or not dir_pin or not en_pin:
                print(f"\n{ERROR}{t('kace.abort_valid_pins')}{RESET}")
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
            if "step_pulse_duration" in src_data:
                # Pulse timing belongs to the reused driver socket, not Z mechanics.
                parsed_data[motor_name]["step_pulse_duration"] = src_data["step_pulse_duration"]
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
        name = t("wizard.driver_standard") if choice == "None (Standard)" else choice
        value = choice
        if is_integrated and choice == detected_type:
            if is_beginner:
                name = f"{name} {WARNING}{t('choice.recommended')}{RESET}"
            preselected_index = idx
        elif is_integrated and choice == "None (Standard)":
            if is_beginner:
                name = f"{name}  ({t('wizard.driver_not_recommended')})"
        formatted_choices.append(Choice(title=name, value=value))
        
    back_ch = _back_choice()
    quit_ch = _quit_choice()
    formatted_choices.append(Choice(title=back_ch["name"], value=back_ch["value"]))
    formatted_choices.append(Choice(title=quit_ch["name"], value=quit_ch["value"]))
    
    default_choice = formatted_choices[preselected_index].value
    
    ans = numbered_select(
        t("wizard.select_driver") or "Select Stepper Driver Type:",
        choices=formatted_choices,
        default=preselected_index
    )
    
    if ans == _QUIT or ans is None: raise WizardExit()
    if ans == _BACK: return _BACK
    
    if not is_integrated and not is_socketed and ans == "None (Standard)":
        confirm_standalone = yes_no(
            t("wizard.confirm_standalone"),
            default=False
        )
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
                name = f"{mode} {WARNING}{t('choice.recommended')}{RESET}"
            preselected_mode_index = idx
        formatted_modes.append(Choice(title=name, value=value))
        
    back_ch = _back_choice()
    quit_ch = _quit_choice()
    formatted_modes.append(Choice(title=back_ch["name"], value=back_ch["value"]))
    formatted_modes.append(Choice(title=quit_ch["name"], value=quit_ch["value"]))
    
    default_mode = formatted_modes[preselected_mode_index].value
    
    ans = numbered_select(
        t("wizard.select_driver_mode", driver=user_data["driver_type"]) or f"Select communication mode for {user_data['driver_type']}:",
        choices=formatted_modes,
        default=preselected_mode_index
    )
    
    if ans == _QUIT or ans is None: raise WizardExit()
    if ans == _BACK: return _BACK
    user_data["driver_mode"] = ans
    return ans



def _step_tmc_currents(user_data):
    """Review unresolved TMC settings after mapping; commit only on acceptance."""
    original = copy.deepcopy(user_data)
    staged = copy.deepcopy(user_data)
    if _apply_z_tmc_mappings(staged) == _BACK:
        return _BACK
    board = staged.get("board_parsed") or {}
    _, provenance = resolve_generation_values(board, staged, validate_motors=False)
    missing = [key for key, owner in provenance.items()
               if key.startswith(("run_current_", "hold_current_", "stealthchop_threshold_")) and owner == "UNRESOLVED"]
    if missing and os.environ.get("KACE_AUTO") == "1":
        raise GenerationError("Explicit TMC settings required: " + ", ".join(missing))
    if missing:
        print(f"\n{SECTION}{t('wizard.tmc_current.title')}{RESET}")
        print(t("wizard.tmc_current.help"))
    for key in missing:
        model = canonical_tmc_model(staged.get("driver_type", ""))
        option, target = key.rsplit("_", 1)
        optional = option != "run_current"
        def validate(value):
            if optional and not str(value).strip():
                return True
            try:
                tmc_setting_value(model, option, value)
                return True
            except GenerationError:
                return t("wizard.tmc_current.invalid")
        label = "wizard.tmc_current.input" if not optional else "wizard.tmc_current." + option
        value = simple_input(t(label, motor=target.upper()),
                             default="", validate=validate, back_value=_BACK)
        if value == _BACK:
            return _BACK
        if value in (None, _QUIT):
            raise WizardExit()
        if optional and not str(value).strip():
            staged.pop(key, None)
            staged.get("_value_provenance", {}).pop(key, None)
            receipts = staged.get("_tmc_current_confirmations")
            if isinstance(receipts, dict):
                receipts.pop(key, None)
            continue
        try:
            staged[key] = tmc_setting_value(model, option, value)
        except GenerationError:
            print(f"{ERROR}{t('wizard.tmc_current.invalid')}{RESET}")
            return "__retry__"
        mark_user_override(staged, key)
    if missing:
        reviewed, owners = resolve_generation_values(board, staged, validate_motors=False)
        for key in missing:
            option, target = key.rsplit("_", 1)
            value = reviewed.get(key, t("wizard.tmc_current.omitted"))
            unit = "mm/s" if option == "stealthchop_threshold" else "A RMS"
            print(f"  {target.upper()} · {option}: {value}" + (f" {unit}" if key in reviewed else ""))
            if owners.get(key) == "UNRESOLVED":
                print(f"{ERROR}{t('wizard.tmc_current.invalid')}{RESET}")
                return "__retry__"
        if not yes_no(t("wizard.tmc_current.confirm"), default=False):
            return "__retry__"
    if user_data != original:
        print(f"{WARNING}{t('wizard.tmc_current.changed')}{RESET}")
        return "__retry__"
    user_data.clear()
    user_data.update(staged)
    return "done"


def _apply_z_tmc_mappings(user_data: dict) -> str | None:
    """Post-processing step: maps Z stepper TMC configurations."""
    from core.tmc_socket import selected_socket_sections
    if isinstance(user_data.get("board_parsed"), dict):
        user_data["board_parsed"].update(selected_socket_sections(user_data["board_parsed"], user_data))
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
    model = canonical_tmc_model(driver_type)

    for motor_name, selected_driver in assignments.items():
        dest_tmc = f"{model} {motor_name}"

        if selected_driver == "custom":
            if driver_mode in ["UART", "SPI"]:
                # Prompt for custom pin
                pin_key = "uart_pin" if driver_mode == "UART" else "cs_pin"
                if dest_tmc not in parsed_data or pin_key not in parsed_data[dest_tmc]:
                    if os.environ.get("KACE_AUTO") == "1":
                        raise GenerationError(f"{dest_tmc}: explicit {pin_key} required.")
                    uart_pin = simple_input(
                        t("wizard.custom_uart_pin", mode=driver_mode.lower(), motor=motor_name),
                        validate=questionary_pin_validator,
                        back_value=_BACK,
                    )
                    if uart_pin == _BACK:
                        return _BACK
                    if not uart_pin:
                        print(f"\n{ERROR}{t('kace.abort_no_uart', mode=driver_mode)}{RESET}")
                        raise WizardExit()
                    parsed_data.setdefault(dest_tmc, {})[pin_key] = uart_pin
        else:
            if dest_tmc in parsed_data:
                # Already mapped, explicitly configured, or reviewed socket wiring.
                continue
            # Socket assignment does not authorize changing the driver model.
            src_tmc = f"{model} {selected_driver}"
            tmc_src_data = parsed_data.get(src_tmc) or _parsed_full.get(src_tmc)
            if tmc_src_data is not None:
                parsed_data[dest_tmc] = tmc_src_data.copy()
                parsed_data.pop(src_tmc, None)
            elif driver_mode in ["UART", "SPI"]:
                print(f"\n{ERROR}{t('kace.abort_no_tmc_map', mode=driver_mode, driver=selected_driver, model=driver_type, board=user_data.get('board') or '?')}{RESET}")
                print(f"{WARNING}{t('kace.abort_generation')}{RESET}")
                raise WizardExit()
