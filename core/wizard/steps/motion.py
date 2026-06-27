import copy
import os
from core.menu import simple_input, yes_no, numbered_select, autocomplete_select, Separator, Choice
from core.scraper import fetch_raw_config, parse_config, extract_profile_defaults
from core.style import custom_style
from core.translations import t, get_lang
from core.exceptions import WizardExit
from core.validators import questionary_numeric_validator, questionary_pos_numeric_validator
from data.profiles import THERMISTOR_PRESETS
from core.wizard.runner import _BACK, _QUIT
from core.wizard.ui import _back_choice, _quit_choice

_PRINTER_PROFILES_DB = None

def _load_printer_profiles() -> list:
    try:
        from core.loader import load_boards_yaml
        db = load_boards_yaml()
        return db.get('printer_profiles', [])
    except Exception:
        return []

def _get_printer_profiles() -> list:
    global _PRINTER_PROFILES_DB
    if _PRINTER_PROFILES_DB is None:
        _PRINTER_PROFILES_DB = _load_printer_profiles()
    return _PRINTER_PROFILES_DB


def print_detected_profile_summary(defaults: dict, parsed: dict, user_data: dict = None) -> None:
    """Print detected profile as a clean information screen."""
    is_custom = False
    if user_data:
        is_custom = user_data.get("printer_profile") == "Custom / Scratch Build"
    elif defaults:
        is_custom = defaults.get("printer_profile") == "Custom / Scratch Build"

    header_key = "profile.custom_header" if is_custom else "profile.detected_header"
    print(f"\n\033[92m{t(header_key)}\033[0m")

    def print_val(label: str, val: str, comment_key: str) -> None:
        comment = t(comment_key)
        dim_comment = f"\033[2m# {comment}\033[0m"
        print(f"  - {label:<24} {str(val):<8} {dim_comment}")

    # ── Motion System ─────────────────────────────────────────────────────────
    kinematics = parsed.get('printer', {}).get('kinematics') or defaults.get('kinematics')
    has_any_axis = any(
        parsed.get(f'stepper_{a}', {}).get(k) is not None or (is_custom and defaults.get(f'{a}_{k}') is not None)
        for a in ['x', 'y', 'z']
        for k in ('position_min', 'position_max', 'position_endstop')
    )
    has_motion = bool(kinematics or has_any_axis)

    if has_motion:
        print("  \033[96mMotion System\033[0m")
        print("  \033[96m─────────────\033[0m")
        print("")

        if kinematics:
            print_val("Kinematics:", kinematics, "profile.comment_kinematics")
            print("")

        for axis in ['x', 'y', 'z']:
            sec = f'stepper_{axis}'
            axis_data = parsed.get(sec, {})
            axis_rows = [
                (f"{axis.upper()} position_min:",     axis_data.get('position_min') or (defaults.get(f'{axis}_position_min') if is_custom else None),     f"profile.comment_position_min_{axis}"),
                (f"{axis.upper()} position_max:",     axis_data.get('position_max') or (defaults.get(f'{axis}_position_max') if is_custom else None),     f"profile.comment_position_max_{axis}"),
                (f"{axis.upper()} position_endstop:", axis_data.get('position_endstop') or (defaults.get(f'{axis}_position_endstop') if is_custom else None), f"profile.comment_position_endstop_{axis}"),
            ]
            if any(v is not None for _, v, _ in axis_rows):
                for label, val, comment_key in axis_rows:
                    if val is not None:
                        print_val(label, val, comment_key)
                print("")

    # ── Build Volume ──────────────────────────────────────────────────────────
    x_size = parsed.get('stepper_x', {}).get('position_max') or defaults.get('x_size')
    y_size = parsed.get('stepper_y', {}).get('position_max') or defaults.get('y_size')
    z_size = parsed.get('stepper_z', {}).get('position_max') or defaults.get('z_size')
    if x_size and y_size and z_size:
        print("  \033[96mBuild Volume\033[0m")
        print("  \033[96m────────────\033[0m")
        print("")
        print_val("Build volume:", f"{x_size} x {y_size} x {z_size}", "profile.comment_build_volume")
        print("")

    # ── Thermistors ───────────────────────────────────────────────────────────
    hotend_therm = parsed.get('extruder', {}).get('sensor_type') or (defaults.get('hotend_thermistor') if is_custom else None)
    bed_therm = parsed.get('heater_bed', {}).get('sensor_type') or (defaults.get('bed_thermistor') if is_custom else None)
    if hotend_therm or bed_therm:
        print("  \033[96mThermistors\033[0m")
        print("  \033[96m───────────\033[0m")
        print("")
        if hotend_therm:
            print_val("Hotend thermistor:", hotend_therm, "profile.comment_hotend_therm")
        if bed_therm:
            print_val("Bed thermistor:", bed_therm, "profile.comment_bed_therm")
        print("")


