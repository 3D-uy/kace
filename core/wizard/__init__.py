import sys
import os
import copy
from core.translations import t, get_lang
from firmware.detector import discover_mcu_hardware


# Scraper functions
from core.scraper import (
    fetch_config_list,
    fetch_raw_config,
    parse_config,
    extract_profile_defaults,
    detect_driver_info,
    is_socketed_board,
    get_reusable_driver_sockets,
    detect_fan_pins,
)

# Custom styling and thermistors
from core.style import custom_style
from data.profiles import THERMISTOR_PRESETS

# Sub-wizards and helpers
from core.display_wizard import run_display_setup_step
from core.probe_offset_visualizer import run_probe_offset_step
from core.exceptions import WizardExit
from core.probe_configuration import normalize_probe_kind
from core.validators import (
    questionary_pin_validator,
    questionary_numeric_validator,
    questionary_pos_numeric_validator,
)

# Re-export runner and UI symbols
from core.wizard.runner import WizardRunner, PHASE_MAP, PHASE_KEYS, PHASE_ORDER, _BACK, _QUIT
from core.wizard.ui import (
    _back_choice,
    _quit_choice,
    _normalize_mcu_family,
    get_current_board_parsed,
    _print_step_header,
    _get_active_phase_steps,
)

# Re-export step submodules
from core.wizard.steps.hardware import (
    _step_board,
    _step_fan_assignment,
    _step_z_motors,
    _step_z_socket_assignment,
    _step_driver_type,
    _step_driver_mode,
    _apply_z_tmc_mappings,
    _has_fan_options,
    _get_mcu_search_terms,
    _load_mcu_search_terms,
)
from core.wizard.steps.motion import (
    _step_printer_profile,
    _step_profile_review,
    _step_kinematics,
    _step_volume,
    _step_x_limits,
    _step_y_limits,
    _step_z_limits,
    _get_printer_profiles,
    _load_printer_profiles,
    print_detected_profile_summary,
    interactive_profile_review,
)
from core.wizard.steps.sensors import (
    _step_probe,
    _step_custom_probe,
    _step_custom_probe_offsets,
    _step_custom_probe_pin,
    _step_custom_probe_signal_option,
    _step_custom_probe_review,
    _step_custom_probe_samples_result,
    _step_guided_custom_probe_offsets,
    _step_guided_custom_probe_value,
    _needs_bltouch_pins,
    _get_unused_pins,
    make_pin_validator_with_collision_check,
    _step_bltouch_pins,
    _step_probe_offsets,
    _step_therm,
)
from core.wizard.steps.software import (
    _step_display,
    _step_web_ui,
)


def discover_mcu():
    return discover_mcu_hardware()


def resolve_bltouch_pins(user_data: dict, parsed_data: dict) -> None:
    """Ensure BLTouch/CR-Touch sensor_pin and control_pin are populated.

    Called by kace.py after the wizard returns when the probe choice is
    BLTouch or CR-Touch.  If the board database already supplied both pins
    (via boards.yaml or the wizard's bltouch_pins step) this function is a
    no-op.  When either pin is still missing or a TODO placeholder, the user
    is prompted interactively to enter the values.

    Mutates *parsed_data* in place (``parsed_data["bltouch"]``) so that
    ``generate_config()`` receives fully-resolved pin values.

    Args:
        user_data:   Live wizard result dict (may contain ``bltouch_sensor_pin``
                     and ``bltouch_control_pin`` keys set by the bltouch_pins step).
        parsed_data: Parsed board config dict.  ``parsed_data["bltouch"]`` is
                     created if absent.
    """
    from core.menu import simple_input

    _blt = parsed_data.setdefault("bltouch", {})
    if user_data.get("bltouch_sensor_pin"):
        _blt["sensor_pin"] = user_data["bltouch_sensor_pin"]
    if user_data.get("bltouch_control_pin"):
        _blt["control_pin"] = user_data["bltouch_control_pin"]

    def _is_missing(p):
        if not p:
            return True
        p_clean = str(p).strip().upper().lstrip("^!~")
        return p_clean == "TODO" or p_clean == ""

    _missing_sensor  = _is_missing(_blt.get("sensor_pin"))
    _missing_control = _is_missing(_blt.get("control_pin"))

    if not (_missing_sensor or _missing_control):
        return  # Both pins already resolved — nothing to do.

    print(f"\n\033[93m[!] BLTouch/CR-Touch selected but pin mapping is unknown or incomplete for:\033[0m")
    print(f"\033[93m    {user_data.get('board', 'unknown board')}\033[0m")
    print(f"\033[96m    Enter the pins manually below (check your board's wiring diagram).\033[0m")
    print(f"\033[2m    Example — Octopus Pro: sensor_pin=^PB7  control_pin=PB6\033[0m\n")

    pin_validator = make_pin_validator_with_collision_check(user_data)

    if _missing_sensor:
        import sys
        _sp = simple_input(
            "BLTouch sensor_pin (e.g. ^PB7 or ^PC5):",
            validate=pin_validator,
        )
        if not _sp:
            print(f"\n\033[91m[!] No sensor_pin provided — aborting.\033[0m")
            sys.exit(1)
        _blt["sensor_pin"] = _sp.strip()

    if _missing_control:
        import sys
        _cp = simple_input(
            "BLTouch control_pin (e.g. PB6 or PE5):",
            validate=pin_validator,
        )
        if not _cp:
            print(f"\n\033[91m[!] No control_pin provided — aborting.\033[0m")
            sys.exit(1)
        _blt["control_pin"] = _cp.strip()


