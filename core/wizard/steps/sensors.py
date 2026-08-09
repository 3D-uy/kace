import re
import os
from core.menu import autocomplete_select, simple_input, yes_no, numbered_select
from core.translations import t, get_lang
from core.exceptions import WizardExit
from core.validators import questionary_pin_validator, questionary_thermistor_validator
from core.probe_offset_visualizer import run_probe_offset_step
from core.profile_values import mark_user_override
from data.profiles import THERMISTOR_PRESETS
from core.wizard.runner import _BACK, _QUIT
from core.wizard.ui import _back_choice, _quit_choice
from core.custom_probe import (
    CustomProbeConfig,
    CustomProbeValidationError,
    GUIDED_PROBE_DEFAULTS,
    GuidedCustomProbeSettings,
)
from core.probe_configuration import (
    PROBE_KIND_BLTOUCH,
    PROBE_KIND_CR_TOUCH,
    PROBE_KIND_CUSTOM,
    PROBE_KIND_INDUCTIVE,
    PROBE_KIND_NONE,
    normalize_probe_kind,
)


def _get_parsed(user_data):
    import core.wizard
    return core.wizard.get_current_board_parsed(user_data)



def _step_probe(user_data):
    choices = [
        {"name": "None", "value": PROBE_KIND_NONE},
        {"name": "BLTouch", "value": PROBE_KIND_BLTOUCH},
        {"name": "Inductive", "value": PROBE_KIND_INDUCTIVE},
        {"name": "CR-Touch", "value": PROBE_KIND_CR_TOUCH},
        {"name": t("wizard.probe_custom"), "value": PROBE_KIND_CUSTOM},
        _back_choice(), _quit_choice(),
    ]
    default_kind = normalize_probe_kind(user_data.get("probe_kind") or user_data.get("probe"))
    default_idx = [
        PROBE_KIND_NONE, PROBE_KIND_BLTOUCH, PROBE_KIND_INDUCTIVE,
        PROBE_KIND_CR_TOUCH, PROBE_KIND_CUSTOM,
    ].index(default_kind)
    ans = numbered_select(
        t("wizard.select_probe"),
        choices=choices,
        default=default_idx
    )
    if ans == _QUIT or ans is None:
        raise WizardExit()
    if ans == _BACK:
        return _BACK
    display_names = {
        PROBE_KIND_NONE: "None",
        PROBE_KIND_BLTOUCH: "BLTouch",
        PROBE_KIND_INDUCTIVE: "Inductive",
        PROBE_KIND_CR_TOUCH: "CR-Touch",
        PROBE_KIND_CUSTOM: "Custom Probe",
    }
    user_data["probe_kind"] = ans
    user_data["probe"] = display_names[ans]  # legacy caller compatibility
    return ans


GUIDED_CUSTOM_PROBE_QUESTIONS = (
    ("custom_probe_z_offset", "wizard.custom_probe_z_offset", None, "optional_number"),
    ("custom_probe_samples", "wizard.custom_probe_samples", GUIDED_PROBE_DEFAULTS["samples"], "positive_int"),
    ("custom_probe_samples_tolerance", "wizard.custom_probe_samples_tolerance", GUIDED_PROBE_DEFAULTS["samples_tolerance"], "nonnegative_number"),
    ("custom_probe_samples_tolerance_retries", "wizard.custom_probe_samples_tolerance_retries", GUIDED_PROBE_DEFAULTS["samples_tolerance_retries"], "nonnegative_int"),
    ("custom_probe_speed", "wizard.custom_probe_speed", GUIDED_PROBE_DEFAULTS["speed"], "positive_number"),
    ("custom_probe_sample_retract_dist", "wizard.custom_probe_sample_retract_dist", GUIDED_PROBE_DEFAULTS["sample_retract_dist"], "positive_number"),
)


