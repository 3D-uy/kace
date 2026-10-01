"""Preserve selected board ADC scaling circuits; validate their physical pins."""
import math
import re
from collections.abc import Mapping

from core.exceptions import GenerationError
from core.pin_validator import PinAliases, PinAliasError
from core.thermistor import BUILTIN_ADC_SENSORS, _is_thermal_consumer


def selected_adc_scaled(board, pins):
    """Scaling is board wiring, never imported from the printer profile."""
    selected = {}
    for section in ("extruder", "heater_bed"):
        pin = pins.get(section, {}).get("sensor_pin", "")
        if not isinstance(pin, str) or ":" not in pin:
            continue
        chip = pin.split(":", 1)[0].strip()
        name = "adc_scaled " + chip
        matches = [options for key, options in board.items()
                   if str(key).casefold() == name.casefold()]
        if not matches:
            continue  # Missing/non-scaled providers have their own final gate.
        if any(not isinstance(value, Mapping) or dict(value) != dict(matches[0]) for value in matches):
            raise GenerationError(f"ADC scaled: conflicting board definition {name!r}.")
        selected[name] = dict(matches[0])
    return selected


def validate_adc_scaled(sections, *, firmware_reservations=None):
    """Check scalar schema, MCU references and exclusive physical ADC use.

    One physical MCU supplies both references and the scaled sensor. Nested ADC
    providers are outside KACE's supported contract. Load-before-use and rejecting
    duplicate_pin_override bypasses are KACE policies. Physical ADC capability and
    electrical calibration still need firmware/hardware evidence.
    """
    definitions = {name: options for name, options in sections.items()
                   if str(name).split() and str(name).split()[0] == "adc_scaled"}
    if not definitions:
        return
    try:
        _validate(sections, definitions, firmware_reservations or {})
    except PinAliasError as exc:
        raise GenerationError(f"ADC scaled: {exc}") from exc


def _validate(sections, definitions, reservations):
    def fail(message):
        raise GenerationError("ADC scaled: " + message)

    mcus = {"mcu"} if "mcu" in sections else set()
    mcus.update(name[4:].strip() for name in sections if name.startswith("mcu "))
    other_chips = {name.split()[-1] for name in sections if name.startswith("ads1x1x ")}
    positions = {name: index for index, name in enumerate(sections)}
    aliases = PinAliases(sections)
    chips, allocated = {}, {}
    factories = set(BUILTIN_ADC_SENSORS)
    factories.update(" ".join(name.split()[1:]) for name in sections
                     if name.split() and name.split()[0] in ("thermistor", "adc_temperature"))

    def pin_parts(token):
        if not isinstance(token, str):
            fail(f"invalid ADC pin {token!r}.")
        parts = [part.strip() for part in token.strip().split(":", 1)]
        chip, pin = parts if len(parts) == 2 else ("mcu", parts[0])
        if (not chip or not pin or any(c in chip + pin for c in "^~!:")
                or any(c.isspace() for c in chip + pin)):
            fail(f"invalid ADC pin {token!r}.")
        return chip, pin

    def allocate(section, field, token):
        identity = aliases.resolve(token)
        if identity in allocated:
            fail(f"[{section}] {field} conflicts with {allocated[identity]} on {identity}.")
        reason = reservations.get(identity[0], {}).get(identity[1])
        if reason is not None:
            fail(f"[{section}] {field} is reserved for {reason}.")
        allocated[identity] = (section, field)
        return identity

    for section, options in definitions.items():
        parts = section.split()
        if len(parts) != 2 or not re.fullmatch(r"[A-Za-z0-9_]+", parts[1]):
            fail(f"invalid provider name [{section}].")
        chip = parts[1]
        if chip in chips or chip in mcus or chip in other_chips:
            fail(f"duplicate pin chip {chip!r}.")
        if not isinstance(options, Mapping):
            fail(f"[{section}] requires reference pins.")
        unused = set(options) - {"vref_pin", "vssa_pin", "smooth_time"}
        if unused:
            fail(f"[{section}] unused options: {', '.join(sorted(unused))}.")
        try:
            smooth = float(options.get("smooth_time", 2.))
        except (TypeError, ValueError):
            fail(f"[{section}] smooth_time must be finite and positive.")
        if not math.isfinite(smooth) or smooth <= 0:
            fail(f"[{section}] smooth_time must be finite and positive.")
        refs = []
        for field in ("vref_pin", "vssa_pin"):
            token = options.get(field, "")
            mcu, pin = pin_parts(token)
            if mcu not in mcus:
                fail(f"[{section}] {field} requires a declared physical MCU; nested ADC providers are unsupported.")
            refs.append(allocate(section, field, f"{mcu}:{pin}"))
        if refs[0][0] != refs[1][0]:
            fail(f"[{section}] vref and vssa must use the same MCU.")
        chips[chip] = section

    # Register scaled consumers, then compare against every other explicit pin.
    for section, options in sections.items():
        if not isinstance(options, Mapping):
            continue
        token = options.get("sensor_pin", "")
        if not isinstance(token, str) or ":" not in token:
            continue
        chip = token.split(":", 1)[0].strip()
        if chip not in chips:
            continue
        pin_parts(token)
        if not _is_thermal_consumer(section) or options.get("sensor_type") not in factories:
            fail(f"[{section}] {chip} supports only ADC thermal inputs in KACE.")
        if positions[chips[chip]] >= positions[section]:
            fail(f"define [{chips[chip]}] before [{section}].")
        allocate(section, "sensor_pin", token)

    for section, options in sections.items():
        if (section in ("board_pins", "duplicate_pin_override")
                or section.startswith(("board_pins ", "gcode_macro ", "delayed_gcode "))):
            continue
        for field, value in options.items():
            if not (field == "pin" or field.endswith("_pin") or field in ("pins", "select_pins", "encoder_pins")):
                continue
            # Whitespace around the namespace separator is accepted by Klipper.
            normalized = re.sub(r"\s*:\s*", ":", value.strip())
            for token in re.split(r"[,\s]+", normalized):
                if not token:
                    continue
                identity = aliases.resolve(token)
                owner = allocated.get(identity)
                if owner == (section, field):
                    continue
                if PinAliases.split_pin(token)[0] in chips:
                    fail(f"[{section}] {field}: {token} supports only ADC thermal inputs in KACE.")
                if owner is not None:
                    fail(f"[{section}] {field} conflicts with {owner} on {identity}.")
