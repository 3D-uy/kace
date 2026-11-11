import copy
import re
import os
import shutil
import textwrap
from collections.abc import Mapping
from core.menu import autocomplete_select, simple_input, yes_no, numbered_select, _wrapped_prompt_lines
from core.translations import t, get_lang
from core.exceptions import GenerationError, WizardExit
from core.terminal import RESET, SECTION, WARNING
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


def _probe_allocation_sections(user_data):
    """Project discovery examples onto the current mapped driver selection."""
    parsed = user_data.get("board_parsed")
    if parsed is None:
        parsed = _get_parsed(user_data)
    if not isinstance(parsed, dict):
        raise GenerationError("The selected board pin map is invalid.")
    binding = user_data.get("_board_parsed_for")
    if binding is not None and binding != user_data.get("board"):
        raise GenerationError("The selected board pin map belongs to another board.")
    from core.tmc_socket import SOURCE as TMC_SOCKET_SOURCE
    socket_source = parsed.get(TMC_SOCKET_SOURCE)
    if (isinstance(socket_source, dict) and user_data.get("board")
            and socket_source.get("profile") != user_data["board"]):
        raise GenerationError("The selected socket pin map belongs to another board.")
    # Legacy standalone validation calls have no selected driver. Retain their
    # conservative known consumers instead of silently releasing unknown wiring.
    if not user_data.get("driver_type"):
        if user_data.get("driver_mode"):
            raise GenerationError("Select a driver type before selecting its communication mode.")
        return parsed
    from core.profile_values import canonical_tmc_model, resolve_tmc_sections
    try:
        model = canonical_tmc_model(user_data["driver_type"])
        if model not in ("tmc2208", "tmc2209", "tmc2130", "tmc5160", "none (standard)", "a4988", "drv8825"):
            raise GenerationError("The selected driver type is invalid.")
        selected = resolve_tmc_sections(parsed, user_data)
        if model.startswith("tmc") and user_data.get("driver_mode") != "Standalone":
            count = int(user_data.get("z_motors") or 1)
            if not 1 <= count <= 4:
                raise GenerationError("The selected Z motor count is invalid.")
            targets = ["stepper_x", "stepper_y", "stepper_z", "extruder"]
            targets += [f"stepper_z{i}" for i in range(1, count)]
            # Generation permits a partial native TMC set (for example, an
            # X/Y SPI chain alongside ordinary Z/extruder drivers). Keep that
            # contract; a wholly unknown selected circuit still fails closed.
            if not selected and any(target in parsed for target in targets):
                raise GenerationError("Selected TMC pin map is incomplete.")
    except (TypeError, ValueError) as exc:
        raise GenerationError("The selected driver pin map is invalid.") from exc
    sections = {name: options for name, options in parsed.items()
                if not str(name).startswith("tmc")}
    sections.update(selected)
    return sections


