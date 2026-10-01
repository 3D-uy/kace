"""Preserve supported selected-board outputs and reject unimplemented dependencies.

This is an explicit support boundary, not physical electrical certification. The
scraper records active/commented provenance for these sections because the UI
also reads commented examples. Older/manual parsed dictionaries fail closed.
"""
import re
import copy
from core.exceptions import GenerationError

SOURCE_ACTIVITY = "_auxiliary_electrical_activity"
SOURCE_OPTIONS = "_auxiliary_electrical_active_options"
UNSUPPORTED_FAMILIES = frozenset({"dac084s085", "ad5206", "mcp4451", "mcp4018", "replicape"})
MOTOR_POWER = "output_pin motor_power"
BOARD_DIGITAL_OUTPUTS = (MOTOR_POWER, "output_pin probe_enable", "output_pin screen",
                         "output_pin probe_reset_pin", "output_pin LED", "output_pin enable_pin",
                         "output_pin machine_enable", "output_pin power")
DEFAULT_ZERO_OUTPUTS = frozenset({"output_pin probe_reset_pin", "output_pin LED"})
SELECTED_ONLY_OUTPUTS = DEFAULT_ZERO_OUTPUTS | {
    "output_pin enable_pin", "output_pin machine_enable", "output_pin power"}


def is_electrical_dependency(section):
    name = str(section).strip().lower()
    return name.split(" ", 1)[0] in UNSUPPORTED_FAMILIES | {"static_digital_output", "output_pin"}


def unresolved_pwm_outputs(parsed_board):
    """Do not silently drop a selected PWM circuit while its contract is pending.

    The UI parser also reads comments. Only proven inactive options may be
    ignored; older/manual PWM definitions without activity evidence fail closed.
    This guard does not ban unrelated PWM sections preserved in user includes.
    """
    activity = parsed_board.get(SOURCE_ACTIVITY, {})
    activity = activity if isinstance(activity, dict) else {}
    active_options = parsed_board.get(SOURCE_OPTIONS, {})
    from core.board_pwm import selected_fixed_pwm_beepers
    supported = selected_fixed_pwm_beepers(parsed_board)
    result = []
    for name, fields in parsed_board.items():
        if name in supported:
            continue
        if not str(name).lower().startswith("output_pin ") or activity.get(name) is False:
            continue
        options = active_options.get(name) if isinstance(active_options, dict) else None
        if (activity.get(name) is True and isinstance(options, list)
                and all(isinstance(key, str) for key in options) and "pwm" not in options):
            continue
        if isinstance(fields, dict) and "pwm" in fields:
            # Unknown boolean syntax also cannot authorize dropping this output.
            if str(fields["pwm"]).strip().lower() not in ("false", "no", "off", "0"):
                result.append(name)
    return sorted(result)


def unresolved_electrical_dependencies(parsed_board):
    activity = parsed_board.get(SOURCE_ACTIVITY, {})
    if not isinstance(activity, dict):
        activity = {}
    controllers = {section for section in parsed_board if is_electrical_dependency(section)
                  and str(section).split(" ", 1)[0].lower() in UNSUPPORTED_FAMILIES
                  and activity.get(section) is not False}
    return sorted(controllers | set(unresolved_pwm_outputs(parsed_board)))


def validate_static_digital_outputs(sections):
    from core.validators import questionary_fan_pin_validator
    for name, options in sections.items():
        if str(name).split(" ", 1)[0].lower() != "static_digital_output":
            continue
        if not re.fullmatch(r"static_digital_output [A-Za-z0-9_-]+", name):
            raise GenerationError(f"Invalid static_digital_output section name: {name!r}.")
        if not isinstance(options, dict) or set(options) != {"pins"} or not isinstance(options["pins"], str):
            raise GenerationError(f"[{name}] requires only an explicit pins list.")
        tokens = options["pins"].split(",")
        if any(questionary_fan_pin_validator(token) is not True for token in tokens):
            raise GenerationError(f"[{name}] requires digital output pins with optional ! inversion; no pull-up/down.")


