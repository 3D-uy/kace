import copy
import os
import shutil
import textwrap
from wcwidth import wcwidth, wcswidth
from core.menu import simple_input, yes_no, numbered_select, autocomplete_select, Separator, Choice
from core.scraper import fetch_raw_config, parse_config, extract_profile_defaults
from core.translations import t
from core.terminal import DIM, ERROR, INFO, RESET, SECTION, WARNING
from core.exceptions import GenerationError, WizardExit
from core.validators import questionary_numeric_validator, questionary_pos_numeric_validator, questionary_thermistor_validator
from data.profiles import THERMISTOR_PRESETS
from core.wizard.runner import _BACK, _QUIT
from core.wizard.ui import _back_choice, _quit_choice
from core.capabilities import finite_number, normalize_and_validate_configuration, supported_kinematics
from core.profile_values import (
    ValueProvenance,
    infer_homing_positive_dir,
    mark_profile_values,
    mark_user_override,
    safe_defaults,
    resolve_generation_values,
    require_resolved_safety_values,
    Z_MECHANICAL_OPTIONS,
    z_mechanics_context,
    z_mechanics_confirmation_matches,
    _z_mechanical_number,
)

_PRINTER_PROFILES_DB = None
_INTERACTIVE_MODE = True


def _motor_board(user):
    parsed = user.get("board_parsed") or {}
    if user.get("_board_parsed_for") not in (None, user.get("board")):
        raise GenerationError("Motor pin source belongs to another board.")
    return parsed


def _motor_label(user, section):
    name = section.removeprefix("stepper_").upper()
    if section == "extruder":
        return t("motor.extruder")
    if user.get("kinematics") == "corexy" and section in ("stepper_x", "stepper_y"):
        name = "A / stepper_x" if section == "stepper_x" else "B / stepper_y"
    return t("motor.label", motor=name)


def _motor_direction_value(parsed, user, section, *, compact=False):
    from core.motor_direction import direction_mode, effective_direction_pin
    try:
        return t("motor.compact_value" if compact else "motor.value",
                 mode=t("motor." + ("compact_" if compact else "") + direction_mode(parsed, user, section)),
                 pin=effective_direction_pin(parsed, user, section))
    except GenerationError:
        return t("motor.review_source")


def _choose_motor_direction(user, section):
    from core.motor_direction import direction_mode, source_direction_pin, set_motor_direction
    from core.menu import _wrapped_prompt_lines
    parsed = _motor_board(user)
    for line in _wrapped_prompt_lines(t("motor.guide")):
        print("  " + line)
    print(f"\n  {SECTION}{_motor_label(user, section)}{RESET}")
    print(f"  {t('motor.source', pin=source_direction_pin(parsed, section))}\n")
    try:
        current = direction_mode(parsed, user, section)
    except GenerationError:
        current = "keep"
    answer = numbered_select(t("motor.choose"), choices=[
        {"name": t("motor.keep"), "value": "keep"},
        {"name": t("motor.invert"), "value": "invert"},
        _back_choice(), _quit_choice(),
    ], default=1 if current == "invert" else 0)
    if answer in (None, _QUIT):
        raise WizardExit()
    if answer != _BACK:
        set_motor_direction(user, parsed, section, answer)
    return answer


def _step_motor_directions(user_data):
    """The profile branch already exposes these options in its staged editor."""
    from core.motor_direction import available_motor_sections, apply_motor_directions
    if user_data.get("profile_loaded") or os.environ.get("KACE_AUTO") == "1":
        apply_motor_directions(copy.deepcopy(_motor_board(user_data)), user_data)
        return "done"
    staged = copy.deepcopy(user_data)
    parsed = _motor_board(staged)
    motors = available_motor_sections(parsed, staged)
    if not motors:
        apply_motor_directions(copy.deepcopy(parsed), staged)
        return "done"
    while True:
        choices = [{"name": f"{_motor_label(staged, motor)}: {_motor_direction_value(parsed, staged, motor)}",
                    "value": motor} for motor in motors]
        choices.extend([
            {"name": t("choice.continue"), "value": "done"},
            _back_choice(), _quit_choice(),
        ])
        answer = numbered_select(t("motor.review"), choices=choices, default=len(motors))
        if answer in (None, _QUIT):
            raise WizardExit()
        if answer == _BACK:
            return _BACK
        if answer == "done":
            try:
                apply_motor_directions(copy.deepcopy(parsed), staged)
            except GenerationError as exc:
                print(f"{ERROR}{exc}{RESET}")
                continue
            if "motor_directions" in staged:
                user_data["motor_directions"] = staged["motor_directions"]
            return "done"
        elif answer in motors:
            _choose_motor_direction(staged, answer)


def _homing_direction_mode(data, axis, defaults=None, parsed=None):
    """Retain explicit source choices and distinguish them from automatic inference."""
    key = f"homing_positive_dir_{axis}"
    if (data.get("_value_provenance") or {}).get(key) == ValueProvenance.INFERRED.value:
        return "auto"
    value = data.get(key)
    if value in (None, ""):
        value = (defaults or {}).get(key)
    if value in (None, ""):
        value = (parsed or {}).get(f"stepper_{axis}", {}).get("homing_positive_dir")
    if value in (None, ""):
        return "auto"
    text = str(value).strip().lower()
    if text not in ("true", "false"):
        raise GenerationError(f"{key} must be True or False.")
    return "True" if text == "true" else "False"


def _homing_direction_inferred(data, axis):
    return infer_homing_positive_dir(
        data.get(f"{axis}_position_endstop"),
        data.get(f"{axis}_position_min"),
        data.get(f"{axis}_position_max"),
    )


def _homing_direction_label(mode, inferred, axis):
    if mode == "auto":
        direction = (t("wizard.homing.positive", axis=axis.upper()) if inferred == "True"
                     else t("wizard.homing.negative", axis=axis.upper()) if inferred == "False"
                     else t("wizard.homing.unresolved"))
        return t("wizard.homing.automatic_direction", direction=direction)
    return t("wizard.homing.maximum" if mode == "True" else "wizard.homing.minimum", axis=axis.upper())


