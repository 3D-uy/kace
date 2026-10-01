import re
import os
from core.menu import autocomplete_select, simple_input, yes_no, numbered_select
from core.translations import t, get_lang
from core.exceptions import WizardExit
from core.validators import questionary_pin_validator, questionary_thermistor_validator
from core.probe_offset_visualizer import run_probe_offset_step
from core.profile_values import mark_user_override
from core.pin_validator import PinAliases, PinAliasError
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
        {"name": t("wizard.probe_none"), "value": PROBE_KIND_NONE},
        {"name": "BLTouch", "value": PROBE_KIND_BLTOUCH},
        {"name": t("wizard.probe_inductive"), "value": PROBE_KIND_INDUCTIVE},
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
        back_value=_BACK,
    )
    if value == _BACK:
        return _BACK
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
    """Offer declared probe inputs and revalidate each selection before storing."""
    dedicated = _get_dedicated_probe_pin(user_data)
    candidates = _get_unused_pins(user_data)
    if dedicated:
        dedicated_pin, pullup, inverted = dedicated
        aliases = PinAliases({name: options for name, options in _get_parsed(user_data).items()
                              if isinstance(options, dict)})
        candidates = [(t("wizard.custom_probe_dedicated_pin"), dedicated_pin)] + [
            candidate for candidate in candidates
            if aliases.resolve(candidate[1]) != aliases.resolve(dedicated_pin)
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
            validation = make_pin_validator_with_collision_check(user_data, for_custom_probe=True)(answer)
            if validation is not True:
                print(f"\n[!] {validation}\n")
                return "__retry__"
            if dedicated and answer == dedicated[0]:
                base_pin, pullup, inverted = dedicated
            else:
                base_pin, pullup, inverted = _split_probe_pin_modifiers(answer)
            user_data["custom_probe_pin"] = base_pin
            user_data.setdefault("custom_probe_pullup", pullup)
            user_data.setdefault("custom_probe_inverted", inverted)
            return "done"

    value = simple_input(
        t("wizard.custom_probe_pin_manual_prompt"),
        default=user_data.get("custom_probe_pin", ""),
        validate=make_pin_validator_with_collision_check(user_data, for_custom_probe=True),
        back_value=_BACK,
    )
    if value == _BACK:
        return _BACK
    if value is None or str(value).strip().lower() in ("<", "back", "volver"):
        return _BACK
    validation = make_pin_validator_with_collision_check(user_data, for_custom_probe=True)(str(value).strip())
    if validation is not True:
        print(f"\n[!] {validation}\n")
        return "__retry__"
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
    """Offer the declared sensor only after checking the custom probe transition."""
    probe_section = _get_parsed(user_data).get("bltouch", {})
    sensor_pin = probe_section.get("sensor_pin") if isinstance(probe_section, dict) else None
    if not sensor_pin or "TODO" in str(sensor_pin).upper():
        return None
    if make_pin_validator_with_collision_check(user_data, for_custom_probe=True)(str(sensor_pin)) is not True:
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
        value = simple_input(t("wizard.custom_probe_x_offset"), validate=_custom_offset_validator, back_value=_BACK)
        if value == _BACK:
            return _BACK
        if value is None:
            return _BACK
        supplied["x_offset"] = value
    if custom_probe.y_offset is None:
        value = simple_input(t("wizard.custom_probe_y_offset"), validate=_custom_offset_validator, back_value=_BACK)
        if value == _BACK:
            return _BACK
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


def _get_mcu_for_board(board_name: str, detected_mcu: str = "") -> str:
    from core.board_identity import resolve_board_mcu
    return resolve_board_mcu(board_name, detected_mcu)



def _pin_allocations(parsed_board, *, ignored_fields=()):
    """Return MCU-local aliases and known pin consumers, without policing sharing."""
    sections = {name: options for name, options in parsed_board.items()
                if isinstance(options, dict)}
    resolver = PinAliases(sections)
    used = {}
    for section, options in sections.items():
        if (section == "board_pins" or section.startswith("board_pins ")
                or section == "duplicate_pin_override"):
            continue
        for key, value in options.items():
            if (section, key) in ignored_fields:
                continue
            if not isinstance(value, str) or not (
                key == "pin" or key.endswith("_pin")
                or key in ("pins", "select_pins", "encoder_pins")
            ):
                continue
            value = "\n".join(line.split("#", 1)[0].split(";", 1)[0]
                              for line in value.splitlines())
            for token in re.split(r"[,\s]+", value.strip()):
                if not token:
                    continue
                identity = resolver.resolve(token)
                comp = section
                if section.startswith("stepper_"):
                    comp = f"stepper {section.replace('stepper_', '').upper()}"
                used.setdefault(identity, f"{comp} ({key})")
    return resolver, used


def _get_unused_pins(user_data) -> list:
    """List board-declared aliases without a known configuration consumer.

    Never synthesize pads from an MCU family. Check known firmware reservations
    when evidence is available; an alias alone cannot certify electrical suitability.
    Manual wiring selection remains available when the board declares no aliases.
    """
    try:
        resolver, used_pins = _pin_allocations(_get_parsed(user_data))
    except PinAliasError:
        # The manual validator reports the invalid table instead of offering
        # candidates based on an ambiguous or reserved assignment.
        return []

    candidates = []
    # Keep friendly aliases in their MCU, and resolve to unchanged physical names.
    for chip, aliases in resolver.aliases.items():
        for alias in aliases:
            friendly = alias if chip == "mcu" else f"{chip}:{alias}"
            candidates.append((friendly, friendly))

    unused = []
    seen = set()
    check = make_pin_validator_with_collision_check(user_data)
    for friendly, token in candidates:
        try:
            chip, physical = resolver.resolve(token)
        except PinAliasError:
            continue
        identity = chip, physical
        pin = physical if chip == "mcu" else f"{chip}:{physical}"
        if identity in used_pins or identity in seen:
            continue
        if check(pin) is not True:
            continue
        seen.add(identity)
        unused.append((friendly, pin))
    return unused


def _validate_pin_for_mcu(pin_clean: str, mcu_type: str):
    """Existing architecture checks, applied to every still-possible board MCU."""
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

    elif "2560" in mcu_type or "1280" in mcu_type or mcu_type == "avr":
        if not (re.match(r'^p[a-l][0-7]$', pin_clean) or re.match(r'^(ar|analog)\d+$', pin_clean)):
            lang = get_lang()
            if lang == "Español":
                return f"Pin inválido para AVR/ATMEGA1280/2560. Debe ser tipo PA0-PL7 o ar0-ar69."
            elif lang == "Português":
                return f"Pino inválido para AVR/ATMEGA1280/2560. Deve ser tipo PA0-PL7 o ar0-ar69."
            else:
                return f"Invalid pin for AVR/ATMEGA1280/2560. Must be PA0-PL7 or ar0-ar69."

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


def make_pin_validator_with_collision_check(user_data, *, for_custom_probe=False):
    """Validate a new exclusive probe input/output against known allocations.

    This is not a whole-config sharing validator: existing shared enables and
    buses remain consumer-owned. A newly selected probe cannot share those
    lines. Alias metadata and duplicate-use permissions allocate no pin.
    """
    parsed_board = _get_parsed(user_data)
    alias_error = None
    from core.firmware_workflow import generation_pin_reservations, validate_checkpoint, FirmwareWorkflowError
    from firmware.identity import FirmwareIdentityError
    from core.exceptions import GenerationError
    try:
        # The guided custom probe replaces either existing probe input and
        # uses a virtual Z endstop. No motor, heater, control output or other
        # consumer is exempt; the final generated configuration is rechecked.
        ignored = (("bltouch", "sensor_pin"), ("probe", "pin"),
                   ("stepper_z", "endstop_pin")) if for_custom_probe else ()
        resolver, used_pins_map = _pin_allocations(parsed_board, ignored_fields=ignored)
        workflow = user_data.get("workflow_checkpoint")
        if (isinstance(workflow, dict) and workflow.get("artifact") is None
                and not any(user_data.get(key) for key in
                            ("firmware_artifact", "firmware_path", "firmware_identity"))):
            # Selection can precede compilation. Validate an early checkpoint,
            # but do not invent firmware evidence for it.
            validate_checkpoint(workflow, verify_artifact=True, current_hardware=user_data)
            reservations = {}
        else:
            # Board examples may contain other driver models or unused Z
            # sockets. Use the same selected-model projection as generation.
            from core.profile_values import resolve_tmc_sections
            # Other peripheral examples have not necessarily been selected.
            # Their authoritative bus check uses rendered/expanded config later.
            bus_sections = {name: options for name, options in parsed_board.items()
                            if isinstance(options, dict)
                            and (name == "board_pins" or name.startswith("board_pins "))}
            if user_data.get("driver_mode") == "SPI":
                bus_sections.update(resolve_tmc_sections(parsed_board, user_data))
            reservations = generation_pin_reservations(user_data, config=bus_sections)
    except (PinAliasError, FirmwareWorkflowError, FirmwareIdentityError, GenerationError) as exc:
        alias_error = str(exc)

    def validator(value: str):
        val_strip = value.strip()
        val_lower = val_strip.lower()
        if val_lower in ("<", "back", "volver"):
            return True

        # Standard format check first
        fmt_res = questionary_pin_validator(val_strip)
        if fmt_res != True:
            return fmt_res
        # Klipper inputs accept pull-up/down first, then optional inversion.
        bare = re.sub(r"^[\^~]?!?", "", val_strip)
        if any(char in bare for char in "^~!"):
            return "Invalid Klipper pin format: use [^~][!][chip:]pin"
        if for_custom_probe and val_strip.startswith("~"):
            return "This guided probe cannot preserve pull-down (~); use the custom configuration input."
        if alias_error:
            return alias_error
        try:
            chip, pin = resolver.resolve(val_strip)
        except PinAliasError as exc:
            return str(exc)
        reason = reservations.get(chip, {}).get(pin)
        if reason is not None:
            return f"Pin {val_strip} is reserved by firmware for {reason}"

        if (chip, pin) in used_pins_map:
            lang = get_lang()
            comp_info = used_pins_map[chip, pin]
            # Display the original user input for clarity in the error message
            display_pin = val_strip
            if lang == "Español":
                return f"El pin {display_pin} ya está en uso por: {comp_info}"
            elif lang == "Português":
                return f"O pino {display_pin} já está em uso por: {comp_info}"
            else:
                return f"Pin {display_pin} is already in use by: {comp_info}"

        # Validate resolved primary-MCU pins, including explicit mcu: and aliases.
        # Do not guess a secondary MCU's architecture from the mainboard.
        from core.board_identity import board_mcu_candidates, canonical_mcu
        candidates = board_mcu_candidates(user_data.get("board", ""))
        observed = canonical_mcu(user_data.get("mcu_type", ""))
        if chip == "mcu":
            if observed and candidates and observed not in candidates:
                return "Selected MCU conflicts with the reviewed board variants."
            # A known variant narrows the checks. Otherwise keep all candidate
            # constraints, without inventing a selected processor or new support.
            models = (observed,) if observed else candidates
            for model in models:
                result = _validate_pin_for_mcu(pin.lower(), model)
                if result is not True:
                    return result
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
                msg += f"    Aliases declarados sin uso detectado en la configuración: {suggested_str}\n"
                msg += "    Verificá el conector, el cableado y las reservas del firmware antes de elegir.\n"
        elif lang == "Português":
            msg = f"\n[!] BLTouch/CR-Touch selecionado, mas o mapeamento de pinos é desconhecido para a placa:\n    {board_name}\n"
            msg += "    Insira os pinos manualmente abaixo (digite '<' ou 'voltar' para retornar).\n"
            if unused:
                suggested_str = ", ".join([f"{u[0]}" for u in unused[:6]])
                msg += f"    Aliases declarados sem uso detectado na configuração: {suggested_str}\n"
                msg += "    Verifique o conector, a fiação e as reservas do firmware antes de escolher.\n"
        else:
            msg = f"\n[!] BLTouch/CR-Touch selected but pin mapping is unknown for board:\n    {board_name}\n"
            msg += "    Enter the pins manually below (you can type '<' or 'back' to go back).\n"
            if unused:
                suggested_str = ", ".join([f"{u[0]}" for u in unused[:6]])
                msg += f"    Declared aliases with no detected configuration use: {suggested_str}\n"
                msg += "    Check the connector, wiring and firmware reservations before choosing.\n"
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
                validate=make_pin_validator_with_collision_check(user_data),
                back_value=_BACK,
            )
            if sp == _BACK:
                return _BACK
            if sp is None or sp.strip().lower() in ("<", "back", "volver"):
                return _BACK
            user_data["bltouch_sensor_pin"] = sp.strip()
            idx += 1

        elif current_prompt == "control":
            cp = simple_input(
                t("wizard.bltouch_control_prompt") or "BLTouch control_pin (e.g. PB6 or PE5):",
                default=user_data.get("bltouch_control_pin") or "",
                validate=make_pin_validator_with_collision_check(user_data),
                back_value=_BACK,
            )
            if cp == _BACK:
                return _BACK
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
        manual_ans = simple_input(custom_msg, validate=questionary_thermistor_validator, back_value=_BACK)
        if manual_ans == _BACK:
            return _BACK
        if manual_ans is None:
            return "__retry__"
        user_data[therm_key] = manual_ans
    else:
        user_data[therm_key] = ans
    mark_user_override(user_data, therm_key)
    return ans