def interactive_profile_review(defaults: dict, parsed: dict, user_data: dict) -> str:
    return _step_profile_review_inner(defaults, parsed, user_data)


def _step_profile_review_inner(defaults: dict, parsed: dict, user_data: dict) -> str:
    """Profile information screen."""
    while True:
        print_detected_profile_summary(defaults, parsed, user_data)

        action = numbered_select(
            t("wizard.profile_review_prompt"),
            choices=[
                {"name": t("choice.continue"),      "value": "confirm"},
                {"name": t("choice.edit_profile"),  "value": "edit"},
                {"name": f"🔙  {t('choice.arrow_back') if t('choice.arrow_back') else 'Back'}",    "value": "back"},
            ]
        )

        if action is None:
            raise WizardExit()
        if action == "confirm":
            return "confirm"
        if action == "back":
            return "back"

        editor_result = _step_profile_editor_inner(defaults, parsed, user_data)
        if editor_result == "back":
            continue


def _step_profile_editor_inner(defaults: dict, parsed: dict, user_data: dict) -> str:
    """Staged profile editor."""
    staged_defaults  = copy.deepcopy(defaults)
    staged_parsed    = copy.deepcopy(parsed)
    staged_user_data = copy.deepcopy(user_data)

    def validate_float(val):
        try:
            float(val)
            return True
        except (ValueError, TypeError):
            return False

    def validate_pos_float(val):
        try:
            return float(val) > 0
        except (ValueError, TypeError):
            return False

    def _resolve(sd, sp):
        kin   = sp.get('printer', {}).get('kinematics') or sd.get('kinematics', 'cartesian')
        x_sz  = sp.get('stepper_x', {}).get('position_max') or sd.get('x_size', '235')
        y_sz  = sp.get('stepper_y', {}).get('position_max') or sd.get('y_size', '235')
        z_sz  = sp.get('stepper_z', {}).get('position_max') or sd.get('z_size', '250')
        x_min = sp.get('stepper_x', {}).get('position_min') or sd.get('x_position_min', '0')
        x_max = sp.get('stepper_x', {}).get('position_max') or sd.get('x_position_max', '235')
        x_end = sp.get('stepper_x', {}).get('position_endstop') or sd.get('x_position_endstop', '0')
        y_min = sp.get('stepper_y', {}).get('position_min') or sd.get('y_position_min', '0')
        y_max = sp.get('stepper_y', {}).get('position_max') or sd.get('y_position_max', '235')
        y_end = sp.get('stepper_y', {}).get('position_endstop') or sd.get('y_position_endstop', '0')
        z_min = sp.get('stepper_z', {}).get('position_min') or sd.get('z_position_min', '0')
        z_max = sp.get('stepper_z', {}).get('position_max') or sd.get('z_position_max', '250')
        z_end = sp.get('stepper_z', {}).get('position_endstop') or sd.get('z_position_endstop', '0')
        ht    = sp.get('extruder', {}).get('sensor_type') or sd.get('hotend_thermistor', 'EPCOS 100K B57560G104F')
        bt    = sp.get('heater_bed', {}).get('sensor_type') or sd.get('bed_thermistor', 'EPCOS 100K B57560G104F')
        return kin, x_sz, y_sz, z_sz, x_min, x_max, x_end, y_min, y_max, y_end, z_min, z_max, z_end, ht, bt

    while True:
        if os.environ.get("KACE_TESTING") != "1" and os.environ.get("KACE_QUIET") != "1":
            os.system('clear' if os.name == 'posix' else 'cls')

        kin, x_sz, y_sz, z_sz, x_min, x_max, x_end, \
            y_min, y_max, y_end, z_min, z_max, z_end, ht, bt = _resolve(staged_defaults, staged_parsed)

        C = "\033[96m"   # cyan
        D = "\033[2m"    # dim
        B = "\033[1m"    # bold
        R = "\033[0m"    # reset
        SEP = "─" * 62

        def _row(idx, label, value, comment_key):
            comment = t(comment_key)
            return f"  {B}{idx:>2}.{R}  {label:<22} {C}{value}{R}  {D}# {comment}{R}"

        print(f"\n  {B}{t('choice.edit_profile')}{R}")
        print(f"  {SEP}")

        def _ansi_choice(text):
            return text

        choices = [
            Choice(title=_ansi_choice(_row(1,  "Kinematics",         kin,                             "profile.comment_kinematics")), value="kinematics"),
            Choice(title=_ansi_choice(_row(2,  "Build Volume",        f"{x_sz} x {y_sz} x {z_sz} mm", "profile.comment_build_volume")), value="volume"),
            Separator("  " + "─" * 62),
            Choice(title=_ansi_choice(_row(3,  "X position_min",      x_min, "profile.comment_position_min_x")), value="x_position_min"),
            Choice(title=_ansi_choice(_row(4,  "X position_max",      x_max, "profile.comment_position_max_x")), value="x_position_max"),
            Choice(title=_ansi_choice(_row(5,  "X position_endstop",  x_end, "profile.comment_position_endstop_x")), value="x_position_endstop"),
            Separator("  " + "─" * 62),
            Choice(title=_ansi_choice(_row(6,  "Y position_min",      y_min, "profile.comment_position_min_y")), value="y_position_min"),
            Choice(title=_ansi_choice(_row(7,  "Y position_max",      y_max, "profile.comment_position_max_y")), value="y_position_max"),
            Choice(title=_ansi_choice(_row(8,  "Y position_endstop",  y_end, "profile.comment_position_endstop_y")), value="y_position_endstop"),
            Separator("  " + "─" * 62),
            Choice(title=_ansi_choice(_row(9,  "Z position_min",      z_min, "profile.comment_position_min_z")), value="z_position_min"),
            Choice(title=_ansi_choice(_row(10, "Z position_max",      z_max, "profile.comment_position_max_z")), value="z_position_max"),
            Choice(title=_ansi_choice(_row(11, "Z position_endstop",  z_end, "profile.comment_position_endstop_z")), value="z_position_endstop"),
            Separator("  " + "─" * 62),
            Choice(title=_ansi_choice(_row(12, "Hotend Thermistor",   ht,    "profile.comment_hotend_therm")), value="hotend_thermistor"),
            Choice(title=_ansi_choice(_row(13, "Bed Thermistor",      bt,    "profile.comment_bed_therm")), value="bed_thermistor"),
            Separator("  " + "─" * 62),
            Choice(title=_ansi_choice(f"  {B}{t('choice.save_continue')}{R}"), value="save"),
            Choice(title=_ansi_choice(f"  {B}{t('choice.back_discard')}{R}"), value="back")
        ]

        prop = numbered_select(
            t("wizard.profile_editor_prompt"),
            choices=choices
        )

        if prop is None:
            raise WizardExit()

        if prop == "save":
            # Sanitize axis limits before saving to ensure position_min <= position_endstop <= position_max
            adjusted_msg = []
            for axis, size_key in [("x", "x_size"), ("y", "y_size"), ("z", "z_size")]:
                try:
                    endstop = float(staged_user_data.get(f"{axis}_position_endstop", 0.0))
                except (ValueError, TypeError):
                    endstop = 0.0

                try:
                    p_min = float(staged_user_data.get(f"{axis}_position_min", 0.0))
                except (ValueError, TypeError):
                    p_min = 0.0

                try:
                    p_max = float(staged_user_data.get(f"{axis}_position_max", staged_user_data.get(size_key, 235.0)))
                except (ValueError, TypeError):
                    p_max = 235.0

                if p_min > endstop:
                    if axis == "z":
                        p_min = min(endstop - 1.0, -2.0)
                    else:
                        p_min = endstop
                    staged_user_data[f"{axis}_position_min"] = f"{p_min:g}"
                    staged_defaults[f"{axis}_position_min"] = f"{p_min:g}"
                    staged_parsed.setdefault(f"stepper_{axis}", {})["position_min"] = f"{p_min:g}"
                    adjusted_msg.append(f"{axis.upper()} position_min adjusted to {p_min:g} to accommodate endstop {endstop:g}")

                if p_max < endstop:
                    p_max = endstop
                    staged_user_data[f"{axis}_position_max"] = f"{p_max:g}"
                    staged_defaults[f"{axis}_position_max"] = f"{p_max:g}"
                    staged_parsed.setdefault(f"stepper_{axis}", {})["position_max"] = f"{p_max:g}"
                    adjusted_msg.append(f"{axis.upper()} position_max adjusted to {p_max:g} to accommodate endstop {endstop:g}")

            if adjusted_msg and os.environ.get("KACE_TESTING") != "1" and os.environ.get("KACE_QUIET") != "1":
                print("\n\033[93m[!] Automatically adjusted limits to ensure physical consistency:\033[0m")
                for msg in adjusted_msg:
                    print(f"    - {msg}")
                # Give the user a moment to see the message
                import time
                time.sleep(2.5)

            defaults.clear()
            defaults.update(staged_defaults)
            parsed.clear()
            parsed.update(staged_parsed)
            user_data.clear()
            user_data.update(staged_user_data)
            return "save"

        if prop == "back":
            return "back"

        if prop == "kinematics":
            new_kin = numbered_select(
                "Select Kinematics:",
                choices=["cartesian", "corexy", "delta"],
                default=["cartesian", "corexy", "delta"].index(kin) if kin in ["cartesian", "corexy", "delta"] else 0
            )
            if new_kin:
                staged_user_data["kinematics"] = new_kin
                staged_defaults["kinematics"] = new_kin
                staged_parsed.setdefault('printer', {})['kinematics'] = new_kin

        elif prop == "volume":
            new_x = simple_input("Enter X build volume (mm):", default=str(x_sz))
            if new_x is not None and validate_pos_float(new_x):
                new_y = simple_input("Enter Y build volume (mm):", default=str(y_sz))
                if new_y is not None and validate_pos_float(new_y):
                    new_z = simple_input("Enter Z build volume (mm):", default=str(z_sz))
                    if new_z is not None and validate_pos_float(new_z):
                        for key, val in [("x_size", new_x), ("y_size", new_y), ("z_size", new_z),
                                         ("x_position_max", new_x), ("y_position_max", new_y), ("z_position_max", new_z)]:
                            staged_user_data[key] = val
                            staged_defaults[key] = val
                        staged_parsed.setdefault('stepper_x', {})['position_max'] = new_x
                        staged_parsed.setdefault('stepper_y', {})['position_max'] = new_y
                        staged_parsed.setdefault('stepper_z', {})['position_max'] = new_z

        elif prop in ("x_position_min", "x_position_max", "x_position_endstop",
                      "y_position_min", "y_position_max", "y_position_endstop",
                      "z_position_min", "z_position_max", "z_position_endstop"):
            axis = prop.split("_")[0]
            field = prop.replace(f"{axis}_", "")
            
            val_map = {
                "x_position_min": x_min, "x_position_max": x_max, "x_position_endstop": x_end,
                "y_position_min": y_min, "y_position_max": y_max, "y_position_endstop": y_end,
                "z_position_min": z_min, "z_position_max": z_max, "z_position_endstop": z_end,
            }
            curr_val = val_map[prop]
            
            new_val = simple_input(
                f"Enter {axis.upper()} {field} (mm):",
                default=str(curr_val),
                validate=questionary_numeric_validator
            )
            
            if new_val is not None and new_val.strip().lower() not in ("<", "back", "volver", ""):
                val_clean = new_val.strip()
                staged_user_data[prop] = val_clean
                staged_defaults[prop] = val_clean
                
                sx = staged_parsed.setdefault(f"stepper_{axis}", {})
                sx[field] = val_clean
                
                if field == "position_max":
                    size_key = f"{axis}_size"
                    staged_user_data[size_key] = val_clean
                    staged_defaults[size_key] = val_clean

        elif prop == "hotend_thermistor":
            th_choices = list(THERMISTOR_PRESETS) + ["Other (Manual Entry)"]
            new_th = numbered_select(
                "Select Hotend Thermistor:",
                choices=th_choices,
                default=th_choices.index(ht) if ht in THERMISTOR_PRESETS else 0
            )
            if new_th == "Other (Manual Entry)":
                new_th = simple_input("Enter custom hotend thermistor name:")
            if new_th:
                staged_user_data["hotend_thermistor"] = new_th
                staged_defaults["hotend_thermistor"] = new_th
                staged_parsed.setdefault('extruder', {})['sensor_type'] = new_th

        elif prop == "bed_thermistor":
            bt_choices = list(THERMISTOR_PRESETS) + ["Other (Manual Entry)"]
            new_tb = numbered_select(
                "Select Bed Thermistor:",
                choices=bt_choices,
                default=bt_choices.index(bt) if bt in THERMISTOR_PRESETS else 0
            )
            if new_tb == "Other (Manual Entry)":
                new_tb = simple_input("Enter custom bed thermistor name:")
            if new_tb:
                staged_user_data["bed_thermistor"] = new_tb
                staged_defaults["bed_thermistor"] = new_tb
                staged_parsed.setdefault('heater_bed', {})['sensor_type'] = new_tb