def _editor_homing_label(mode, inferred, axis):
    direction = inferred if mode == "auto" else mode
    if direction not in ("True", "False"):
        return t("profile.editor.homing_unresolved")
    text = t("profile.editor.homing_max" if direction == "True" else "profile.editor.homing_min",
             axis=axis.upper())
    return t("profile.editor.homing_auto", direction=text) if mode == "auto" else text


def _editor_cell_text(text, width):
    """Abbreviate display text only; field editing retains the complete value."""
    from core.menu import _plain_label
    text = " ".join(_plain_label(str(text)).split())
    if wcswidth(text) <= width:
        return text
    result, cells = [], 0
    for char in text:
        size = max(0, wcwidth(char))
        if cells + size > max(0, width - 1):
            break
        result.append(char)
        cells += size
    return "".join(result) + "…"


def _select_homing_direction(data, axis, defaults=None, parsed=None):
    mode = _homing_direction_mode(data, axis, defaults, parsed)
    inferred = _homing_direction_inferred(data, axis)
    if axis == "z" and mode == "auto":
        print(f"{DIM}{t('wizard.homing.z_probe_hint')}{RESET}")
    while True:
        answer = numbered_select(
            t("wizard.homing.choose", axis=axis.upper()),
            choices=[
                {"name": _homing_direction_label("auto", inferred, axis), "value": "auto"},
                {"name": t("wizard.homing.minimum", axis=axis.upper()), "value": "False"},
                {"name": t("wizard.homing.maximum", axis=axis.upper()), "value": "True"},
                _back_choice(), _quit_choice(),
            ],
            default=("auto", "False", "True").index(mode),
            require_explicit=inferred is None and mode == "auto",
        )
        if answer in (_QUIT, None):
            raise WizardExit()
        if answer == "auto" and inferred is None:
            print(f"{WARNING}{t('wizard.homing.ambiguous', axis=axis.upper())}{RESET}")
            continue
        if answer in ("auto", "False", "True", _BACK):
            return answer


def _apply_homing_direction(data, axis, mode):
    key = f"homing_positive_dir_{axis}"
    if mode == "auto":
        data.pop(key, None)
        inferred = _homing_direction_inferred(data, axis)
        if inferred is not None:
            data[key] = inferred
        provenance = dict(data.get("_value_provenance") or {})
        provenance[key] = ValueProvenance.INFERRED.value
        data["_value_provenance"] = provenance
    else:
        data[key] = mode
        mark_user_override(data, key)


def _z_mechanics_input(option, value):
    text = str(value).strip()
    if option == "gear_ratio" and not text:
        text = "1:1"
    if option == "full_steps_per_rotation":
        steps = int(text)
        if steps < 1 or steps % 4:
            raise ValueError("full steps must be a positive multiple of four")
        return str(steps)
    _z_mechanical_number(f"{option}_z", text)
    if option in ("rotation_distance", "microsteps"):
        finite_number(option, text, minimum=0, minimum_inclusive=False,
                      maximum=256 if option == "microsteps" else 2000,
                      integer=option == "microsteps")
    return text


def _clear_copied_z_mechanics(user_data):
    receipt = user_data.pop("_z_mechanics_confirmation", {})
    owned = receipt.get("owned_values", {}) if isinstance(receipt, dict) else {}
    if not isinstance(owned, dict):
        owned = {}
    provenance = dict(user_data.get("_value_provenance") or {})
    for key, value in owned.items():
        if key not in {f"{option}_z{i}" for i in (1, 2, 3) for option in Z_MECHANICAL_OPTIONS}:
            continue
        if user_data.get(key) == value and provenance.get(key) == "USER_OVERRIDE":
            user_data.pop(key, None)
            provenance.pop(key, None)
    user_data["_value_provenance"] = provenance


def _print_z_mechanics_review(staged, resolved):
    """Compare motors without repeating input examples; wrap for narrow terminals."""
    targets = ["z" + (str(i) if i else "") for i in range(int(staged["z_motors"]))]
    assignments = staged.get("z_socket_assignments") or {}
    sockets = {"stepper_z": "Z", "extruder": "E0", "extruder1": "E1",
               "extruder2": "E2", "extruder3": "E3"}
    rows = [(t("wizard.z_mechanics.socket"), [
        sockets.get(assignments.get("stepper_" + target, "stepper_" + target),
                    assignments.get("stepper_" + target, "stepper_" + target).removeprefix("stepper_").upper())
        for target in targets])]
    rows += [(t("wizard.z_mechanics.short_" + option), [
        resolved[f"{option}_{target}"] or "1:1" for target in targets])
        for option in Z_MECHANICAL_OPTIONS]
    labels = [t("wizard.z_mechanics.parameter")] + [label for label, _ in rows]
    widths = [max(map(len, labels))] + [
        max(len(target), *(len(values[i]) for _, values in rows)) for i, target in enumerate(targets)]
    width = max(20, shutil.get_terminal_size((100, 24)).columns - 4)
    print(f"\n{SECTION}{t('wizard.z_mechanics.review')}{RESET}")
    if sum(widths) + 3 * len(targets) <= width:
        def row(values):
            print("  " + "   ".join(value.ljust(size) for value, size in zip(values, widths)))
        row([labels[0]] + [target.upper() for target in targets])
        for label, values in rows:
            row([label] + values)
    else:
        for label, values in rows:
            print("  " + label)
            for line in textwrap.wrap(" | ".join(f"{target.upper()}: {value}" for target, value in zip(targets, values)), width=width):
                print("    " + line)
    print("\n" + textwrap.fill(t("wizard.z_mechanics.staged_hint"), width=width))


