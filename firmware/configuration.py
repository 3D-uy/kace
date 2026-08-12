"""Typed editing and validation contract for Klipper firmware configuration."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Optional


_HEX_OFFSET_RE = re.compile(r"^0[xX][0-9a-fA-F]+$")
_COMMUNICATION_KEYS = {
    "usb": "CONFIG_USB",
    "uart": "CONFIG_SERIAL",
    "can": "CONFIG_CANBUS",
    "spi": "CONFIG_SPI",
}


class FirmwareConfigurationError(ValueError):
    """Raised when a firmware configuration is internally inconsistent."""


class BootloaderOffsetKind(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NO_BOOTLOADER = "NO_BOOTLOADER"
    ADDRESS = "ADDRESS"


@dataclass(frozen=True)
class BootloaderOffset:
    """Distinguish no bootloader from an architecture without flash offset."""

    kind: BootloaderOffsetKind
    address: Optional[int] = None

    def __post_init__(self) -> None:
        if self.kind is BootloaderOffsetKind.NOT_APPLICABLE and self.address is not None:
            raise FirmwareConfigurationError("A non-applicable offset cannot have an address.")
        if self.kind is BootloaderOffsetKind.NO_BOOTLOADER and self.address != 0:
            raise FirmwareConfigurationError("No bootloader must use address 0.")
        if self.kind is BootloaderOffsetKind.ADDRESS and (
            self.address is None or self.address <= 0
        ):
            raise FirmwareConfigurationError("A bootloader address must be greater than zero.")

    @classmethod
    def not_applicable(cls) -> "BootloaderOffset":
        return cls(BootloaderOffsetKind.NOT_APPLICABLE)

    @classmethod
    def no_bootloader(cls) -> "BootloaderOffset":
        return cls(BootloaderOffsetKind.NO_BOOTLOADER, 0)

    @classmethod
    def from_value(cls, value: object) -> "BootloaderOffset":
        if isinstance(value, cls):
            return value
        text = str(value or "").strip()
        if not _HEX_OFFSET_RE.fullmatch(text):
            raise FirmwareConfigurationError(
                f"Bootloader offset {text!r} must be hexadecimal (for example 0x8000)."
            )
        address = int(text, 16)
        if address == 0:
            return cls.no_bootloader()
        return cls(BootloaderOffsetKind.ADDRESS, address)

    @property
    def kconfig_value(self) -> Optional[str]:
        if self.kind is BootloaderOffsetKind.NOT_APPLICABLE:
            return None
        return f"0x{int(self.address or 0):x}"


def resolve_processor_profile(processor: object) -> dict:
    """Return the first-match firmware profile for a processor input."""
    from firmware.derivation import _get_fw_db

    normalized = str(processor or "").strip().lower()
    for entry in _get_fw_db():
        if str(entry.get("pattern", "")).lower() in normalized:
            return dict(entry)
    raise FirmwareConfigurationError(f"Unknown MCU processor {normalized!r}.")


def processor_architecture(processor: object) -> str:
    return str(resolve_processor_profile(processor).get("arch", "")).lower()


def validate_processor_for_architecture(processor: object, architecture: object) -> str:
    normalized = str(processor or "").strip().lower()
    expected = str(architecture or "").strip().lower()
    actual = processor_architecture(normalized)
    if actual != expected:
        raise FirmwareConfigurationError(
            f"Processor {normalized!r} belongs to {actual!r}, not {expected!r}."
        )
    return normalized


def bootloader_offset_from_config(
    config: Mapping[str, object], processor: object
) -> BootloaderOffset:
    profile = resolve_processor_profile(processor)
    if "flash_start" not in profile:
        if "CONFIG_FLASH_START" in config:
            raise FirmwareConfigurationError(
                f"{profile['arch']} does not accept CONFIG_FLASH_START."
            )
        return BootloaderOffset.not_applicable()
    if "CONFIG_FLASH_START" not in config:
        raise FirmwareConfigurationError(
            "Bootloader offset is required; use 0x0 to represent no bootloader."
        )
    return BootloaderOffset.from_value(config["CONFIG_FLASH_START"])


def communication_from_config(config: Mapping[str, object], *, linux: bool = False) -> Optional[str]:
    enabled = [
        name for name, key in _COMMUNICATION_KEYS.items()
        if str(config.get(key, "n")).lower() == "y"
    ]
    if linux:
        if enabled:
            raise FirmwareConfigurationError("Linux MCU configuration cannot enable MCU transport flags.")
        return None
    if len(enabled) != 1:
        raise FirmwareConfigurationError(
            "Exactly one firmware communication interface must be enabled."
        )
    return enabled[0]


def validate_firmware_configuration(
    config: Mapping[str, object], *, processor: object
) -> dict[str, str]:
    """Validate target-dependent flags as one coherent configuration."""
    normalized = {str(key): str(value) for key, value in config.items()}
    profile = resolve_processor_profile(processor)
    expected_arch = str(profile.get("arch", "")).lower()
    actual_arch = normalized.get("CONFIG_MCU", "").strip('"').lower()
    if actual_arch != expected_arch:
        raise FirmwareConfigurationError(
            f"CONFIG_MCU={actual_arch!r} conflicts with processor architecture {expected_arch!r}."
        )

    linux = bool(profile.get("early_return"))
    communication = communication_from_config(normalized, linux=linux)
    offset = bootloader_offset_from_config(normalized, processor)

    from firmware.derivation import derive_config

    expected = derive_config(
        str(processor).strip().lower(),
        communication,
        flash_start=offset,
    )
    actual_clock = normalized.get("CONFIG_CLOCK_FREQ")
    expected_clock = expected.get("CONFIG_CLOCK_FREQ")
    if expected_clock is None and actual_clock is not None:
        raise FirmwareConfigurationError(
            f"CONFIG_CLOCK_FREQ is not valid for processor {processor!r}."
        )
    if expected_clock is not None:
        if actual_clock is None or not actual_clock.isdigit() or int(actual_clock) <= 0:
            raise FirmwareConfigurationError(
                "CONFIG_CLOCK_FREQ must be a positive integer for this processor."
            )

    comparable_actual = dict(normalized)
    comparable_expected = dict(expected)
    comparable_actual.pop("CONFIG_CLOCK_FREQ", None)
    comparable_expected.pop("CONFIG_CLOCK_FREQ", None)
    if comparable_actual != comparable_expected:
        stale = sorted(set(comparable_actual) - set(comparable_expected))
        missing = sorted(set(comparable_expected) - set(comparable_actual))
        changed = sorted(
            key for key in set(comparable_actual) & set(comparable_expected)
            if comparable_actual[key] != comparable_expected[key]
        )
        details = []
        if stale:
            details.append("stale fields: " + ", ".join(stale))
        if missing:
            details.append("missing fields: " + ", ".join(missing))
        if changed:
            details.append("conflicting fields: " + ", ".join(changed))
        raise FirmwareConfigurationError(
            "Firmware configuration is not a complete derivation"
            + (": " + "; ".join(details) if details else ".")
        )
    return normalized


def render_config(config: Mapping[str, object]) -> str:
    return "".join(f"{key}={config[key]}\n" for key in sorted(config))


def render_config_diff(before: Mapping[str, object], after: Mapping[str, object]) -> str:
    return "".join(
        difflib.unified_diff(
            render_config(before).splitlines(keepends=True),
            render_config(after).splitlines(keepends=True),
            fromfile="derived/.config",
            tofile="planned/.config",
        )
    )
