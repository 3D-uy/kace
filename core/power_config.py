"""Versioned desired-state contract for KACE-managed Moonraker power.

``power.json`` records configuration that has already been reconciled and
verified through Moonraker. Runtime ON/OFF state remains owned by Moonraker's
Power API and is deliberately absent from this schema.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from typing import Mapping, Optional


POWER_SCHEMA = "kace-power/v1"
LEGACY_SCHEMA = 1
_DEVICE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_PIN_RE = re.compile(r"^gpiochip[0-9]+/gpio[0-9]{1,3}$")


class PowerConfigError(ValueError):
    """Raised when desired or persisted power configuration is unsafe."""


@dataclass(frozen=True)
class PowerConfig:
    schema: str = POWER_SCHEMA
    revision: int = 1
    enabled: bool = False
    device: Optional[str] = None
    pin: Optional[str] = None
    active_low: bool = False
    initial_state: str = "off"
    restart_klipper_when_powered: bool = False
    off_when_shutdown: bool = True
    legacy: bool = False

    def validated(self, *, allow_legacy: bool = False) -> "PowerConfig":
        if self.legacy:
            if not allow_legacy:
                raise PowerConfigError("legacy power configuration must be reconciled before use")
            if self.enabled and not _valid_device(self.device):
                raise PowerConfigError("legacy POWER_DEVICE is missing or invalid")
            return self
        if self.schema != POWER_SCHEMA:
            raise PowerConfigError(f"unsupported power schema: {self.schema!r}")
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 1:
            raise PowerConfigError("power revision must be a positive integer")
        if self.initial_state not in ("on", "off"):
            raise PowerConfigError("initial_state must be 'on' or 'off'")
        for field_name in (
            "enabled", "active_low", "restart_klipper_when_powered", "off_when_shutdown"
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise PowerConfigError(f"{field_name} must be a boolean")
        if self.enabled:
            if not _valid_device(self.device):
                raise PowerConfigError("POWER_DEVICE is missing or invalid")
            if not isinstance(self.pin, str) or not _PIN_RE.fullmatch(self.pin):
                raise PowerConfigError("pin must use gpiochipN/gpioN syntax")
        elif self.device is not None or self.pin is not None:
            raise PowerConfigError("disabled power configuration must not name a device or pin")
        return self

    def to_mapping(self) -> dict:
        data = asdict(self)
        data.pop("legacy", None)
        return data

    def moonraker_pin(self) -> str:
        if not self.enabled or self.pin is None:
            raise PowerConfigError("disabled power configuration has no Moonraker pin")
        return f"!{self.pin}" if self.active_low else self.pin


def _valid_device(value: object) -> bool:
    return isinstance(value, str) and _DEVICE_RE.fullmatch(value) is not None


def power_config_from_mapping(data: Mapping[str, object], *, allow_legacy: bool = True) -> PowerConfig:
    if not isinstance(data, Mapping):
        raise PowerConfigError("KACE power configuration must be a JSON object")
    if data.get("schema") == LEGACY_SCHEMA:
        if not isinstance(data.get("enabled"), bool):
            raise PowerConfigError("legacy enabled must be a boolean")
        enabled = data["enabled"]
        config = PowerConfig(
            schema=str(LEGACY_SCHEMA),
            revision=0,
            enabled=enabled,
            device=data.get("device") if enabled else None,
            pin=None,
            legacy=True,
        )
        return config.validated(allow_legacy=allow_legacy)
    required = {
        "schema", "revision", "enabled", "device", "pin", "active_low",
        "initial_state", "restart_klipper_when_powered", "off_when_shutdown",
    }
    missing = sorted(required - set(data))
    if missing:
        raise PowerConfigError("power configuration is missing: " + ", ".join(missing))
    config = PowerConfig(
        schema=data.get("schema"),
        revision=data.get("revision"),
        enabled=data.get("enabled"),
        device=data.get("device"),
        pin=data.get("pin"),
        active_low=data.get("active_low"),
        initial_state=data.get("initial_state"),
        restart_klipper_when_powered=data.get("restart_klipper_when_powered"),
        off_when_shutdown=data.get("off_when_shutdown"),
    )
    return config.validated()


def load_power_config(path: str | os.PathLike, *, missing_disabled: bool = True) -> PowerConfig:
    try:
        with open(os.path.expanduser(os.fspath(path)), "r", encoding="utf-8") as source:
            data = json.load(source)
    except FileNotFoundError:
        if missing_disabled:
            return PowerConfig()
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise PowerConfigError(f"could not read power configuration: {exc}") from exc
    return power_config_from_mapping(data)
