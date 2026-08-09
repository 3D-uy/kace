"""Moonraker-backed printer power control shared by KACE workflows and Studio.

The configured device name is persisted by bootstrap. Runtime state always
comes from Moonraker's Power API; this module never accesses GPIO directly.
"""

import re
import time

from core.moonraker import DEFAULT_PORT, get_power_devices, set_power_device
from core.power_config import PowerConfigError, load_power_config as load_versioned_power_config


DEFAULT_CONFIG_PATH = "~/.config/kace/power.json"
VALID_STATES = frozenset(("on", "off", "init", "error"))
_DEVICE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class PowerControllerError(RuntimeError):
    """Raised when Moonraker cannot provide a safe, verified power result."""


def load_power_config(path: str = DEFAULT_CONFIG_PATH) -> dict:
    """Load bootstrap's verified power identity and full desired-state schema."""
    try:
        config = load_versioned_power_config(path)
    except PowerConfigError as exc:
        raise PowerControllerError(f"could not read power configuration: {exc}") from exc
    return {
        "schema": config.schema,
        "revision": config.revision,
        "enabled": config.enabled,
        "device": config.device if config.enabled else None,
        "pin": config.pin if config.enabled else None,
        "active_low": config.active_low,
        "initial_state": config.initial_state,
        "restart_klipper_when_powered": config.restart_klipper_when_powered,
        "off_when_shutdown": config.off_when_shutdown,
        "legacy": config.legacy,
    }


class MoonrakerPowerController:
    """Single internal API for one configured Moonraker power device."""

    def __init__(
        self,
        device: str,
        host: str = "localhost",
        port: int = DEFAULT_PORT,
        api_key: str = None,
        poll_interval: float = 0.5,
    ):
        if not isinstance(device, str) or not _DEVICE_RE.fullmatch(device):
            raise ValueError("POWER_DEVICE is missing or invalid")
        self.device = device
        self.host = host
        self.port = int(port)
        self.api_key = api_key
        self.poll_interval = poll_interval

    def get_status(self) -> str:
        """Return the real Moonraker state: on, off, init, or error."""
        ok, detail, devices = get_power_devices(
            self.host, self.port, api_key=self.api_key
        )
        if not ok:
            raise PowerControllerError(f"Moonraker Power API unavailable: {detail}")
        for item in devices:
            if isinstance(item, dict) and item.get("device") == self.device:
                status = str(item.get("status", "error")).lower()
                return status if status in VALID_STATES else "error"
        raise PowerControllerError(
            f"POWER_DEVICE '{self.device}' is not configured in Moonraker"
        )

    def wait_until_ready(self, timeout: float = 30.0) -> str:
        """Wait until the device leaves init; fail immediately on error."""
        deadline = time.monotonic() + timeout
        while True:
            status = self.get_status()
            if status == "error":
                raise PowerControllerError(
                    f"Moonraker power device '{self.device}' entered error state"
                )
            if status != "init":
                return status
            if time.monotonic() >= deadline:
                raise PowerControllerError(
                    f"timed out waiting for power device '{self.device}' to leave init"
                )
            time.sleep(self.poll_interval)

    def _set_and_confirm(self, action: str, timeout: float) -> str:
        self.wait_until_ready(timeout=timeout)
        ok, detail = set_power_device(
            self.host, self.port, self.device, action, api_key=self.api_key
        )
        if not ok:
            raise PowerControllerError(
                f"could not switch power device '{self.device}' {action}: {detail}"
            )
        deadline = time.monotonic() + timeout
        while True:
            status = self.get_status()
            if status == action:
                return status
            if status == "error":
                raise PowerControllerError(
                    f"Moonraker power device '{self.device}' entered error state"
                )
            if time.monotonic() >= deadline:
                raise PowerControllerError(
                    f"power device '{self.device}' did not reach {action}"
                )
            time.sleep(self.poll_interval)

    def power_on(self, timeout: float = 30.0) -> str:
        """Request ON through Moonraker and verify the final state."""
        return self._set_and_confirm("on", timeout)

    def power_off(self, timeout: float = 30.0) -> str:
        """Request OFF through Moonraker and verify the final state."""
        return self._set_and_confirm("off", timeout)


def configured_power_controller(
    host: str = "localhost",
    port: int = DEFAULT_PORT,
    api_key: str = None,
    config_path: str = DEFAULT_CONFIG_PATH,
):
    """Return the configured controller, or ``None`` when relay control is off."""
    config = load_power_config(config_path)
    if not config["enabled"]:
        return None
    return MoonrakerPowerController(
        config["device"], host=host, port=port, api_key=api_key
    )
