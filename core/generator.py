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
    resolve_tmc_sections,
)
from core.probe_configuration import (
    apply_probe_compatibility_context,
    is_probe_virtual_endstop,
    resolve_probe_configuration,
    selected_bltouch_flags,
    validate_bltouch_flags,
    selected_bltouch_hardware_options,
    validate_bltouch_hardware_options,
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
            hw_info   = classify_hardware_combination(wizard_display_key, board_filename, parsed_data, user_ctx.get("mcu_type", ""))
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

                hw_info = classify_hardware_combination(section, board_filename, parsed_data, user_ctx.get("mcu_type", ""))
                if hw_info.get("hardware_evidence") == "unknown":
                    raise GenerationError("Unknown display hardware compatibility: board identity, interface and electrical evidence are required.")
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

def generate_config(parsed_data, user_data, output_path=None, include_macros=False, verbose=True, *, thermal_review_only=False):
    """Generate printer.cfg from parsed config and user data using Jinja2."""
    from core.homing_source import require_supported_source_homing, require_supported_homing_context
    require_supported_source_homing(parsed_data)
    require_supported_homing_context(user_data)
    from core.board_auxiliary import (require_supported_board_electrical_dependencies,
                                      selected_static_digital_outputs, validate_static_digital_outputs)
    require_supported_board_electrical_dependencies(parsed_data)
    from core.board_cooling import required_board_fans, validate_required_cooling
    required_cooling = required_board_fans(parsed_data, user_data.get("board"))
    static_outputs = selected_static_digital_outputs(parsed_data)
    from core.board_auxiliary import MOTOR_POWER, selected_board_digital_outputs, validate_board_digital_outputs
    board_outputs = selected_board_digital_outputs(parsed_data)
    from core.board_pwm import selected_fixed_pwm_beepers, validate_fixed_pwm_outputs
    pwm_outputs = selected_fixed_pwm_beepers(parsed_data)
    # Avoid in-place mutation of user_data by using a localized context dict
    user_ctx = dict(user_data)
    resolved_values, value_provenance = resolve_generation_values(parsed_data, user_ctx)
    from core.profile_values import validate_motion_timing
    if value_provenance.get('minimum_cruise_ratio') == 'UNRESOLVED':
        raise GenerationError("minimum_cruise_ratio is unresolved; review the explicit value.")
    if 'minimum_cruise_ratio' not in resolved_values:
        user_ctx.pop('minimum_cruise_ratio', None)
    validate_motion_timing({'printer': {
        key: value for key, value in resolved_values.items() if key == 'minimum_cruise_ratio'
    }})
    from core.profile_values import HOMING_OPTIONS, validate_homing_options
    for axis in ("x", "y", "z"):
        for option in HOMING_OPTIONS:
            key = f"{option}_{axis}"
            if (key in (user_ctx.get('_value_provenance') or {})
                    and value_provenance.get(key) == 'UNRESOLVED'):
                raise GenerationError(f"{key} is unresolved; review the explicit homing value.")
            if key not in resolved_values:
                # A new profile may omit an old optional value still in wizard state.
                user_ctx.pop(key, None)
    validate_homing_options({f"stepper_{axis}": {
        option: resolved_values[f"{option}_{axis}"] for option in HOMING_OPTIONS
        if f"{option}_{axis}" in resolved_values
    } for axis in ("x", "y", "z")})
    from core.profile_values import EXTRUDER_OPTIONS, validate_primary_extruder_options
    for option in EXTRUDER_OPTIONS:
        key = "extruder_" + option
        if key in (user_ctx.get('_value_provenance') or {}) and value_provenance.get(key) == 'UNRESOLVED':
            raise GenerationError(f"{key} is unresolved; review the explicit value.")
        if key not in resolved_values:
            user_ctx.pop(key, None)
    user_ctx['_extruder_options'] = {option: resolved_values['extruder_' + option]
                                     for option in EXTRUDER_OPTIONS if 'extruder_' + option in resolved_values}
    require_resolved_safety_values(value_provenance)
    user_ctx.update(resolved_values)
    user_ctx["value_provenance"] = value_provenance
    user_ctx["emit_value_provenance"] = False
    user_ctx["kinematics"] = validate_kinematics(user_ctx.get("kinematics"))
    user_ctx["include_macros"] = include_macros
    probe_configuration = resolve_probe_configuration(user_ctx)
    apply_probe_compatibility_context(user_ctx, probe_configuration)
    user_ctx["probe_configuration"] = probe_configuration
    if (
        user_ctx.get("probe_uses_virtual_z_endstop")
        and value_provenance.get("z_position_min") == ValueProvenance.SAFE_DEFAULT.value
    ):
        # A small negative calibration range is the safe contextual default for
        # probe-based Z homing. Never replace an explicit profile/user value.
        user_ctx["z_position_min"] = "-2"

    normalize_and_validate_configuration(user_ctx)
    validate_display_selection(user_ctx, parsed_data)

    # Invalid travel/endstop geometry must be reported before asking for a
    # direction: an explicit homing choice cannot repair an invalid range.
    require_resolved_homing_values(
        value_provenance,
        uses_virtual_z_endstop=probe_configuration.uses_virtual_z_endstop,
    )

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
    from core.bed_mesh import generate_bed_mesh_config, validate_mesh_clearance, validate_mesh_interpolation
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
    from core.homing_source import additional_z_endstops, validate_additional_z_endstops
    pins_ctx['_additional_z_endstops'] = additional_z_endstops(parsed_data)
    pins_ctx['_bltouch_flags'] = {}
    from core.probe_sampling import selected_bltouch_sampling, validate_probe_sampling
    pins_ctx['_bltouch_hardware'] = {}
    pins_ctx['_bltouch_sampling'] = {}
    if probe_configuration.kind in ("bltouch", "cr_touch"):
        pins_ctx['_bltouch_flags'] = selected_bltouch_flags(parsed_data, user_ctx)
        pins_ctx['_bltouch_sampling'] = selected_bltouch_sampling(parsed_data, user_ctx)
        for field in ("sensor_pin", "control_pin"):
            choice = user_ctx.get(f"bltouch_{field}")
            if choice is not None:
                pins_ctx.setdefault("bltouch", {})[field] = choice
        pins_ctx['_bltouch_hardware'] = selected_bltouch_hardware_options(parsed_data, user_ctx, pins_ctx)
    pins_ctx['_tmc_sections'] = resolve_tmc_sections(parsed_data, user_ctx)
    
    # Apply custom fan assignments if present in user_data
    from core.part_fan import selected_part_fan, validate_part_fan_options, SCALAR_OPTIONS
    part_fan = selected_part_fan(parsed_data, user_data.get("fan_part_cooling_pin"))
    if part_fan is None:
        pins_ctx.pop("fan", None)
    else:
        pins_ctx["fan"] = part_fan
    pins_ctx["_part_fan_scalar_options"] = SCALAR_OPTIONS
            
    from core.hotend_fan import selected_hotend_fans, validate_heater_fan_options
    selected_hotend = selected_hotend_fans(parsed_data, user_data.get("fan_hotend_pin"))
    selected_hotend = {**required_cooling, **selected_hotend}
    pins_ctx["_selected_hotend_fans"] = {n: v for n, v in selected_hotend.items() if n.startswith("heater_fan ")}
    pins_ctx["_selected_controller_fans"] = {n: v for n, v in selected_hotend.items() if n.startswith("controller_fan ")}
    pins_ctx.pop("heater_fan hotend_fan", None)
    pins_ctx.update(selected_hotend)

    if "fan" in pins_ctx:
        fan_fields = pins_ctx["fan"]
        fan_pin = fan_fields.get("pin") if isinstance(fan_fields, dict) else None
        if not isinstance(fan_pin, str) or not fan_pin.strip():
            raise GenerationError("Part cooling fan requires a nonempty pin.")

    from core.validators import questionary_fan_pin_validator
    for section in ("fan", *selected_hotend):
        if section not in pins_ctx:
            continue
        fields = pins_ctx[section]
        token = fields.get("pin") if isinstance(fields, dict) else None
        if (not isinstance(token, str)
                or questionary_fan_pin_validator(token) is not True):
            raise GenerationError(f"{section}: invalid fan pin {token!r}; PWM allows only a leading !.")

    pins_ctx['_advanced_sections'] = get_advanced_sections(parsed_data)
    pins_ctx['_native_features'] = _native_feature_sections(parsed_data)
    from core.thermistor import selected_custom_thermistors, validate_custom_thermistors
    pins_ctx['_custom_thermistors'] = selected_custom_thermistors(parsed_data, user_ctx)
    from core.adc_scaled import selected_adc_scaled, validate_adc_scaled
    pins_ctx['_adc_scaled'] = selected_adc_scaled(parsed_data, pins_ctx)
    from core.host_mcu import selected_host_adc_mcus, validate_host_adc_mcus
    pins_ctx['_host_adc_mcus'] = selected_host_adc_mcus(parsed_data, pins_ctx)
    from core.primary_mcu import selected_restart_method
    user_ctx['mcu_restart_method'] = selected_restart_method(parsed_data, user_ctx.get('mcu_path'))
    pins_ctx['_board_pin_sections'] = {
        name: options for name, options in parsed_data.items()
        if name == 'board_pins' or name.startswith('board_pins ')
    }

    # Record effective hardware inputs separately from profile-derived values.
    # These include explicit wizard assignments; they are not a claim that
    # every source section is rendered or that physical wiring was verified.
    configuration_sources = {
        "board": user_ctx.get("board"),
        "selected_hotend_fans": copy.deepcopy(selected_hotend),
        "required_board_cooling": copy.deepcopy(required_cooling),
        "printer_profile": user_ctx.get("printer_profile"),
        "hardware_source_policy": user_ctx.get("hardware_source_policy"),
        "custom_thermistors": copy.deepcopy(pins_ctx['_custom_thermistors']),
        "adc_scaled": copy.deepcopy(pins_ctx['_adc_scaled']),
        "host_adc_mcus": copy.deepcopy(pins_ctx['_host_adc_mcus']),
        "bltouch_flags": copy.deepcopy(pins_ctx['_bltouch_flags']),
        "bltouch_hardware": copy.deepcopy(pins_ctx['_bltouch_hardware']),
        "bltouch_sampling": copy.deepcopy(pins_ctx['_bltouch_sampling']),
        "static_digital_outputs": copy.deepcopy(static_outputs),
        "motor_power": {name: copy.deepcopy(fields) for name, fields in board_outputs.items() if name == MOTOR_POWER},
        "auxiliary_digital_outputs": {name: copy.deepcopy(fields) for name, fields in board_outputs.items() if name != MOTOR_POWER},
        "fixed_pwm_beepers": copy.deepcopy(pwm_outputs),
        "probe_reset": copy.deepcopy(parsed_data.get("_board_probe_reset_source")),
        "bx_panel": copy.deepcopy(parsed_data.get("_board_bx_panel_source")),
        "hardware_options": copy.deepcopy({
            name: options for name, options in pins_ctx.items()
            if not name.startswith("_")
        }),
        "hardware_choices": {
            key: user_ctx[key] for key in (
                "z_socket_assignments", "driver_type", "driver_mode", "probe",
                "fan_part_cooling_pin", "fan_hotend_pin",
            ) if key in user_ctx
        },
    }

    # These resistors belong to the selected board's ADC circuit, like the
    # sensor pin, not to a separate printer profile or a thermal preset.
    from core.profile_values import validate_sensor_resistors
    validate_sensor_resistors({name: pins_ctx[name] for name in ("extruder", "heater_bed") if name in pins_ctx})
    from core.thermistor import validate_adc_sensor_options, validate_sensor_references, validate_adc_pin_dependencies, validate_bed_circuit
    selected_sensors = {
        name: {**pins_ctx.get(name, {}), "sensor_type": user_ctx[key]}
        for name, key in (("extruder", "hotend_thermistor"), ("heater_bed", "bed_thermistor"))
    }
    selected_sections = {**pins_ctx['_custom_thermistors'], **selected_sensors}
    validate_bed_circuit(selected_sections, required=True)
    validate_sensor_references(selected_sections, generating=True)
    validate_adc_sensor_options(selected_sections)

    # Render the template with parsed pins and user input
    output = template.render(
        pins=pins_ctx,
        user=user_ctx
    )
    
    final_output = _postprocess_generated_output(output)

    # â”€â”€ Display blocks rendering â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    final_output += _render_display_blocks(user_ctx, pins_ctx, parsed_data)
    for name, fields in static_outputs.items():
        final_output += f"\n[{name}]\npins: {fields['pins']}\n"
    for name, fields in {**board_outputs, **pwm_outputs}.items():
        final_output += f"\n[{name}]\n" + "".join(f"{key}: {value}\n" for key, value in fields.items())
    from core.board_probe_reset import render_probe_reset
    final_output = render_probe_reset(parsed_data, final_output)
    from core.board_bx_panel import render_bx_panel, validate_bx_panel, selected_bx_cooling
    final_output = render_bx_panel(parsed_data, final_output)
    configuration_sources["bx_cooling"] = selected_bx_cooling(parsed_data)

    from core.thermal_review import review_payload, render_confirmed_policy
    thermal_review = review_payload(parsed_data, user_data, final_output)
    if not thermal_review_only:
        final_output = render_confirmed_policy(thermal_review, user_data, final_output)
        if thermal_review["policy"]:
            configuration_sources["thermal_policy_confirmation"] = thermal_review


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

    # Validate the effective assignments after template/display rendering and
    # before writing anything, including when choices came from a checkpoint.
    from core.tmc_uart import validate_uart_config
    validate_uart_config(final_output)
    from core.pin_validator import _read_pin_config
    from core.profile_values import (
        tmc_option_sources, validate_tmc_sense_resistors,
        validate_tmc_current_settings, validate_tmc_spi_options, validate_tmc_register_values,
        validate_tmc_auxiliary_options,
    )
    rendered_sections = _read_pin_config(final_output)[0]
    validate_additional_z_endstops(parsed_data, rendered_sections, z_count=int(user_ctx.get('z_motors') or 1))
    from core.primary_mcu import validate_primary_restart
    validate_primary_restart(rendered_sections, expected=user_ctx['mcu_restart_method'])
    from core.heater_verification import validate_verify_heater, validate_source_verification
    validate_verify_heater(final_output)
    if not thermal_review_only:
        validate_source_verification(parsed_data, final_output)
        profile_source = user_data.get("_profile_parsed")
        if isinstance(profile_source, dict):
            validate_source_verification(profile_source, final_output)
    validate_part_fan_options(rendered_sections)
    validate_heater_fan_options(final_output)
    validate_mesh_clearance(rendered_sections)
    validate_mesh_interpolation(rendered_sections)
    validate_static_digital_outputs(rendered_sections)
    validate_bltouch_flags(rendered_sections)
    validate_bltouch_hardware_options(rendered_sections, expected=pins_ctx['_bltouch_hardware'])
    validate_probe_sampling(rendered_sections, expected=pins_ctx['_bltouch_sampling'])
    validate_motion_timing(rendered_sections)
    validate_homing_options(rendered_sections)
    validate_primary_extruder_options(rendered_sections)
    validate_bed_circuit(rendered_sections, required=True)
    from core.board_auxiliary import validate_replicape_platform
    validate_replicape_platform(rendered_sections)
    validate_sensor_references(rendered_sections, generating=True)
    validate_custom_thermistors(rendered_sections)
    validate_sensor_resistors(rendered_sections)
    validate_adc_sensor_options(rendered_sections)
    validate_adc_pin_dependencies(rendered_sections)
    validate_host_adc_mcus(rendered_sections, expected=pins_ctx['_host_adc_mcus'])
    validate_adc_scaled(rendered_sections)
    validate_tmc_sense_resistors(rendered_sections)
    validate_tmc_current_settings(rendered_sections)
    validate_tmc_spi_options(rendered_sections)
    validate_tmc_register_values(rendered_sections)
    validate_tmc_auxiliary_options(rendered_sections)
    from core.tmc_sensorless import validate_tmc_virtual_endstops
    validate_tmc_virtual_endstops(rendered_sections)
    if (is_probe_virtual_endstop(rendered_sections.get('stepper_z', {}).get('endstop_pin', ''))
            and not any(name in rendered_sections for name in ('probe', 'bltouch'))):
        raise GenerationError("[stepper_z] probe:z_virtual_endstop requires a generated probe; select the board's probe or an explicit physical Z endstop.")
    from core.tmc_spi import validate_spi_config
    validate_spi_config(final_output)
    configuration_sources["tmc_options"] = tmc_option_sources(
        user_ctx, pins_ctx['_tmc_sections'], rendered_sections, value_provenance)
    from core.pin_validator import validate_probe_pin_usage, PinAliasError
    from core.firmware_workflow import generation_pin_reservations, FirmwareWorkflowError
    from firmware.identity import FirmwareIdentityError
    try:
        reservations = {}
        if required_cooling or static_outputs or board_outputs or pwm_outputs or pins_ctx['_adc_scaled'] or probe_configuration.structured_section_name in ("bltouch", "probe") or probe_configuration.kind == "custom":
            reservations = generation_pin_reservations(user_data, config=final_output)
        from core.board_auxiliary import validate_static_pin_usage
        validate_static_pin_usage(rendered_sections, firmware_reservations=reservations)
        validate_board_digital_outputs(rendered_sections, firmware_reservations=reservations, selected_outputs=board_outputs)
        validate_fixed_pwm_outputs(rendered_sections, pwm_outputs, firmware_reservations=reservations)
        validate_bx_panel(parsed_data, rendered_sections, firmware_reservations=reservations)
        validate_required_cooling(parsed_data, rendered_sections, firmware_reservations=reservations)
        validate_adc_scaled(rendered_sections, firmware_reservations=reservations)
        validate_probe_pin_usage(final_output, firmware_reservations=reservations)
    except (PinAliasError, FirmwareIdentityError, FirmwareWorkflowError) as exc:
        raise GenerationError(str(exc)) from exc

    if thermal_review_only:
        # No CFG, provenance, macro or directory writes. Return review facts,
        # never a deployable content/path result with source requirements omitted.
        return {"thermal_review": thermal_review}

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
    import json
    write_text_atomically(cfg_file + ".provenance.json", json.dumps(
        {"schema": "kace-config-provenance/v1", "values": value_provenance,
         "resolved_values": {key: user_ctx.get(key) for key in resolved_values},
         "sources": configuration_sources},
        indent=2, sort_keys=True,
    ) + "\n")

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
