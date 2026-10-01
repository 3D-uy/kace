"""Validate existing heater-protection sections; never tune or import them."""
import math
import re
import copy

from core.exceptions import GenerationError

OPTIONS = {"max_error", "hysteresis", "heating_gain", "check_gain_time"}
SOURCE = "_verify_heater_source_options"
PROFILE_SOURCE = "_verify_heater_profile_source"


def is_verifier(name):
    return name == "verify_heater" or name.startswith("verify_heater ")


def _settings(name, fields):
    extra = set(fields) - OPTIONS
    if extra:
        raise GenerationError(f"[{name}]: unsupported verify_heater options: {', '.join(sorted(extra))}.")
    defaults = {"max_error": 120., "hysteresis": 5., "heating_gain": 2.,
                "check_gain_time": 60. if name == "verify_heater heater_bed" else 20.}
    values = {}
    for option, default in defaults.items():
        try:
            value = float(fields.get(option, default))
        except (TypeError, ValueError, OverflowError) as exc:
            raise GenerationError(f"[{name}]: {option} must be a finite number.") from exc
        # Finiteness is KACE policy; comparisons in ConfigWrapper accept NaN.
        invalid = (not math.isfinite(value) or value < 0
                   or (option == "heating_gain" and value <= 0)
                   or (option == "check_gain_time" and value < 1))
        if invalid:
            raise GenerationError(f"[{name}]: invalid {option}; require finite max_error/hysteresis >= 0, "
                                  "heating_gain > 0 and check_gain_time >= 1.")
        values[option] = value
    return values


def source_verification_options(parsed):
    """Extract only proven active verification options, never circuit fields."""
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise GenerationError("verify_heater source is malformed; reload the selected source.")
    names = {name for name in parsed if is_verifier(name)}
    evidence = parsed.get(SOURCE)
    if not names and evidence is None:
        return {}
    if not isinstance(evidence, dict) or names != set(evidence):
        raise GenerationError("verify_heater source activity is unavailable or changed; reload the selected source.")
    result = {}
    for name, fields in evidence.items():
        if fields is None:  # Proven commented example, not a dependency.
            continue
        current = parsed.get(name)
        if (not isinstance(fields, dict) or not isinstance(current, dict)
                or any(current.get(key) != value for key, value in fields.items())):
            raise GenerationError(f"[{name}]: active source options changed; reload the selected source.")
        _settings(name, fields)
        result[name] = dict(fields)
    return result


def _profile_verification_options(data):
    parsed = data.get("_profile_parsed")
    loaded = data.get("profile_loaded")
    if loaded is False:
        # Do not silently erase a saved policy by flipping only the loaded flag.
        if source_verification_options(parsed):
            raise GenerationError("Thermal profile selection is inconsistent; reload the printer profile.")
        return {}
    if parsed is None and loaded is not True:
        return {}
    raw = data.get("raw_config")
    if isinstance(raw, str) and raw.strip():
        from core.scraper import parse_config
        raw_parsed = parse_config(raw, data.get("printer_profile") or "", keep_comments=True)
        raw_options = source_verification_options(raw_parsed)
        if isinstance(parsed, dict):
            if SOURCE in parsed:
                if source_verification_options(parsed) != raw_options:
                    raise GenerationError("Thermal profile text differs from parsed verification policy; reload the profile.")
            else:
                # Recover pre-B31 activity only from the saved profile text.
                # Commented examples may occur in the old UI map, but cannot
                # authorize a value absent from the active raw source.
                names = {name for name in parsed if is_verifier(name)}
                raw_names = {name for name in raw_parsed if is_verifier(name)}
                if (names - raw_names or set(raw_options) - names
                        or any(not isinstance(parsed.get(name), dict)
                               or any(parsed[name].get(key) != value for key, value in fields.items())
                               for name, fields in raw_options.items())):
                    raise GenerationError("Thermal profile text differs from saved verification policy; reload the profile.")
        elif parsed is not None:
            raise GenerationError("Thermal profile source is malformed; reload the printer profile.")
        return raw_options
    if not isinstance(parsed, dict) or (loaded is True and not parsed):
        raise GenerationError("Thermal profile source is unavailable; reload the printer profile.")
    return source_verification_options(parsed)


def attach_profile_verification(board_source, user_data, saved):
    """Carry a separate thermal requirement through the existing source context.

    Only verification sections travel in this metadata. Profile GPIO, buses,
    macros and other hardware never become selected-board electrical authority.
    A live/saved selection conflict must be resolved by regenerating its context.
    """
    previous = _profile_verification_options(saved)
    current = _profile_verification_options({**saved, **user_data})
    if previous and (previous != current or
            ("printer_profile" in user_data and saved.get("printer_profile")
             and user_data["printer_profile"] != saved["printer_profile"])):
        raise GenerationError("Thermal profile differs from the saved workflow; regenerate with the selected profile.")
    result = board_source
    if current:
        result = copy.deepcopy(board_source) if board_source is not None else {}
        result[PROFILE_SOURCE] = {SOURCE: copy.deepcopy(current), **copy.deepcopy(current)}
    from core.thermal_review import attach_thermal_review
    return attach_thermal_review(result, user_data, saved)


def validate_source_verification(parsed, content):
    """Reject silent loss of selected-source protection; never import tuning.

    An omitted section uses upstream defaults, not disabled verification. It is
    equivalent only if all the source's effective values equal those defaults.
    This checks policy preservation, not physical heater/circuit equivalence.
    """
    from core.managed_config import _section_options
    sections = _section_options(content)
    for name, fields in source_verification_options(parsed).items():
        # Validate the source's exact heater reference against the artifact as
        # well, even when it has no explicit verification section of its own.
        source_text = "\n".join(f"{key}: {value}" for key, value in fields.items())
        validate_verify_heater(content + f"\n[{name}]\n{source_text}\n")
        expected = _settings(name, fields)
        actual = _settings(name, sections.get(name, {}))
        changed = [key for key in expected if expected[key] != actual[key]]
        if changed:
            raise GenerationError(f"[{name}]: selected-source protection is missing or changed "
                                  f"({', '.join(changed)}). Thermal-policy migration requires review; "
                                  "KACE cannot silently substitute defaults or import tuning for another circuit.")


def validate_verify_heater(content):
    from core.managed_config import _section_options
    sections = _section_options(content)
    # Keep heater registration names exact. Some legacy maps fold their keys,
    # while upstream PrinterHeaters.lookup_heater does not fold or alias them.
    available = set()
    for match in re.finditer(r"(?m)^\s*\[([^\]\r\n]+)\]\s*(?:[#;].*)?$", content):
        name = match.group(1).strip()
        if re.fullmatch(r"extruder\d*|heater_bed", name) or name.startswith("heater_generic "):
            available.add(name.split()[-1])
    for name, fields in sections.items():
        if not is_verifier(name):
            continue
        parts = name.split()
        if len(parts) != 2 or parts[1] not in available:
            raise GenerationError(f"[{name}]: verify_heater must reference an available heater with its exact name.")
        _settings(name, fields)
