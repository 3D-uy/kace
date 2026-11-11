"""Bounded SX1509 PWM provider checks, without I2C or physical qualification."""
import re

from core.exceptions import GenerationError
from core.pwm_output import _number, _TRUE


def _sx1509_leaves(sections, token, providers, seen=()):
    """Keep multi_pin leaf order; aliases do not rename virtual providers.

    Literal prefixes/inversion follow the pin provider. No ADC mapping or MCU
    name resemblance establishes an SX1509. Missing providers and invalid pin
    syntax remain with their own validators and the pinned loader.
    """
    if not isinstance(token, str):
        return [False]
    token = token.strip()
    invert = token.startswith("!")
    if invert:
        token = token[1:].strip()
    if any(c in token for c in "!^~"):
        return [False]
    chip, pin = (token.split(":", 1) if ":" in token else ("mcu", token))
    chip, pin = chip.strip(), pin.strip()
    if (chip == "mcu" and "mcu" in sections) or "mcu " + chip in sections:
        return [False]
    if chip in providers:
        return [True]
    name = "multi_pin " + pin
    if chip != "multi_pin" or name not in sections or name in seen:
        return [False]
    children = sections[name].get("pins", "")
    if not isinstance(children, str) or not children.strip():
        return [False]
    return [leaf for child in children.split(",")
            for leaf in _sx1509_leaves(sections,
                ("!" if invert else "") + child.strip(), providers, (*seen, name))]


def validate_sx1509_pwm(sections):
    """Check known consumers against the pinned SX1509 callback contract.

    Fans and PWM output_pin use zero watchdog duration and need hardware_pwm.
    Heater uses nonzero duration and software mode, both rejected by SX1509.
    Fractional levels and fan periods are not limited by the MCU software PWM
    rule. output_pin's own 3 s nominal ceiling still applies through get_mcu().
    These checks do not enable generation or certify pins, shutdown or timing.
    """
    providers = {"sx1509_" + parts[1] for name in sections
                 if len(parts := name.split()) >= 2 and parts[0] == "sx1509"}
    for name, fields in sections.items():
        parts = name.split()
        kind = parts[0] if parts else ""
        heater = bool(re.fullmatch(r"extruder\d*", kind) or kind in ("heater_bed", "heater_generic"))
        output = kind == "output_pin" and str(fields.get("pwm", "false")).strip().lower() in _TRUE
        fan = kind in ("fan", "fan_generic", "heater_fan", "controller_fan", "temperature_fan")
        if not (heater or output or fan):
            continue
        leaves = _sx1509_leaves(sections, fields.get("heater_pin" if heater else "pin"), providers)
        if not any(leaves):
            continue
        if heater:
            raise GenerationError(
                f"[{name}] SX1509 PWM cannot drive a Heater: the pinned provider "
                "rejects its nonzero watchdog duration and software PWM mode.")
        if str(fields.get("hardware_pwm", "false")).strip().lower() not in _TRUE:
            raise GenerationError(f"[{name}] SX1509 PWM requires hardware_pwm: true.")
        if output and leaves[0]:
            cycle = _number(fields, "cycle_time", .100)
            if cycle is not None and cycle > 3.:
                raise GenerationError(
                    f"[{name}] cycle_time must be at most 3 seconds for output_pin's MCU contract.")