def selected_static_digital_outputs(parsed_board):
    activity = parsed_board.get(SOURCE_ACTIVITY, {})
    activity = activity if isinstance(activity, dict) else {}
    active_options = parsed_board.get(SOURCE_OPTIONS, {})
    result = {}
    for name, fields in parsed_board.items():
        if str(name).split(" ", 1)[0].lower() != "static_digital_output" or activity.get(name) is False:
            continue
        if activity.get(name) is not True:
            raise GenerationError(f"[{name}] has no active-source evidence; reload the selected board before generation.")
        options = active_options.get(name) if isinstance(active_options, dict) else None
        if not isinstance(options, list) or "pins" not in options:
            raise GenerationError(f"[{name}] has no active pins; commented examples cannot enable electrical outputs.")
        result[name] = dict(fields) if isinstance(fields, dict) else fields
    validate_static_digital_outputs(result)
    return {name: {"pins": ", ".join(pin.strip() for pin in fields["pins"].split(","))}
            for name, fields in result.items()}


def validate_static_pin_usage(sections, *, firmware_reservations=None):
    """Static outputs exclusively own physical GPIOs; bypasses are unsupported.

    Reuse the board alias/MCU identity resolver. Firmware-provided bus and
    reserved-pin evidence is checked when available, as for probes/scaled ADC.
    This does not certify electrical levels or a physical MCU's capabilities.
    """
    validate_static_digital_outputs(sections)
    outputs = {name: fields["pins"].split(",") for name, fields in sections.items()
               if name.startswith("static_digital_output ")}
    _validate_exclusive_output_pins(sections, outputs, firmware_reservations, "Static digital output")


def _validate_exclusive_output_pins(sections, outputs, firmware_reservations, label):
    from core.pin_validator import PinAliases, PinAliasError
    if not outputs:
        return
    try:
        aliases = PinAliases(sections)
        mcus = {"mcu"} if "mcu" in sections else set()
        mcus.update(name[4:].strip() for name in sections if name.startswith("mcu "))
        allocated = {}
        for name, pins in outputs.items():
            for token in pins:
                if PinAliases.split_pin(token)[0] not in mcus:
                    raise PinAliasError(f"[{name}] requires a declared physical MCU: {token}")
                identity = aliases.resolve(token)
                if identity in allocated:
                    raise PinAliasError(f"[{name}] pin {token} conflicts with [{allocated[identity]}]")
                reason = (firmware_reservations or {}).get(identity[0], {}).get(identity[1])
                if reason is not None:
                    raise PinAliasError(f"[{name}] pin {token} is reserved for {reason}")
                allocated[identity] = name
        for name, fields in sections.items():
            if (name in outputs or name in ("board_pins", "duplicate_pin_override")
                    or name.startswith(("board_pins ", "gcode_macro ", "delayed_gcode "))):
                continue
            for field, value in fields.items():
                if not (field == "pin" or field.endswith("_pin")
                        or field in ("pins", "select_pins", "encoder_pins")):
                    continue
                normalized = re.sub(r"\s*:\s*", ":", value.strip())
                for token in re.split(r"[,\s]+", normalized):
                    if token and aliases.resolve(token) in allocated:
                        raise PinAliasError(f"[{name}] {field} conflicts with {label}: {token}")
    except PinAliasError as exc:
        raise GenerationError(f"{label}: {exc}") from exc


