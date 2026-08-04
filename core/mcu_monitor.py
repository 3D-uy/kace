"""Physical MCU presence monitoring for SD-card firmware workflows.

The monitor is armed before the user is asked to power-cycle the printer. On
Linux it consumes udev ``tty`` add/remove events, preserving the physical
identity across changes such as ``/dev/ttyACM0`` becoming ``/dev/ttyACM1``.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import shutil
import subprocess
import threading
import time
from typing import Callable, Optional


class McuMonitorError(RuntimeError):
    """Base error for physical MCU monitoring."""


class McuMonitorUnavailable(McuMonitorError):
    """Raised when a safe physical-device monitor cannot be started."""


class McuIdentityMismatch(McuMonitorError):
    """Raised when a different device appears in the monitored physical slot."""


class McuMonitorCancelled(McuMonitorError):
    """Raised when the user cancels an indefinite device wait."""


@dataclass(frozen=True)
class McuIdentity:
    configured_path: str
    device_node: str
    devpath: str = ""
    serial: str = ""
    physical_path: str = ""
    vendor_id: str = ""
    model_id: str = ""

    def matches(self, other: "McuIdentity") -> bool:
        """Return whether ``other`` is the same physical controller."""
        if self.serial and other.serial:
            return (
                self.serial == other.serial
                and (not self.vendor_id or not other.vendor_id or self.vendor_id == other.vendor_id)
                and (not self.model_id or not other.model_id or self.model_id == other.model_id)
            )
        if self.physical_path and other.physical_path:
            return self.physical_path == other.physical_path
        if self.devpath and other.devpath:
            return self.devpath == other.devpath
        return self.device_node == other.device_node

    def occupies_same_slot(self, other: "McuIdentity") -> bool:
        """Return whether a candidate occupies the monitored USB connection."""
        if self.physical_path and other.physical_path:
            return self.physical_path == other.physical_path
        if self.devpath and other.devpath:
            return self.devpath == other.devpath
        return self.device_node == other.device_node


class McuIdentityReader:
    """Read stable udev identity properties for one serial device."""

    _PROPERTY_KEYS = {
        "DEVNAME",
        "DEVPATH",
        "ID_SERIAL_SHORT",
        "ID_PATH",
        "ID_VENDOR_ID",
        "ID_MODEL_ID",
    }

    def read(self, configured_path: str) -> Optional[McuIdentity]:
        path = os.path.expanduser(configured_path or "")
        if not path or not os.path.exists(path):
            return None
        device_node = os.path.realpath(path)
        properties = self._udevadm_properties(device_node)
        return self.from_properties(properties, configured_path=path, device_node=device_node)

    def from_properties(
        self,
        properties: dict,
        *,
        configured_path: str = "",
        device_node: str = "",
    ) -> McuIdentity:
        node = properties.get("DEVNAME") or device_node
        return McuIdentity(
            configured_path=configured_path or node,
            device_node=node,
            devpath=properties.get("DEVPATH", ""),
            serial=properties.get("ID_SERIAL_SHORT", ""),
            physical_path=properties.get("ID_PATH", ""),
            vendor_id=properties.get("ID_VENDOR_ID", ""),
            model_id=properties.get("ID_MODEL_ID", ""),
        )

    def _udevadm_properties(self, device_node: str) -> dict:
        if not shutil.which("udevadm"):
            raise McuMonitorUnavailable("udevadm is required for safe MCU identity monitoring")
        try:
            result = subprocess.run(
                ["udevadm", "info", "--query=property", "--name", device_node],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise McuMonitorUnavailable(f"could not query MCU identity: {exc}") from exc
        if result.returncode != 0:
            raise McuMonitorUnavailable(
                f"udevadm could not identify {device_node}: {result.stderr.strip()}"
            )
        properties = {}
        for line in result.stdout.splitlines():
            key, separator, value = line.partition("=")
            if separator and key in self._PROPERTY_KEYS:
                properties[key] = value
        properties.setdefault("DEVNAME", device_node)
        return properties


class UdevTtyEventSource:
    """Stream Linux udev tty events on a background thread."""

    def __init__(self):
        self._process = None
        self._thread = None
        self._ready = threading.Event()

    def start(self, callback: Callable[[dict], None]) -> None:
        if not shutil.which("udevadm"):
            raise McuMonitorUnavailable("udevadm is required for MCU event monitoring")
        try:
            self._process = subprocess.Popen(
                ["udevadm", "monitor", "--udev", "--subsystem-match=tty", "--property"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            raise McuMonitorUnavailable(f"could not start udev monitor: {exc}") from exc

        self._thread = threading.Thread(
            target=self._read_events,
            args=(callback,),
            name="kace-mcu-udev-monitor",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(3):
            self.stop()
            raise McuMonitorUnavailable("udev monitor did not become ready")

    def _read_events(self, callback: Callable[[dict], None]) -> None:
        properties = {}
        assert self._process is not None and self._process.stdout is not None
        for raw_line in self._process.stdout:
            line = raw_line.strip()
            # udevadm prints a human-readable preamble before subscribing.
            # Treat that line as the readiness handshake so the caller does
            # not prompt the user until event capture is live.
            if line and "monitor will print" in line.lower():
                self._ready.set()
                continue
            if not line:
                if properties.get("ACTION"):
                    callback(dict(properties))
                properties.clear()
                continue
            key, separator, value = line.partition("=")
            if separator:
                self._ready.set()
                properties[key] = value
        if properties.get("ACTION"):
            callback(dict(properties))

    def stop(self) -> None:
        process = self._process
        self._process = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()


class McuPresenceMonitor:
    """Latch ordered physical removal and re-addition of one MCU."""

    def __init__(self, configured_path: str, reader=None, event_source=None):
        self.configured_path = configured_path
        self.reader = reader or McuIdentityReader()
        self.event_source = event_source or UdevTtyEventSource()
        self.baseline: Optional[McuIdentity] = None
        self.reconnected: Optional[McuIdentity] = None
        self._absent = threading.Event()
        self._present = threading.Event()
        self._mismatch = threading.Event()
        self._mismatched_identity: Optional[McuIdentity] = None
        self._armed = False

    def arm(self) -> McuIdentity:
        """Capture identity and start event capture before user instructions."""
        baseline = self.reader.read(self.configured_path)
        if baseline is None:
            raise McuMonitorUnavailable(
                f"MCU is not present at the configured path: {self.configured_path}"
            )
        if not (baseline.serial or baseline.physical_path):
            raise McuMonitorUnavailable(
                "MCU identity is incomplete: udev did not provide a serial or physical USB path"
            )
        self.baseline = baseline
        self._armed = True
        try:
            self.event_source.start(self._on_event)
        except Exception:
            self._armed = False
            raise

        # Close the setup race: if it vanished while udev monitoring started,
        # latch the absence immediately even if the remove line was already sent.
        if self.reader.read(self.configured_path) is None:
            self._absent.set()
        return baseline

    def _on_event(self, properties: dict) -> None:
        if not self._armed or self.baseline is None:
            return
        action = properties.get("ACTION", "").lower()
        candidate = self.reader.from_properties(properties)

        if action == "remove" and (
            self.baseline.matches(candidate) or self.baseline.occupies_same_slot(candidate)
        ):
            self._absent.set()
            return

        if action != "add" or not self._absent.is_set():
            return

        device_node = properties.get("DEVNAME", "")
        if device_node and os.path.exists(device_node):
            refreshed = self.reader.read(device_node)
            if refreshed is not None:
                candidate = refreshed

        if self.baseline.matches(candidate):
            self.reconnected = candidate
            self._present.set()
        elif self.baseline.occupies_same_slot(candidate):
            self._mismatched_identity = candidate
            self._mismatch.set()

    @staticmethod
    def _wait(event: threading.Event, cancel_event: threading.Event, timeout=None) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        while not event.wait(0.1):
            if cancel_event.is_set():
                raise McuMonitorCancelled("MCU wait cancelled by user")
            if deadline is not None and time.monotonic() >= deadline:
                return False
        return True

    def wait_until_absent(self, cancel_event: threading.Event) -> None:
        if not self._armed:
            raise McuMonitorError("MCU monitor was not armed")
        self._wait(self._absent, cancel_event)

    def wait_until_present(self, cancel_event: threading.Event) -> McuIdentity:
        if not self._armed:
            raise McuMonitorError("MCU monitor was not armed")
        while True:
            if self._mismatch.is_set():
                raise McuIdentityMismatch(
                    f"a different MCU appeared at {self._mismatched_identity.device_node}"
                )
            if self._present.wait(0.1):
                return self.reconnected
            if cancel_event.is_set():
                raise McuMonitorCancelled("MCU wait cancelled by user")

    def wait_for_absent(self, *, cancel_event: threading.Event, timeout=None) -> None:
        if not self._armed:
            raise McuMonitorError("MCU monitor was not armed")
        if not self._wait(self._absent, cancel_event, timeout):
            raise TimeoutError("MCU did not disappear before the configured deadline")

    def wait_for_present(self, *, cancel_event: threading.Event, timeout=None) -> McuIdentity:
        if not self._armed:
            raise McuMonitorError("MCU monitor was not armed")
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            if self._mismatch.is_set():
                raise McuIdentityMismatch(
                    f"a different MCU appeared at {self._mismatched_identity.device_node}"
                )
            if self._present.wait(0.1):
                return self.reconnected
            if cancel_event.is_set():
                raise McuMonitorCancelled("MCU wait cancelled by user")
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("MCU did not reappear before the configured deadline")

    def close(self) -> None:
        self.event_source.stop()

    def __enter__(self):
        self.arm()
        return self

    def __exit__(self, *_exc):
        self.close()