def _finite_numeric_validator(value: str, *, allow_empty: bool = False, minimum: float | None = None,
                              integer: bool = False):
    text = str(value or "").strip()
    if not text and allow_empty:
        return True
    try:
        parsed = float(text)
    except ValueError:
        return "Enter a finite number."
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return "Enter a finite number."
    if integer and not parsed.is_integer():
        return "Enter a whole number."
    if minimum is not None and parsed < minimum:
        return f"Enter a value of at least {minimum:g}."
    return True


def _guided_probe_validator(kind: str):
    validators = {
        "number": lambda value: _finite_numeric_validator(value),
        "optional_number": lambda value: _finite_numeric_validator(value, allow_empty=True),
        "positive_int": lambda value: _finite_numeric_validator(value, minimum=1, integer=True),
        "nonnegative_int": lambda value: _finite_numeric_validator(value, minimum=0, integer=True),
        "nonnegative_number": lambda value: _finite_numeric_validator(value, minimum=0),
        "positive_number": lambda value: _finite_numeric_validator(value, minimum=float.fromhex("0x1p-1022")),
    }
    return validators[kind]


def _step_guided_custom_probe_value(user_data, key: str):
    """Ask one reusable common-probe question; strategy-specific flows can extend this list."""
    question = next(item for item in GUIDED_CUSTOM_PROBE_QUESTIONS if item[0] == key)
    _, prompt_key, default, validator_kind = question
    value = simple_input(
        t(prompt_key),
        default=user_data.get(key, default),
        validate=_guided_probe_validator(validator_kind),
    )
    if value is None or str(value).strip().lower() in ("<", "back", "volver"):
        return _BACK
    user_data[key] = str(value).strip()
    return "done"


def _step_guided_custom_probe_offsets(user_data):
    """Collect custom-probe offsets with the shared live ASCII preview."""
    preview_data = dict(user_data)
    preview_data["probe"] = t("wizard.probe_custom")
    offset_result = run_probe_offset_step(
        user_data=preview_data,
        board_filename=user_data.get("board") or "",
    )
    if offset_result.get("probe_x_offset") == "__back__" or \
       offset_result.get("probe_y_offset") == "__back__":
        return _BACK

    for offset in ("x", "y"):
        value = offset_result.get(f"probe_{offset}_offset", "0")
        user_data[f"custom_probe_{offset}_offset"] = value
        user_data[f"probe_{offset}_offset"] = value
    return "done"


def _step_custom_probe_pin(user_data):
    """Prefer board-derived unassigned pins; manual input is a validated fallback."""
    dedicated = _get_dedicated_probe_pin(user_data)
    candidates = _get_unused_pins(user_data)
    if dedicated:
        dedicated_pin, pullup, inverted = dedicated
        user_data.setdefault("custom_probe_pullup", pullup)
        user_data.setdefault("custom_probe_inverted", inverted)
        candidates = [(t("wizard.custom_probe_dedicated_pin"), dedicated_pin)] + [
            candidate for candidate in candidates if candidate[1].upper() != dedicated_pin.upper()
        ]
    if candidates:
        choices = [
            {"name": f"{friendly} ({pin})" if friendly != pin else pin, "value": pin}
            for friendly, pin in candidates
        ]
        choices.extend([
            {"name": t("wizard.custom_probe_pin_manual"), "value": "__manual__"},
            _back_choice(), _quit_choice(),
        ])
        answer = autocomplete_select(t("wizard.custom_probe_pin"), choices=choices, default=0)
        if answer == _QUIT or answer is None:
            raise WizardExit()
        if answer == _BACK:
            return _BACK
        if answer != "__manual__":
            base_pin, pullup, inverted = _split_probe_pin_modifiers(answer)
            user_data["custom_probe_pin"] = base_pin
            user_data.setdefault("custom_probe_pullup", pullup)
            user_data.setdefault("custom_probe_inverted", inverted)
            return "done"

    value = simple_input(
        t("wizard.custom_probe_pin_manual_prompt"),
        default=user_data.get("custom_probe_pin", ""),
        validate=make_pin_validator_with_collision_check(user_data),
    )
    if value is None or str(value).strip().lower() in ("<", "back", "volver"):
        return _BACK
    base_pin, pullup, inverted = _split_probe_pin_modifiers(str(value).strip())
    user_data["custom_probe_pin"] = base_pin
    user_data.setdefault("custom_probe_pullup", pullup)
    user_data.setdefault("custom_probe_inverted", inverted)
    return "done"