def digital_output_settings(fields, *, section=MOTOR_POWER):
    """Supported digital subset, with Klipper's omitted shutdown value of zero.

    Existing power/enable/screen signals require explicit start values; the
    reviewed reset/LED subset also supports Klipper's omitted zero default.
    All levels must be binary and finite.
    PWM/cycle/scale/static/extension options need a separate support contract.
    """
    from core.validators import questionary_fan_pin_validator
    required = {"pin"} if section in DEFAULT_ZERO_OUTPUTS else {"pin", "value"}
    if (not isinstance(fields, dict) or not required <= fields.keys()
            or set(fields) - {"pin", "value", "shutdown_value", "pwm"}):
        raise GenerationError(f"[{section}] requires explicit {'/'.join(sorted(required))} and only digital output options.")
    if str(fields.get("pwm", "false")).strip().lower() not in ("false", "no", "off", "0"):
        raise GenerationError(f"[{section}] PWM is unsupported; preserve a digital board signal.")
    if not isinstance(fields["pin"], str) or questionary_fan_pin_validator(fields["pin"]) is not True:
        raise GenerationError(f"[{section}] requires one digital output pin with optional ! inversion.")
    try:
        values = tuple(float(fields.get(key, "0")) for key in ("value", "shutdown_value"))
    except (ValueError, TypeError, OverflowError) as exc:
        raise GenerationError(f"[{section}] start/shutdown values must be binary finite levels.") from exc
    if any(value not in (0., 1.) for value in values):
        raise GenerationError(f"[{section}] start/shutdown values must be binary finite levels.")
    return values


def _selected_digital_output(parsed_board, section):
    if section not in parsed_board:
        return {}
    activity = parsed_board.get(SOURCE_ACTIVITY, {})
    activity = activity if isinstance(activity, dict) else {}
    if activity.get(section) is False:
        return {}
    if activity.get(section) is not True:
        raise GenerationError(f"[{section}] has no active-source evidence; reload the selected board.")
    active = parsed_board.get(SOURCE_OPTIONS, {})
    active = active.get(section) if isinstance(active, dict) else None
    fields = parsed_board[section]
    required = {"pin"} if section in DEFAULT_ZERO_OUTPUTS else {"pin", "value"}
    if (not isinstance(active, list) or any(not isinstance(key, str) for key in active)
            or not required <= set(active)
            or not isinstance(fields, dict) or any(key not in fields for key in active)):
        raise GenerationError(f"[{section}] requires active pin/value; commented examples cannot enable board outputs.")
    selected = {key: fields[key] for key in active}
    digital_output_settings(selected, section=section)
    return {section: selected}


def selected_board_digital_outputs(parsed_board):
    """Explicit digital subset of the catalog, not arbitrary output_pin support."""
    return {name: fields for section in BOARD_DIGITAL_OUTPUTS
            for name, fields in _selected_digital_output(parsed_board, section).items()}


def selected_motor_power(parsed_board):
    return _selected_digital_output(parsed_board, MOTOR_POWER)


def motor_power_settings(fields):
    return digital_output_settings(fields)


def validate_motor_power(sections, *, firmware_reservations=None):
    _validate_digital_output(sections, MOTOR_POWER, firmware_reservations)


def _validate_digital_output(sections, section, firmware_reservations):
    if section in sections:
        fields = sections[section]
        digital_output_settings(fields, section=section)
        _validate_exclusive_output_pins(sections, {section: [fields["pin"]]},
                                        firmware_reservations, section)


def validate_board_digital_outputs(sections, *, firmware_reservations=None, selected_outputs=None):
    for section in BOARD_DIGITAL_OUTPUTS:
        if section in SELECTED_ONLY_OUTPUTS and selected_outputs is not None and section not in selected_outputs:
            continue
        _validate_digital_output(sections, section, firmware_reservations)


def require_supported_board_electrical_dependencies(parsed_board):
    from core.homing_source import require_supported_source_homing
    require_supported_source_homing(parsed_board)
    from core.board_cooling import required_board_fans
    required_board_fans(parsed_board)
    selected_board_digital_outputs(parsed_board)
    from core.board_probe_reset import selected_probe_reset
    selected_probe_reset(parsed_board)
    from core.board_bx_panel import selected_bx_panel
    selected_bx_panel(parsed_board)
    sections = unresolved_electrical_dependencies(parsed_board)
    if sections:
        names = ", ".join(f"[{name}]" for name in sections)
        raise GenerationError(
            f"Selected board has unsupported electrical dependencies: {names}. "
            "KACE cannot yet preserve and validate these functions; configuration generation is blocked. "
            "Commented output is not a functional substitute."
        )


