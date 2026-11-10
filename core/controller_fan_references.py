"""Bounded controller_fan reference-list checks from Klipper fe4eb865."""
from core.exceptions import GenerationError


def validate_controller_fan_references(sections):
    """Reject empty names inside nonempty heater/stepper lists.

    Input is the effective parsed CFG. Omission and an explicitly empty list
    retain different Klipper defaults. Nonempty names remain case-sensitive,
    including full manual_stepper/extruder_stepper names. This does not infer
    a complete object registry from section prefixes: missing names, external
    registrations and conditional motor construction still need connect-time
    validation by Klipper.
    """
    for section, fields in sections.items():
        parts = section.split()
        if len(parts) < 2 or parts[0] != "controller_fan":
            continue
        for option in ("heater", "stepper"):
            if option not in fields:
                continue
            text = str(fields[option]).strip()
            if text and any(not name.strip() for name in text.split(",")):
                raise GenerationError(
                    f"[{section}] {option} contains an empty reference; "
                    "use complete names or an explicitly empty list."
                )