def _step_z_mechanics(user_data):
    """Stage every additional motor, then confirm the displayed values once."""
    staged = copy.deepcopy(user_data)
    board = staged.get("board_parsed") or {}
    count = int(staged.get("z_motors") or 1)
    if count <= 1:
        _clear_copied_z_mechanics(user_data)
        return "__skip__"
    if os.environ.get("KACE_AUTO") == "1":
        _, provenance = resolve_generation_values(board, staged)
        require_resolved_safety_values({key: value for key, value in provenance.items()
                                        if not key.startswith(("run_current_", "hold_current_", "stealthchop_threshold_"))})
        return "__skip__"
    draft, provenance = resolve_generation_values(board, staged, validate_motors=False)
    fresh = False
    try:
        fresh = z_mechanics_confirmation_matches(board, staged, draft)
    except (ValueError, TypeError):
        pass
    previous = staged.get("_z_mechanics_confirmation") or {}
    owned = dict(previous.get("owned_values", {})) if fresh else {}
    if not fresh and "_z_mechanics_confirmation" in staged:
        _clear_copied_z_mechanics(staged)
        draft, provenance = resolve_generation_values(board, staged, validate_motors=False)
        print(f"{WARNING}{t('wizard.z_mechanics.changed')}{RESET}")
    staged.pop("_z_mechanics_confirmation", None)
    try:
        primary = {option: _z_mechanics_input(option, draft[f"{option}_z"])
                   for option in Z_MECHANICAL_OPTIONS}
    except (ValueError, TypeError, KeyError, GenerationError) as exc:
        print(f"{ERROR}{t('wizard.z_mechanics.invalid_primary', detail=str(exc))}{RESET}")
        return _BACK
    entry_context = z_mechanics_context(board, staged, draft)
    selected_keys = [f"{option}_z{i}" for i in range(1, count) for option in Z_MECHANICAL_OPTIONS]
    entry_inputs = {key: (user_data.get(key), (user_data.get("_value_provenance") or {}).get(key))
                    for key in selected_keys}
    for index in range(1, count):
        target = f"z{index}"
        fields = {option: f"{option}_{target}" for option in Z_MECHANICAL_OPTIONS}
        current = {option: draft.get(key, "") for option, key in fields.items()}
        can_keep = all(provenance.get(fields[option]) in ("PROFILE", "USER_OVERRIDE")
                       for option in ("rotation_distance", "microsteps"))
        try:
            for option, value in current.items():
                _z_mechanics_input(option, value)
        except (ValueError, TypeError, GenerationError):
            can_keep = False
        print(f"\n{SECTION}{t('wizard.z_mechanics.title', motor=target.upper())}{RESET}")
        for option in Z_MECHANICAL_OPTIONS:
            print(f"  {t('wizard.z_mechanics.' + option)}: {current[option]}")
        choices = []
        if can_keep:
            choices.append({"name": t("wizard.z_mechanics.keep"), "value": "keep"})
        choices += [{"name": t("wizard.z_mechanics.individual"), "value": "individual"},
                    {"name": t("wizard.z_mechanics.same"), "value": "same"}, _back_choice(), _quit_choice()]
        mode = numbered_select(t("wizard.z_mechanics.choose"), choices=choices)
        if mode == _BACK:
            return _BACK
        if mode in (_QUIT, None):
            raise WizardExit()
        if mode == "keep" and can_keep:
            continue
        if mode not in ("same", "individual"):
            return "__retry__"
        for option, key in fields.items():
            value = primary[option]
            if mode == "individual":
                def validate(text, field=option):
                    try:
                        _z_mechanics_input(field, text)
                        return True
                    except (ValueError, TypeError, GenerationError):
                        return t("wizard.z_mechanics.invalid")
                value = simple_input(t("wizard.z_mechanics." + option),
                                     default=current[option] or ("1:1" if option == "gear_ratio" else ""),
                                     validate=validate, back_value=_BACK)
                if value == _BACK:
                    return _BACK
                if value is None:
                    raise WizardExit()
            try:
                staged[key] = _z_mechanics_input(option, value)
            except (ValueError, TypeError, GenerationError):
                print(f"{ERROR}{t('wizard.z_mechanics.invalid')}{RESET}")
                return "__retry__"
            mark_user_override(staged, key)
            owned[key] = staged[key]
    resolved, provenance = resolve_generation_values(board, staged)
    require_resolved_safety_values({key: value for key, value in provenance.items()
                                    if not key.startswith(("run_current_", "hold_current_", "stealthchop_threshold_"))})
    _print_z_mechanics_review(staged, resolved)
    action = numbered_select(t("wizard.z_mechanics.review_action"), choices=[
        {"name": t("wizard.z_mechanics.confirm_continue"), "value": "confirm"},
        {"name": t("wizard.z_mechanics.edit"), "value": "edit"},
        _back_choice(), _quit_choice(),
    ], default=1, require_explicit=True)
    if action == _BACK:
        return _BACK
    if action in (_QUIT, None):
        raise WizardExit()
    if action != "confirm":
        return "__retry__"
    try:
        live_board = user_data.get("board_parsed") or {}
        live, _ = resolve_generation_values(live_board, user_data, validate_motors=False)
        unchanged = z_mechanics_context(live_board, user_data, live) == entry_context
        unchanged = unchanged and entry_inputs == {
            key: (user_data.get(key), (user_data.get("_value_provenance") or {}).get(key))
            for key in selected_keys}
    except (ValueError, TypeError, GenerationError):
        unchanged = False
    if not unchanged:
        print(f"{WARNING}{t('wizard.z_mechanics.changed')}{RESET}")
        return "__retry__"
    staged["_z_mechanics_confirmation"] = {
        "schema": 1, "context": z_mechanics_context(board, staged, resolved),
        "values": {f"{option}_z{i}": resolved[f"{option}_z{i}"]
                   for i in range(1, count) for option in Z_MECHANICAL_OPTIONS},
        "owned_values": owned,
    }
    user_data.clear()
    user_data.update(staged)
    return "done"

def set_interactive_mode(interactive: bool) -> None:
    """Configure whether interactive operations (like clear screen, sleep) are performed."""
    global _INTERACTIVE_MODE
    _INTERACTIVE_MODE = interactive


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


def _printable_bounds_value(defaults: dict, user_data: dict) -> str:
    """Present saved bed coordinates without deriving them from rail travel."""
    values = dict(defaults)
    values.update(user_data or {})
    axes = []
    for axis in ("x", "y"):
        bounds = [values.get(f"printable_{axis}_{bound}") for bound in ("min", "max")]
        shown = [t("profile.bounds_undefined") if value in (None, "") else str(value)
                 for value in bounds]
        interval = shown[0] if all(value in (None, "") for value in bounds) else "..".join(shown)
        if all(value not in (None, "") for value in bounds):
            interval += " mm"
        axes.append(f"{axis.upper()} {interval}")
    return " / ".join(axes)