def validate_replicape_platform(sections):
    """Reject the unsupported host platform and its orphaned pin consumers.

    Only effective sections belong here (not the UI's commented examples).
    An explicit MCU named replicape is a different pin provider, not the board.
    This check neither provisions a host nor validates arbitrary pin chips.
    """
    from core.pin_validator import PinAliases
    if any(str(name).split(" ", 1)[0].casefold() == "replicape" for name in sections):
        raise GenerationError(
            "Replicape requires host-specific PRU, pinmux and SPI/PWM evidence; "
            "this platform is outside KACE installation support and cannot be published.")
    if "mcu replicape" in sections:
        return  # Ordinary MCU ownership checks remain applicable.
    for name, options in sections.items():
        if not isinstance(options, dict):
            continue
        for field, value in options.items():
            if not isinstance(value, str) or not (field == "pin" or field.endswith("_pin")
                    or field in ("pins", "select_pins", "encoder_pins")):
                continue
            normalized = re.sub(r"\s*:\s*", ":", value.strip())
            for token in re.split(r"[,\s]+", normalized):
                if token and PinAliases.split_pin(token)[0] == "replicape":
                    raise GenerationError(
                        f"[{name}] {field}: Replicape pin provider is absent; "
                        "KACE cannot publish partial configuration for this unsupported host platform.")


def selected_board_electrical_source(user_data):
    """Read board circuits and carry separate thermal/probe policy requirements.

    Raw selected-board text can recover active/commented provenance missing in
    an old parsed checkpoint. No network lookup or guessed GPIO is performed.
    Generic configuration APIs without selected sources remain source-agnostic.
    Printer-profile GPIOs never enter board authority; only thermal verification and probe sampling
    requirements travel in their own metadata for recovery/publication checks.
    """
    from core.homing_source import require_supported_homing_context
    require_supported_homing_context(user_data)
    checkpoint = user_data.get("workflow_checkpoint")
    saved = checkpoint.get("wizard_data", {}) if isinstance(checkpoint, dict) else {}
    saved = saved if isinstance(saved, dict) else {}
    board = user_data.get("board") or saved.get("board")
    if user_data.get("board") and saved.get("board") and user_data["board"] != saved["board"]:
        raise GenerationError("Selected board differs from its saved electrical source; reload the board.")
    source = {**saved, **user_data}
    from core.heater_verification import attach_profile_verification
    from core.probe_sampling import attach_profile_sampling

    def attach_context(board_source):
        thermal = attach_profile_verification(board_source, user_data, saved)
        return attach_profile_sampling(thermal, user_data, saved)

    raw = source.get("board_raw_config")
    if isinstance(raw, str) and raw.strip():
        from core.scraper import parse_config
        return attach_context(parse_config(raw, board or "", keep_comments=False))
    parsed = source.get("board_parsed")
    if isinstance(parsed, dict) and parsed:
        from core.board_cooling import required_board_fans
        required_board_fans(parsed, board)
        return attach_context(copy.deepcopy(parsed))
    if board or raw is not None or parsed is not None or checkpoint is not None:
        raise GenerationError("Selected-board electrical source is unavailable; reload the board before deployment.")
    return attach_context(None)


