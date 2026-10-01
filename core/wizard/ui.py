import os
from core.translations import t, get_mode
from core.wizard.runner import PHASE_MAP, PHASE_KEYS, _BACK, _QUIT
from core.terminal import HINT, INPUT, QUESTION, RESET, SECTION


_SUPPRESS_HEADERS = False

def set_suppress_headers(suppress: bool) -> None:
    """Toggle suppression of UI step headers (useful in test runner context)."""
    global _SUPPRESS_HEADERS
    _SUPPRESS_HEADERS = suppress

def _print_step_header(step_id: str, user_data: dict, *, active_steps=None) -> None:
    """Print a visually rich step header box in stdout if quiet/auto mode is not enabled."""
    if get_mode() == "Advanced":
        return
    if _SUPPRESS_HEADERS:
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
    active_steps = active_steps if active_steps is not None else [step_id]
    try:
        step_idx = active_steps.index(step_id) + 1
    except ValueError:
        step_idx = 1

    # Get header and hint translations
    header_key = f"wizard.step.{step_id}.header"
    hint_key = f"wizard.step.{step_id}.hint"
    if step_id.startswith("custom_probe"):
        header_key = ("wizard.step.probe_offsets.header" if step_id in
                      ("custom_probe_offset_preview", "custom_probe_offsets") else f"wizard.step.{step_id}.header")
        hint_key = "wizard.step.probe_offsets.hint" if step_id.endswith(("preview", "offsets")) else "wizard.custom_probe_guided_hint"
    header_text = t(header_key)
    hint_text = t(hint_key)

    # Styling colors
    C_BORDER = SECTION
    C_PHASE = SECTION
    C_STEP = INPUT
    C_HEADER = QUESTION
    C_HINT = HINT
    C_RESET = RESET

    lbl_phase = t("wizard.phase_label") or "Phase"
    lbl_step = t("wizard.step_label") or "Step"

    # Print the beautiful UI block
    box_width = 72
    print(f"\n{C_BORDER}┌" + "─" * (box_width - 2) + f"┐{C_RESET}")
    
    # Phase & Step progress line
    content = f"{lbl_phase}: {translated_phase} | {lbl_step} {step_idx}"
    padding_len = box_width - 4 - len(content)
    left_padding = padding_len // 2
    right_padding = padding_len - left_padding
    print(f"{C_BORDER}│ {C_RESET}{' ' * left_padding}{C_PHASE}{lbl_phase}: {translated_phase}{C_RESET} | {C_STEP}{lbl_step} {step_idx}{C_RESET}{' ' * right_padding} {C_BORDER}│{C_RESET}")
    
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
