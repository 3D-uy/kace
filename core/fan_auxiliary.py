"""Bounded auxiliary fan pin contracts from Klipper fe4eb865.

Pin grammar and known counter providers are admission checks, not proof of MCU
pin availability, sampling frequency, aliases, collisions or electrical wiring.
"""
from core.exceptions import GenerationError


def validate_fan_auxiliary(sections):
    """Check auxiliary pins without treating output providers as MCU counters.

    The counter uses lookup_pin(can_pullup=True) and then calls the chip's MCU
    interface directly. enable_pin instead delegates digital_out via setup_pin.
    Unknown extension chips remain the pinned loader's responsibility. Aliases
    cannot change chip identity or pin modifiers; no ADC-provider mapping applies.
    """
    sx_providers = {"sx1509_" + parts[1] for name in sections
                    if len(parts := name.split()) >= 2 and parts[0] == "sx1509"}
    has_multi = any(name.startswith("multi_pin ") for name in sections)
    for name, fields in sections.items():
        parts = name.split()
        if name != "fan" and not (len(parts) >= 2 and parts[0] in (
                "fan_generic", "heater_fan", "controller_fan", "temperature_fan")):
            continue
        for option in ("enable_pin", "tachometer_pin"):
            if option not in fields:
                continue
            token = fields[option]
            if not isinstance(token, str):
                raise GenerationError(f"[{name}] {option} must be a pin description.")
            token = token.strip()
            allowed = "^~" if option == "tachometer_pin" else "!"
            if token.startswith(tuple(allowed)):
                token = token[1:].strip()
            chip, pin = (token.split(":", 1) if ":" in token else ("mcu", token))
            chip, pin = chip.strip(), pin.strip()
            if any(char in pin for char in "^~!:") or "".join(pin.split()) != pin:
                raise GenerationError(
                    f"[{name}] {option} has invalid pin syntax; "
                    + ("the tachometer permits one ^ or ~ prefix, not inversion."
                       if option == "tachometer_pin" else "enable_pin permits one ! prefix, not pullup/pulldown."))
            if option != "tachometer_pin":
                continue
            if (chip == "mcu" and "mcu" in sections) or "mcu " + chip in sections:
                continue
            if (chip == "multi_pin" and has_multi) or chip in sx_providers:
                raise GenerationError(
                    f"[{name}] tachometer_pin requires a direct MCU counter; "
                    f"the declared {chip} provider does not implement that interface.")
