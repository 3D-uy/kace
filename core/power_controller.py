"""Moonraker-backed printer power control shared by KACE workflows and Studio.

The configured device name is persisted by bootstrap. Runtime state always
comes from Moonraker's Power API; this module never accesses GPIO directly.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
import time

from core.moonraker import DEFAULT_PORT, get_power_devices, set_power_device
from core.power_config import PowerConfigError, load_power_config as load_versioned_power_config


DEFAULT_CONFIG_PATH = "~/.config/kace/power.json"
VALID_STATES = frozenset(("on", "off", "init", "error"))
_DEVICE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class PowerControllerError(RuntimeError):
    """Raised when Moonraker cannot provide a safe, verified power result."""


class PrinterPowerState(str, Enum):
    ON = "ON"
    OFF = "OFF"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ManualPowerResult:
    """One operator-initiated observation or relay command result."""

    state: PrinterPowerState
    timestamp: str
    detail: str
    requested_action: str = ""
    confirmed: bool = False

    @property
    def display(self) -> str:
        return f"Printer power: {self.state.value}"


def _power_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


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


class ManualRelayControl:
    """Operator-only façade over the existing Moonraker controller.

    Merely constructing or refreshing this object cannot switch the relay.
    The two mutating methods are deliberately named ``request_*`` and are
    intended to be called only from direct UI actions.
    """

    def __init__(self, controller: MoonrakerPowerController):
        if not isinstance(controller, MoonrakerPowerController):
            raise TypeError("manual relay control requires MoonrakerPowerController")
        self.controller = controller

    @staticmethod
    def _state(value: str) -> PrinterPowerState:
        return {
            "on": PrinterPowerState.ON,
            "off": PrinterPowerState.OFF,
        }.get(str(value or "").lower(), PrinterPowerState.UNKNOWN)

    def refresh(self) -> ManualPowerResult:
        try:
            raw = self.controller.get_status()
            state = self._state(raw)
            detail = (
                f"Moonraker confirmed {raw}"
                if state is not PrinterPowerState.UNKNOWN
                else f"Moonraker reported non-terminal state {raw!r}"
            )
        except (PowerControllerError, OSError, TimeoutError) as exc:
            state = PrinterPowerState.UNKNOWN
            detail = str(exc)
        return ManualPowerResult(state, _power_timestamp(), detail)

    def _request(self, action: str, timeout: float) -> ManualPowerResult:
        expected = PrinterPowerState.ON if action == "ON" else PrinterPowerState.OFF
        command = self.controller.power_on if action == "ON" else self.controller.power_off
        try:
            command(timeout=timeout)
            # Do not trust command completion alone: perform a fresh read and
            # report success only when Moonraker confirms the requested state.
            observed = self.controller.get_status()
            state = self._state(observed)
            confirmed = state is expected
            detail = (
                f"Moonraker confirmed relay {action}"
                if confirmed
                else f"relay command returned but Moonraker reports {observed!r}"
            )
        except (PowerControllerError, OSError, TimeoutError) as exc:
            state = PrinterPowerState.UNKNOWN
            confirmed = False
            detail = str(exc)
        return ManualPowerResult(
            state, _power_timestamp(), detail,
            requested_action=action, confirmed=confirmed,
        )

    def request_on(self, timeout: float = 30.0) -> ManualPowerResult:
        return self._request("ON", timeout)

    def request_off(self, timeout: float = 30.0) -> ManualPowerResult:
        return self._request("OFF", timeout)


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


def configured_manual_relay_control(**kwargs):
    """Return the operator façade for the already configured controller."""
    controller = configured_power_controller(**kwargs)
    return ManualRelayControl(controller) if controller is not None else None