def _check_is_non_stock(board_name: str, printer_profile: str, board_parsed: dict, profile_parsed: dict) -> bool:
    """Determine if the selected board is a non-stock upgrade for the selected printer profile."""
    if not board_name or not printer_profile or not profile_parsed or not board_parsed:
        return False

    # 1. Look up printer profile expected MCU database in data/boards.yaml
    expected_mcus = []
    try:
        from core.loader import load_boards_yaml
        db = load_boards_yaml()
        printer_profiles_db = db.get('printer_profiles', [])
        for entry in printer_profiles_db:
            if any(term.lower() in printer_profile.lower() for term in entry.get("search_terms", [])):
                expected_mcus = entry.get("expected_mcu", [])
                break
    except Exception:
        pass

    # 2. If expected stock MCUs are defined, retrieve selected board's MCU and compare
    if expected_mcus:
        board_mcu = ""
        try:
            for entry in db.get('boards', []):
                mcu = entry.get('mcu', '')
                search_terms = entry.get('search_terms', [])
                if any(term.lower() in board_name.lower() for term in search_terms):
                    board_mcu = mcu
                    break
        except Exception:
            pass

        if board_mcu:
            norm_board = _normalize_mcu_family(board_mcu)
            match_found = any(
                norm_board == _normalize_mcu_family(exp)
                or board_mcu.lower().startswith(exp.lower())
                or exp.lower().startswith(board_mcu.lower())
                for exp in expected_mcus
            )
            if not match_found:
                return True
            return False

    # 3. Fallback: Heuristic style check based on pin formats
    profile_pins = []
    for section, sdata in profile_parsed.items():
        if isinstance(sdata, dict):
            for k, val in sdata.items():
                if (k == 'pin' or k == 'pins' or k.endswith('_pin')) and isinstance(val, str):
                    cleaned = val.strip().lstrip('!^~')
                    if ':' in cleaned:
                        cleaned = cleaned.split(':', 1)[1].strip().lstrip('!^~')
                    if cleaned and not cleaned.upper().startswith("TODO"):
                        profile_pins.append(cleaned)

    board_pins = []
    for section, sdata in board_parsed.items():
        if isinstance(sdata, dict):
            for k, val in sdata.items():
                if (k == 'pin' or k == 'pins' or k.endswith('_pin')) and isinstance(val, str):
                    cleaned = val.strip().lstrip('!^~')
                    if ':' in cleaned:
                        cleaned = cleaned.split(':', 1)[1].strip().lstrip('!^~')
                    if cleaned and not cleaned.upper().startswith("TODO"):
                        board_pins.append(cleaned)

    def get_pin_style(pin: str) -> str:
        pin_upper = pin.upper()
        if '.' in pin_upper:
            return 'LPC'
        if pin_upper.startswith('GPIO'):
            return 'RP2040'
        import re
        if re.match(r'^P[A-L]\d+', pin_upper):
            return 'STM32_AVR'
        return 'UNKNOWN'

    profile_styles = {get_pin_style(p) for p in profile_pins} - {'UNKNOWN'}
    board_styles = {get_pin_style(p) for p in board_pins} - {'UNKNOWN'}

    if profile_styles and board_styles:
        if not (profile_styles & board_styles):
            return True

    return False