def print_detected_profile_summary(defaults: dict, parsed: dict, user_data: dict = None) -> None:
    """Print the complete profile and its explanations without clipping content."""
    is_custom = (user_data or defaults).get("printer_profile") == "Custom / Scratch Build"
    width = max(20, shutil.get_terminal_size(fallback=(80, 24)).columns - 2)
    header_key = "profile.custom_header" if is_custom else "profile.detected_header"
    print(f"\n{SECTION}{t(header_key)}{RESET}")

    def section(key):
        title = t(key)
        for line in textwrap.wrap(title, width=width - 2):
            print(f"  {SECTION}{line}{RESET}")
        print(f"  {SECTION}{'─' * min(len(title), width - 2)}{RESET}\n")

    def print_val(label, value, comment_key):
        text = f"  - {label:<24} {value}  # {t(comment_key)}"
        in_comment = False
        for line in textwrap.wrap(text, width=width, subsequent_indent="      ",
                                  break_long_words=False, break_on_hyphens=False):
            if "#" in line:
                content, comment = line.split("#", 1)
                print(f"{content}{DIM}#{comment}{RESET}")
                in_comment = True
            elif in_comment:
                print(f"{DIM}{line}{RESET}")
            else:
                print(line)

    kinematics = parsed.get("printer", {}).get("kinematics") or defaults.get("kinematics")
    has_axis = any(
        parsed.get(f"stepper_{axis}", {}).get(field) is not None
        or (is_custom and defaults.get(f"{axis}_{field}") is not None)
        for axis in ("x", "y", "z")
        for field in ("position_min", "position_max", "position_endstop")
    )
    if kinematics or has_axis:
        section("wizard.review_profile.motion")
        if kinematics:
            print_val(f"{t('profile.kinematics')}:", kinematics, "profile.comment_kinematics")
            print()
        for axis in ("x", "y", "z"):
            axis_data = parsed.get(f"stepper_{axis}", {})
            values = {}
            for field in ("position_min", "position_max", "position_endstop"):
                value = axis_data.get(field)
                if value is None and is_custom:
                    value = defaults.get(f"{axis}_{field}")
                if value is not None:
                    values[field] = value
            if not values:
                continue
            for field, value in values.items():
                print_val(f"{axis.upper()} {field}:", value, f"profile.comment_{field}_{axis}")
            homing_data = dict(defaults)
            homing_data.update(user_data or {})
            for field in ("position_min", "position_max", "position_endstop"):
                key = f"{axis}_{field}"
                if key not in homing_data and axis_data.get(field) is not None:
                    homing_data[key] = axis_data[field]
            mode = _homing_direction_mode(homing_data, axis, defaults, parsed)
            print_val(t("wizard.homing.axis_label", axis=axis.upper()),
                      _homing_direction_label(mode, _homing_direction_inferred(homing_data, axis), axis),
                      "wizard.homing.comment")
            if axis == "z" and mode == "auto":
                for line in textwrap.wrap(t("wizard.homing.z_probe_hint"), width=width - 2,
                                          break_long_words=False, break_on_hyphens=False):
                    print(f"  {DIM}{line}{RESET}")
            print()

    from core.motor_direction import available_motor_sections
    motor_user = user_data or {}
    motor_source = _motor_board(motor_user)
    motors = available_motor_sections(motor_source, motor_user)
    if motors:
        section("motor.review")
        for motor in motors:
            print_val(_motor_label(motor_user, motor), _motor_direction_value(motor_source, motor_user, motor), "motor.comment")
        print()

    sizes = [(user_data or {}).get(f"{axis}_size") or defaults.get(f"{axis}_size")
             or parsed.get(f"stepper_{axis}", {}).get("position_max") for axis in ("x", "y", "z")]
    section("wizard.review_profile.volume")
    if all(sizes):
        print_val(f"{t('profile.build_volume')}:", " x ".join(str(value) for value in sizes),
                  "profile.comment_build_volume")
    print_val(f"{t('profile.printable_bounds')}:", _printable_bounds_value(defaults, user_data),
              "profile.comment_printable_bounds")
    print()
    from core.nozzle_bed_visualizer import print_nozzle_bed_preview
    geometry = dict(defaults)
    for axis in ('x', 'y'):
        for field in ('position_min', 'position_max', 'position_endstop'):
            value = parsed.get(f'stepper_{axis}', {}).get(field)
            if value is not None:
                geometry[f'{axis}_{field}'] = value
    geometry.update(user_data or {})
    print_nozzle_bed_preview(geometry)
    print()

    hotend = parsed.get("extruder", {}).get("sensor_type") or (defaults.get("hotend_thermistor") if is_custom else None)
    bed = parsed.get("heater_bed", {}).get("sensor_type") or (defaults.get("bed_thermistor") if is_custom else None)
    if hotend or bed:
        section("wizard.review_profile.thermistors")
        if hotend:
            print_val(f"{t('profile.hotend_thermistor')}:", hotend, "profile.comment_hotend_therm")
        if bed:
            print_val(f"{t('profile.bed_thermistor')}:", bed, "profile.comment_bed_therm")
        print()


def interactive_profile_review(defaults: dict, parsed: dict, user_data: dict) -> str:
    return _step_profile_review_inner(defaults, parsed, user_data)


def _step_profile_review_inner(defaults: dict, parsed: dict, user_data: dict) -> str:
    """Show the explained profile before Continue, Edit or Back."""
    while True:
        print_detected_profile_summary(defaults, parsed, user_data)
        action = numbered_select(
            t("wizard.profile_review_prompt"),
            choices=[
                {"name": t("choice.continue"), "value": "confirm"},
                {"name": t("choice.edit_profile"), "value": "edit"},
                {"name": t("choice.arrow_back"), "value": "back"},
            ],
        )
        if action is None:
            raise WizardExit()
        if action == "confirm":
            from core.motor_direction import apply_motor_directions
            try:
                apply_motor_directions(copy.deepcopy(_motor_board(user_data)), user_data)
            except GenerationError as exc:
                print(f"{ERROR}{exc}{RESET}")
                continue
        if action in ("confirm", "back"):
            return action
        _step_profile_editor_inner(defaults, parsed, user_data)


