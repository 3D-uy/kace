"""Finite stock probe sampling contract; no calibration or G-code migration."""
import copy
import math
from collections.abc import Mapping

from core.exceptions import GenerationError

OPTIONS = ("speed", "lift_speed", "samples", "sample_retract_dist", "samples_result",
           "samples_tolerance", "samples_tolerance_retries")
SOURCE = "_bltouch_sampling_source"
PROFILE_SOURCE = "_bltouch_sampling_profile_source"


def sampling_value(option, value):
    text = str(value).strip()
    if option == "samples_result":
        if text not in ("median", "average"):
            raise GenerationError(f"probe {option}: expected median or average.")
        return text
    integer = option in ("samples", "samples_tolerance_retries")
    try:
        number = int(text) if integer else float(text)
        finite = True if integer else math.isfinite(number)
    except (TypeError, ValueError, OverflowError) as exc:
        raise GenerationError(f"probe {option}: expected a finite {'integer' if integer else 'number'}.") from exc
    zero_allowed = option in ("samples_tolerance", "samples_tolerance_retries")
    if not finite or number < 0 or (not zero_allowed and number == 0):
        raise GenerationError(f"probe {option}: expected {'nonnegative' if zero_allowed else 'positive'} finite value.")
    return str(number)


def source_options(parsed):
    if parsed is None:
        return {}
    if not isinstance(parsed, Mapping):
        raise GenerationError("BLTouch sampling source is malformed; reload the source.")
    source = parsed.get(SOURCE, parsed.get("bltouch", {}))
    if not isinstance(source, Mapping):
        raise GenerationError("BLTouch sampling activity evidence is malformed; reload the source.")
    if SOURCE in parsed:
        current = parsed.get("bltouch", {})
        if not isinstance(current, Mapping) or any(current.get(key) != value for key, value in source.items()):
            raise GenerationError("BLTouch sampling source changed after activity capture; reload it.")
    return {key: source[key] for key in OPTIONS if key in source}


def selected_bltouch_sampling(board, user):
    selected = {}
    for label, values in (("board", source_options(board)), ("printer_profile", _profile_options(user))):
        for key, raw in values.items():
            value = sampling_value(key, raw)
            if key in selected and selected[key]["value"] != value:
                raise GenerationError(f"conflicting BLTouch sampling policy {key} in board and printer profile.")
            entry = selected.setdefault(key, {"value": value, "sources": []})
            entry["sources"].append(label)
    return selected


def validate_probe_sampling(sections, *, expected=None):
    # Both stock modules share ProbeParameterHelper; custom/raw data stays
    # verbatim and is validated, never replaced with upstream profile policy.
    for name in ("probe", "bltouch"):
        for key, value in sections.get(name, {}).items():
            if key in OPTIONS:
                sampling_value(key, value)
    actual = sections.get("bltouch", {})
    for key, entry in (expected or {}).items():
        if key not in actual or sampling_value(key, actual[key]) != entry["value"]:
            raise GenerationError(f"BLTouch sampling policy {key} is missing or changed; regenerate before publication.")


def _profile_options(data):
    parsed = data.get("_profile_parsed")
    raw = data.get("raw_config")
    if isinstance(raw, str) and raw.strip():
        from core.scraper import parse_config
        active = source_options(parse_config(raw, data.get("printer_profile") or ""))
        if isinstance(parsed, Mapping):
            if SOURCE in parsed:
                if source_options(parsed) != active:
                    raise GenerationError("Probe sampling profile text differs from its saved policy; reload it.")
            elif any(parsed.get("bltouch", {}).get(key) != value for key, value in active.items()):
                raise GenerationError("Probe sampling legacy profile differs from its saved text; reload it.")
        elif parsed is not None:
            raise GenerationError("Probe sampling profile is malformed; reload it.")
        result = active
    else:
        result = source_options(parsed)
    if data.get("profile_loaded") is False and result:
        raise GenerationError("Probe sampling profile selection is inconsistent; reload it.")
    return result


def attach_profile_sampling(board, user, saved):
    """Carry only sampling policy through the existing deployment source context."""
    previous = _profile_options(saved)
    current = _profile_options({**saved, **user})
    if previous != current and previous:
        raise GenerationError("Probe sampling profile differs from the saved workflow; regenerate its policy.")
    if not current:
        return board
    result = copy.deepcopy(board) if board is not None else {}
    result[PROFILE_SOURCE] = {"bltouch": copy.deepcopy(current)}
    return result


def validate_source_sampling(board, sections):
    validate_probe_sampling(sections)
    if board is not None and "bltouch" in sections:
        expected = selected_bltouch_sampling(board, {"_profile_parsed": board.get(PROFILE_SOURCE)})
        validate_probe_sampling(sections, expected=expected)