def _get_probe_input_candidates(user_data):
    """Offer declared or explicitly reviewed connectors, with allocation checks."""
    try:
        sections = _probe_allocation_sections(user_data)
        aliases = PinAliases({name: options for name, options in sections.items()
                              if isinstance(options, dict)})
    except (GenerationError, PinAliasError):
        return []
    check = make_pin_validator_with_collision_check(user_data, for_custom_probe=True)
    inputs = (("probe", "pin", "wizard.custom_probe_existing_input", "probe"),
              ("bltouch", "sensor_pin", "wizard.custom_probe_dedicated_pin", "bltouch"),
              ("stepper_z", "endstop_pin", "wizard.custom_probe_z_endstop_input", "z_endstop"))
    candidates, seen = [], set()
    for section, field, label, source in inputs:
        options = sections.get(section, {})
        pin = options.get(field) if isinstance(options, dict) else None
        if (not isinstance(pin, str) or not pin.strip() or "TODO" in pin.upper()
                or "virtual_endstop" in pin.lower() or check(pin) is not True):
            continue
        try:
            chip, physical = aliases.resolve(pin)
        except PinAliasError:
            continue
        if (chip, physical) in seen:
            continue
        base_pin = physical if chip == "mcu" else f"{chip}:{physical}"
        _, pullup, inverted = _split_probe_pin_modifiers(pin)
        if source == "z_endstop":
            pullup = inverted = False
        candidates.append({"name": t(label), "pin": base_pin, "pullup": pullup,
                           "inverted": inverted, "source": source})
        seen.add((chip, physical))
    # Klipper's example may omit a physical connector. Supplement it only with
    # separately attributed manufacturer evidence for the exact board and MCU;
    # never turn MCU-family GPIO availability into a connector recommendation.
    from core.loader import load_boards_yaml
    from core.board_identity import canonical_mcu
    from core.bus_pins import hardware_bus_requests
    metadata = load_boards_yaml().get("probe_connector_mappings", {}).get(user_data.get("board"), {})
    if canonical_mcu(user_data.get("mcu_type")) not in metadata.get("mcu_models", []):
        return candidates
    try:
        buses = hardware_bus_requests({name: options for name, options in sections.items()
                                      if isinstance(options, dict) and not name.startswith("_")})
    except PinAliasError:
        return candidates
    for connector in metadata.get("connectors", []):
        pin = connector["pin"]
        if any(tuple(bus) in buses.get("mcu", []) for bus in connector["conflicts_with_buses"]):
            candidates = [item for item in candidates if aliases.resolve(item["pin"]) != ("mcu", pin)]
            continue
        if check(pin) is not True:
            continue
        try:
            identity = aliases.resolve(pin)
        except PinAliasError:
            continue
        # A same-spelled user alias cannot redirect a physical connector map.
        if identity != ("mcu", pin) or identity in seen:
            continue
        candidate = {"name": t("wizard.probe_signal.manufacturer_connector").format(connector=connector["name"]),
                     "pin": pin, "pullup": False, "inverted": False,
                     "source": "manufacturer", "source_url": connector["manufacturer_source"]}
        index = next((i for i, item in enumerate(candidates) if item["source"] == "z_endstop"), len(candidates))
        candidates.insert(index, candidate)
        seen.add(identity)
    return candidates



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
    if ans != default_kind:
        user_data.pop("custom_probe_polarity_unverified", None)
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
    if key == "custom_probe_z_offset" and os.environ.get("KACE_AUTO") != "1":
        return _step_probe_z_decision(user_data)
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