def _split_probe_pin_modifiers(pin: str) -> tuple[str, bool, bool]:
    """Separate Klipper input modifiers so the wizard asks about each explicitly."""
    text = str(pin).strip()
    pullup = "^" in text[:3]
    inverted = "!" in text[:3]
    return text.lstrip("^!~"), pullup, inverted


def _get_dedicated_probe_pin(user_data) -> tuple[str, bool, bool] | None:
    """Return a board-defined probe connector before generic GPIO candidates."""
    probe_section = _get_parsed(user_data).get("bltouch", {})
    sensor_pin = probe_section.get("sensor_pin") if isinstance(probe_section, dict) else None
    if not sensor_pin or "TODO" in str(sensor_pin).upper():
        return None
    base_pin, pullup, inverted = _split_probe_pin_modifiers(str(sensor_pin))
    if not base_pin or base_pin.startswith("<"):
        return None
    return base_pin, pullup, inverted


def _step_custom_probe_signal_option(user_data, option: str):
    prompts = {
        "pullup": "wizard.custom_probe_pullup",
        "inverted": "wizard.custom_probe_inverted",
    }
    default = bool(user_data.get(f"custom_probe_{option}", False))
    user_data[f"custom_probe_{option}"] = yes_no(t(prompts[option]), default=default)
    return "done"


def _step_custom_probe_samples_result(user_data):
    choices = [
        {"name": t("wizard.custom_probe_samples_result_median"), "value": "median"},
        {"name": t("wizard.custom_probe_samples_result_average"), "value": "average"},
        _back_choice(), _quit_choice(),
    ]
    default = GUIDED_PROBE_DEFAULTS["samples_result"]
    current = user_data.get("custom_probe_samples_result", default)
    answer = numbered_select(t("wizard.custom_probe_samples_result"), choices=choices,
                             default=0 if current == "median" else 1)
    if answer == _QUIT or answer is None:
        raise WizardExit()
    if answer == _BACK:
        return _BACK
    user_data["custom_probe_samples_result"] = answer
    return "done"


def _step_custom_probe(user_data):
    """Build the validated typed custom probe payload from guided wizard answers."""
    required = ("custom_probe_pin", "custom_probe_x_offset", "custom_probe_y_offset")
    missing = [key for key in required if user_data.get(key) in (None, "")]
    if missing:
        print(f"\n[!] {t('wizard.custom_probe_missing_fields')}\n")
        return "__retry__"
    try:
        z_text = user_data.get("custom_probe_z_offset", "")
        pin_prefix = ("^" if user_data.get("custom_probe_pullup") else "") + (
            "!" if user_data.get("custom_probe_inverted") else ""
        )
        settings = GuidedCustomProbeSettings(
            pin=pin_prefix + user_data["custom_probe_pin"],
            x_offset=float(user_data["custom_probe_x_offset"]),
            y_offset=float(user_data["custom_probe_y_offset"]),
            z_offset=float(z_text) if str(z_text).strip() else None,
            samples=int(float(user_data.get("custom_probe_samples", GUIDED_PROBE_DEFAULTS["samples"]))),
            samples_tolerance=float(user_data.get("custom_probe_samples_tolerance", GUIDED_PROBE_DEFAULTS["samples_tolerance"])),
            samples_tolerance_retries=int(float(user_data.get("custom_probe_samples_tolerance_retries", GUIDED_PROBE_DEFAULTS["samples_tolerance_retries"]))),
            speed=float(user_data.get("custom_probe_speed", GUIDED_PROBE_DEFAULTS["speed"])),
            samples_result=user_data.get("custom_probe_samples_result", GUIDED_PROBE_DEFAULTS["samples_result"]),
            sample_retract_dist=float(user_data.get("custom_probe_sample_retract_dist", GUIDED_PROBE_DEFAULTS["sample_retract_dist"])),
        )
        user_data["custom_probe_settings"] = settings
        user_data["custom_probe"] = settings.to_config()
    except (ValueError, CustomProbeValidationError) as exc:
        print(f"\n[!] {t('wizard.custom_probe_invalid')}: {exc}\n")
        return "__retry__"

    user_data["probe_x_offset"] = f"{settings.x_offset:g}"
    user_data["probe_y_offset"] = f"{settings.y_offset:g}"
    return "done"


