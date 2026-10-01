"""Validate UART topology before rendering or publishing, without driver IO.

Contract: pinned Klipper extras/tmc_uart.py and pins.py. Callers expand includes;
this module does not prove electrical wiring or implicit firmware reservations.
"""
import re

from core.exceptions import GenerationError
from core.pin_validator import PinAliases, PinAliasError, _read_pin_config


def validate_uart_config(content):
    """Check all UART models/targets and explicit consumers in effective CFG."""
    if not re.search(r"(?m)^\s*\[tmc(?:220[89]|2240)\s+", content):
        return
    try:
        parsed, _ = _read_pin_config(content)
        sections = {name: options for name, options in parsed.items()
                    if name.startswith(("tmc2208 ", "tmc2209 "))
                    or name.startswith("tmc2240 ") and "uart_pin" in options}
        _validate_uart_sections(parsed, sections, check_consumers=True)
    except PinAliasError as exc:
        raise GenerationError(f"TMC UART: {exc}") from exc


def validate_uart_sections(parsed, sections):
    if not sections:
        return
    try:
        _validate_uart_sections(parsed, sections)
    except PinAliasError as exc:
        raise GenerationError(f"TMC UART: {exc}") from exc


def _validate_uart_sections(parsed, sections, *, check_consumers=False):
    aliases = PinAliases(parsed)
    chips = {"mcu"} | {name[4:] for name in parsed if name.startswith("mcu ")}
    allocated, buses, spellings = {}, {}, {}

    def pin(token, role, *, allocate=True):
        value = token.strip()
        polarity = 0
        if role == "rx" and value[:1] in ("^", "~"):
            polarity = 1 if value[0] == "^" else -1
            value = value[1:].strip()
        if role == "select" and value.startswith("!"):
            polarity = 1
            value = value[1:].strip()
        parts = value.split(":", 1)
        chip, spelling = (part.strip() for part in parts) if len(parts) == 2 else ("mcu", value)
        if (chip not in chips or not spelling or any(c in spelling for c in "^~!:")
                or "".join(spelling.split()) != spelling):
            raise GenerationError(f"TMC UART: invalid {role} pin {token!r}.")
        identity = aliases.resolve(f"{chip}:{spelling}")
        previous = spellings.setdefault(identity, spelling)
        if previous != spelling:
            # Klipper resolves aliases after allocating consumers and rejects
            # multiple spellings of a physical pin, even for distinct addresses.
            raise GenerationError(f"TMC UART: aliases {previous} and {spelling} use the same pin.")
        if allocate:
            usage = role, polarity
            if identity in allocated and (role == "select" or allocated[identity] != usage):
                raise GenerationError(f"TMC UART: shared pin {token} has incompatible use or polarity.")
            allocated[identity] = usage
        return identity, polarity

    for name, options in sections.items():
        if name.startswith("tmc2240 "):
            unused = {key for key in options if key.startswith("spi_")
                      or key in ("cs_pin", "chain_length", "chain_position")}
            if unused:
                raise GenerationError(f"{name}: TMC UART unused SPI options: {', '.join(sorted(unused))}.")
        if not options.get("uart_pin"):
            raise GenerationError(f"{name}: TMC UART requires uart_pin.")
        try:
            address = int(options.get("uart_address", "0"))
        except (TypeError, ValueError) as exc:
            raise GenerationError(f"{name}: TMC UART has invalid uart_address.") from exc
        maximum = 7 if name.startswith("tmc2240 ") else (3 if name.startswith("tmc2209 ") else 0)
        if not 0 <= address <= maximum:
            raise GenerationError(f"{name}: TMC UART uart_address out of range.")
        rx, _ = pin(options["uart_pin"], "rx")
        tx = pin(options["tx_pin"], "tx")[0] if "tx_pin" in options else rx
        if rx[0] != tx[0]:
            raise GenerationError(f"{name}: TMC UART RX and TX must use the same MCU.")
        existing = buses.get(rx)
        select_tokens = options.get("select_pins")
        selectors = None
        if select_tokens is not None:
            selectors = [pin(token, "select", allocate=existing is None)
                         for token in select_tokens.split(",")]
            if any(identity[0] != rx[0] for identity, _ in selectors):
                raise GenerationError(f"{name}: TMC UART mux pins must use the same MCU.")
        layout = None if selectors is None else tuple(identity for identity, _ in selectors)
        instance = None if selectors is None else tuple(not invert for _, invert in selectors)
        if existing is None:
            existing = buses[rx] = {"tx": tx, "selectors": layout, "instances": set()}
        elif existing["tx"] != tx or existing["selectors"] != layout:
            raise GenerationError(f"{name}: shared UART requires identical RX/TX and ordered mux pins.")
        key = instance, address
        if key in existing["instances"]:
            raise GenerationError(f"{name}: shared UART requires unique address or select_pins polarity.")
        existing["instances"].add(key)

    if check_consumers:
        for name, options in parsed.items():
            if (name in ("board_pins", "duplicate_pin_override")
                    or name.startswith(("board_pins ", "gcode_macro ", "delayed_gcode "))):
                continue
            for field, value in options.items():
                if name in sections and field in ("uart_pin", "tx_pin", "select_pins"):
                    continue
                if not (field == "pin" or field.endswith("_pin")
                        or field in ("pins", "select_pins", "encoder_pins")):
                    continue
                for token in re.split(r"[,\s]+", value.strip()):
                    if token and aliases.resolve(token) in allocated:
                        raise GenerationError(f"TMC UART pin conflicts with [{name}] {field}: {token}")