def _step_profile_editor_inner(defaults: dict, parsed: dict, user_data: dict) -> str:
    """Staged profile editor."""
    staged_defaults  = copy.deepcopy(defaults)
    staged_parsed    = copy.deepcopy(parsed)
    staged_user_data = copy.deepcopy(user_data)

    def validated_candidate(overrides=None):
        candidate = safe_defaults()
        candidate.update(staged_defaults)
        candidate.update(staged_user_data)
        if overrides:
            candidate.update(overrides)
            mark_user_override(candidate, *overrides)
        if "_profile_parsed" in staged_user_data or "board_parsed" in staged_user_data:
            resolved, _ = resolve_generation_values(
                staged_user_data.get("board_parsed") or {}, candidate, validate_motors=False,
            )
            candidate.update(resolved)
        normalize_and_validate_configuration(candidate)
        return candidate

    def validate_pos_float(val):
        try:
            finite_number("build_volume", val, minimum=0.0, maximum=2000.0, minimum_inclusive=False)
            return True
        except GenerationError:
            return False

    def _resolve(sd, sp):
        kin   = sp.get('printer', {}).get('kinematics') or sd.get('kinematics', 'cartesian')
        x_sz  = sd.get('x_size') or sp.get('stepper_x', {}).get('position_max') or '235'
        y_sz  = sd.get('y_size') or sp.get('stepper_y', {}).get('position_max') or '235'
        z_sz  = sd.get('z_size') or sp.get('stepper_z', {}).get('position_max') or '250'
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
        if _INTERACTIVE_MODE and os.environ.get("KACE_QUIET") != "1":
            os.system('clear' if os.name == 'posix' else 'cls')

        kin, x_sz, y_sz, z_sz, x_min, x_max, x_end, \
            y_min, y_max, y_end, z_min, z_max, z_end, ht, bt = _resolve(staged_defaults, staged_parsed)

        C = "\033[96m"   # cyan
        D = "\033[2m"    # dim
        B = ""           # normal-weight wizard headings
        R = "\033[0m"    # reset
        columns = shutil.get_terminal_size(fallback=(80, 24)).columns
        separator_width = max(1, min(62, columns - 7))
        SEP = "─" * separator_width
        editor_details = {}

        def _row(label, value, comment_key, *, full_value=None):
            # Reserve the two-digit numbered_select prefix and one spare cell.
            # Hints yield space before values; no stored setting is shortened.
            width = max(3, columns - 9)
            label_width = min(22, max(1, width // 2))
            shown_label = _editor_cell_text(label, label_width)
            shown_value = _editor_cell_text(value, max(1, width - label_width - 1))
            row = f"{shown_label}{' ' * (label_width - wcswidth(shown_label))} {C}{shown_value}{R}"
            short_key = comment_key.replace("profile.comment_", "profile.editor.")
            if comment_key.startswith("profile.comment_position_"):
                short_key = short_key.rsplit("_", 1)[0]
            if comment_key == "wizard.homing.comment":
                short_key = "profile.editor.homing"
            elif comment_key == "motor.comment":
                short_key = "profile.editor.motor"
            hint = "  # " + t(short_key)
            if label_width + 1 + wcswidth(shown_value) + wcswidth(hint) <= width:
                row += f"{D}{hint}{R}"
            editor_details[row] = (label, value if full_value is None else full_value, t(comment_key))
            return row

        print(f"\n  {B}{t('choice.edit_profile')}{R}")
        print(f"  {SEP}")

        def _ansi_choice(text):
            return text

        choices = [
            Choice(title=_ansi_choice(_row("Kinematics",         kin,                             "profile.comment_kinematics")), value="kinematics"),
            Choice(title=_ansi_choice(_row("Build Volume",        f"{x_sz} x {y_sz} x {z_sz} mm", "profile.comment_build_volume")), value="volume"),
            Choice(title=_row(
                t("profile.printable_bounds"),
                _printable_bounds_value(staged_defaults, staged_user_data), "profile.comment_printable_bounds",
            ), value="printable_bounds"),
            Separator("  " + SEP),
            Choice(title=_ansi_choice(_row("X position_min",      x_min, "profile.comment_position_min_x")), value="x_position_min"),
            Choice(title=_ansi_choice(_row("X position_max",      x_max, "profile.comment_position_max_x")), value="x_position_max"),
            Choice(title=_ansi_choice(_row("X position_endstop",  x_end, "profile.comment_position_endstop_x")), value="x_position_endstop"),
            Separator("  " + SEP),
            Choice(title=_ansi_choice(_row("Y position_min",      y_min, "profile.comment_position_min_y")), value="y_position_min"),
            Choice(title=_ansi_choice(_row("Y position_max",      y_max, "profile.comment_position_max_y")), value="y_position_max"),
            Choice(title=_ansi_choice(_row("Y position_endstop",  y_end, "profile.comment_position_endstop_y")), value="y_position_endstop"),
            Separator("  " + SEP),
            Choice(title=_ansi_choice(_row("Z position_min",      z_min, "profile.comment_position_min_z")), value="z_position_min"),
            Choice(title=_ansi_choice(_row("Z position_max",      z_max, "profile.comment_position_max_z")), value="z_position_max"),
            Choice(title=_ansi_choice(_row("Z position_endstop",  z_end, "profile.comment_position_endstop_z")), value="z_position_endstop"),
            Separator("  " + SEP),
            Choice(title=_ansi_choice(_row("Hotend Thermistor",   ht,    "profile.comment_hotend_therm")), value="hotend_thermistor"),
            Choice(title=_ansi_choice(_row("Bed Thermistor",      bt,    "profile.comment_bed_therm")), value="bed_thermistor"),
            Separator("  " + SEP),
            Choice(title=_ansi_choice(f"{B}{t('choice.save_continue')}{R}"), value="save"),
            Choice(title=_ansi_choice(f"{B}{t('choice.back_discard')}{R}"), value="back")
        ]

        homing_data = dict(staged_defaults)
        homing_data.update(staged_user_data)
        for axis in ("x", "y", "z"):
            for field in ("position_min", "position_max", "position_endstop"):
                key = f"{axis}_{field}"
                value = staged_parsed.get(f"stepper_{axis}", {}).get(field)
                if key not in homing_data and value is not None:
                    homing_data[key] = value
            mode = _homing_direction_mode(staged_user_data, axis, staged_defaults, staged_parsed)
            label = _homing_direction_label(mode, _homing_direction_inferred(homing_data, axis), axis)
            insert_at = next(i for i, choice in enumerate(choices)
                             if getattr(choice, "value", None) == f"{axis}_position_endstop") + 1
            choices.insert(insert_at, Choice(
                title=_row(t("wizard.homing.axis_label", axis=axis.upper()),
                           _editor_homing_label(mode, _homing_direction_inferred(homing_data, axis), axis),
                           "wizard.homing.comment", full_value=label),
                value=f"homing_positive_dir_{axis}",
            ))
            if axis == "z" and mode == "auto":
                from core.menu import _wrapped_prompt_lines
                for line in _wrapped_prompt_lines(t('wizard.homing.z_probe_hint')):
                    print(f"  {D}{line}{R}")

        from core.motor_direction import available_motor_sections
        motor_source = _motor_board(staged_user_data)
        motors = available_motor_sections(motor_source, staged_user_data)
        for motor in motors:
            axis = motor.removeprefix("stepper_")
            anchor = f"homing_positive_dir_{axis}" if axis in ("x", "y", "z") else None
            insert_at = (next(i for i, choice in enumerate(choices) if getattr(choice, "value", None) == anchor) + 1
                         if anchor else next(i for i, choice in enumerate(choices)
                                             if getattr(choice, "value", None) == "hotend_thermistor"))
            choices.insert(insert_at, Choice(title=_row(
                _motor_label(staged_user_data, motor),
                _motor_direction_value(motor_source, staged_user_data, motor, compact=True),
                "motor.comment", full_value=_motor_direction_value(motor_source, staged_user_data, motor)),
                value="motor_direction_" + motor))

        prop = numbered_select(
            t("wizard.profile_editor_prompt"),
            choices=choices
        )

        if prop in (None, _QUIT):
            raise WizardExit()

        if prop == "save":
            try:
                from core.motor_direction import apply_motor_directions
                apply_motor_directions(copy.deepcopy(motor_source), staged_user_data)
                validation_data = validated_candidate()
            except GenerationError as exc:
                print(f"\n{ERROR}[!] Configuration Validation Failed:{RESET}")
                print(f"    - {exc}")
                continue

            staged_user_data.update(validation_data)

            for key in (
                "printable_x_min", "printable_x_max",
                "printable_y_min", "printable_y_max", "printable_z_max",
            ):
                staged_defaults[key] = staged_user_data[key]
            staged_defaults["_printable_bounds_defaults"] = copy.deepcopy(
                staged_user_data["_printable_bounds_defaults"]
            )

            defaults.clear()
            defaults.update(staged_defaults)
            parsed.clear()
            parsed.update(staged_parsed)
            user_data.clear()
            user_data.update(staged_user_data)
            return "save"

        if prop == "back":
            return "back"

        selected = next((choice for choice in choices if getattr(choice, "value", None) == prop), None)
        detail = editor_details.get(getattr(selected, "title", None))
        if detail:
            from core.menu import _wrapped_prompt_lines
            label, value, explanation = detail
            for line in _wrapped_prompt_lines(f"{label}: {value}\n{explanation}"):
                print("  " + line)

        if prop.startswith("motor_direction_"):
            _choose_motor_direction(staged_user_data, prop.removeprefix("motor_direction_"))

        elif prop == "kinematics":
            new_kin = numbered_select(
                "Select Kinematics:",
                choices=[*supported_kinematics(), _back_choice()],
                default=list(supported_kinematics()).index(kin) if kin in supported_kinematics() else 0
            )
            if new_kin == _BACK:
                continue
            if new_kin:
                staged_user_data["kinematics"] = new_kin
                mark_user_override(staged_user_data, "kinematics")
                staged_defaults["kinematics"] = new_kin
                staged_parsed.setdefault('printer', {})['kinematics'] = new_kin

        elif prop == "volume":
            new_x = simple_input("Enter X build volume (mm):", default=str(x_sz), back_value=_BACK)
            if new_x == _BACK:
                continue
            if new_x is not None and validate_pos_float(new_x):
                new_y = simple_input("Enter Y build volume (mm):", default=str(y_sz), back_value=_BACK)
                if new_y == _BACK:
                    continue
                if new_y is not None and validate_pos_float(new_y):
                    new_z = simple_input("Enter Z build volume (mm):", default=str(z_sz), back_value=_BACK)
                    if new_z == _BACK:
                        continue
                    if new_z is not None and validate_pos_float(new_z):
                        # Update bed sizes (Printable Area logical bounds)
                        for key, val in [("x_size", new_x), ("y_size", new_y), ("z_size", new_z),
                                         ("printable_x_min", "0"), ("printable_x_max", new_x),
                                         ("printable_y_min", "0"), ("printable_y_max", new_y),
                                         ("printable_z_max", new_z)]:
                            staged_user_data[key] = val
                            staged_defaults[key] = val
                        mark_user_override(
                            staged_user_data,
                            "x_size", "y_size", "z_size",
                            "printable_x_min", "printable_x_max",
                            "printable_y_min", "printable_y_max", "printable_z_max",
                        )

                        # Proposed mechanical changes remain visible in the editor
                        # until Save; generation must retain them as user overrides.
                        try:
                            curr_x_max = float(staged_user_data.get("x_position_max", x_max))
                            if curr_x_max < float(new_x):
                                staged_user_data["x_position_max"] = new_x
                                mark_user_override(staged_user_data, "x_position_max")
                                staged_defaults["x_position_max"] = new_x
                                staged_parsed.setdefault('stepper_x', {})['position_max'] = new_x
                        except (ValueError, TypeError):
                            pass

                        try:
                            curr_y_max = float(staged_user_data.get("y_position_max", y_max))
                            if curr_y_max < float(new_y):
                                staged_user_data["y_position_max"] = new_y
                                mark_user_override(staged_user_data, "y_position_max")
                                staged_defaults["y_position_max"] = new_y
                                staged_parsed.setdefault('stepper_y', {})['position_max'] = new_y
                        except (ValueError, TypeError):
                            pass

                        try:
                            curr_z_max = float(staged_user_data.get("z_position_max", z_max))
                            if curr_z_max < float(new_z):
                                staged_user_data["z_position_max"] = new_z
                                mark_user_override(staged_user_data, "z_position_max")
                                staged_defaults["z_position_max"] = new_z
                                staged_parsed.setdefault('stepper_z', {})['position_max'] = new_z
                        except (ValueError, TypeError):
                            pass

        elif prop == "printable_bounds":
            help_width = max(20, shutil.get_terminal_size(fallback=(80, 24)).columns - 4)
            for line in textwrap.wrap(t("profile.printable_bounds_help"), width=help_width):
                print(f"  {INFO}{line}{RESET}")
            updates = {}
            for axis, fallback_max in (("x", x_sz), ("y", y_sz)):
                for bound, fallback in (("min", "0"), ("max", fallback_max)):
                    key = f"printable_{axis}_{bound}"
                    current = staged_user_data.get(key, staged_defaults.get(key, fallback))
                    answer = simple_input(
                        t("profile.printable_bound_prompt", field=t(f"profile.printable_{bound}", axis=axis.upper())),
                        default=str(current), validate=questionary_numeric_validator, back_value=_BACK,
                    )
                    if answer in (None, _BACK):
                        break
                    updates[key] = answer.strip() or str(current)
                else:
                    continue
                break
            if len(updates) != 4:
                continue
            try:
                candidate = validated_candidate(updates)
            except GenerationError as exc:
                print(f"\n{ERROR}{t('profile.printable_bounds_invalid')}{RESET}")
                print(f"    - {exc}")
                continue
            for key in updates:
                staged_user_data[key] = candidate[key]
                staged_defaults[key] = candidate[key]
            mark_user_override(staged_user_data, *updates)

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
                validate=questionary_numeric_validator,
                back_value=_BACK,
            )
            if new_val == _BACK:
                continue
            
            if new_val is not None and new_val.strip().lower() not in ("<", "back", "volver", ""):
                val_clean = new_val.strip()
                staged_user_data[prop] = val_clean
                mark_user_override(staged_user_data, prop)
                staged_defaults[prop] = val_clean
                
                sx = staged_parsed.setdefault(f"stepper_{axis}", {})
                sx[field] = val_clean
                
                pass

        elif prop in ("homing_positive_dir_x", "homing_positive_dir_y", "homing_positive_dir_z"):
            axis = prop.rsplit("_", 1)[1]
            answer = _select_homing_direction(homing_data, axis, staged_defaults, staged_parsed)
            if answer == _BACK:
                continue
            # Automatic mode removes the old source directive; generation re-infers
            # from the current geometry rather than retaining an imported override.
            if answer == "auto":
                staged_defaults.pop(prop, None)
                staged_parsed.setdefault(f"stepper_{axis}", {}).pop("homing_positive_dir", None)
            else:
                staged_defaults[prop] = answer
                staged_parsed.setdefault(f"stepper_{axis}", {})["homing_positive_dir"] = answer
            _apply_homing_direction(staged_user_data, axis, answer)

        elif prop == "hotend_thermistor":
            th_choices = list(THERMISTOR_PRESETS) + ["Other (Manual Entry)"]
            new_th = numbered_select(
                "Select Hotend Thermistor:",
                choices=[*th_choices, _back_choice()],
                default=th_choices.index(ht) if ht in THERMISTOR_PRESETS else 0
            )
            if new_th == _BACK:
                continue
            if new_th == "Other (Manual Entry)":
                new_th = simple_input("Enter custom hotend thermistor name:", validate=questionary_thermistor_validator, back_value=_BACK)
                if new_th == _BACK:
                    continue
            if new_th:
                staged_user_data["hotend_thermistor"] = new_th
                mark_user_override(staged_user_data, "hotend_thermistor")
                staged_defaults["hotend_thermistor"] = new_th
                staged_parsed.setdefault('extruder', {})['sensor_type'] = new_th

        elif prop == "bed_thermistor":
            bt_choices = list(THERMISTOR_PRESETS) + ["Other (Manual Entry)"]
            new_tb = numbered_select(
                "Select Bed Thermistor:",
                choices=[*bt_choices, _back_choice()],
                default=bt_choices.index(bt) if bt in THERMISTOR_PRESETS else 0
            )
            if new_tb == _BACK:
                continue
            if new_tb == "Other (Manual Entry)":
                new_tb = simple_input("Enter custom bed thermistor name:", validate=questionary_thermistor_validator, back_value=_BACK)
                if new_tb == _BACK:
                    continue
            if new_tb:
                staged_user_data["bed_thermistor"] = new_tb
                mark_user_override(staged_user_data, "bed_thermistor")
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
            choices=[*printer_configs, _back_choice(), _quit_choice()],
            require_explicit=True,
            search_first=True,
            renumber_results=True,
        )
        if ans == _QUIT:
            raise WizardExit()
        if ans in (None, _BACK):
            return "__retry__"

    print(f"\n{INFO}>>> Loading defaults for {ans}...{RESET}")
    raw = fetch_raw_config(ans)
    if not raw:
        print(f"\n{ERROR}[!] Failed to load printer profile: '{ans}'{RESET}")
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
    try:
        from core.capabilities import validate_kinematics
        defaults["kinematics"] = validate_kinematics(defaults.get("kinematics"))
    except GenerationError as exc:
        print(f"\n{ERROR}[!] Unsupported printer profile: {exc}{RESET}")
        return "__retry__"
    for k, v in defaults.items():
        user_data[k] = v
    user_data["profile_loaded"]  = True
    user_data["_profile_parsed"]   = parsed
    user_data["_profile_defaults"] = defaults
    mark_profile_values(user_data, parsed)
    return ans