def _step_custom_probe_review(user_data):
    """Show the exact KACE-generated section before continuing the wizard."""
    custom_probe = user_data.get("custom_probe")
    if not isinstance(custom_probe, CustomProbeConfig):
        return "__retry__"
    print(f"\n{t('wizard.custom_probe_review')}\n\n{custom_probe.config_text}\n")
    return "done"


def _custom_offset_validator(value: str):
    try:
        parsed = float(value.strip())
    except (TypeError, ValueError):
        return "Enter a finite number (for example: -38, 0, or 23.5)."
    return parsed == parsed and parsed not in (float("inf"), float("-inf"))


def _step_custom_probe_offsets(user_data):
    """Ask only for offsets absent from the custom block, then append them once."""
    custom_probe = user_data.get("custom_probe")
    if not isinstance(custom_probe, CustomProbeConfig):
        print("\n[!] Custom probe data is missing. Please enter the configuration again.\n")
        return _BACK

    supplied = {}
    if custom_probe.x_offset is None:
        value = simple_input(t("wizard.custom_probe_x_offset"), validate=_custom_offset_validator)
        if value is None:
            return _BACK
        supplied["x_offset"] = value
    if custom_probe.y_offset is None:
        value = simple_input(t("wizard.custom_probe_y_offset"), validate=_custom_offset_validator)
        if value is None:
            return _BACK
        supplied["y_offset"] = value

    try:
        custom_probe = custom_probe.with_missing_offsets(**supplied)
    except CustomProbeValidationError as exc:
        print(f"\n[!] Invalid custom probe offsets: {exc}\n")
        return "__retry__"

    user_data["custom_probe"] = custom_probe
    user_data["probe_x_offset"] = str(custom_probe.x_offset)
    user_data["probe_y_offset"] = str(custom_probe.y_offset)
    return "done"


def _needs_bltouch_pins(user_data) -> bool:
    parsed_board = _get_parsed(user_data)
    blt = parsed_board.get("bltouch", {})
    s_pin = blt.get("sensor_pin")
    c_pin = blt.get("control_pin")

    def is_missing(p):
        if not p:
            return True
        p_clean = str(p).strip().upper().lstrip('^!~')
        return p_clean == "TODO" or p_clean == ""

    return is_missing(s_pin) or is_missing(c_pin)


def _get_mcu_for_board(board_name: str) -> str:
    if not board_name:
        return ""
    try:
        from core.loader import load_boards_yaml
        db = load_boards_yaml()
        board_lower = board_name.lower()
        for entry in db.get('boards', []):
            mcu = entry.get('mcu', '')
            search_terms = entry.get('search_terms', [])
            for term in search_terms:
                if term.lower() in board_lower:
                    return mcu
    except Exception:
        pass
    return ""


