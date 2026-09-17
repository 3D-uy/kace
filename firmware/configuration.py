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
    reference = comparable_actual.pop("CONFIG_CLOCK_REF_FREQ", None)
    if reference is not None and (expected_arch != "stm32" or reference not in
                                 {"8000000", "12000000", "16000000", "20000000", "24000000", "25000000", "1"}):
        raise FirmwareConfigurationError("Invalid STM32 reference clock.")
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


def klipper_config(config: Mapping[str, object], processor: str) -> dict[str, str]:
    """Translate the wizard's editing contract into writable Klipper choices.

    CONFIG_MCU, CLOCK_FREQ and FLASH_APPLICATION_ADDRESS are derived outputs,
    not selectors. Keep the editing API separate from the actual .config.
    Resolution is checked again after olddefconfig, including unavailable choices.
    """
    values = validate_firmware_configuration(config, processor=processor)
    arch = processor_architecture(processor)
    model = processor.lower()
    choices = {"CONFIG_LOW_LEVEL_OPTIONS": "y"}
    machine = {"stm32": "STM32", "lpc176x": "LPC176X", "rp2040": "RPXXXX",
               "avr": "AVR", "linux": "LINUX"}.get(arch)
    if machine is None:
        raise FirmwareConfigurationError(f"No verified Klipper selectors for {arch}")
    choices[f"CONFIG_MACH_{machine}"] = "y"
    if arch == "linux":
        return choices
    if arch == "stm32":
        reference = values.get("CONFIG_CLOCK_REF_FREQ")
        if reference is None:
            raise FirmwareConfigurationError("An explicit board reference clock is required for STM32.")
        clock = "INTERNAL" if reference == "1" else f"{int(reference) // 1000000}M"
        choices[f"CONFIG_STM32_CLOCK_REF_{clock}"] = "y"
        match = re.fullmatch(r"(stm32[a-z][0-9a-z]{3})(?:[a-z0-9]*)", model)
        if not match:
            raise FirmwareConfigurationError("An exact STM32 processor model is required")
        selector = match.group(1).upper()
        choices[f"CONFIG_MACH_{selector}"] = "y"
        if model == "stm32f103x6":
            choices["CONFIG_MACH_STM32F103x6"] = "y"
    elif arch == "avr":
        if not re.fullmatch(r"atmega\d+p?", model):
            raise FirmwareConfigurationError("An exact AVR processor model is required")
        choices[f"CONFIG_MACH_{model}"] = "y"
    else:
        if model not in {"lpc1768", "lpc1769", "rp2040"}:
            raise FirmwareConfigurationError("An exact processor model is required")
        choices[f"CONFIG_MACH_{model.upper()}"] = "y"
    if arch in {"stm32", "lpc176x"}:
        offset = int(values["CONFIG_FLASH_START"], 16)
        prefix = "STM32" if arch == "stm32" else "LPC"
        choices[f"CONFIG_{prefix}_FLASH_START_{offset:04X}"] = "y"
    elif arch == "rp2040":
        choices["CONFIG_RPXXXX_FLASH_START_0100"] = "y"
    comm = communication_from_config(values)
    transports = {
        "stm32": {"usb": "STM32_USB_PA11_PA12", "uart": "STM32_SERIAL_USART1", "can": "STM32_CANBUS_PA11_PA12"},
        "lpc176x": {"usb": "LPC_USB", "uart": "LPC_SERIAL_UART0_P03_P02", "can": "LPC_MMENU_CANBUS_P0_0_P0_1"},
        "rp2040": {"usb": "RPXXXX_USB", "uart": "RPXXXX_SERIAL_UART0_PINS_0_1", "can": "RPXXXX_CANBUS"},
        "avr": {"uart": "AVR_SERIAL_UART0", "usb": "AVR_SERIAL_UART0"},
    }
    transport = transports[arch].get(comm)
    if transport is None:
        raise FirmwareConfigurationError(f"No verified {comm} interface for {model}")
    choices[f"CONFIG_{transport}"] = "y"
    return choices


def board_reference_clock(board: str, processor: str) -> Optional[str]:
    """Exact upstream board facts; never infer a crystal from the MCU family."""
    if board == "generic-bigtreetech-octopus-v1.1.cfg":
        model = str(processor).lower()
        if model in {"stm32f446", "stm32f446xx"}:
            return "12000000"
        if model in {"stm32f429", "stm32f429xx"}:
            return "8000000"
        raise FirmwareConfigurationError("Octopus v1.1 requires an exact F446 or F429 processor.")
    return None


def render_config_diff(before: Mapping[str, object], after: Mapping[str, object]) -> str:
    return "".join(
        difflib.unified_diff(
            render_config(before).splitlines(keepends=True),
            render_config(after).splitlines(keepends=True),
            fromfile="derived/.config",
            tofile="planned/.config",
        )
    )
