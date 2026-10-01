"""Section identity shared by source extraction and deployment planning."""


def section_identity(name: str) -> str:
    """Keep output_pin, supported automatic fans and verify_heater names exact.

    Klipper's output/fan objects and heater references are case-sensitive. Keep the existing folded
    identities for other families; this is not a general parser replacement.
    """
    name = name.strip()
    return name if name.startswith(("heater_fan ", "controller_fan ", "verify_heater ")) or name.casefold().startswith("output_pin ") else name.casefold()