def _parse_and_normalize_pin(pin_str: str) -> str:
    """Normalize a Klipper pin string to a bare uppercase pin identifier.

    Strips:
    - Leading/trailing whitespace
    - Klipper logic modifiers: !, ^, ~  (before and after an MCU prefix)
    - MCU ownership prefix: e.g. toolhead:, mcu:, z: are removed

    Examples:
        'toolhead:gpio5'  -> 'GPIO5'
        '!toolhead:!gpio5' -> 'GPIO5'
        '^PA0'            -> 'PA0'
        'z:P1.27'         -> 'P1.27'
        'PB1'             -> 'PB1'
    """
    if not isinstance(pin_str, str):
        return ""
    cleaned = pin_str.strip().lstrip('!^~')
    if not cleaned:
        return ""
    if ':' in cleaned:
        # Strip the MCU prefix entirely — pins are globally unique physical lines
        pin_part = cleaned.split(':', 1)[1].strip().lstrip('!^~')
        return pin_part.upper()
    return cleaned.upper()


def _get_unused_pins(user_data) -> list:
    """Scan parsed board config for all used pins, and return a list of typical unused microcontroller pins."""
    parsed_board = _get_parsed(user_data)
    
    # Collect all normalized (prefix-stripped) used pins
    used_pins = set()
    for section, sdata in parsed_board.items():
        if isinstance(sdata, dict):
            for key, val in sdata.items():
                if isinstance(val, str):
                    pin_p = _parse_and_normalize_pin(val)
                    if pin_p:
                        used_pins.add(pin_p.lower())
                    
    # Identify the MCU family for generating candidate pins
    board_name = user_data.get("board", "")
    mcu = _get_mcu_for_board(board_name)
    if not mcu:
        mcu = user_data.get("mcu_type", "").lower()
    else:
        mcu = mcu.lower()
        
    # Collect alias pin names from [board_pins] so we can suggest human-readable aliases
    board_pins = parsed_board.get("board_pins", {})
    aliases_str = board_pins.get("aliases", "") if isinstance(board_pins, dict) else ""
    all_alias_pins = {}
    if aliases_str:
        # e.g. EXP1_1=PB5, EXP1_2=PB6
        for part in aliases_str.replace('\n', ',').split(','):
            if '=' in part:
                parts = part.split('=', 1)
                alias_name = parts[0].strip()
                target_pin = parts[1].strip()
                if target_pin:
                    pin_a = _parse_and_normalize_pin(target_pin)
                    if pin_a:
                        all_alias_pins[pin_a.lower()] = alias_name
                    
    # Generate candidate pins for the MCU architecture
    all_mcu_pins = []
    if "1284" in mcu or "atmega1284" in mcu:
        # Melzi / AVR 1284p
        all_mcu_pins = [f"PA{i}" for i in range(8)] + [f"PB{i}" for i in range(8)] + [f"PC{i}" for i in range(8)] + [f"PD{i}" for i in range(8)]
    elif "2560" in mcu or "atmega2560" in mcu:
        all_mcu_pins = [f"PA{i}" for i in range(8)] + [f"PB{i}" for i in range(8)] + [f"PC{i}" for i in range(8)] + [f"PD{i}" for i in range(8)] + \
                       [f"PE{i}" for i in range(8)] + [f"PF{i}" for i in range(8)] + [f"PG{i}" for i in range(6)] + [f"PH{i}" for i in range(8)] + \
                       [f"PJ{i}" for i in range(8)] + [f"PK{i}" for i in range(8)] + [f"PL{i}" for i in range(8)]
    elif "stm32" in mcu:
        all_mcu_pins = [f"PA{i}" for i in range(16)] + [f"PB{i}" for i in range(16)] + [f"PC{i}" for i in range(16)] + [f"PD{i}" for i in range(16)] + \
                       [f"PE{i}" for i in range(16)] + [f"PF{i}" for i in range(16)] + [f"PG{i}" for i in range(16)] + [f"PH{i}" for i in range(16)]
    elif "rp2040" in mcu:
        all_mcu_pins = [f"gpio{i}" for i in range(30)]
    elif "lpc176" in mcu:
        all_mcu_pins = [f"P0.{i}" for i in range(32)] + [f"P1.{i}" for i in range(32)] + [f"P2.{i}" for i in range(14)]
        
    unused = []
    # First suggest EXP alias pins that are not used
    for pin_lower, alias in all_alias_pins.items():
        if pin_lower not in used_pins:
            unused.append((alias, pin_lower.upper()))
            
    # Then suggest raw unused MCU pins
    for pin in all_mcu_pins:
        if pin.lower() not in used_pins and pin.lower() not in all_alias_pins:
            unused.append((pin, pin.upper()))
            
    # Alias tables often include power, ground, reset, or no-connect entries.
    # They are not GPIO inputs and must never be offered as probe candidates.
    # Keep one friendly name per physical pin to avoid duplicated menu entries.
    filtered = []
    seen_pins = set()
    for friendly, pin in unused:
        normalized = _parse_and_normalize_pin(pin)
        if not normalized or normalized.startswith("<"):
            continue
        if questionary_pin_validator(normalized) is not True:
            continue
        key = normalized.lower()
        if key in seen_pins:
            continue
        seen_pins.add(key)
        filtered.append((friendly, pin))
    return filtered


