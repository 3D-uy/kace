"""Validate shared TMC SPI chip-selects in effective configuration order.

No transport is created and no pins are rewritten. This covers chain identity
and ownership of transport options, not every explicit/implicit bus consumer.
"""
import re

from core.exceptions import GenerationError
from core.pin_validator import PinAliases, PinAliasError, _read_pin_config


_TRANSPORT_OPTIONS = frozenset((
    "spi_speed", "spi_bus", "spi_software_sclk_pin",
    "spi_software_mosi_pin", "spi_software_miso_pin",
))


def validate_spi_config(content):
    if not re.search(r"(?m)^\s*\[tmc(?:2130|2240|2660|5160)\s+", content):
        return
    try:
        parsed, _ = _read_pin_config(content)
        owners = spi_transport_owners(parsed, require_declared_mcus=True)
        if owners:
            _validate_spi_pins(parsed, owners)
    except PinAliasError as exc:
        raise GenerationError(f"TMC SPI: {exc}") from exc


def _validate_spi_pins(parsed, owners):
    """Check supported transports and reviewed exclusive consumers in final CFG.

    Reviewed peripherals use the shared bus dispatch. Implicit firmware pins
    are not modeled here. Same-role sharing requires one alias spelling.
    """
    aliases = PinAliases(parsed)
    chips = {"mcu"} | {name[4:] for name in parsed if name.startswith("mcu ")}
    allocated, spellings = {}, {}

    def allocate(token, role):
        value = token.strip()
        parts = value.split(":", 1)
        chip, spelling = (part.strip() for part in parts) if len(parts) == 2 else ("mcu", value)
        if (chip not in chips or not spelling or any(c in spelling for c in "^~!:")
                or "".join(spelling.split()) != spelling):
            raise GenerationError(f"TMC SPI: invalid {role} pin {token!r}.")
        identity = aliases.resolve(f"{chip}:{spelling}")
        if spellings.setdefault(identity, spelling) != spelling:
            raise GenerationError(f"TMC SPI: multiple alias spellings use {identity}.")
        if identity in allocated and allocated[identity] != role:
            raise GenerationError(f"TMC SPI: pin {token} has incompatible roles {allocated[identity]} and {role}.")
        allocated[identity] = role
        return chip

    from core.bus_pins import peripheral_bus_selection
    transports = {name: "cs_pin" for name, owner in owners.items() if name == owner}
    for name, options in parsed.items():
        kind, field = peripheral_bus_selection(name, options)
        if kind == "spi":
            transports[name] = field
    signal_fields = tuple(f"spi_software_{signal}_pin" for signal in ("miso", "mosi", "sclk"))
    for name, cs_field in transports.items():
        options = parsed[name]
        token = options.get(cs_field, "")
        parts = token.strip().split(":", 1)
        chip, spelling = (part.strip() for part in parts) if len(parts) == 2 else ("mcu", token.strip())
        if chip not in chips or not spelling or any(c in spelling for c in "^~!:"):
            raise GenerationError(f"{name}: TMC SPI invalid {cs_field} {token!r}.")
        if spelling != "None":
            allocate(token, f"cs:{name}")
        if "spi_software_sclk_pin" not in options:
            if any(field in options for field in signal_fields):
                raise GenerationError(f"{name}: TMC SPI software pins require spi_software_sclk_pin.")
            continue
        if "spi_bus" in options:
            raise GenerationError(f"{name}: TMC SPI spi_bus is unused with software SPI.")
        for field in signal_fields:
            if field not in options:
                raise GenerationError(f"{name}: TMC SPI requires {field}.")
            if allocate(options[field], field) != chip:
                raise GenerationError(f"{name}: TMC SPI pins must be on the same MCU.")

    for name, cs_field in transports.items():
        options = parsed[name]
        kind = name.split(" ", 1)[0]
        auxiliary_fields = ()
        if kind == "display":
            lcd = options.get("lcd_type")
            if lcd == "uc1701":
                auxiliary_fields = ("a0_pin", "rst_pin")
            elif lcd in ("ssd1306", "sh1106"):
                auxiliary_fields = ("dc_pin", "reset_pin")
        elif kind in ("load_cell", "load_cell_probe"):
            auxiliary_fields = ("data_ready_pin",)
        if auxiliary_fields and auxiliary_fields[0] not in options:
            raise GenerationError(f"{name}: TMC SPI requires {auxiliary_fields[0]}.")
        chip = PinAliases.split_pin(options[cs_field])[0].strip()
        for field in auxiliary_fields:
            if field not in options:
                continue  # Reset is optional; the first field is required.
            if allocate(options[field], f"aux:{name}:{field}") != chip:
                raise GenerationError(f"{name}: TMC SPI {field} must be on the same MCU as its bus.")

    for name, options in parsed.items():
        if (name.split(" ", 1)[0] != "display" or "reset_pin" not in options
                or options.get("lcd_type") not in ("ssd1306", "sh1106")
                or peripheral_bus_selection(name, options)[0] != "i2c"):
            continue
        chip = options.get("i2c_mcu", "mcu")
        if chip not in chips:
            raise GenerationError(f"{name}: TMC SPI review found unknown I2C MCU {chip!r}.")
        if "i2c_software_scl_pin" in options:
            if "i2c_bus" in options:
                raise GenerationError(f"{name}: TMC SPI review found unused i2c_bus with software I2C.")
            for field in ("i2c_software_scl_pin", "i2c_software_sda_pin"):
                if field not in options:
                    raise GenerationError(f"{name}: TMC SPI review requires {field}.")
                if allocate(options[field], field) != chip:
                    raise GenerationError(f"{name}: TMC SPI review requires I2C pins on their bus MCU.")
        elif "i2c_software_sda_pin" in options:
            raise GenerationError(f"{name}: TMC SPI review found unused i2c_software_sda_pin.")
        if allocate(options["reset_pin"], f"aux:{name}:reset_pin") != chip:
            raise GenerationError(f"{name}: TMC SPI review requires reset_pin on its I2C MCU.")

    for name, options in parsed.items():
        kind = name.split(" ", 1)[0]
        fields = set()
        if kind.startswith("stepper_") or kind in ("manual_stepper", "extruder_stepper") or re.fullmatch(r"extruder\d*", kind):
            fields.update(("step_pin", "dir_pin", "enable_pin", "endstop_pin"))
        if re.fullmatch(r"extruder\d*", kind) or kind in ("heater_bed", "heater_generic", "temperature_fan"):
            fields.update(("heater_pin", "sensor_pin"))
        if kind in ("fan", "fan_generic", "heater_fan", "controller_fan", "temperature_fan", "output_pin", "probe"):
            fields.add("pin")
        if kind in ("fan", "fan_generic", "heater_fan", "controller_fan", "temperature_fan"):
            fields.update(("enable_pin", "tachometer_pin"))
        if kind == "bltouch":
            fields.update(("sensor_pin", "control_pin"))
        for field in fields.intersection(options):
            if transports.get(name) == field:
                continue  # Sensor factories already allocated this field as CS.
            token = options[field]
            if aliases.resolve(token) in allocated:
                raise GenerationError(f"TMC SPI pin conflicts with [{name}] {field}: {token}")


