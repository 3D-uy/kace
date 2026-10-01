"""Read MCU pin reservations from the exact, identity-bound firmware bytes."""
import hashlib
import json
from pathlib import Path
import re
from collections.abc import Mapping
import zlib

from firmware.identity import FirmwareIdentityError, firmware_version_matches

_MAX_ARTIFACT = 32 * 1024 * 1024
_MAX_DICTIONARY = 2 * 1024 * 1024
_MAX_BUS_ENUMERATIONS = 65536


def read_reserved_pins(path, identity, *, buses=()):
    """Return physical pin -> reservation for one MCU, never an inferred map.

    A missing dictionary is an error, distinct from a verified empty map.
    Identity/hash checks bind this read to an existing build; this function does
    not prove which firmware is currently running on the physical MCU.
    ``buses`` contains ("spi_bus" or "i2c_bus", name or None) selections for
    this MCU only. None selects Klipper's firmware-defined default. The caller
    must project active hardware consumers; software buses must not be included.
    """
    dictionary = read_identify_dictionary(path, identity)
    reserved = {}
    for name, value in dictionary["config"].items():
        if not name.startswith("RESERVE_PINS_"):
            continue
        reason = name[len("RESERVE_PINS_"):]
        if not reason or not isinstance(value, str) or not value:
            raise FirmwareIdentityError(f"invalid firmware reservation {name}")
        _reserve_pins(reserved, value, reason)
    _reserve_selected_buses(reserved, dictionary, buses)
    return reserved


def read_identify_dictionary(path, identity):
    """Read exactly one version/hash-bound identify dictionary from native bytes."""
    if hasattr(identity, "to_dict"):
        identity = identity.to_dict()
    if not isinstance(identity, Mapping):
        raise FirmwareIdentityError("firmware identity is required for pin reservations")
    expected = identity.get("reported_version", "")
    digest, size = identity.get("artifact_sha256"), identity.get("artifact_size")
    if (not isinstance(expected, str) or not re.fullmatch(r"kace-b1-[0-9a-f]{32}", expected)
            or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or type(size) is not int or not 0 < size <= _MAX_ARTIFACT):
        raise FirmwareIdentityError("invalid firmware identity for pin reservations")
    try:
        with Path(path).expanduser().open("rb") as source:
            content = source.read(size + 1)
    except (OSError, TypeError, ValueError) as exc:
        raise FirmwareIdentityError(f"cannot read firmware pin reservations: {exc}") from exc
    if len(content) != size or hashlib.sha256(content).hexdigest() != digest:
        raise FirmwareIdentityError("firmware bytes changed before reading pin reservations")

    # Reuse the deployment decoder; never scan HEX text or UF2 framing as BIN.
    from firmware.boards.kconfig import _decode_ihex_payload, _decode_uf2_payload
    fmt = identity.get("artifact_format")
    if fmt == "BIN":
        payload = content
    elif fmt == "UF2":
        payload = _decode_uf2_payload(content)
    elif fmt == "IHEX":
        payload = _decode_ihex_payload(content)
    else:
        raise FirmwareIdentityError("unsupported firmware format for pin reservations")
    if payload is None:
        raise FirmwareIdentityError("invalid firmware container for pin reservations")

    dictionaries = []
    # Klipper buildcommands emits zlib-compressed JSON, not a plain marker.
    for match in re.finditer(b"\x78", payload):
        try:
            decoder = zlib.decompressobj()
            decoded = decoder.decompress(payload[match.start():], _MAX_DICTIONARY + 1)
            if not decoder.eof or len(decoded) > _MAX_DICTIONARY:
                continue
            dictionary = json.loads(decoded.decode("utf-8"))
        except (zlib.error, UnicodeDecodeError, ValueError):
            continue
        if (isinstance(dictionary, dict)
                and firmware_version_matches(dictionary.get("version"), expected)):
            dictionaries.append(dictionary)
    if len(dictionaries) != 1:
        raise FirmwareIdentityError("firmware must contain exactly one matching identify dictionary")
    constants = dictionaries[0].get("config")
    if not isinstance(constants, dict) or not isinstance(constants.get("MCU"), str):
        raise FirmwareIdentityError("firmware identify dictionary has no MCU constants")
    return dictionaries[0]


def _reserve_pins(reserved, value, reason):
    if not isinstance(value, str) or not value:
        raise FirmwareIdentityError(f"invalid firmware pin reservation for {reason}")
    for pin in value.split(","):
        if not re.fullmatch(r"[A-Za-z0-9_.]+", pin):
            raise FirmwareIdentityError(f"invalid firmware reserved pin {pin!r}")
        if pin in reserved and reserved[pin] != reason:
            raise FirmwareIdentityError(f"conflicting firmware reservations for {pin}")
        reserved[pin] = reason


def _expand_bus_enumeration(raw):
    """Expand identify ranges in insertion order, as MessageParser does."""
    if not isinstance(raw, dict):
        raise FirmwareIdentityError("invalid firmware bus enumeration")
    expanded = {}
    total = 0
    for name, value in raw.items():
        if type(value) is int:
            start, count = value, 1
            names = [name]
        else:
            if (not isinstance(value, list) or len(value) != 2
                    or any(type(item) is not int for item in value)
                    or not 0 <= value[1] <= _MAX_BUS_ENUMERATIONS):
                raise FirmwareIdentityError("invalid firmware bus enumeration range")
            start, count = value
            root = name.rstrip("0123456789")
            first = int(name[len(root):]) if root != name else 0
            names = (root + str(first + offset) for offset in range(count))
        total += count
        if total > _MAX_BUS_ENUMERATIONS:
            raise FirmwareIdentityError("firmware bus enumeration exceeds limit")
        for offset, enum_name in enumerate(names):
            expanded[enum_name] = start + offset
    return expanded


def _reserve_selected_buses(reserved, dictionary, buses):
    """Mirror extras.bus.resolve_bus_name for explicit per-MCU selections."""
    for request in buses:
        if (not isinstance(request, (tuple, list)) or len(request) != 2
                or request[0] not in ("spi_bus", "i2c_bus")
                or (request[1] is not None and not isinstance(request[1], str))):
            raise FirmwareIdentityError("invalid firmware bus selection")
        param, selected = request
        enumerations = dictionary.get("enumerations", {})
        if not isinstance(enumerations, dict):
            raise FirmwareIdentityError("invalid firmware bus enumerations")
        # A present dedicated enumeration wins even when empty. A missing one
        # falls back to the older shared 'bus' enumeration, exactly as upstream.
        if param in enumerations:
            raw = enumerations[param]
        elif "bus" in enumerations:
            raw = enumerations["bus"]
        else:
            # Upstream returns before consulting BUS_PINS in this legacy path.
            continue
        enums = _expand_bus_enumeration(raw)
        if selected is None:
            reverse = {value: name for name, value in enums.items()}
            if 0 not in reverse:
                raise FirmwareIdentityError(f"must specify {param}: firmware has no default bus")
            selected = reverse[0]
        if selected not in enums:
            raise FirmwareIdentityError(f"unknown firmware {param} {selected!r}")
        pins = dictionary["config"].get(f"BUS_PINS_{selected}")
        if pins is not None:
            _reserve_pins(reserved, pins, selected)