def make_pin_validator_with_collision_check(user_data):
    parsed_board = _get_parsed(user_data)
    
    # Pre-build a map of normalized-pin -> component name.
    # MCU prefixes are stripped so that toolhead:gpio5 and gpio5 map to the
    # same physical line and will correctly collide.
    used_pins_map = {}
    aliases = []
    
    if isinstance(parsed_board, dict):
        # Extract aliases from [board_pins]
        board_pins = parsed_board.get("board_pins", {})
        aliases_str = board_pins.get("aliases", "") if isinstance(board_pins, dict) else ""
        if aliases_str:
            for part in aliases_str.replace('\n', ',').split(','):
                if '=' in part:
                    alias_name = part.split('=', 1)[0].strip()
                    if alias_name:
                        aliases.append(alias_name)
                        
        for section, sdata in parsed_board.items():
            if isinstance(sdata, dict):
                for key, val in sdata.items():
                    if isinstance(val, str):
                        pin_p = _parse_and_normalize_pin(val)
                        if pin_p:
                            comp = section
                            if section.startswith("stepper_"):
                                comp = f"stepper {section.replace('stepper_', '').upper()}"
                            used_pins_map[pin_p] = f"{comp} ({key})"

    def validator(value: str):
        val_strip = value.strip()
        val_lower = val_strip.lower()
        if val_lower in ("<", "back", "volver"):
            return True
            
        # Standard format check first
        fmt_res = questionary_pin_validator(val_strip)
        if fmt_res != True:
            return fmt_res
            
        # Collision check — normalize by stripping MCU prefix and modifiers
        pin = _parse_and_normalize_pin(val_strip)
        if not pin:
            return "Invalid Klipper pin format"
            
        if pin in used_pins_map:
            lang = get_lang()
            comp_info = used_pins_map[pin]
            # Display the original user input for clarity in the error message
            display_pin = val_strip
            if lang == "Español":
                return f"El pin {display_pin} ya está en uso por: {comp_info}"
            elif lang == "Português":
                return f"O pino {display_pin} já está em uso por: {comp_info}"
            else:
                return f"Pin {display_pin} is already in use by: {comp_info}"
                
        # MCU specific physical pin checks — only for pins without an MCU prefix,
        # since secondary MCU pins (e.g. toolhead:gpio5) are not constrained by
        # the primary mainboard's architecture patterns.
        is_prefixed = ':' in val_strip
        board_name = user_data.get("board", "")
        mcu_type = _get_mcu_for_board(board_name)
        if not mcu_type:
            mcu_type = user_data.get("mcu_type", "").lower()
        else:
            mcu_type = mcu_type.lower()
            
        if mcu_type and not is_prefixed:
            pin_clean = pin.lower()
            
            # Check if it is a defined board alias
            is_alias = False
            for alias in aliases:
                if pin_clean == alias.lower():
                    is_alias = True
                    break
                    
            if not is_alias:
                # Validate against MCU architecture specs
                if "1284" in mcu_type or "atmega1284" in mcu_type:
                    if not re.match(r'^p[a-d][0-7]$', pin_clean):
                        lang = get_lang()
                        if lang == "Español":
                            return f"Pin inválido para ATMEGA1284P. Debe ser tipo PA0-PD7 (ej. PA5)."
                        elif lang == "Português":
                            return f"Pino inválido para ATMEGA1284P. Deve ser tipo PA0-PD7 (ex. PA5)."
                        else:
                            return f"Invalid pin for ATMEGA1284P. Must be PA0-PD7 (e.g. PA5)."
                            
                elif "2560" in mcu_type or "atmega2560" in mcu_type or mcu_type == "avr":
                    if not (re.match(r'^p[a-l][0-7]$', pin_clean) or re.match(r'^(ar|analog)\d+$', pin_clean)):
                        lang = get_lang()
                        if lang == "Español":
                            return f"Pin inválido para AVR/ATMEGA2560. Debe ser tipo PA0-PL7 o ar0-ar69."
                        elif lang == "Português":
                            return f"Pino inválido para AVR/ATMEGA2560. Deve ser tipo PA0-PL7 o ar0-ar69."
                        else:
                            return f"Invalid pin for AVR/ATMEGA2560. Must be PA0-PL7 or ar0-ar69."
                            
                elif "stm32" in mcu_type:
                    if not re.match(r'^p[a-i](1[0-5]|\d)$', pin_clean):
                        lang = get_lang()
                        if lang == "Español":
                            return f"Pin inválido para STM32. Debe ser tipo PA0-PI15 (ej. PB7)."
                        elif lang == "Português":
                            return f"Pino inválido para STM32. Deve ser tipo PA0-PI15 (ex. PB7)."
                        else:
                            return f"Invalid pin for STM32. Must be PA0-PI15 (e.g. PB7)."
                            
                elif "rp2040" in mcu_type:
                    if not re.match(r'^gpio(2[0-9]|[0-1]?\d)$', pin_clean):
                        lang = get_lang()
                        if lang == "Español":
                            return f"Pin inválido para RP2040. Debe ser tipo gpio0-gpio29."
                        elif lang == "Português":
                            return f"Pino inválido para RP2040. Deve ser tipo gpio0-gpio29."
                        else:
                            return f"Invalid pin for RP2040. Must be gpio0-gpio29."
                            
                elif "lpc176" in mcu_type:
                    if not re.match(r'^p[0-4]\.(3[0-1]|[0-2]?\d)$', pin_clean):
                        lang = get_lang()
                        if lang == "Español":
                            return f"Pin inválido para LPC176x. Debe ser tipo P0.0-P4.29 (ej. P0.10)."
                        elif lang == "Português":
                            return f"Pino inválido para LPC176x. Deve ser tipo P0.0-P4.29 (ex. P0.10)."
                        else:
                            return f"Invalid pin for LPC176x. Must be P0.0-P4.29 (e.g. P0.10)."
                            
        return True
        
    return validator