def _step_kinematics(user_data):
    if "kinematics" in user_data.get("_authoritative", set()):
        return user_data["kinematics"]
    choices = list(supported_kinematics()) + [_back_choice(), _quit_choice()]
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
    mark_user_override(user_data, "kinematics")
    return ans


def _step_volume(user_data, size_key, max_key, msg_text):
    if size_key in user_data.get("_authoritative", set()):
        return user_data[size_key]
    ans = simple_input(
        msg_text,
        default=str(user_data.get(size_key) or ""),
        validate=questionary_pos_numeric_validator,
        back_value=_BACK,
    )
    if ans == _BACK:
        return _BACK
    if ans is None or ans.strip().lower() in ("<", "back", "volver"):
        return _BACK
    val_clean = ans.strip()
    old_val = user_data.get(size_key)
    user_data[size_key] = val_clean
    mark_user_override(user_data, size_key)
    if user_data.get(max_key) == old_val or not user_data.get(max_key):
        user_data[max_key] = val_clean
    
    # Decouple Printable Area by storing printable_* limits
    axis = size_key.split("_")[0]  # "x", "y", "z"
    if axis in ("x", "y"):
        user_data[f"printable_{axis}_min"] = "0"
        user_data[f"printable_{axis}_max"] = val_clean
    elif axis == "z":
        user_data[f"printable_z_max"] = val_clean

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
                validate=questionary_numeric_validator,
                back_value="<",
            )
            if val is None:
                raise WizardExit()
            if val.strip().lower() in ("<", "back", "volver"):
                return _BACK
            user_data["x_position_min"] = val.strip()
            mark_user_override(user_data, "x_position_min")
            idx += 1
        elif curr == "max":
            val = simple_input(
                t("wizard.x_position_max") or "Enter X position_max (mm) [type '<' to go back]:",
                default=str(user_data.get("x_position_max") or user_data.get("x_size") or "235"),
                validate=questionary_numeric_validator,
                back_value="<",
            )
            if val is None:
                raise WizardExit()
            if val.strip().lower() in ("<", "back", "volver"):
                idx -= 1
                continue
            user_data["x_position_max"] = val.strip()
            mark_user_override(user_data, "x_position_max")
            idx += 1
        elif curr == "endstop":
            val = simple_input(
                t("wizard.x_position_endstop") or "Enter X position_endstop (mm) [type '<' to go back]:",
                default=str(user_data.get("x_position_endstop") if user_data.get("x_position_endstop") is not None else "0"),
                validate=questionary_numeric_validator,
                back_value="<",
            )
            if val is None:
                raise WizardExit()
            if val.strip().lower() in ("<", "back", "volver"):
                idx -= 1
                continue
            user_data["x_position_endstop"] = val.strip()
            mark_user_override(user_data, "x_position_endstop")
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
                validate=questionary_numeric_validator,
                back_value="<",
            )
            if val is None:
                raise WizardExit()
            if val.strip().lower() in ("<", "back", "volver"):
                return _BACK
            user_data["y_position_min"] = val.strip()
            mark_user_override(user_data, "y_position_min")
            idx += 1
        elif curr == "max":
            val = simple_input(
                t("wizard.y_position_max") or "Enter Y position_max (mm) [type '<' to go back]:",
                default=str(user_data.get("y_position_max") or user_data.get("y_size") or "235"),
                validate=questionary_numeric_validator,
                back_value="<",
            )
            if val is None:
                raise WizardExit()
            if val.strip().lower() in ("<", "back", "volver"):
                idx -= 1
                continue
            user_data["y_position_max"] = val.strip()
            mark_user_override(user_data, "y_position_max")
            idx += 1
        elif curr == "endstop":
            val = simple_input(
                t("wizard.y_position_endstop") or "Enter Y position_endstop (mm) [type '<' to go back]:",
                default=str(user_data.get("y_position_endstop") if user_data.get("y_position_endstop") is not None else "0"),
                validate=questionary_numeric_validator,
                back_value="<",
            )
            if val is None:
                raise WizardExit()
            if val.strip().lower() in ("<", "back", "volver"):
                idx -= 1
                continue
            user_data["y_position_endstop"] = val.strip()
            mark_user_override(user_data, "y_position_endstop")
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
                validate=questionary_numeric_validator,
                back_value="<",
            )
            if val is None:
                raise WizardExit()
            if val.strip().lower() in ("<", "back", "volver"):
                return _BACK
            user_data["z_position_min"] = val.strip()
            mark_user_override(user_data, "z_position_min")
            idx += 1
        elif curr == "max":
            val = simple_input(
                t("wizard.z_position_max") or "Enter Z position_max (mm) [type '<' to go back]:",
                default=str(user_data.get("z_position_max") or user_data.get("z_size") or "250"),
                validate=questionary_numeric_validator,
                back_value="<",
            )
            if val is None:
                raise WizardExit()
            if val.strip().lower() in ("<", "back", "volver"):
                idx -= 1
                continue
            user_data["z_position_max"] = val.strip()
            mark_user_override(user_data, "z_position_max")
            idx += 1
        elif curr == "endstop":
            val = simple_input(
                t("wizard.z_position_endstop") or "Enter Z position_endstop (mm) [type '<' to go back]:",
                default=str(user_data.get("z_position_endstop") if user_data.get("z_position_endstop") is not None else "0"),
                validate=questionary_numeric_validator,
                back_value="<",
            )
            if val is None:
                raise WizardExit()
            if val.strip().lower() in ("<", "back", "volver"):
                idx -= 1
                continue
            user_data["z_position_endstop"] = val.strip()
            mark_user_override(user_data, "z_position_endstop")
            idx += 1
    return "done"


