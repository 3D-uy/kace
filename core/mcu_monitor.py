"""Physical MCU presence monitoring for SD-card firmware workflows.

The monitor is armed before the user is asked to power-cycle the printer. On
Linux it consumes udev ``tty`` add/remove events, preserving the physical
identity across changes such as ``/dev/ttyACM0`` becoming ``/dev/ttyACM1``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import glob
import os
import re
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


class McuIdentityAmbiguous(McuMonitorError):
    """Raised when the available evidence cannot safely identify the MCU."""


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
    physical_port: str = ""
    by_path: tuple[str, ...] = ()

    @property
    def vid_pid(self) -> str:
        if not self.vendor_id or not self.model_id:
            return ""
        return f"{self.vendor_id.lower()}:{self.model_id.lower()}"

    @property
    def has_topology(self) -> bool:
        return bool(self.physical_port or self.by_path or self.physical_path or self.devpath)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["by_path"] = list(self.by_path)
        data["vid_pid"] = self.vid_pid
        return data

    def matches(self, other: "McuIdentity") -> bool:
        """Conservative compatibility helper retained for removal events."""
        if not self.occupies_same_slot(other):
            return False
        if self.vid_pid and other.vid_pid and self.vid_pid != other.vid_pid:
            return False
        if self.serial and other.serial and self.serial != other.serial:
            return False
        return True

    def occupies_same_slot(self, other: "McuIdentity") -> bool:
        """Return whether a candidate occupies the monitored USB connection."""
        if self.physical_port and other.physical_port:
            return self.physical_port == other.physical_port
        if self.by_path and other.by_path:
            return bool(set(self.by_path).intersection(other.by_path))
        if self.physical_path and other.physical_path:
            return self.physical_path == other.physical_path
        if self.devpath and other.devpath:
            return self.devpath == other.devpath
        return self.device_node == other.device_node


class McuIdentityVerdict(str, Enum):
    MATCH = "MATCH"
    AMBIGUOUS = "AMBIGUOUS"
    MISMATCH = "MISMATCH"
    TRANSIENT = "TRANSIENT"
    UNRELATED = "UNRELATED"


@dataclass(frozen=True)
class McuIdentityAssessment:
    verdict: McuIdentityVerdict
    baseline: McuIdentity
    candidate: McuIdentity
    reasons: tuple[str, ...]
    topology_evidence: tuple[str, ...] = ()
    expected_vid_pids: tuple[str, ...] = ()
    score: int = 0
    automatic_threshold: int = 90

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict.value,
            "reasons": list(self.reasons),
            "topology_evidence": list(self.topology_evidence),
            "expected_vid_pids": list(self.expected_vid_pids),
            "score": self.score,
            "automatic_threshold": self.automatic_threshold,
            "baseline": self.baseline.to_dict(),
            "candidate": self.candidate.to_dict(),
        }

    def describe(self) -> str:
        return "; ".join(self.reasons) or self.verdict.value.lower()


def _normalized_vid_pids(values) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value).strip().lower() for value in values if value))


def assess_mcu_identity(
    baseline: McuIdentity,
    candidate: McuIdentity,
    *,
    expected_vid_pids=(),
    bootloader_vid_pids=(),
) -> McuIdentityAssessment:
    """Classify post-flash identity without converting partial evidence to success."""
    expected = _normalized_vid_pids(expected_vid_pids)
    bootloader = _normalized_vid_pids(bootloader_vid_pids)
    topology = []
    if (
        baseline.physical_port
        and candidate.physical_port
        and baseline.physical_port == candidate.physical_port
    ):
        topology.append("physical_port")
    if baseline.by_path and candidate.by_path and set(baseline.by_path).intersection(candidate.by_path):
        topology.append("by_path")
    if (
        baseline.physical_path
        and candidate.physical_path
        and baseline.physical_path == candidate.physical_path
    ):
        topology.append("udev_id_path")
    if baseline.devpath and candidate.devpath and baseline.devpath == candidate.devpath:
        topology.append("devpath")

    serial_match = bool(baseline.serial and candidate.serial and baseline.serial == candidate.serial)
    serial_conflict = bool(
        baseline.serial and candidate.serial and baseline.serial != candidate.serial
    )
    observed = candidate.vid_pid
    topology_score = 0
    if "physical_port" in topology or "by_path" in topology:
        topology_score = 60
    elif "udev_id_path" in topology:
        topology_score = 55
    elif "devpath" in topology:
        topology_score = 50
    identity_score = topology_score
    if expected and observed in expected:
        identity_score += 30
    if serial_match:
        identity_score += 10
    elif serial_conflict:
        identity_score = max(0, identity_score - 20)

    def result(verdict, *reasons):
        return McuIdentityAssessment(
            verdict,
            baseline,
            candidate,
            tuple(reasons),
            tuple(topology),
            expected,
            identity_score,
        )

    if topology:
        if observed and observed in bootloader and observed not in expected:
            return result(
                McuIdentityVerdict.TRANSIENT,
                f"declared bootloader VID:PID {observed} appeared on the expected physical port",
            )
        if not expected:
            return result(
                McuIdentityVerdict.AMBIGUOUS,
                "physical topology matches but no application VID:PID contract was supplied",
            )
        if expected and not observed:
            return result(
                McuIdentityVerdict.AMBIGUOUS,
                "physical topology matches but candidate VID:PID is unavailable",
            )
        if expected and observed not in expected:
            return result(
                McuIdentityVerdict.MISMATCH,
                f"candidate VID:PID {observed} is not allowed; expected {', '.join(expected)}",
            )
        if serial_conflict:
            return result(
                McuIdentityVerdict.AMBIGUOUS,
                "physical topology and VID:PID match but the reported serial changed",
            )
        if identity_score < 90:
            return result(
                McuIdentityVerdict.AMBIGUOUS,
                f"identity evidence score {identity_score} is below the automatic threshold 90",
            )
        reasons = ["candidate reappeared on the same physical USB topology"]
        if expected:
            reasons.append(f"candidate VID:PID {observed} matches the board profile")
        if serial_match:
            reasons.append("reported serial remained stable")
        elif not baseline.serial or not candidate.serial:
            reasons.append("serial evidence is unavailable and was not used")
        return result(McuIdentityVerdict.MATCH, *reasons)

    if expected and observed in expected:
        reasons = ["candidate has an expected VID:PID but not the captured physical topology"]
        if serial_match:
            reasons.append("reported serial matches but cannot override the port mismatch")
        return result(McuIdentityVerdict.AMBIGUOUS, *reasons)
    if serial_match:
        return result(
            McuIdentityVerdict.AMBIGUOUS,
            "reported serial matches but physical topology and expected VID:PID do not prove identity",
        )
    return result(
        McuIdentityVerdict.UNRELATED,
        "candidate does not match the captured physical topology or expected board identity",
    )


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
        return self.from_properties(
            properties,
            configured_path=path,
            device_node=device_node,
            by_path=self._by_path_aliases(device_node, configured_path=path),
        )

    @staticmethod
    def _physical_port(physical_path: str, devpath: str) -> str:
        if physical_path:
            return re.sub(r":\d+\.\d+(?:-port\d+)?$", "", physical_path)
        if devpath:
            return re.sub(r"/[^/]+:\d+\.\d+(?:/.*)?$", "", devpath)
        return ""

    @staticmethod
    def _by_path_aliases(device_node: str, *, configured_path: str = "") -> tuple[str, ...]:
        aliases = []
        if configured_path.startswith("/dev/serial/by-path/"):
            aliases.append(configured_path)
        for alias in glob.glob("/dev/serial/by-path/*"):
            try:
                if os.path.realpath(alias) == device_node:
                    aliases.append(alias)
            except OSError:
                continue
        return tuple(sorted(set(aliases)))

    def from_properties(
        self,
        properties: dict,
        *,
        configured_path: str = "",
        device_node: str = "",
        by_path: tuple[str, ...] = (),
    ) -> McuIdentity:
        node = properties.get("DEVNAME") or device_node
        physical_path = properties.get("ID_PATH", "")
        devpath = properties.get("DEVPATH", "")
        return McuIdentity(
            configured_path=configured_path or node,
            device_node=node,
            devpath=devpath,
            serial=properties.get("ID_SERIAL_SHORT", ""),
            physical_path=physical_path,
            vendor_id=properties.get("ID_VENDOR_ID", ""),
            model_id=properties.get("ID_MODEL_ID", ""),
            physical_port=self._physical_port(physical_path, devpath),
            by_path=tuple(by_path),
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

    def __init__(
        self,
        configured_path: str,
        reader=None,
        event_source=None,
        *,
        expected_vid_pids=(),
        bootloader_vid_pids=(),
        ambiguity_resolver: Optional[Callable[[McuIdentityAssessment], bool]] = None,
    ):
        self.configured_path = configured_path
        self.reader = reader or McuIdentityReader()
        self.event_source = event_source or UdevTtyEventSource()
        self.baseline: Optional[McuIdentity] = None
        self.reconnected: Optional[McuIdentity] = None
        self.expected_vid_pids = _normalized_vid_pids(expected_vid_pids)
        self.bootloader_vid_pids = _normalized_vid_pids(bootloader_vid_pids)
        self.ambiguity_resolver = ambiguity_resolver
        self.last_assessment: Optional[McuIdentityAssessment] = None
        self.manual_confirmation_used = False
        self._absent = threading.Event()
        self._present = threading.Event()
        self._ambiguous = threading.Event()
        self._mismatch = threading.Event()
        self._mismatched_identity: Optional[McuIdentity] = None
        self._ambiguous_identity: Optional[McuIdentity] = None
        self._ambiguous_assessment: Optional[McuIdentityAssessment] = None
        self._armed = False

    def arm(self) -> McuIdentity:
        """Capture identity and start event capture before user instructions."""
        baseline = self.reader.read(self.configured_path)
        if baseline is None:
            raise McuMonitorUnavailable(
                f"MCU is not present at the configured path: {self.configured_path}"
            )
        if not (baseline.has_topology or baseline.serial):
            raise McuMonitorUnavailable(
                "MCU identity is incomplete: udev did not provide physical topology, by-path, or serial evidence"
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
        try:
            current = self.reader.read(self.configured_path)
        except (McuMonitorError, OSError) as exc:
            self.event_source.stop()
            self._armed = False
            raise McuMonitorUnavailable(
                f"could not verify MCU presence after arming the monitor: {exc}"
            ) from exc
        if current is None:
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
            try:
                refreshed = self.reader.read(device_node)
            except (McuMonitorError, OSError):
                refreshed = None
            if refreshed is not None:
                candidate = refreshed

        assessment = assess_mcu_identity(
            self.baseline,
            candidate,
            expected_vid_pids=self.expected_vid_pids,
            bootloader_vid_pids=self.bootloader_vid_pids,
        )
        if assessment.verdict is McuIdentityVerdict.MATCH:
            self.reconnected = candidate
            self.last_assessment = assessment
            self._present.set()
        elif assessment.verdict is McuIdentityVerdict.AMBIGUOUS:
            self._ambiguous_identity = candidate
            self._ambiguous_assessment = assessment
            self._ambiguous.set()
        elif assessment.verdict is McuIdentityVerdict.MISMATCH:
            self._mismatched_identity = candidate
            self.last_assessment = assessment
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
        return self.wait_for_present(cancel_event=cancel_event, timeout=None)

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
                detail = self.last_assessment.describe() if self.last_assessment else "identity mismatch"
                raise McuIdentityMismatch(
                    f"a different MCU appeared at {self._mismatched_identity.device_node}: {detail}"
                )
            if self._present.is_set():
                return self.reconnected
            if self._ambiguous.is_set():
                assessment = self._ambiguous_assessment
                candidate = self._ambiguous_identity
                self._ambiguous.clear()
                if assessment is None or candidate is None:
                    raise McuIdentityAmbiguous("MCU identity evidence became unavailable")
                if self.ambiguity_resolver is None:
                    raise McuIdentityAmbiguous(assessment.describe())
                if self.ambiguity_resolver(assessment) is not True:
                    raise McuMonitorCancelled("ambiguous MCU identity was not confirmed")
                self.reconnected = candidate
                self.last_assessment = assessment
                self.manual_confirmation_used = True
                self._present.set()
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
