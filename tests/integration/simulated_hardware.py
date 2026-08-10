"""Stateful Moonraker, power, and udev simulator for integration tests.

The simulator deliberately exposes the real HTTP and MCU-monitor boundaries.
Tests use KACE's production Moonraker adapter, power controller, firmware
deployment service, and physical identity monitor instead of mocking their
individual methods.
"""

from __future__ import annotations

import json
import re
import threading
import urllib.parse
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from core.mcu_monitor import McuIdentity, McuIdentityReader


PHYSICAL_PATH = "pci-0000:00:14.0-usb-0:2.3:1.0"
DEVPATH = "/devices/pci0000:00/0000:00:14.0/usb1/1-2/1-2.3/1-2.3:1.0/tty/ttyACM0"


def identity(
    *,
    device_node: str = "/dev/ttyACM0",
    serial: str = "KACE-LAB-MCU",
    vendor_id: str = "1d50",
    model_id: str = "614e",
    physical_path: str = PHYSICAL_PATH,
    devpath: str = DEVPATH,
) -> McuIdentity:
    return McuIdentity(
        configured_path="/dev/serial/by-id/usb-KACE-LAB-MCU",
        device_node=device_node,
        devpath=devpath,
        serial=serial,
        physical_path=physical_path,
        vendor_id=vendor_id,
        model_id=model_id,
        physical_port=McuIdentityReader._physical_port(physical_path, devpath),
        by_path=("/dev/serial/by-path/pci-0000:00:14.0-usb-0:2.3:1.0",),
    )


def udev_properties(action: str, value: McuIdentity) -> dict[str, str]:
    return {
        "ACTION": action,
        "DEVNAME": value.device_node,
        "DEVPATH": value.devpath,
        "ID_SERIAL_SHORT": value.serial,
        "ID_PATH": value.physical_path,
        "ID_VENDOR_ID": value.vendor_id,
        "ID_MODEL_ID": value.model_id,
    }


class SimulatedIdentityReader:
    def __init__(self, baseline: McuIdentity):
        self.current = baseline
        self.present = True
        self._parser = McuIdentityReader()

    def read(self, _configured_path: str):
        return self.current if self.present else None

    def from_properties(self, properties: dict) -> McuIdentity:
        return self._parser.from_properties(properties)


class SimulatedUdevSource:
    def __init__(self):
        self.callback = None
        self.started = False
        self.stopped = False

    def start(self, callback) -> None:
        if self.started:
            raise RuntimeError("simulated udev source was armed twice")
        self.callback = callback
        self.started = True

    def emit(self, properties: dict) -> None:
        if not self.started or self.callback is None:
            raise RuntimeError("simulated udev event emitted before monitor arm")
        self.callback(dict(properties))

    def stop(self) -> None:
        self.stopped = True


class SimulatedPhysicalMcu:
    """Emit ordered removal/bootloader/application events at one USB port."""

    def __init__(self):
        self.baseline = identity()
        self.reader = SimulatedIdentityReader(self.baseline)
        self.events = SimulatedUdevSource()
        self.candidate_mode = "match"
        self.emit_bootloader = True
        self.application_vendor_id = "1d50"
        self.application_model_id = "614e"
        self.history: list[str] = []

    def disconnect(self) -> None:
        self.history.append("remove")
        self.reader.present = False
        self.events.emit(udev_properties("remove", self.reader.current))

    def reconnect(self) -> None:
        if self.emit_bootloader:
            bootloader = identity(
                device_node="/dev/ttyACM1",
                vendor_id="0483",
                model_id="df11",
            )
            self.history.append("bootloader")
            self.events.emit(udev_properties("add", bootloader))

        candidate = identity(
            device_node="/dev/ttyACM2",
            vendor_id=self.application_vendor_id,
            model_id=self.application_model_id,
        )
        if self.candidate_mode == "wrong_vid_pid":
            candidate = identity(
                device_node="/dev/ttyACM2", vendor_id="ffff", model_id="0001"
            )
        elif self.candidate_mode == "serial_changed":
            candidate = identity(device_node="/dev/ttyACM2", serial="OTHER-SERIAL")
        elif self.candidate_mode == "wrong_port":
            candidate = identity(
                device_node="/dev/ttyACM2",
                physical_path="pci-0000:00:14.0-usb-0:9.1:1.0",
                devpath="/devices/pci0000:00/usb1/1-9/1-9.1/tty/ttyACM2",
            )

        self.reader.current = candidate
        self.reader.present = True
        self.history.append("application")
        self.events.emit(udev_properties("add", candidate))

    def cycle(self) -> None:
        self.disconnect()
        self.reconnect()