def _step_homing_directions(user_data, *, reviewed=False):
    """Offer automatic/manual directions, committing only after every axis is reviewed."""
    staged = copy.deepcopy(user_data)
    for axis in ("x", "y", "z"):
        key = f"homing_positive_dir_{axis}"
        if reviewed or os.environ.get("KACE_AUTO") == "1":
            answer = _homing_direction_mode(staged, axis, parsed=staged.get("_profile_parsed"))
            if answer == "auto" and _homing_direction_inferred(staged, axis) is None:
                if os.environ.get("KACE_AUTO") == "1":
                    raise GenerationError(
                        f"Cannot infer {key}; run the interactive wizard or provide it explicitly."
                    )
                answer = _select_homing_direction(staged, axis, parsed=staged.get("_profile_parsed"))
        else:
            answer = _select_homing_direction(staged, axis, parsed=staged.get("_profile_parsed"))
        if answer == _BACK:
            return _BACK
        previous_mode = _homing_direction_mode(staged, axis, parsed=staged.get("_profile_parsed"))
        _apply_homing_direction(staged, axis, answer)
        if answer == previous_mode and answer != "auto":
            previous_provenance = (user_data.get("_value_provenance") or {}).get(key)
            if previous_provenance == ValueProvenance.PROFILE.value:
                staged["_value_provenance"][key] = previous_provenance
    user_data.clear()
    user_data.update(staged)
    return "done"
