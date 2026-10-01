"""Retain the explicitly selected heater fan without inventing cooling roles."""
from collections.abc import Mapping
import math
import re

from core.exceptions import GenerationError
from core.part_fan import SCALAR_OPTIONS, validate_part_fan_options
from core.pin_validator import PinAliases, PinAliasError


SOURCE_OPTIONS = "_active_fan_sections"
CANONICAL = "heater_fan hotend_fan"
HEATER_OPTIONS = ("heater", "heater_temp", "fan_speed")
FAMILIES = ("fan", "heater_fan", "controller_fan", "temperature_fan", "fan_generic")


def is_fan_section(name):
    return bool(name.split()) and name.split()[0] in FAMILIES


def active_fan_sources(parsed, *, role="heater_fan"):
    """Resolve source activity once for either supported wizard fan role."""
    sources = parsed.get(SOURCE_OPTIONS)
    if sources is None:
        # Dictionary API/legacy inputs do not establish original comment activity.
        sources = {n: v for n, v in parsed.items() if is_fan_section(n)}
    if not isinstance(sources, Mapping):
        raise GenerationError(f"{role}: invalid source activity evidence; reload the board.")
    return sources


def match_fan_source(parsed, sources, choice, *, role="heater_fan"):
    """Match MCU/GPIO before allowing a new token to discard source settings."""
    if not isinstance(choice, str):
        raise GenerationError(f"{role}: invalid fan pin.")
    try:
        aliases = PinAliases(parsed)
        identity = aliases.resolve(choice)
        matches = [(name, fields) for name, fields in sources.items()
                   if isinstance(fields, Mapping) and isinstance(fields.get("pin"), str)
                   and aliases.resolve(fields["pin"]) == identity]
    except PinAliasError as exc:
        raise GenerationError(f"{role}: {exc}") from exc
    if len(matches) > 1:
        raise GenerationError(f"{role}: ambiguous source pin; review the original fan sections.")
    if matches and matches[0][1]["pin"] != choice:
        raise GenerationError(f"{role}: source GPIO alias/polarity changed; select its original pin token before preserving options.")
    return matches[0] if matches else None


def selected_hotend_fans(parsed, choice):
    sources = active_fan_sources(parsed)
    if choice == "none":
        return {}
    if not choice:
        source = sources.get(CANONICAL)
        if source is None:
            return {}
        if not isinstance(source, Mapping):
            raise GenerationError("heater_fan: invalid source options; reload the board.")
        choice = source.get("pin")
        if not choice:
            raise GenerationError("heater_fan: selected source requires a pin.")
    match = match_fan_source(parsed, sources, choice)
    if match:
        name, fields = match
        if name.startswith("heater_fan "):
            unsupported = set(fields) - {"pin", *SCALAR_OPTIONS, *HEATER_OPTIONS}
            if unsupported:
                raise GenerationError(f"{name}: preservation of {', '.join(sorted(unsupported))} is not implemented; do not remove required options.")
            return {name: dict(fields)}
        if name.startswith(("controller_fan ", "temperature_fan ")) or set(fields) != {"pin"}:
            raise GenerationError(f"{name}: cooling role conversion needs review; cannot silently replace its dependencies with a hotend fan.")
    # Explicit custom socket (or a pin-only manual fan) retains the existing UI
    # policy. No electrical settings are borrowed from another source resource.
    return {CANONICAL: {"pin": choice, "heater": "extruder", "heater_temp": "50.0"}}


def validate_heater_fan_options(content):
    from core.managed_config import _section_options
    # The simple review option map omits continuation lines. Reuse the existing
    # multiline reader so every heater in a list is checked, including includes.
    sections = _section_options(content)
    if any(name.startswith("heater_fan ") for name in sections):
        try:
            aliases = PinAliases(sections)
            allocated = {}
            for name, fields in sections.items():
                if not is_fan_section(name) or "pin" not in fields:
                    continue
                identity = aliases.resolve(fields["pin"])
                if identity in allocated:
                    raise GenerationError(f"{name}: fan GPIO conflicts with [{allocated[identity]}]; reconcile existing fan sections before publication.")
                allocated[identity] = name
        except PinAliasError as exc:
            raise GenerationError(f"heater_fan GPIO: {exc}") from exc
    # Heater instance names are case-sensitive. Do not infer them from folded
    # section keys used elsewhere in the legacy scraper/review machinery.
    available = set()
    for match in re.finditer(r"(?m)^\s*\[([^\]\r\n]+)\]\s*(?:[#;].*)?$", content):
        name = match.group(1).strip()
        if re.fullmatch(r"extruder\d*|heater_bed", name) or name.startswith("heater_generic "):
            available.add(name.split()[-1])
    for name, options in sections.items():
        if not name.startswith("heater_fan "):
            continue
        try:
            validate_part_fan_options({"fan": options})
        except GenerationError as exc:
            raise GenerationError(f"{name}: {exc}") from exc
        for option in ("heater_temp", "fan_speed"):
            if option not in options:
                continue
            try:
                value = float(str(options[option]).strip())
            except (TypeError, ValueError) as exc:
                raise GenerationError(f"{name}: {option} must be a finite number.") from exc
            if not math.isfinite(value) or (option == "fan_speed" and not 0 <= value <= 1):
                raise GenerationError(f"{name}: invalid {option}; use a finite number" + (" between 0 and 1." if option == "fan_speed" else "."))
        heater_text = "\n".join(line.split("#", 1)[0].split(";", 1)[0]
                                for line in str(options.get("heater", "extruder")).splitlines())
        heaters = [n.strip() for n in heater_text.split(",")]
        if not all(heaters) or any(n not in available for n in heaters):
            raise GenerationError(f"{name}: heater references must name available heaters: {', '.join(heaters)}.")