def validate_board_electrical_artifact(parsed_board, content):
    """Bind this K19 subset to an artifact or expanded effective configuration.

    This is not full profile reconciliation. It prevents already-generated
    artifacts from bypassing the unsupported-dependency guard and checks every
    selected active static/catalog digital output against physical MCU/GPIO and
    polarity, plus digital start and shutdown values.
    """
    from core.pin_validator import PinAliases, PinAliasError, _read_pin_config
    try:
        text = content.decode("utf-8") if isinstance(content, bytes) else content
        validate_replicape_platform(_read_pin_config(text)[0])
        from core.homing_source import validate_additional_z_endstops
        validate_additional_z_endstops(parsed_board, _read_pin_config(text)[0])
        from core.probe_configuration import validate_source_bltouch_hardware
        validate_source_bltouch_hardware(parsed_board, _read_pin_config(text)[0])
        from core.probe_sampling import validate_source_sampling
        validate_source_sampling(parsed_board, _read_pin_config(text)[0])
    except (PinAliasError, UnicodeError) as exc:
        raise GenerationError(f"Board electrical artifact validation failed: {exc}") from exc
    if parsed_board is None:
        return
    require_supported_board_electrical_dependencies(parsed_board)
    expected = selected_static_digital_outputs(parsed_board)
    expected_power = selected_board_digital_outputs(parsed_board)
    from core.board_pwm import selected_fixed_pwm_beepers, fixed_pwm_settings, validate_fixed_pwm_outputs
    expected_pwm = selected_fixed_pwm_beepers(parsed_board)
    try:
        text = content.decode("utf-8") if isinstance(content, bytes) else content
        from core.heater_verification import validate_source_verification, PROFILE_SOURCE, SOURCE
        validate_source_verification(parsed_board, text)
        if PROFILE_SOURCE in parsed_board:
            profile = parsed_board[PROFILE_SOURCE]
            if not isinstance(profile, dict) or not profile.get(SOURCE):
                raise GenerationError("Thermal profile requirements are malformed; reload the source context.")
            validate_source_verification(profile, text)
        from core.thermal_review import validate_reviewed_artifact
        validate_reviewed_artifact(parsed_board, text)
        actual = _read_pin_config(text)[0]
        from core.primary_mcu import validate_source_restart
        validate_source_restart(parsed_board, actual)
        from core.board_cooling import validate_required_cooling
        validate_required_cooling(parsed_board, actual)
        from core.fan_preservation import validate_present_fan_sources
        validate_present_fan_sources(parsed_board, actual)
        from core.board_probe_reset import validate_probe_reset_artifact
        validate_probe_reset_artifact(parsed_board, actual)
        validate_static_pin_usage(actual)
        validate_board_digital_outputs(actual, selected_outputs=expected_power)
        validate_fixed_pwm_outputs(actual, expected_pwm)
        from core.board_bx_panel import validate_bx_panel
        validate_bx_panel(parsed_board, actual)
        before, after = PinAliases(parsed_board), PinAliases(actual)

        def signals(options, aliases):
            return sorted((aliases.resolve(pin), pin.strip().startswith("!"))
                          for pin in options["pins"].split(","))

        for section, options in expected.items():
            if section not in actual or signals(options, before) != signals(actual[section], after):
                raise GenerationError(
                    f"Selected-board electrical dependency [{section}] is missing or changed; "
                    "reload the board and regenerate printer.cfg before deployment."
                )
        for section, original in {**expected_power, **expected_pwm}.items():
            candidate = actual.get(section)
            settings = (lambda fields: fixed_pwm_settings(fields, section)) if section in expected_pwm else (
                lambda fields: digital_output_settings(fields, section=section))
            if (candidate is None
                    or before.resolve(original["pin"]) != after.resolve(candidate["pin"])
                    or original["pin"].strip().startswith("!") != candidate["pin"].strip().startswith("!")
                    or settings(original) != settings(candidate)):
                raise GenerationError(f"Selected-board electrical dependency [{section}] is missing or changed; "
                                      "reload the board and regenerate printer.cfg before deployment.")
    except (PinAliasError, UnicodeError) as exc:
        raise GenerationError(f"Board electrical artifact validation failed: {exc}") from exc