def _step_probe_z_decision(user_data):
    """Separate a supplied measurement from a deliberate deferred calibration."""
    for line in _wrapped_prompt_lines(t("wizard.probe_z.definition")):
        print("  " + line)
    while True:
        answer = numbered_select(t("wizard.probe_z.decision"), choices=[
            {"name": t("wizard.probe_z.known"), "value": "known"},
            {"name": t("wizard.probe_z.later"), "value": "later"},
            _back_choice(), _quit_choice(),
        ], require_explicit=True)
        if answer is None or answer == _QUIT:
            raise WizardExit()
        if answer == _BACK:
            return _BACK
        if answer == "later":
            # Resolve the provisional offset's travel here, while the user is
            # making this decision. Future sampling questions still own their
            # values, so the temporary probe block must never be published.
            staged = copy.deepcopy(user_data)
            staged["custom_probe_z_offset"] = ""
            existing_probe = staged.get("custom_probe")
            if isinstance(existing_probe, CustomProbeConfig) and existing_probe.z_offset is not None:
                staged["custom_probe"] = existing_probe.with_z_offset("0")
                staged["custom_probe_settings"] = {"z_offset": None}
            elif _step_custom_probe(staged) != "done":
                return _BACK
            from core.wizard.steps.probe_homing import review_probe_homing_geometry
            try:
                accepted = review_probe_homing_geometry(staged, back_label=t("wizard.probe_z.back_offset"))
            except GenerationError:
                for line in _wrapped_prompt_lines(t("wizard.probe_z.range_unresolved")):
                    print("  " + line)
                return _BACK
            if not accepted:
                continue
            old_minimum = (user_data.get("z_position_min"),
                           (user_data.get("_value_provenance") or {}).get("z_position_min"))
            new_minimum = (staged.get("z_position_min"),
                           (staged.get("_value_provenance") or {}).get("z_position_min"))
            if new_minimum != old_minimum:
                user_data["z_position_min"] = staged["z_position_min"]
                mark_user_override(user_data, "z_position_min")
            user_data["custom_probe_z_offset"] = ""
            for line in _wrapped_prompt_lines(t("wizard.probe_z.calibration_later")):
                print("  " + line)
            return "done"
        if answer == "known":
            value = simple_input(t("wizard.probe_z.known_input"),
                                 default=user_data.get("custom_probe_z_offset") or None,
                                 validate=_guided_probe_validator("number"), back_value=_BACK)
            if value is None or value == _BACK:
                continue
            user_data["custom_probe_z_offset"] = str(value).strip()
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
    """Prioritize declared inputs; keep connector aliases in an advanced submenu."""
    while True:
        candidates = _get_probe_input_candidates(user_data)
        advanced = _get_unused_pins(user_data, for_custom_probe=True)
        try:
            aliases = PinAliases({name: options for name, options in _probe_allocation_sections(user_data).items()
                                  if isinstance(options, dict)})
            primary_ids = {aliases.resolve(candidate["pin"]) for candidate in candidates}
            advanced = [item for item in advanced if aliases.resolve(item[1]) not in primary_ids]
        except (GenerationError, PinAliasError):
            candidates, advanced = [], []
        selected_candidate = None
        selected_advanced = None
        answer = "__manual__"
        if candidates or advanced:
            choices = [{"name": f"{item['name']} — {item['pin']}", "value": item["pin"]}
                       for item in candidates]
            if advanced:
                choices.append({"name": t("wizard.custom_probe_advanced_pins"), "value": "__advanced__"})
            choices.extend([
                {"name": t("wizard.custom_probe_pin_manual"), "value": "__manual__"},
                _back_choice(), _quit_choice(),
            ])
            hints = [t("wizard.custom_probe_connector_hint")]
            if any(candidate["source"] == "manufacturer" for candidate in candidates):
                hints.append(t("wizard.probe_signal.manufacturer_source"))
            if candidates and all(item["source"] == "z_endstop" for item in candidates):
                hints.append(t("wizard.probe_signal.only_z_input"))
            for hint in hints:
                print("\n".join(_wrapped_prompt_lines(hint)))
            answer = autocomplete_select(t("wizard.custom_probe_pin"), choices=choices, default=0)
            if answer == _QUIT or answer is None:
                raise WizardExit()
            if answer == _BACK:
                return _BACK
            if answer == "__advanced__":
                advanced_choices = [{"name": f"{friendly} ({pin})" if friendly != pin else pin,
                                     "value": pin} for friendly, pin in advanced]
                advanced_choices += [_back_choice(), _quit_choice()]
                answer = autocomplete_select(t("wizard.custom_probe_advanced_prompt"),
                                             choices=advanced_choices, default=0)
                if answer == _QUIT or answer is None:
                    raise WizardExit()
                if answer == _BACK:
                    continue
                selected_advanced = next((item for item in advanced if item[1] == answer), None)
            else:
                selected_candidate = next((item for item in candidates if item["pin"] == answer), None)
        if answer == "__manual__":
            answer = simple_input(
                t("wizard.custom_probe_pin_manual_prompt"),
                default=user_data.get("custom_probe_pin", ""),
                validate=make_pin_validator_with_collision_check(user_data, for_custom_probe=True),
                back_value=_BACK,
            )
            if answer is None or str(answer).strip().lower() in ("<", "back", "volver") or answer == _BACK:
                return _BACK
        value = str(answer).strip()
        # Re-read the mapped consumers and firmware evidence after interaction.
        validation = make_pin_validator_with_collision_check(user_data, for_custom_probe=True)(value)
        if validation is not True:
            print(f"\n[!] {validation}\n")
            return "__retry__"
        if selected_candidate is not None and selected_candidate not in _get_probe_input_candidates(user_data):
            print(f"\n[!] {t('wizard.custom_probe_input_changed')}\n")
            return "__retry__"
        if selected_advanced is not None and selected_advanced not in _get_unused_pins(user_data, for_custom_probe=True):
            print(f"\n[!] {t('wizard.custom_probe_input_changed')}\n")
            return "__retry__"
        base_pin, pullup, inverted = _split_probe_pin_modifiers(value)
        if selected_candidate is not None:
            pullup, inverted = selected_candidate["pullup"], selected_candidate["inverted"]
        try:
            current_aliases = PinAliases({name: options for name, options in _probe_allocation_sections(user_data).items()
                                          if isinstance(options, dict)})
            chip, physical = current_aliases.resolve(base_pin)
            base_pin = physical if chip == "mcu" else f"{chip}:{physical}"
            previous = user_data.get("custom_probe_pin")
            same_input = bool(previous) and current_aliases.resolve(previous) == (chip, physical)
        except (GenerationError, PinAliasError) as exc:
            print(f"\n[!] {exc}\n")
            return "__retry__"
        # A changed GPIO must not inherit signal defaults from another sensor.
        user_data["custom_probe_pin"] = base_pin
        if same_input and not value.startswith(("^", "!")):
            user_data.setdefault("custom_probe_pullup", pullup)
            user_data.setdefault("custom_probe_inverted", inverted)
        else:
            user_data["custom_probe_pullup"] = pullup
            user_data["custom_probe_inverted"] = inverted
            user_data.pop("custom_probe_polarity_unverified", None)
        return "done"