def _step_bltouch_pins(user_data):
    parsed_board = _get_parsed(user_data)
    blt = parsed_board.get("bltouch", {})
    missing_sensor = not blt.get("sensor_pin")
    missing_control = not blt.get("control_pin")
    
    if os.environ.get("KACE_AUTO") != "1" and os.environ.get("KACE_QUIET") != "1":
        board_name = user_data.get("board", "")
        unused = _get_unused_pins(user_data)
        lang = get_lang()
        if lang == "Español":
            msg = f"\n[!] Se seleccionó BLTouch/CR-Touch pero se desconoce el mapa de pines para la placa:\n    {board_name}\n"
            msg += "    Ingrese los pines manualmente a continuación (puedes escribir '<' o 'volver' para regresar).\n"
            if unused:
                suggested_str = ", ".join([f"{u[0]}" for u in unused[:6]])
                msg += f"    Pines no asignados que podrían estar libres: {suggested_str}\n"
        elif lang == "Português":
            msg = f"\n[!] BLTouch/CR-Touch selecionado, mas o mapeamento de pinos é desconhecido para a placa:\n    {board_name}\n"
            msg += "    Insira os pinos manualmente abaixo (digite '<' ou 'voltar' para retornar).\n"
            if unused:
                suggested_str = ", ".join([f"{u[0]}" for u in unused[:6]])
                msg += f"    Pinos não atribuídos que podem estar livres: {suggested_str}\n"
        else:
            msg = f"\n[!] BLTouch/CR-Touch selected but pin mapping is unknown for board:\n    {board_name}\n"
            msg += "    Enter the pins manually below (you can type '<' or 'back' to go back).\n"
            if unused:
                suggested_str = ", ".join([f"{u[0]}" for u in unused[:6]])
                msg += f"    Unassigned pins that might be free: {suggested_str}\n"
        print(msg)

    prompts = []
    if missing_sensor:
        prompts.append("sensor")
    if missing_control:
        prompts.append("control")
        
    idx = 0
    while idx < len(prompts):
        current_prompt = prompts[idx]
        if current_prompt == "sensor":
            sp = simple_input(
                t("wizard.bltouch_sensor_prompt") or "BLTouch sensor_pin (e.g. ^PB7 or ^PC5):",
                default=user_data.get("bltouch_sensor_pin") or "",
                validate=make_pin_validator_with_collision_check(user_data)
            )
            if sp is None or sp.strip().lower() in ("<", "back", "volver"):
                return _BACK
            user_data["bltouch_sensor_pin"] = sp.strip()
            idx += 1
            
        elif current_prompt == "control":
            cp = simple_input(
                t("wizard.bltouch_control_prompt") or "BLTouch control_pin (e.g. PB6 or PE5):",
                default=user_data.get("bltouch_control_pin") or "",
                validate=make_pin_validator_with_collision_check(user_data)
            )
            if cp is None or cp.strip().lower() in ("<", "back", "volver"):
                if idx > 0:
                    idx -= 1
                    continue
                else:
                    return _BACK
            user_data["bltouch_control_pin"] = cp.strip()
            idx += 1
            
    return "done"