def _step_profile_review(user_data):
    parsed   = user_data.get("_profile_parsed",   {})
    defaults = user_data.get("_profile_defaults",  {})

    result = _step_profile_review_inner(defaults, parsed, user_data)

    if result == "back":
        # Clear profile so printer_profile step reruns cleanly
        user_data["profile_loaded"] = False
        user_data.pop("_profile_parsed", None)
        user_data.pop("_profile_defaults", None)
        return _BACK

    # result == "confirm" → mark keys as authoritative
    _profile_keys = {
        "kinematics",
        "x_size", "y_size", "z_size",
        "x_position_min", "x_position_max", "x_position_endstop",
        "y_position_min", "y_position_max", "y_position_endstop",
        "z_position_min", "z_position_max", "z_position_endstop",
        "hotend_thermistor", "bed_thermistor",
    }
    existing_auth = user_data.get("_authoritative", set())
    user_data["_authoritative"] = existing_auth | _profile_keys
    return "confirm"


def _step_printer_profile(user_data, printer_configs):
    custom_choice_str = t("choice.custom_scratch")
    search_choice_str = t("choice.search_manually")
    
    choices = [
        {"name": f"✨  {custom_choice_str}", "value": "custom"},
        {"name": f"🔍  {search_choice_str}", "value": "search"},
        _back_choice(),
        _quit_choice(),
    ]

    ans = numbered_select(
        t("wizard.select_printer_model_menu"),
        choices=choices
    )

    if ans == _QUIT or ans is None:
        raise WizardExit()
    if ans == _BACK:
        return _BACK

    if ans == "custom":
        user_data["printer_profile"] = "Custom / Scratch Build"
        user_data["profile_loaded"]  = False
        user_data.pop("_profile_parsed", None)
        user_data.pop("_profile_defaults", None)
        return "Custom / Scratch Build"

    if ans == "search":
        ans = autocomplete_select(
            t("wizard.select_printer_model"),
            choices=printer_configs
        )
        if ans is None:
            return "__retry__"

    print(f"\n\033[96m>>> Loading defaults for {ans}...\033[0m")
    raw = fetch_raw_config(ans)
    if not raw:
        print(f"\n\033[91m[!] Failed to load printer profile: '{ans}'\033[0m")
        fallback = yes_no(
            "Continue as Custom / Scratch Build?",
            default=True
        )
        if fallback:
            user_data["printer_profile"] = "Custom / Scratch Build"
            user_data["profile_loaded"]  = False
            user_data.pop("_profile_parsed", None)
            user_data.pop("_profile_defaults", None)
            return "Custom / Scratch Build"
        return "__retry__"

    user_data["printer_profile"] = ans
    user_data["raw_config"]      = raw
    parsed   = parse_config(raw, ans)
    defaults = extract_profile_defaults(parsed)
    for k, v in defaults.items():
        user_data[k] = v
    user_data["profile_loaded"]  = True
    user_data["_profile_parsed"]   = parsed
    user_data["_profile_defaults"] = defaults
    return ans


