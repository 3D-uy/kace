import os
from jinja2 import Environment, FileSystemLoader
from core.translations import translate_comment, get_lang
from core.macro_generator import generate_starter_macros
from core.advanced_module_handler import get_advanced_sections
from core.exceptions import GenerationError

# Resolve templates directory relative to this file's location, not the CWD
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEMPLATES_DIR = os.path.join(_BASE_DIR, 'templates')

def has_todo_pins(parsed_data: dict) -> list:
    """Return a list of (section, key) tuples for any unresolved TODO pins.

    Scans parsed config values for literal 'TODO' strings.  Called early
    in kace.py — before the firmware compilation prompt — so the user is
    not sent through compilation for a config that is already known to be
    incomplete.  An empty list means the config is clean.
    """
    todos = []
    current_section = "unknown"
    for section, values in parsed_data.items():
        if isinstance(values, dict):
            for key, val in values.items():
                if isinstance(val, str) and "TODO" in val:
                    todos.append((section, key))
    return todos

def generate_config(parsed_data, user_data, output_path=None, include_macros=False):
    """Generate printer.cfg from parsed config and user data using Jinja2."""
    # Avoid in-place mutation of user_data by using a localized context dict
    user_ctx = dict(user_data)
    user_ctx["include_macros"] = include_macros

    # Enforce position_min <= position_endstop <= position_max for each axis to prevent Klipper startup errors
    _uses_probe = user_ctx.get("probe", "None") != "None"

    for axis, size_key in [("x", "x_size"), ("y", "y_size"), ("z", "z_size")]:
        # When a probe is active (BLTouch/CR-Touch), the Z axis uses
        # probe:z_virtual_endstop — there is no position_endstop at all.
        # Skip endstop constraint enforcement for Z and ensure position_min
        # is negative so PROBE_CALIBRATE can work.
        if axis == "z" and _uses_probe:
            try:
                p_min = float(user_ctx.get("z_position_min", 0.0))
            except (ValueError, TypeError):
                p_min = 0.0
            if p_min >= 0:
                user_ctx["z_position_min"] = "-2"
            continue

        try:
            endstop = float(user_ctx.get(f"{axis}_position_endstop", 0.0))
        except (ValueError, TypeError):
            endstop = 0.0

        try:
            p_min = float(user_ctx.get(f"{axis}_position_min", 0.0))
        except (ValueError, TypeError):
            p_min = 0.0

        try:
            p_max = float(user_ctx.get(f"{axis}_position_max", user_ctx.get(size_key, 235.0)))
        except (ValueError, TypeError):
            p_max = 235.0

        if p_min > endstop:
            if axis == "z":
                # For Z-axis, give a standard safety buffer below the endstop (default -2.0 or endstop - 1.0)
                p_min = min(endstop - 1.0, -2.0)
            else:
                p_min = endstop
            user_ctx[f"{axis}_position_min"] = f"{p_min:g}"

        if p_max < endstop:
            p_max = endstop
            user_ctx[f"{axis}_position_max"] = f"{p_max:g}"

    # ── ADR 001 Validation Layer ──────────────────────────────────────────────
    try:
        # Stepper positions
        x_min_stepper = float(user_ctx.get("x_position_min", 0.0))
        x_max_stepper = float(user_ctx.get("x_position_max", float(user_ctx.get("x_size", 235.0))))
        y_min_stepper = float(user_ctx.get("y_position_min", 0.0))
        y_max_stepper = float(user_ctx.get("y_position_max", float(user_ctx.get("y_size", 235.0))))
        z_min_stepper = float(user_ctx.get("z_position_min", 0.0))
        z_max_stepper = float(user_ctx.get("z_position_max", float(user_ctx.get("z_size", 250.0))))

        # Printable limits (with robust derivation fallback)
        printable_x_min = float(user_ctx.get("printable_x_min", x_min_stepper if x_min_stepper > 0.0 else 0.0))
        printable_x_max = float(user_ctx.get("printable_x_max", float(user_ctx.get("x_size", 235.0))))
        printable_y_min = float(user_ctx.get("printable_y_min", y_min_stepper if y_min_stepper > 0.0 else 0.0))
        printable_y_max = float(user_ctx.get("printable_y_max", float(user_ctx.get("y_size", 235.0))))
        printable_z_max = float(user_ctx.get("printable_z_max", float(user_ctx.get("z_size", 250.0))))
    except (ValueError, TypeError) as e:
        raise GenerationError(f"Invalid numeric value in geometry settings: {e}")

    # Validate endstop bounds constraints (except Z when probe is active)
    for axis, p_min, p_max in [("x", x_min_stepper, x_max_stepper), 
                               ("y", y_min_stepper, y_max_stepper), 
                               ("z", z_min_stepper, z_max_stepper)]:
        if axis == "z" and _uses_probe:
            continue
        try:
            endstop = float(user_ctx.get(f"{axis}_position_endstop", 0.0))
            if not (p_min <= endstop <= p_max):
                raise GenerationError(f"{axis.upper()} position_endstop ({endstop:g}) must be within mechanical limits [{p_min:g}, {p_max:g}].")
        except (ValueError, TypeError):
            pass

    # Validate Printable Area fits within travel boundaries
    if (printable_x_max - printable_x_min) > (x_max_stepper - x_min_stepper):
        raise GenerationError(f"Printable area width ({printable_x_max - printable_x_min:g}mm) exceeds maximum X travel range ({x_max_stepper - x_min_stepper:g}mm).")
    if (printable_y_max - printable_y_min) > (y_max_stepper - y_min_stepper):
        raise GenerationError(f"Printable area depth ({printable_y_max - printable_y_min:g}mm) exceeds maximum Y travel range ({y_max_stepper - y_min_stepper:g}mm).")
    if printable_z_max > (z_max_stepper - z_min_stepper):
        raise GenerationError(f"Printable area height ({printable_z_max:g}mm) exceeds maximum Z travel range ({z_max_stepper - z_min_stepper:g}mm).")

    # Validate Printable Area inclusion within travel limits
    if printable_x_min < x_min_stepper or printable_x_max > x_max_stepper:
        raise GenerationError(f"Printable X boundary [{printable_x_min:g}, {printable_x_max:g}] is outside physical X travel limits [{x_min_stepper:g}, {x_max_stepper:g}].")
    if printable_y_min < y_min_stepper or printable_y_max > y_max_stepper:
        raise GenerationError(f"Printable Y boundary [{printable_y_min:g}, {printable_y_max:g}] is outside physical Y travel limits [{y_min_stepper:g}, {y_max_stepper:g}].")

    user_ctx["printable_center_x"] = f"{(printable_x_min + printable_x_max) / 2:g}"
    user_ctx["printable_center_y"] = f"{(printable_y_min + printable_y_max) / 2:g}"

    # Build and serialize the motion space model using the sanitized user_ctx
    from core.motion_model import PrinterMotionSpace
    space = PrinterMotionSpace(user_ctx)
    user_ctx["motion_space"] = space.to_dict()

    # Auto-generate bed_mesh config
    from core.bed_mesh import generate_bed_mesh_config
    user_ctx["bed_mesh"] = generate_bed_mesh_config(space, user_ctx, parsed_data)

    # Derive leveling coordinates
    from core.leveling import derive_leveling_points
    user_ctx["leveling"] = derive_leveling_points(space, int(user_ctx.get("z_motors") or 1))
    # Setup Jinja2 environment
    env = Environment(loader=FileSystemLoader(_TEMPLATES_DIR, encoding='utf-8'))
    template = env.get_template('printer.cfg.j2')

    # Collect advanced sections (neopixel, adxl345, sx1509 …) and pre-render
    # them as commented-out passthrough blocks for the template to inject.
    # We copy parsed_data so the caller's dict is never mutated.
    pins_ctx = dict(parsed_data)
    
    # Apply custom fan assignments if present in user_data
    fan_part = user_data.get("fan_part_cooling_pin")
    if fan_part:
        if fan_part == "none":
            if "fan" in pins_ctx:
                del pins_ctx["fan"]
        elif fan_part != "default":
            pins_ctx["fan"] = {"pin": fan_part}
            
    fan_hotend = user_data.get("fan_hotend_pin")
    if fan_hotend and fan_hotend != "none":
        pins_ctx["heater_fan hotend_fan"] = {"pin": fan_hotend}

    pins_ctx['_advanced_sections'] = get_advanced_sections(parsed_data)

    # Render the template with parsed pins and user input
    output = template.render(
        pins=pins_ctx,
        user=user_ctx
    )
    
    # Align inline comments for a professional look
    aligned_lines = []
    comment_col = 48
    # get_lang() is always authoritative: set by the dashboard language picker
    # before the wizard runs. user_data['language'] is a synced copy of it.
    language = get_lang()
    for line in output.splitlines():
        # Check if line is a commented setting that contains an inline comment
        is_commented_setting = line.lstrip().startswith('#') and line.count('#') > 1
        if ('#' in line and not line.lstrip().startswith('#')) or is_commented_setting:
            if not is_commented_setting:
                content, comment = line.split('#', 1)
            else:
                first_hash = line.find('#')
                second_hash = line.find('#', first_hash + 1)
                content, comment = line[:second_hash], line[second_hash+1:]

            content = content.rstrip()
            comment = comment.strip()
            
            # Translate if necessary
            comment = translate_comment(comment, language)
            
            # Ensure at least one space before the comment
            padding = max(1, comment_col - len(content))
            aligned_lines.append(f"{content}{' ' * padding}# {comment}")
        else:
            # Regular line or normal full-line comment
            if line.lstrip().startswith('#'):
                comment = line.lstrip()[1:].strip()
                translated = translate_comment(comment, language)
                if comment != translated:
                    # Update translated full line comment
                    line = line.replace(f"# {comment}", f"# {translated}")
            aligned_lines.append(line)
    
    final_output = chr(10).join(aligned_lines)
    
    # ── Display blocks rendering ──────────────────────────────────────────────
    display_blocks = []
    from core.display_checker import detect_display_sections, classify_hardware_combination, _WIZARD_SKIP_SECTIONS
 
    display_choice = user_ctx.get("display_choice")
    board_filename  = user_ctx.get('board', '')

    # ── Respect wizard display choice ─────────────────────────────────────────
    # "none": user opted out — strip all display sections, generate no blocks.
    # "recommended:<key>" / "manual:<key>" / "override:<key>": use wizard choice
    #    as authoritative, ignore whatever the board config may have detected.
    # None (auto/CI mode): fall through to existing detection-based logic.

    if display_choice == "none":
        # Strip display-related keys from parsed_data so they don't leak into
        # the Jinja2 template render or the advanced_sections passthrough.
        _DISPLAY_STRIP_PREFIXES = {
            "display", "lcd_menu", "display_status", "display_template",
            "display_data", "hd44780", "ssd1306", "uc1701", "st7920",
            "t5uid1", "dwin_set", "tft_serial", "sh1106", "emulated_st7920",
            "btt_tft35", "mks_mini12864", "aip31068_spi", "hd44780_spi",
        }
        for strip_key in list(pins_ctx.keys()):
            if strip_key.split()[0].lower() in _DISPLAY_STRIP_PREFIXES:
                del pins_ctx[strip_key]
        # No display_blocks generated — intentional.

    elif display_choice and display_choice not in (None,) and not display_choice.startswith("__"):
        # Extract the section key from the wizard choice prefix
        # e.g. "recommended:uc1701" → "uc1701"
        colon_idx = display_choice.find(":")
        wizard_display_key = display_choice[colon_idx + 1:] if colon_idx != -1 else None

        if wizard_display_key:
            # Build a display block for the wizard-chosen section.
            # We don't require that section to exist in parsed_data —
            # for manual/override picks the user is explicitly requesting it.
            hw_info   = classify_hardware_combination(wizard_display_key, board_filename, parsed_data)
            comp_class = hw_info.get("compatibility_class", "experimental")

            # Pull existing fields from parsed_data if the section exists there,
            # otherwise generate a minimal commented block.
            existing_key = None
            for k in parsed_data:
                if k.split()[0].lower() == wizard_display_key:
                    existing_key = k
                    break

            fields = parsed_data.get(existing_key, {}) if existing_key else {}

            lines = []
            lines.append("# " + "=" * 60)
            lines.append(f"# DISPLAY: {wizard_display_key.upper()}")
            lines.append(f"# Compatibility: {comp_class.upper()}")
            lines.append(f"# Selected by user during KACE display setup wizard")

            if comp_class == "unsafe":
                lines.append("# 🔴 DANGER: THIS COMBINATION IS UNSAFE / HIGH RISK!")
                for risk in hw_info.get("damage_risks", []):
                    lines.append(f"#    RISK: {risk}")
                for mod in hw_info.get("required_modifications", []):
                    lines.append(f"#    REQUIRED MODIFICATION: {mod}")
            elif comp_class == "compatible_with_adapter":
                lines.append("# 🟡 WARNING: ADAPTER OR WIRING MODIFICATION REQUIRED.")
                for mod in hw_info.get("required_modifications", []):
                    lines.append(f"#    REQUIRED: {mod}")
            elif comp_class == "experimental":
                lines.append("# 🟠 EXPERIMENTAL: Community reports only — outcome uncertain.")

            for note in hw_info.get("notes", []):
                lines.append(f"# Note: {note}")
            lines.append("# " + "=" * 60)

            if comp_class in ("unsafe", "compatible_with_adapter"):
                lines.append(f"# [{wizard_display_key}]")
                if fields:
                    for k, v in fields.items():
                        if "pin" in k.lower():
                            lines.append(f"# {k}: TODO # WAS: {v}")
                        else:
                            lines.append(f"# {k}: {v}")
                else:
                    lines.append(f"# TODO: Configure [{wizard_display_key}] section manually")
                    lines.append(f"# Refer to Klipper docs: Config_Reference.md#[display]")
            else:
                lines.append(f"[{wizard_display_key}]")
                if fields:
                    for k, v in fields.items():
                        lines.append(f"{k}: {v}")
                else:
                    lines.append(f"# TODO: Add pin configuration for [{wizard_display_key}]")
                    lines.append(f"# Refer to Klipper docs: Config_Reference.md#[display]")

            display_blocks.append("\n".join(lines))

    else:
        # Fallback / auto mode: existing detection-based logic (no wizard choice)
        detected_displays = detect_display_sections(parsed_data)

        for section in detected_displays:
            if section in _WIZARD_SKIP_SECTIONS:
                continue
            matching_keys = [k for k in parsed_data if k.split()[0].lower() == section]
            for full_key in matching_keys:
                fields = parsed_data[full_key]
                if not isinstance(fields, dict):
                    continue

                hw_info = classify_hardware_combination(section, board_filename, parsed_data)
                comp_class = hw_info.get("compatibility_class", "experimental")

                lines = []
                lines.append("# " + "=" * 60)
                lines.append(f"# DISPLAY: {full_key.upper()}")
                lines.append(f"# Compatibility: {comp_class.upper()}")

                if comp_class == "unsafe":
                    lines.append("# 🔴 DANGER: THIS COMBINATION IS UNSAFE / HIGH RISK!")
                    for risk in hw_info.get("damage_risks", []):
                        lines.append(f"#    RISK: {risk}")
                    for mod in hw_info.get("required_modifications", []):
                        lines.append(f"#    REQUIRED MODIFICATION: {mod}")
                elif comp_class == "compatible_with_adapter":
                    lines.append("# 🟡 WARNING: ADAPTER OR WIRING MODIFICATION REQUIRED.")
                    for mod in hw_info.get("required_modifications", []):
                        lines.append(f"#    REQUIRED: {mod}")

                for note in hw_info.get("notes", []):
                    lines.append(f"# Note: {note}")
                lines.append("# " + "=" * 60)

                if comp_class in ("unsafe", "compatible_with_adapter"):
                    lines.append(f"# [{full_key}]")
                    for k, v in fields.items():
                        if "pin" in k.lower():
                            lines.append(f"# {k}: TODO # WAS: {v}")
                        else:
                            lines.append(f"# {k}: {v}")
                else:
                    lines.append(f"[{full_key}]")
                    for k, v in fields.items():
                        lines.append(f"{k}: {v}")

                display_blocks.append("\n".join(lines))

    if display_blocks:
        final_output += "\n\n# ==================================================\n# DISPLAY HARDWARE SECTIONS\n# ==================================================\n"
        final_output += "\n\n".join(display_blocks) + "\n"


    # Validation: Do not proceed if generic TODO pins are left active, preventing Klipper startup errors
    active_todos = []
    current_section = "unknown"
    for line in final_output.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and "]" in stripped:
            current_section = stripped
        elif "TODO" in line and not line.lstrip().startswith("#"):
            key = line.split(":")[0].strip().lstrip("#").strip()
            active_todos.append((current_section, key))

    if active_todos:
        if os.environ.get("KACE_TESTING") != "1":
            print("\n\033[91mCRITICAL ERROR: Configuration generated with unresolved 'TODO' values!\033[0m")
            print("\033[93mThis usually happens if your board does not map all required pins natively.\033[0m")
            for section, key in active_todos:
                print(f"TODO_FOUND: {section} -> {key}")
            print("\033[91mGeneration aborted to guarantee it starts without errors in Klipper.\033[0m")
        raise GenerationError(
            "Configuration has unresolved TODO pins — generation aborted.",
            todos=active_todos,
        )
        
    # Write to printer.cfg
    if not output_path:
        base_path = os.path.expanduser('~/kace')
        os.makedirs(base_path, exist_ok=True)
        cfg_file = os.path.join(base_path, 'printer.cfg')
    else:
        parent = os.path.dirname(os.path.abspath(output_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        cfg_file = output_path
        
    with open(cfg_file, 'w', encoding='utf-8') as f:
        f.write(final_output)

    if include_macros or user_data.get("macros_generated"):
        output_dir = os.path.dirname(cfg_file)
        generate_starter_macros(output_dir)

    return {
        "content": final_output,
        "motion_space": user_ctx["motion_space"],
        "bed_mesh": user_ctx.get("bed_mesh")
    }
