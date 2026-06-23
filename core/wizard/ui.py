import os
from core.translations import t, get_mode
from core.wizard.runner import PHASE_MAP, PHASE_KEYS, PHASE_ORDER, _BACK, _QUIT


def _get_active_phase_steps(phase: str, user_data: dict) -> list:
    """Dynamically determine which steps in the given phase are active/visible."""
    all_steps = [step_id for step_id, p in PHASE_MAP.items() if p == phase]
    active = []
    for step_id in all_steps:
        if step_id == "fan_assignment":
            from core.wizard.steps.hardware import _has_fan_options
            if not _has_fan_options(user_data):
                continue
        elif step_id == "z_socket_assignment":
            z_motors = user_data.get("z_motors")
            if z_motors is None or int(z_motors) <= 1:
                continue
        elif step_id == "driver_mode":
            d_type = user_data.get("driver_type")
            if d_type in ["None (Standard)", "A4988", "DRV8825"]:
                continue
        elif step_id == "profile_review":
            if not user_data.get("profile_loaded"):
                continue
        elif step_id == "kinematics":
            if "kinematics" in user_data.get("_authoritative", set()):
                continue
        elif step_id == "x_volume":
            if "x_size" in user_data.get("_authoritative", set()):
                continue
        elif step_id == "y_volume":
            if "y_size" in user_data.get("_authoritative", set()):
                continue
        elif step_id == "z_volume":
            if "z_size" in user_data.get("_authoritative", set()):
                continue
        elif step_id == "x_limits":
            if "x_position_min" in user_data.get("_authoritative", set()):
                continue
        elif step_id == "y_limits":
            if "y_position_min" in user_data.get("_authoritative", set()):
                continue
        elif step_id == "z_limits":
            if "z_position_min" in user_data.get("_authoritative", set()):
                continue
        elif step_id == "probe_offsets":
            probe = user_data.get("probe")
            if probe is None or probe == "None":
                continue
        elif step_id == "hotend_therm":
            if "hotend_thermistor" in user_data.get("_authoritative", set()):
                continue
        elif step_id == "bed_therm":
            if "bed_thermistor" in user_data.get("_authoritative", set()):
                continue
        active.append(step_id)
    return active


def _print_step_header(step_id: str, user_data: dict) -> None:
    """Print a visually rich step header box in stdout if quiet/auto mode is not enabled."""
    if get_mode() == "Advanced":
        return
    if os.environ.get("KACE_TESTING") == "1":
        return
    if os.environ.get("KACE_AUTO") == "1":
        return
    if os.environ.get("KACE_QUIET") == "1":
        return

    phase = PHASE_MAP.get(step_id)
    if not phase:
        return

    # Translate phase name
    phase_key = PHASE_KEYS.get(phase)
    translated_phase = t(phase_key) if phase_key else phase

    # Get active steps in phase
    active_steps = _get_active_phase_steps(phase, user_data)
    try:
        step_idx = active_steps.index(step_id) + 1
    except ValueError:
        step_idx = 1
    total_steps = len(active_steps)

    # Get header and hint translations
    header_key = f"wizard.step.{step_id}.header"
    hint_key = f"wizard.step.{step_id}.hint"
    header_text = t(header_key)
    hint_text = t(hint_key)

    # Styling colors
    C_BORDER = "\033[36m"   # Cyan border
    C_PHASE = "\033[1;96m"  # Bold Cyan phase name
    C_STEP = "\033[1;92m"   # Bold Green step counter
    C_HEADER = "\033[1;97m" # Bold White step header
    C_HINT = "\033[37m"     # Light gray hint
    C_RESET = "\033[0m"

    lbl_phase = t("wizard.phase_label") or "Phase"
    lbl_step = t("wizard.step_label") or "Step"
    lbl_of = t("wizard.of_label") or "of"

    # Print the beautiful UI block
    box_width = 72
    print(f"\n{C_BORDER}┌" + "─" * (box_width - 2) + f"┐{C_RESET}")
    
    # Phase & Step progress line
    content = f"{lbl_phase}: {translated_phase} | {lbl_step} {step_idx} {lbl_of} {total_steps}"
    padding_len = box_width - 4 - len(content)
    left_padding = padding_len // 2
    right_padding = padding_len - left_padding
    print(f"{C_BORDER}│ {C_RESET}{' ' * left_padding}{C_PHASE}{lbl_phase}: {translated_phase}{C_RESET} | {C_STEP}{lbl_step} {step_idx} {lbl_of} {total_steps}{C_RESET}{' ' * right_padding} {C_BORDER}│{C_RESET}")
    
    print(f"{C_BORDER}├" + "─" * (box_width - 2) + f"┤{C_RESET}")
    
    # Header line
    header_line = f"  {header_text}"
    header_padding = box_width - 4 - len(header_line)
    if header_padding > 0:
        print(f"{C_BORDER}│ {C_HEADER}{header_line}{C_RESET}{' ' * header_padding} {C_BORDER}│{C_RESET}")
    else:
        print(f"{C_BORDER}│ {C_HEADER}{header_line[:box_width-4]}{C_RESET} {C_BORDER}│{C_RESET}")
        
    # Hint line(s) (word wrap to fit box_width - 4)
    words = hint_text.split()
    lines = []
    current_line = "  "
    for word in words:
        if len(current_line) + len(word) + 1 <= box_width - 4:
            if current_line == "  ":
                current_line += word
            else:
                current_line += " " + word
        else:
            lines.append(current_line)
            current_line = "  " + word
    if current_line.strip():
        lines.append(current_line)
        
    for line in lines:
        line_padding = box_width - 4 - len(line)
        print(f"{C_BORDER}│ {C_HINT}{line}{C_RESET}{' ' * line_padding} {C_BORDER}│{C_RESET}")
        
    print(f"{C_BORDER}└" + "─" * (box_width - 2) + f"┘{C_RESET}\n")


def _back_choice():
    return {"name": t("choice.back"), "value": _BACK}


def _quit_choice():
    return {"name": t("choice.quit"), "value": _QUIT}


def _normalize_mcu_family(mcu: str) -> str:
    if not mcu:
        return ""
    m = mcu.lower()
    if m.startswith("lpc176"): return "lpc176x"
    if m.startswith("stm32f103"): return "stm32f103"
    if m.startswith("stm32f4"): return "stm32f4"
    if m.startswith("stm32g0b"): return "stm32g0b"
    if m.startswith("atmega2560"): return "atmega2560"
    if m.startswith("rp2040"): return "rp2040"
    return m


def get_current_board_parsed(user_data) -> dict:
    from core.scraper import fetch_raw_config, parse_config
    if user_data.get("board") == user_data.get("printer_profile") and user_data.get("profile_loaded"):
        raw = user_data.get("raw_config", "")
    else:
        board_name = user_data.get("board")
        if not board_name:
            return {}
        raw = fetch_raw_config(board_name)
    if not raw:
        return {}
    return parse_config(raw, user_data.get("board") or "", keep_comments=True)