def _split_probe_pin_modifiers(pin: str) -> tuple[str, bool, bool]:
    """Separate Klipper input modifiers so the wizard asks about each explicitly."""
    text = str(pin).strip()
    pullup = "^" in text[:3]
    inverted = "!" in text[:3]
    return text.lstrip("^!~"), pullup, inverted


def _get_dedicated_probe_pin(user_data) -> tuple[str, bool, bool] | None:
    """Offer the declared sensor only after checking the custom probe transition."""
    try:
        probe_section = _probe_allocation_sections(user_data).get("bltouch", {})
    except GenerationError:
        return None
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
    if option == "inverted":
        print()
        for line in _wrapped_prompt_lines(t("wizard.probe_signal.guide")):
            print("  " + line)
        answer = numbered_select(t("wizard.probe_signal.prompt"), choices=[
            {"name": t("wizard.probe_signal.normal"), "value": "normal"},
            {"name": t("wizard.probe_signal.inverted"), "value": "inverted"},
            {"name": t("wizard.probe_signal.unknown"), "value": "unknown"},
            _back_choice(), _quit_choice(),
        ], default=(2 if user_data.get("custom_probe_polarity_unverified") else
                    1 if user_data.get("custom_probe_inverted") else 0), require_explicit=True)
        if answer == _QUIT or answer is None:
            raise WizardExit()
        if answer == _BACK:
            return _BACK
        user_data["custom_probe_inverted"] = answer == "inverted"
        user_data["custom_probe_polarity_unverified"] = answer == "unknown"
        if answer == "unknown":
            print(t("wizard.probe_signal.pending"))
        return "done"
    answer = numbered_select(t("wizard.custom_probe_pullup"), choices=[
        {"name": t("wizard.probe_signal.pullup_on"), "value": True},
        {"name": t("wizard.probe_signal.pullup_off"), "value": False},
        _back_choice(), _quit_choice(),
    ], default=0 if user_data.get("custom_probe_pullup") else 1, require_explicit=True)
    if answer is None or answer == _QUIT:
        raise WizardExit()
    if answer == _BACK:
        return _BACK
    user_data["custom_probe_pullup"] = answer
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
        return _BACK
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
        user_data["custom_probe"] = settings.to_config(
            language=get_lang(),
            polarity_unverified=bool(user_data.get("custom_probe_polarity_unverified")),
        )
    except (ValueError, CustomProbeValidationError) as exc:
        print(f"\n[!] {t('wizard.custom_probe_invalid')}: {exc}\n")
        return _BACK

    user_data["probe_x_offset"] = f"{settings.x_offset:g}"
    user_data["probe_y_offset"] = f"{settings.y_offset:g}"
    return "done"


def _stage_known_custom_probe_offset(user_data, value):
    """Prepare an explicit offset edit without altering the caller's draft."""
    staged = copy.deepcopy(user_data)
    custom_probe = staged.get("custom_probe")
    if not isinstance(custom_probe, CustomProbeConfig):
        raise CustomProbeValidationError("Custom probe data is missing.")
    # Validate through the raw model even when guided settings are available.
    edited = custom_probe.with_z_offset(value)
    staged["custom_probe_z_offset"] = str(value).strip()
    if isinstance(staged.get("custom_probe_settings"), GuidedCustomProbeSettings):
        if _step_custom_probe(staged) != "done":
            raise CustomProbeValidationError("The guided probe offset could not be rebuilt.")
    else:
        staged["custom_probe"] = edited
        # Checkpoints preserve guided settings as a plain mapping while the raw
        # block stays authoritative. Keep the saved draft consistent as well.
        if isinstance(staged.get("custom_probe_settings"), dict):
            staged["custom_probe_settings"]["z_offset"] = edited.z_offset
    return staged


