"""Finite Anycubic probe-reset contract; not arbitrary macro preservation."""
from core.exceptions import GenerationError

SOURCE_RESET = "_board_probe_reset_source"
RESET_OUTPUT = "output_pin probe_reset_pin"
RESET_MACRO = "gcode_macro probe_reset"
RESET_COMMANDS = (
    "SET_PIN PIN=probe_reset_pin VALUE=0", "G4 P300",
    "SET_PIN PIN=probe_reset_pin VALUE=1", "G4 P100",
)


def capture_probe_reset_source(raw):
    from core.pin_validator import _read_pin_config
    sections = _read_pin_config(raw)[0]
    if RESET_OUTPUT not in sections:
        return None
    return {"probe": {key: sections.get("probe", {}).get(key) for key in ("pin", "activate_gcode", "deactivate_gcode")},
            "macros": {name: fields for name, fields in sections.items()
                       if name.lower() == RESET_MACRO}}


def _commands(value):
    return tuple(line.strip() for line in value.splitlines() if line.strip()) if isinstance(value, str) else ()


def _macro(sections):
    matches = [(name, fields) for name, fields in sections.items() if name.lower() == RESET_MACRO]
    if (len(matches) != 1 or not isinstance(matches[0][1], dict) or set(matches[0][1]) != {"gcode"}
            or _commands(matches[0][1]["gcode"]) != RESET_COMMANDS):
        raise GenerationError("[gcode_macro probe_reset] is missing or changed; only the reviewed four-command reset is supported.")


def selected_probe_reset(parsed):
    from core.board_auxiliary import SOURCE_ACTIVITY
    activity = parsed.get(SOURCE_ACTIVITY, {})
    if RESET_OUTPUT not in parsed or (isinstance(activity, dict) and activity.get(RESET_OUTPUT) is False):
        return None
    evidence = parsed.get(SOURCE_RESET)
    if not isinstance(evidence, dict):
        raise GenerationError("[output_pin probe_reset_pin] requires active probe/macro source evidence; reload the selected board.")
    probe, macros = evidence.get("probe"), evidence.get("macros")
    if (not isinstance(probe, dict) or not isinstance(probe.get("pin"), str)
            or not probe["pin"].strip() or _commands(probe.get("activate_gcode")) != ("probe_reset",)
            or _commands(probe.get("deactivate_gcode"))
            or not isinstance(macros, dict)):
        raise GenerationError("[probe] reset dependency is missing or changed; review the selected board's activate_gcode.")
    _macro(macros)
    return probe


def _probe_matches(parsed, sections, expected):
    from core.pin_validator import PinAliases, PinAliasError
    if "probe" not in sections:
        return False  # Explicit no-probe generation retains output and standalone reset.
    pin = sections["probe"].get("pin", "")
    original = expected["pin"]
    try:
        same = (PinAliases(parsed).resolve(original) == PinAliases(sections).resolve(pin)
                and tuple(flag in original.split(":")[0] for flag in "!^~")
                == tuple(flag in pin.split(":")[0] for flag in "!^~"))
    except PinAliasError as exc:
        raise GenerationError(f"Invalid probe reset pin identity: {exc}") from exc
    if not same:
        raise GenerationError("[probe] pin differs from the selected reset circuit; this combination is not supported.")
    if _commands(sections["probe"].get("deactivate_gcode")):
        raise GenerationError("[probe] deactivate_gcode is outside the reviewed reset circuit.")
    return True


def render_probe_reset(parsed, text):
    from core.pin_validator import _read_pin_config
    from core.managed_config import _replace_or_insert_option
    expected = selected_probe_reset(parsed)
    if expected is None:
        return text
    sections = _read_pin_config(text)[0]
    if any(name.lower() == RESET_MACRO for name in sections):
        _macro(sections)  # Never overwrite a supplied custom macro.
    else:
        text += "\n["+RESET_MACRO+"]\ngcode:\n"+"".join("    "+cmd+"\n" for cmd in RESET_COMMANDS)
    if _probe_matches(parsed, sections, expected):
        hook = sections["probe"].get("activate_gcode")
        if hook is not None and _commands(hook) != ("probe_reset",):
            raise GenerationError("[probe] activate_gcode conflicts with the selected reset circuit.")
        if hook is None:
            text = _replace_or_insert_option(text, "probe", "activate_gcode", "probe_reset")
    return text


def validate_probe_reset_artifact(parsed, sections):
    expected = selected_probe_reset(parsed)
    if expected is None:
        return
    _macro(sections)
    if (_probe_matches(parsed, sections, expected)
            and _commands(sections["probe"].get("activate_gcode")) != ("probe_reset",)):
        raise GenerationError("[probe] activate_gcode is missing or changed; the selected reset circuit must run before probing.")