def _step_kinematics(user_data):
    if "kinematics" in user_data.get("_authoritative", set()):
        return user_data["kinematics"]
    choices = ["cartesian", "corexy", "delta", _back_choice(), _quit_choice()]
    default_kin = user_data.get("kinematics")
    default_idx = choices.index(default_kin) if default_kin in choices[:3] else 0
    ans = numbered_select(
        t("wizard.select_kinematics"),
        choices=choices,
        default=default_idx
    )
    if ans == _QUIT or ans is None: raise WizardExit()
    if ans == _BACK: return _BACK
    user_data["kinematics"] = ans
    return ans


def _step_volume(user_data, size_key, max_key, msg_text):
    if size_key in user_data.get("_authoritative", set()):
        return user_data[size_key]
    ans = simple_input(
        msg_text,
        default=str(user_data.get(size_key) or ""),
        validate=questionary_pos_numeric_validator
    )
    if ans is None or ans.strip().lower() in ("<", "back", "volver"):
        return _BACK
    val_clean = ans.strip()
    old_val = user_data.get(size_key)
    user_data[size_key] = val_clean
    if user_data.get(max_key) == old_val or not user_data.get(max_key):
        user_data[max_key] = val_clean
    return val_clean


def _step_x_limits(user_data):
    prompts = ["min", "max", "endstop"]
    idx = 0
    while idx < len(prompts):
        curr = prompts[idx]
        if curr == "min":
            val = simple_input(
                t("wizard.x_position_min") or "Enter X position_min (mm) [type '<' to go back]:",
                default=str(user_data.get("x_position_min") if user_data.get("x_position_min") is not None else "0"),
                validate=questionary_numeric_validator
            )
            if val is None:
                raise WizardExit()
            if val.strip().lower() in ("<", "back", "volver"):
                return _BACK
            user_data["x_position_min"] = val.strip()
            idx += 1
        elif curr == "max":
            val = simple_input(
                t("wizard.x_position_max") or "Enter X position_max (mm) [type '<' to go back]:",
                default=str(user_data.get("x_position_max") or user_data.get("x_size") or "235"),
                validate=questionary_numeric_validator
            )
            if val is None:
                raise WizardExit()
            if val.strip().lower() in ("<", "back", "volver"):
                idx -= 1
                continue
            user_data["x_position_max"] = val.strip()
            user_data["x_size"] = val.strip()
            idx += 1
        elif curr == "endstop":
            val = simple_input(
                t("wizard.x_position_endstop") or "Enter X position_endstop (mm) [type '<' to go back]:",
                default=str(user_data.get("x_position_endstop") if user_data.get("x_position_endstop") is not None else "0"),
                validate=questionary_numeric_validator
            )
            if val is None:
                raise WizardExit()
            if val.strip().lower() in ("<", "back", "volver"):
                idx -= 1
                continue
            user_data["x_position_endstop"] = val.strip()
            idx += 1
    return "done"