class MoonrakerLab:
    """Loopback HTTP implementation of the Moonraker endpoints KACE consumes."""

    def __init__(self, *, api_key: str = "integration-secret"):
        self.api_key = api_key
        self.files: dict[str, bytes] = {"printer.cfg": b"[printer]\nold: true\n"}
        self.uploads: list[str] = []
        self.deletes: list[str] = []
        self.restarts: list[str] = []
        self.power_history: list[str] = []
        self.power_status = "on"
        self.mcu_versions = {"mcu": "previous-firmware"}
        self.klippy_states = deque()
        self.moonraker_available = True
        self.corrupt_download_once: set[str] = set()
        self.auth_failures = 0
        self.physical_mcu = SimulatedPhysicalMcu()
        self.version_after_reconnect = "desired-firmware"
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _MoonrakerHandler)
        self._server.lab = self
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="kace-simulated-moonraker",
            daemon=True,
        )

    @property
    def host(self) -> str:
        return "127.0.0.1"

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    def start(self):
        self._thread.start()
        return self

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)

    def __enter__(self):
        return self.start()

    def __exit__(self, *_exc):
        self.close()

    def authorize(self, handler: BaseHTTPRequestHandler) -> bool:
        if handler.headers.get("X-Api-Key") == self.api_key:
            return True
        self.auth_failures += 1
        handler.send_error(401, "missing test API key")
        return False

    def next_klippy_state(self) -> str:
        return self.klippy_states.popleft() if self.klippy_states else "ready"

    def physical_power_action(self, action: str) -> None:
        self.power_history.append(action)
        if action == "off":
            self.physical_mcu.disconnect()
            return
        self.physical_mcu.reconnect()
        self.mcu_versions = {"mcu": self.version_after_reconnect}

    def simulate_usb_flash(self) -> None:
        self.physical_mcu.cycle()
        self.mcu_versions = {"mcu": self.version_after_reconnect}


class _MoonrakerHandler(BaseHTTPRequestHandler):
    server_version = "KaceMoonrakerLab/1"

    @property
    def lab(self) -> MoonrakerLab:
        return self.server.lab

    def log_message(self, _format, *_args):
        return

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, payload: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _body(self) -> bytes:
        return self.rfile.read(int(self.headers.get("Content-Length", "0")))

    def do_GET(self):
        if not self.lab.authorize(self):
            return
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        if path == "/server/info":
            if not self.lab.moonraker_available:
                self.send_error(503, "simulated outage")
                return
            self._json({"result": {"moonraker_version": "simulated-1"}})
            return
        if path == "/printer/info":
            self._json({"result": {"state": self.lab.next_klippy_state()}})
            return
        if path == "/printer/objects/list":
            self._json({"result": {"objects": list(self.lab.mcu_versions)}})
            return
        if path == "/printer/objects/query":
            self._json({
                "result": {
                    "status": {
                        name: {"mcu_version": version}
                        for name, version in self.lab.mcu_versions.items()
                    }
                }
            })
            return
        if path == "/machine/device_power/devices":
            self._json({
                "result": {
                    "devices": [{"device": "printer", "status": self.lab.power_status}]
                }
            })
            return
        if path == "/server/files/list":
            self._json({"result": [{"path": name} for name in sorted(self.lab.files)]})
            return
        prefix = "/server/files/config/"
        if path.startswith(prefix):
            filename = urllib.parse.unquote(path[len(prefix):])
            if filename not in self.lab.files:
                self.send_error(404, "missing simulated file")
                return
            payload = self.lab.files[filename]
            if filename in self.lab.corrupt_download_once:
                self.lab.corrupt_download_once.remove(filename)
                payload += b"simulated-corruption"
            self._bytes(payload)
            return
        self.send_error(404)

    def do_POST(self):
        if not self.lab.authorize(self):
            return
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/server/files/upload":
            filename, payload = self._multipart_file(self._body())
            self.lab.files[filename] = payload
            self.lab.uploads.append(filename)
            self._json({"result": {"item": {"path": filename}}})
            return
        if parsed.path == "/printer/restart":
            self._body()
            self.lab.restarts.append("klipper")
            self._json({"result": "ok"})
            return
        if parsed.path == "/machine/services/restart":
            self._body()
            service = urllib.parse.parse_qs(parsed.query).get("service", [""])[0]
            self.lab.restarts.append(service)
            self._json({"result": "ok"})
            return
        if parsed.path == "/machine/device_power/device":
            payload = json.loads(self._body().decode("utf-8"))
            if payload.get("device") != "printer" or payload.get("action") not in ("on", "off"):
                self.send_error(400)
                return
            action = payload["action"]
            self.lab.power_status = action
            self.lab.physical_power_action(action)
            self._json({"result": {"device": "printer", "status": action}})
            return
        self.send_error(404)

    def do_DELETE(self):
        if not self.lab.authorize(self):
            return
        prefix = "/server/files/config/"
        path = urllib.parse.urlsplit(self.path).path
        if not path.startswith(prefix):
            self.send_error(404)
            return
        filename = urllib.parse.unquote(path[len(prefix):])
        self.lab.files.pop(filename, None)
        self.lab.deletes.append(filename)
        self._json({"result": "ok"})

    def _multipart_file(self, body: bytes) -> tuple[str, bytes]:
        content_type = self.headers.get("Content-Type", "")
        match = re.search(r"boundary=([^;]+)", content_type)
        if not match:
            raise ValueError("multipart boundary missing")
        marker = b"--" + match.group(1).encode("ascii")
        for part in body.split(marker):
            if b"filename=" not in part:
                continue
            header, separator, payload = part.partition(b"\r\n\r\n")
            if not separator:
                continue
            name_match = re.search(br'filename="([^"]+)"', header)
            if name_match:
                # The multipart encoder contributes exactly one CRLF before
                # the following boundary. Preserve every byte that belongs to
                # the uploaded configuration, including its final newline.
                if payload.endswith(b"\r\n"):
                    payload = payload[:-2]
                return name_match.group(1).decode("utf-8"), payload
        raise ValueError("multipart file missing")