def spi_transport_owners(parsed, *, require_declared_mcus=False):
    """Map each supported SPI section to its first loaded transport owner.

    Reservation callers may supply only selected sections and alias metadata;
    complete-config validation additionally requires declared MCU names.
    """
    try:
        sections = {name: options for name, options in parsed.items()
                    if name.startswith(("tmc2130 ", "tmc2660 ", "tmc5160 "))
                    or name.startswith("tmc2240 ") and "uart_pin" not in options}
        from core.profile_values import validate_tmc_spi_options
        validate_tmc_spi_options(sections)
        aliases = PinAliases(parsed)
        chips = {"mcu"} | {name[4:] for name in parsed if name.startswith("mcu ")}
        chains, spellings, owners = {}, {}, {}
        for name, options in sections.items():
            token = options.get("cs_pin", "").strip()
            parts = token.split(":", 1)
            chip, spelling = (part.strip() for part in parts) if len(parts) == 2 else ("mcu", token)
            if ((require_declared_mcus and chip not in chips) or not chip or not spelling
                    or any(c in chip for c in "^~!:") or "".join(chip.split()) != chip
                    or any(c in spelling for c in "^~!:")
                    or "".join(spelling.split()) != spelling):
                raise GenerationError(f"{name}: TMC SPI invalid cs_pin {token!r}.")
            # bus.MCU_SPI_from_config resets sharing for literal None. Such
            # transports have no CS; they are not a shared physical chain.
            if spelling == "None":
                owners[name] = name
                continue
            identity = aliases.resolve(f"{chip}:{spelling}")
            previous = spellings.setdefault(identity, spelling)
            if previous != spelling:
                raise GenerationError(f"TMC SPI: aliases {previous} and {spelling} use the same cs_pin.")
            length = int(options["chain_length"]) if "chain_length" in options else 1
            position = int(options.get("chain_position", "1"))
            existing = chains.get(identity)
            if existing is None:
                chains[identity] = (length, {position}, name)
                owners[name] = name
                continue
            old_length, positions, owner = existing
            if length == 1 or old_length == 1:
                raise GenerationError(f"{name}: TMC SPI cs_pin is already used by {owner} without a shared chain.")
            if length != old_length:
                raise GenerationError(f"{name}: TMC SPI chain_length must match {owner}.")
            if position in positions:
                raise GenerationError(f"{name}: TMC SPI duplicate chain_position {position}.")
            unused = _TRANSPORT_OPTIONS.intersection(options)
            if unused:
                raise GenerationError(
                    f"{name}: TMC SPI transport options belong to the first chain section ({owner}); "
                    f"unused options: {', '.join(sorted(unused))}.")
            positions.add(position)
            owners[name] = owner
        return owners
    except PinAliasError as exc:
        raise GenerationError(f"TMC SPI: {exc}") from exc