def _step_y_limits(user_data):
    prompts = ["min", "max", "endstop"]
    idx = 0
    while idx < len(prompts):
        curr = prompts[idx]
        if curr == "min":
            val = simple_input(
                t("wizard.y_position_min") or "Enter Y position_min (mm) [type '<' to go back]:",
                default=str(user_data.get("y_position_min") if user_data.get("y_position_min") is not None else "0"),
                validate=questionary_numeric_validator
            )
            if val is None:
                raise WizardExit()
            if val.strip().lower() in ("<", "back", "volver"):
                return _BACK
            user_data["y_position_min"] = val.strip()
            idx += 1
        elif curr == "max":
            val = simple_input(
                t("wizard.y_position_max") or "Enter Y position_max (mm) [type '<' to go back]:",
                default=str(user_data.get("y_position_max") or user_data.get("y_size") or "235"),
                validate=questionary_numeric_validator
            )
            if val is None:
                raise WizardExit()
            if val.strip().lower() in ("<", "back", "volver"):
                idx -= 1
                continue
            user_data["y_position_max"] = val.strip()
            user_data["y_size"] = val.strip()
            idx += 1
        elif curr == "endstop":
            val = simple_input(
                t("wizard.y_position_endstop") or "Enter Y position_endstop (mm) [type '<' to go back]:",
                default=str(user_data.get("y_position_endstop") if user_data.get("y_position_endstop") is not None else "0"),
                validate=questionary_numeric_validator
            )
            if val is None:
                raise WizardExit()
            if val.strip().lower() in ("<", "back", "volver"):
                idx -= 1
                continue
            user_data["y_position_endstop"] = val.strip()
            idx += 1
    return "done"