def _step_custom_probe_review(user_data):
    """Review or edit guided values without losing the other probe answers."""
    while True:
        custom_probe = user_data.get("custom_probe")
        if not isinstance(custom_probe, CustomProbeConfig):
            return _BACK
        settings = user_data.get("custom_probe_settings")
        # A checkpoint keeps guided settings as a mapping. Reconstruct only for
        # presentation; the validated raw block remains authoritative.
        if isinstance(settings, Mapping):
            try:
                settings = GuidedCustomProbeSettings(**dict(settings))
            except (TypeError, ValueError):
                settings = None
        rows = [(t("wizard.review_probe.title", section=custom_probe.primary_section), None)]
        columns = shutil.get_terminal_size(fallback=(80, 24)).columns
        if isinstance(settings, GuidedCustomProbeSettings):
            values = [
                ("pin", settings.pin, ""),
                ("x_offset", str(custom_probe.x_offset).removesuffix(".0"), "mm"),
                ("y_offset", str(custom_probe.y_offset).removesuffix(".0"), "mm"),
                ("z_offset", str(custom_probe.z_offset).removesuffix(".0"), "mm"),
                ("samples", settings.samples, ""),
                ("samples_result", settings.samples_result, ""),
                ("samples_tolerance", f"{settings.samples_tolerance:g}", "mm"),
                ("samples_tolerance_retries", settings.samples_tolerance_retries, ""),
                ("speed", f"{settings.speed:g}", "mm/s"),
                ("sample_retract_dist", f"{settings.sample_retract_dist:g}", "mm"),
            ]
            value_width = max(len(f"{value} {unit}".rstrip()) for _, value, unit in values)
            for name, value, unit in values:
                if name in ("pin", "x_offset", "samples"):
                    group = {"pin": "connection", "x_offset": "offsets", "samples": "measurements"}[name]
                    rows.append((t("wizard.probe_review.group_" + group), None))
                right = f"{value} {unit}".rstrip()
                if columns >= 80:
                    right = f"{right:<{value_width}}"
                explanation = t("wizard.probe_parameter." + name)
                rows.append((name + ":", right + (" — " + explanation if columns >= 80 else "")))
                if columns < 80:
                    rows.append((None, explanation))
            state = t("wizard.review_probe.provisional" if settings.z_offset is None and custom_probe.z_offset == 0
                      else "wizard.review_probe.supplied")
            label, _, value = state.partition(": ")
            rows.append((label + ":", value))
        else:
            rows.extend([
                (None, t("wizard.review_probe.offsets", x=custom_probe.x_offset,
                         y=custom_probe.y_offset, z=custom_probe.z_offset)),
                (None, t("wizard.review_probe.imported")),
            ])
        if user_data.get("custom_probe_polarity_unverified"):
            rows.append((None, t("wizard.review_probe.signal_pending")))
        name_width = max((len(label) for label, value in rows if label and value is not None), default=0)
        print()
        parameter_names = {name for name, _, _ in values} if isinstance(settings, GuidedCustomProbeSettings) else set()
        explanation_texts = {t("wizard.probe_parameter." + name) for name in parameter_names}
        description_color = "\033[97m"
        for label, value in rows:
            if value is None or label is None:
                role, text = (SECTION, label) if value is None else (description_color if value in explanation_texts else WARNING, value)
                for line in _wrapped_prompt_lines(text):
                    print(f"  {role}{line}{RESET}")
                continue
            prefix = f"{label:<{name_width}}  "
            if len(prefix) + len(value.split()[0]) > max(20, columns - 2):
                # Keep long values and calibration words intact in narrow terminals.
                for line in _wrapped_prompt_lines(label):
                    print(f"  {SECTION}{line}{RESET}")
                for line in _wrapped_prompt_lines(value):
                    print(f"  {WARNING}{line}{RESET}")
                continue
            rendered = textwrap.fill(value, width=max(20, columns - 2), initial_indent=prefix,
                                     subsequent_indent=" " * len(prefix) if columns >= 80 else "  ",
                                     break_long_words=False, break_on_hyphens=False)
            in_explanation = False
            for index, line in enumerate(rendered.splitlines()):
                content = line[len(prefix):] if index == 0 else line
                if label.removesuffix(":") in parameter_names:
                    if " — " in content:
                        before, after = content.split(" — ", 1)
                        content = f"{WARNING}{before}{RESET}{description_color} — {after}{RESET}"
                        in_explanation = True
                    else:
                        content = f"{description_color if in_explanation else WARNING}{content}{RESET}"
                else:
                    content = f"{WARNING}{content}{RESET}"
                if index == 0:
                    print(f"  {SECTION}{line[:len(prefix)]}{RESET}{content}")
                else:
                    print(f"  {content}")
        if os.environ.get("KACE_AUTO") == "1":
            return "done"
        choices = [{"name": t("choice.continue"), "value": "continue"}]
        if isinstance(settings, GuidedCustomProbeSettings):
            choices.extend([
                {"name": t("wizard.probe_review.edit_offset"), "value": "offset"},
                {"name": t("wizard.probe_review.edit_signal"), "value": "signal"},
            ])
        choices.extend([
            {"name": t("wizard.review_probe.details"), "value": "details"},
        ])
        if not isinstance(settings, GuidedCustomProbeSettings) and custom_probe.z_offset is not None:
            choices.append({"name": t("wizard.probe_z.edit_known"), "value": "known_offset"})
        choices.extend([_back_choice(), _quit_choice()])
        action = numbered_select(t("wizard.profile_review_prompt"), choices=choices,
                                 require_explicit=True)
        if action is None or action == _QUIT:
            raise WizardExit()
        if action == _BACK:
            return _BACK
        if action == "continue":
            return "done"
        if action == "details":
            print("\n" + custom_probe.config_text + "\n")
            numbered_select(t("wizard.review_probe.detail_return"), choices=[
                {"name": t("wizard.review_probe.back_summary"), "value": "summary"},
            ], require_explicit=True)
            continue
        staged = copy.deepcopy(user_data)
        if action == "offset":
            result = _step_guided_custom_probe_value(staged, "custom_probe_z_offset")
        elif action == "known_offset":
            value = simple_input(t("wizard.probe_z.known_input"), validate=_custom_offset_validator,
                                 back_value=_BACK)
            if value is None or value == _BACK:
                continue
            staged = _stage_known_custom_probe_offset(user_data, value)
            user_data.clear()
            user_data.update(staged)
            continue
        elif action == "signal":
            result = _step_custom_probe_signal_option(staged, "inverted")
        else:
            continue
        if result == _BACK:
            continue
        if isinstance(user_data.get("custom_probe_settings"), Mapping) and action == "offset":
            value = staged["custom_probe_z_offset"]
            staged = _stage_known_custom_probe_offset(staged, value or "0")
            if not value:
                staged["custom_probe_z_offset"] = ""
                staged["custom_probe_settings"]["z_offset"] = None
            user_data.clear()
            user_data.update(staged)
            continue
        if _step_custom_probe(staged) == "done":
            user_data.clear()
            user_data.update(staged)


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