def run_wizard(user_data_arg=None):
    """Runs the interactive CLI wizard to gather user preferences.

    New step order (all hardware decisions first):
      board → z_motors → z_socket_assignment → driver_type → driver_mode
      → printer_profile → profile_review → kinematics → x/y/z_volume
      → probe → probe_offsets → hotend_therm → bed_therm → display → web_ui

    The wizard now also handles Z socket wiring and display setup internally,
    so kace.py only handles file generation and deployment after the wizard
    returns a fully-populated user_data.
    """
    if os.environ.get("KACE_AUTO") != "1" and os.environ.get("KACE_QUIET") != "1":
        from core.terminal import HINT, RESET
        print(f"{HINT}  {t('wizard.hardware_discovery_start')}{RESET}")
    mcu_context = discover_mcu()
    mcu_path = mcu_context.get("mcu_path")
    detected_mcu = mcu_context.get("derived_mcu")
    mcu_hint = mcu_context.get("hint")

    if os.environ.get("KACE_AUTO") != "1" and os.environ.get("KACE_QUIET") != "1":
        from core.terminal import HINT, RESET
        print(f"{HINT}  {t('wizard.board_database_fetch')}{RESET}")
    boards = fetch_config_list()

    printer_configs = [b for b in boards if b.startswith("printer-")]
    board_configs   = [b for b in boards if b.startswith("generic-")]

    suggested_configs = []
    if detected_mcu:
        print(f"\n{t('wizard.detected_mcu')}: {detected_mcu.upper()}\n")
        exact_matches = []
        for base_mcu, terms in _get_mcu_search_terms().items():
            if detected_mcu == base_mcu or detected_mcu.startswith(base_mcu):
                for b in board_configs:
                    if any(term in b.lower() for term in terms) and b not in exact_matches:
                        exact_matches.append(b)
                if exact_matches:
                    break
        if exact_matches:
            suggested_configs = exact_matches
        else:
            norm_det = _normalize_mcu_family(detected_mcu)
            if norm_det:
                fallback_matches = []
                for base_mcu, terms in _get_mcu_search_terms().items():
                    if (_normalize_mcu_family(base_mcu) == norm_det
                            or base_mcu.startswith(norm_det)
                            or norm_det.startswith(base_mcu)):
                        for b in board_configs:
                            if any(term in b.lower() for term in terms) and b not in fallback_matches:
                                fallback_matches.append(b)
                suggested_configs = fallback_matches

    if mcu_hint == "manual" and not detected_mcu:
        print("\nUsing manual MCU. You will have a chance to enter the compiler configuration later.")

    initial_defaults = {
        "mcu_path":              mcu_path,
        "mcu_type":              detected_mcu,
        "mcu_hint":              mcu_hint,
        "language":              get_lang(),
        "printer_profile":       None,
        "profile_loaded":        False,
        "board":                 None,
        "board_raw_config":      None,   # loaded in _step_board
        "board_parsed":          None,   # parsed in _step_board
        "kinematics":            "cartesian",
        "x_size":                "235",
        "y_size":                "235",
        "z_size":                "250",
        "x_position_endstop":    "0",
        "x_position_min":        "0",
        "x_position_max":        "235",
        "y_position_endstop":    "0",
        "y_position_min":        "0",
        "y_position_max":        "235",
        "z_position_endstop":    "0",
        "z_position_min":        "0",
        "z_position_max":        "250",
        "probe":                 "None",
        "probe_kind":            "none",
        "hotend_thermistor":     "EPCOS 100K B57560G104F",
        "bed_thermistor":        "EPCOS 100K B57560G104F",
        "driver_type":           None,
        "driver_mode":           "Standalone",
        "z_motors":              None,
        "web_interface":         None,
        "display_choice":        None,
        "display_section":       None,
        "display_compat_class":  None,
        "display_risk_accepted": False,
        "probe_x_offset":        "0",
        "probe_y_offset":        "0",
        "custom_probe":          None,
        "fan_part_cooling_pin":  None,
        "fan_hotend_pin":        None,
    }

    # ── Step order: hardware first, software last ──────────────────────────────
    step_order = [
        "board",
        "fan_assignment",
        "z_motors",
        "z_socket_assignment",
        "driver_type",
        "driver_mode",
        "printer_profile",
        "profile_review",
        "kinematics",
        "x_volume",
        "y_volume",
        "z_volume",
        "x_limits",
        "y_limits",
        "z_limits",
        "probe",
        "custom_probe",
        "custom_probe_offset_preview",
        "custom_probe_offsets",
        "bltouch_pins",
        "probe_offsets",
        "hotend_therm",
        "bed_therm",
        "display",
        "web_ui",
    ]

    # ── Step catalog ───────────────────────────────────────────────────────────
    steps_config = {
        "board": {
            "prompt": lambda ud: _step_board(ud, suggested_configs, board_configs),
            "next":   lambda ans, ud: "fan_assignment" if _has_fan_options(ud) else "z_motors"
        },
        "fan_assignment": {
            "prompt": lambda ud: _step_fan_assignment(ud),
            "next":   lambda ans, ud: "z_motors"
        },
        "z_motors": {
            "prompt": lambda ud: _step_z_motors(ud),
            "next":   lambda ans, ud: "driver_type" if int(ans or 1) <= 1 else "z_socket_assignment"
        },
        "z_socket_assignment": {
            "prompt": lambda ud: _step_z_socket_assignment(ud),
            # Skip assignment entirely when only 1 Z motor is used.
            "next":   lambda ans, ud: "driver_type"
        },
        "driver_type": {
            "prompt": lambda ud: _step_driver_type(ud),
            # Skip driver mode for basic/standalone drivers.
            "next":   lambda ans, ud: "printer_profile" if ans in ["None (Standard)", "A4988", "DRV8825"] else "driver_mode"
        },
        "driver_mode": {
            "prompt": lambda ud: _step_driver_mode(ud)
        },
        "printer_profile": {
            "prompt": lambda ud: _step_printer_profile(ud, printer_configs),
            # Skip profile_review when no real profile was loaded.
            "next":   lambda ans, ud: "kinematics" if not ud.get("profile_loaded") else "profile_review"
        },
        "profile_review": {
            "prompt": lambda ud: _step_profile_review(ud),
            # After review always continue to the next authoritative-skip steps.
            "next":   lambda ans, ud: "probe" if ans == "confirm" else _BACK
        },
        "kinematics": {
            "prompt": lambda ud: _step_kinematics(ud)
        },
        "x_volume": {
            "prompt": lambda ud: _step_volume(ud, "x_size", "x_position_max", t("wizard.x_volume"))
        },
        "y_volume": {
            "prompt": lambda ud: _step_volume(ud, "y_size", "y_position_max", t("wizard.y_volume"))
        },
        "z_volume": {
            "prompt": lambda ud: _step_volume(ud, "z_size", "z_position_max", t("wizard.z_volume"))
        },
        "x_limits": {
            "prompt": lambda ud: _step_x_limits(ud)
        },
        "y_limits": {
            "prompt": lambda ud: _step_y_limits(ud)
        },
        "z_limits": {
            "prompt": lambda ud: _step_z_limits(ud)
        },
        "probe": {
            "prompt": lambda ud: _step_probe(ud),
            "next":   lambda ans, ud: "hotend_therm" if normalize_probe_kind(ans) == "none" else (
                "custom_probe_pin" if normalize_probe_kind(ans) == "custom" else (
                "bltouch_pins" if normalize_probe_kind(ans) in ("bltouch", "cr_touch") and _needs_bltouch_pins(ud) else "probe_offsets"
                )
            )
        },
        "custom_probe_pin": {
            "prompt": lambda ud: _step_custom_probe_pin(ud),
            "next": lambda ans, ud: "custom_probe_pullup",
        },
        "custom_probe_pullup": {
            "prompt": lambda ud: _step_custom_probe_signal_option(ud, "pullup"),
            "next": lambda ans, ud: "custom_probe_inverted",
        },
        "custom_probe_inverted": {
            "prompt": lambda ud: _step_custom_probe_signal_option(ud, "inverted"),
            "next": lambda ans, ud: "custom_probe_offset_preview",
        },
        "custom_probe_offset_preview": {
            "prompt": lambda ud: _step_guided_custom_probe_offsets(ud),
            "next": "custom_probe_z_offset",
        },
        "custom_probe_z_offset": {
            "prompt": lambda ud: _step_guided_custom_probe_value(ud, "custom_probe_z_offset"),
            "next": lambda ans, ud: "custom_probe_speed",
        },
        "custom_probe_speed": {
            "prompt": lambda ud: _step_guided_custom_probe_value(ud, "custom_probe_speed"),
            "next": lambda ans, ud: "custom_probe_samples",
        },
        "custom_probe_samples": {
            "prompt": lambda ud: _step_guided_custom_probe_value(ud, "custom_probe_samples"),
            "next": lambda ans, ud: "custom_probe_samples_result",
        },
        "custom_probe_samples_result": {
            "prompt": lambda ud: _step_custom_probe_samples_result(ud),
            "next": lambda ans, ud: "custom_probe_samples_tolerance",
        },
        "custom_probe_samples_tolerance": {
            "prompt": lambda ud: _step_guided_custom_probe_value(ud, "custom_probe_samples_tolerance"),
            "next": lambda ans, ud: "custom_probe_samples_tolerance_retries",
        },
        "custom_probe_samples_tolerance_retries": {
            "prompt": lambda ud: _step_guided_custom_probe_value(ud, "custom_probe_samples_tolerance_retries"),
            "next": lambda ans, ud: "custom_probe_sample_retract_dist",
        },
        "custom_probe_sample_retract_dist": {
            "prompt": lambda ud: _step_guided_custom_probe_value(ud, "custom_probe_sample_retract_dist"),
            "next": lambda ans, ud: "custom_probe",
        },
        "custom_probe": {
            "prompt": lambda ud: _step_custom_probe(ud),
            "next": lambda ans, ud: "custom_probe_review",
        },
        "custom_probe_review": {
            "prompt": lambda ud: _step_custom_probe_review(ud),
            "next": lambda ans, ud: "hotend_therm",
        },
        "custom_probe_offsets": {
            "prompt": lambda ud: _step_custom_probe_offsets(ud),
            "next":   lambda ans, ud: "hotend_therm"
        },
        "bltouch_pins": {
            "prompt": lambda ud: _step_bltouch_pins(ud),
            "next":   lambda ans, ud: "probe_offsets"
        },
        "probe_offsets": {
            "prompt": lambda ud: _step_probe_offsets(ud)
        },
        "hotend_therm": {
            "prompt": lambda ud: _step_therm(ud, "hotend_thermistor", t("wizard.select_hotend_therm"), t("wizard.custom_hotend_therm"))
        },
        "bed_therm": {
            "prompt": lambda ud: _step_therm(ud, "bed_thermistor", t("wizard.select_bed_therm"), t("wizard.custom_bed_therm"))
        },
        "display": {
            "prompt": lambda ud: _step_display(ud)
        },
        "web_ui": {
            "prompt": lambda ud: _step_web_ui(ud)
        },
    }

    user_data = dict(initial_defaults)
    if user_data_arg is not None:
        user_data.update(user_data_arg)
    # The dashboard selection is session state.  Callers may pass persisted
    # wizard defaults, but those must never replace the locale selected at
    # the start of this interactive run.
    user_data["language"] = get_lang()
    start_step = user_data.pop("start_step", "board")

    runner = WizardRunner(steps_config, step_order, initial_data=user_data)
    result_data = runner.run(start_step)
    _apply_z_tmc_mappings(result_data)

    # Merge printer profile pins into board_parsed to override board-default pins
    profile_parsed = result_data.get("_profile_parsed")
    board_parsed = result_data.get("board_parsed")
    if profile_parsed and board_parsed is not None:
        board_name = result_data.get("board", "")
        printer_profile = result_data.get("printer_profile", "")
        is_non_stock = _check_is_non_stock(board_name, printer_profile, board_parsed, profile_parsed)

        for section, section_data in profile_parsed.items():
            if section == "board_pins" and is_non_stock:
                continue
            if section not in board_parsed:
                board_parsed[section] = {}
            for key, value in section_data.items():
                if is_non_stock and (key == "pin" or key == "pins" or key.endswith("_pin")):
                    continue
                board_parsed[section][key] = value

    return result_data


def __getattr__(name: str):
    if name == "MCU_SEARCH_TERMS":
        return _get_mcu_search_terms()
    if name == "PRINTER_PROFILES_DB":
        return _get_printer_profiles()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