def _step_z_limits(user_data):
    prompts = ["min", "max", "endstop"]
    idx = 0
    while idx < len(prompts):
        curr = prompts[idx]
        if curr == "min":
            val = simple_input(
                t("wizard.z_position_min") or "Enter Z position_min (mm) [type '<' to go back]:",
                default=str(user_data.get("z_position_min") if user_data.get("z_position_min") is not None else "0"),
                validate=questionary_numeric_validator
            )
            if val is None:
                raise WizardExit()
            if val.strip().lower() in ("<", "back", "volver"):
                return _BACK
            user_data["z_position_min"] = val.strip()
            idx += 1
        elif curr == "max":
            val = simple_input(
                t("wizard.z_position_max") or "Enter Z position_max (mm) [type '<' to go back]:",
                default=str(user_data.get("z_position_max") or user_data.get("z_size") or "250"),
                validate=questionary_numeric_validator
            )
            if val is None:
                raise WizardExit()
            if val.strip().lower() in ("<", "back", "volver"):
                idx -= 1
                continue
            user_data["z_position_max"] = val.strip()
            user_data["z_size"] = val.strip()
            idx += 1
        elif curr == "endstop":
            val = simple_input(
                t("wizard.z_position_endstop") or "Enter Z position_endstop (mm) [type '<' to go back]:",
                default=str(user_data.get("z_position_endstop") if user_data.get("z_position_endstop") is not None else "0"),
                validate=questionary_numeric_validator
            )
            if val is None:
                raise WizardExit()
            if val.strip().lower() in ("<", "back", "volver"):
                idx -= 1
                continue
            user_data["z_position_endstop"] = val.strip()
            idx += 1
    return "done"