def _get_unused_pins(user_data, *, for_custom_probe=False) -> list:
    """List board-declared aliases without a known configuration consumer.

    Never synthesize pads from an MCU family. Check known firmware reservations
    when evidence is available; an alias alone cannot certify electrical suitability.
    Manual wiring selection remains available when the board declares no aliases.
    """
    try:
        ignored = (("bltouch", "sensor_pin"), ("probe", "pin"),
                   ("stepper_z", "endstop_pin")) if for_custom_probe else ()
        resolver, used_pins = _pin_allocations(_probe_allocation_sections(user_data), ignored_fields=ignored)
    except (GenerationError, PinAliasError):
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
    check = make_pin_validator_with_collision_check(user_data, for_custom_probe=for_custom_probe)
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
    alias_error = None
    from core.firmware_workflow import generation_pin_reservations, validate_checkpoint, FirmwareWorkflowError
    from firmware.identity import FirmwareIdentityError
    try:
        parsed_board = _probe_allocation_sections(user_data)
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
            # Other peripheral examples have not necessarily been selected.
            # Their authoritative bus check uses rendered/expanded config later.
            bus_sections = {name: options for name, options in parsed_board.items()
                            if isinstance(options, dict)
                            and (name == "board_pins" or name.startswith("board_pins "))}
            if user_data.get("driver_mode") == "SPI":
                bus_sections.update({name: options for name, options in parsed_board.items()
                                     if str(name).startswith("tmc") and isinstance(options, dict)})
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
            return t("wizard.custom_probe_pull_down_unsupported")
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
        for paragraph in msg.splitlines():
            indent = "    " if paragraph.startswith("    ") else ""
            for line in _wrapped_prompt_lines(paragraph.strip(), indent=indent):
                print(indent + line)

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