def _step_probe_offsets(user_data):
    offset_result = run_probe_offset_step(
        user_data=user_data,
        board_filename=user_data.get("board") or "",
    )
    if offset_result.get("probe_x_offset") == "__back__" or \
       offset_result.get("probe_y_offset") == "__back__":
        return _BACK
    user_data["probe_x_offset"] = offset_result.get("probe_x_offset", "0")
    user_data["probe_y_offset"] = offset_result.get("probe_y_offset", "0")
    mark_user_override(user_data, "probe_x_offset", "probe_y_offset")
    return "done"


def _step_therm(user_data, therm_key, select_msg, custom_msg):
    if therm_key in user_data.get("_authoritative", set()):
        return user_data[therm_key]
    preset_choices = list(THERMISTOR_PRESETS)
    if user_data[therm_key] not in preset_choices:
        preset_choices.insert(0, user_data[therm_key])
    choices = preset_choices + [{"name": t("choice.other_manual"), "value": "__other__"}, _back_choice(), _quit_choice()]

    # Find default index
    default_val = user_data[therm_key]
    default_idx = 0
    for idx_c, choice in enumerate(choices):
        if isinstance(choice, dict) and choice.get("value") == default_val:
            default_idx = idx_c
            break
        elif choice == default_val:
            default_idx = idx_c
            break

    ans = numbered_select(
        select_msg,
        choices=choices,
        default=default_idx
    )
    if ans == _QUIT or ans is None:
        raise WizardExit()
    if ans == _BACK:
        return _BACK
    if ans == "__other__":
        manual_ans = simple_input(custom_msg, validate=questionary_thermistor_validator)
        if manual_ans is None:
            return "__retry__"
        user_data[therm_key] = manual_ans
    else:
        user_data[therm_key] = ans
    mark_user_override(user_data, therm_key)
    return ans
