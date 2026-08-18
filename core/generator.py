import os
import re
from jinja2 import Environment, FileSystemLoader
from core.translations import translate_comment, get_lang
from core.macro_generator import generate_starter_macros
from core.advanced_module_handler import get_advanced_sections
from core.exceptions import GenerationError
from core.capabilities import (
    normalize_and_validate_configuration,
    validate_display_selection,
    validate_kinematics,
)
from core.profile_values import (
    ValueProvenance,
    require_resolved_homing_values,
    require_resolved_safety_values,
    resolve_generation_values,
)
from core.probe_configuration import (
    apply_probe_compatibility_context,
    resolve_probe_configuration,
)

# D2-03: Pre-compiled module-level regex for inline comment boundary matching
_INLINE_COMMENT_RE = re.compile(r'(\s)(#)(.*)')
_VERBATIM_CUSTOM_BEGIN = "__KACE_VERBATIM_CUSTOM_PROBE_BEGIN__"
_VERBATIM_CUSTOM_END = "__KACE_VERBATIM_CUSTOM_PROBE_END__"

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


def _native_feature_sections(parsed_data: dict) -> dict:
    """Return idempotent defaults for KACE-managed Klipper features.

    Existing section values are copied verbatim. Defaults are added only when
    the corresponding option is absent, including case-insensitive matches.
    """
    sections = {}
    for target in ("exclude_object", "force_move"):
        existing = next(
            (
                values
                for name, values in parsed_data.items()
                if str(name).strip().casefold() == target
                and isinstance(values, dict)
            ),
            {},
        )
        sections[target] = dict(existing)

    force_move = sections["force_move"]
    if not any(str(key).strip().casefold() == "enable_force_move" for key in force_move):
        force_move["enable_force_move"] = "True"

    return sections


def _validate_and_sanitize_geometry(user_ctx: dict) -> None:
    """Compatibility wrapper over the authoritative capability validator."""
    normalize_and_validate_configuration(user_ctx)

def _render_display_blocks(user_ctx, pins_ctx, parsed_data) -> str:
    """Generate display hardware blocks and strip display pins if display is 'none'.

    Mutates pins_ctx in place.
    Returns:
        str: Rendered display section text to append to final config, or empty string.
    """
    display_blocks = []
    from core.display_checker import (
        detect_display_sections,
        classify_hardware_combination,
        _WIZARD_SKIP_SECTIONS
    )
 
    display_choice = user_ctx.get("display_choice")
    board_filename = user_ctx.get('board', '')

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
        return ""

    if display_choice and display_choice not in (None,) and not display_choice.startswith("__"):
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
        return "\n\n# ==================================================\n# DISPLAY HARDWARE SECTIONS\n# ==================================================\n" + "\n\n".join(display_blocks) + "\n"
    return ""

def generate_config(parsed_data, user_data, output_path=None, include_macros=False, verbose=True):
    """Generate printer.cfg from parsed config and user data using Jinja2."""
    # Avoid in-place mutation of user_data by using a localized context dict
    user_ctx = dict(user_data)
    resolved_values, value_provenance = resolve_generation_values(parsed_data, user_ctx)
    require_resolved_safety_values(value_provenance)
    user_ctx.update(resolved_values)
    user_ctx["value_provenance"] = value_provenance
    user_ctx["emit_value_provenance"] = bool(user_data.get("_value_provenance"))
    user_ctx["kinematics"] = validate_kinematics(user_ctx.get("kinematics"))
    user_ctx["include_macros"] = include_macros
    probe_configuration = resolve_probe_configuration(user_ctx)
    apply_probe_compatibility_context(user_ctx, probe_configuration)
    user_ctx["probe_configuration"] = probe_configuration
    require_resolved_homing_values(
        value_provenance,
        uses_virtual_z_endstop=probe_configuration.uses_virtual_z_endstop,
    )
    if (
        user_ctx.get("probe_uses_virtual_z_endstop")
        and value_provenance.get("z_position_min") == ValueProvenance.SAFE_DEFAULT.value
    ):
        # A small negative calibration range is the safe contextual default for
        # probe-based Z homing. Never replace an explicit profile/user value.
        user_ctx["z_position_min"] = "-2"

    normalize_and_validate_configuration(user_ctx)
    validate_display_selection(user_ctx, parsed_data)

    # Build and serialize the motion space model using the sanitized user_ctx
    from core.motion_model import PrinterMotionSpace
    space = PrinterMotionSpace(user_ctx)
    if probe_configuration.generates_safe_z_home or probe_configuration.generates_bed_mesh:
        try:
            space.validate_probeable_area()
            safe_home_x, safe_home_y = space.safe_z_home_position()
        except ValueError as exc:
            raise GenerationError(str(exc)) from exc
        user_ctx["safe_z_home_x"] = f"{safe_home_x:g}"
        user_ctx["safe_z_home_y"] = f"{safe_home_y:g}"
    user_ctx["motion_space"] = space.to_dict()

    # Auto-generate bed_mesh config
    from core.bed_mesh import generate_bed_mesh_config
    user_ctx["bed_mesh"] = generate_bed_mesh_config(
        space, user_ctx, parsed_data, probe_configuration=probe_configuration
    )

    # Derive leveling coordinates
    from core.leveling import derive_leveling_points
    user_ctx["leveling"] = derive_leveling_points(space, int(user_ctx.get("z_motors") or 1))
    # Setup Jinja2 environment
    env = Environment(loader=FileSystemLoader(_TEMPLATES_DIR, encoding='utf-8'))
    template = env.get_template('printer.cfg.j2')

    # Q-06: Use deepcopy so fan-pin mutations to pins_ctx cannot bleed back
    # into the caller's parsed_data through shared nested dict references.
    import copy
    pins_ctx = copy.deepcopy(parsed_data)
    
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
    pins_ctx['_native_features'] = _native_feature_sections(parsed_data)

    # Render the template with parsed pins and user input
    output = template.render(
        pins=pins_ctx,
        user=user_ctx
    )
    
    final_output = _postprocess_generated_output(output)

    # â”€â”€ Display blocks rendering â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    final_output += _render_display_blocks(user_ctx, pins_ctx, parsed_data)


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
        if verbose:
            print("\n\033[91mCRITICAL ERROR: Configuration generated with unresolved 'TODO' values!\033[0m")
            print("\033[93mThis usually happens if your board does not map all required pins natively.\033[0m")
            for section, key in active_todos:
                print(f"TODO_FOUND: {section} -> {key}")
            print("\033[91mGeneration aborted to guarantee it starts without errors in Klipper.\033[0m")
        raise GenerationError(
            "Configuration has unresolved TODO pins â€” generation aborted.",
            todos=active_todos,
        )

    # Generation owns only the requested output artifacts. Reconciliation with
    # live printer.cfg/moonraker.conf is a deployment concern: reading or
    # mutating ~/printer_data here made USB/temp generation unexpectedly alter
    # the running printer.
    from core.reconciler import write_text_atomically

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

    write_text_atomically(cfg_file, final_output)

    if include_macros or user_data.get("macros_generated"):
        output_dir = os.path.dirname(cfg_file)
        generate_starter_macros(
            output_dir,
            motion_space=space,
            hotend_control=user_ctx.get("hotend_control", "pid"),
            bed_control=user_ctx.get("bed_control", "pid"),
        )

    return {
        "content": final_output,
        "motion_space": user_ctx["motion_space"],
        "bed_mesh": user_ctx.get("bed_mesh"),
        "value_provenance": value_provenance,
    }


def _postprocess_generated_output(output: str) -> str:
    """Align generated text while leaving custom blocks byte-for-byte intact.

    The template emits sentinel lines around a custom block.  The only allowed
    change to that block is one newline inserted after it when needed to keep
    the following generated section on a separate line.
    """
    if _VERBATIM_CUSTOM_BEGIN not in output:
        return _align_and_translate_generated_output(output)
    begin = f"{_VERBATIM_CUSTOM_BEGIN}\n"
    end = f"\n{_VERBATIM_CUSTOM_END}"
    if output.count(begin) != 1 or output.count(end) != 1:
        raise GenerationError("Invalid custom probe rendering boundary.")
    prefix, remainder = output.split(begin, 1)
    custom_block, suffix = remainder.split(end, 1)
    processed_prefix = _align_and_translate_generated_output(prefix)
    prefix_boundary = "" if not processed_prefix or processed_prefix.endswith("\n") else "\n"
    boundary = "" if custom_block.endswith("\n") else "\n"
    return (
        processed_prefix
        + prefix_boundary
        + custom_block
        + boundary
        + _align_and_translate_generated_output(suffix)
    )


def _align_and_translate_generated_output(output: str) -> str:
    """Apply KACE's existing comment formatting only to KACE-generated text."""
    # R-04 / D2-03: Locate the inline comment boundary using pre-compiled regex.
    aligned_lines = []
    comment_col = 48
    # get_lang() is always authoritative: set by the dashboard language picker
    # before the wizard runs. user_data['language'] is a synced copy of it.
    language = get_lang()
    for line in output.splitlines():
        # Detect whether this line has a genuine inline comment delimiter.
        # A full-line comment (starts with '#') is handled separately below.
        is_full_line_comment = line.lstrip().startswith('#')
        inline_match = None if is_full_line_comment else _INLINE_COMMENT_RE.search(line)

        if inline_match:
            # Split at the matched '#' to isolate content from comment text.
            split_pos = inline_match.start(2)  # position of the '#'
            content = line[:split_pos].rstrip()
            comment = line[split_pos + 1:].strip()

            # Translate if necessary
            comment = translate_comment(comment, language)

            # Ensure at least one space before the comment
            padding = max(1, comment_col - len(content))
            aligned_lines.append(f"{content}{' ' * padding}# {comment}")
        elif is_full_line_comment and line.count('#') > 1:
            # Commented setting lines (## style) — find the second '#'
            first_hash = line.find('#')
            second_hash = line.find('#', first_hash + 1)
            content = line[:second_hash].rstrip()
            comment = line[second_hash + 1:].strip()

            comment = translate_comment(comment, language)

            padding = max(1, comment_col - len(content))
            aligned_lines.append(f"{content}{' ' * padding}# {comment}")
        else:
            # Regular line or normal full-line comment
            if line.lstrip().startswith('#'):
                comment = line.lstrip()[1:].strip()
                # R2-05: Guard against empty comment lines (e.g. plain '#')
                if comment:
                    translated = translate_comment(comment, language)
                    if comment != translated:
                        # Update translated full line comment
                        line = line.replace(f"# {comment}", f"# {translated}")
            aligned_lines.append(line)

    return chr(10).join(aligned_lines)
