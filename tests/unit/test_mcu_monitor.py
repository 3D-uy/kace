import threading
import unittest

from core.mcu_monitor import (
    McuIdentity, McuIdentityMismatch, McuMonitorCancelled, McuPresenceMonitor,
)


class Reader:
    def __init__(self, values):
        self.values = list(values)

    def read(self, _path):
        return self.values.pop(0) if self.values else None

    def from_properties(self, props, **_kwargs):
        return McuIdentity(
            props.get("DEVNAME", ""), props.get("DEVNAME", ""),
            devpath=props.get("DEVPATH", ""), serial=props.get("ID_SERIAL_SHORT", ""),
            physical_path=props.get("ID_PATH", ""),
        )


class Source:
    def __init__(self, during_start=None):
        self.callback = None
        self.during_start = during_start
        self.stopped = False

    def start(self, callback):
        self.callback = callback
        if self.during_start:
            callback(self.during_start)

    def emit(self, **properties):
        self.callback(properties)

    def stop(self):
        self.stopped = True


class McuMonitorTests(unittest.TestCase):
    def identity(self, node="/dev/ttyACM0", serial="abc", path="usb-1"):
        return McuIdentity(node, node, serial=serial, physical_path=path)

    def test_disconnect_during_arm_is_latched(self):
        baseline = self.identity()
        source = Source({
            "ACTION": "remove", "DEVNAME": "/dev/ttyACM0",
            "ID_SERIAL_SHORT": "abc", "ID_PATH": "usb-1",
        })
        monitor = McuPresenceMonitor("/dev/by-id/mcu", Reader([baseline, None]), source)
        monitor.arm()
        monitor.wait_for_absent(cancel_event=threading.Event(), timeout=0.01)

    def test_tty_change_preserves_physical_identity(self):
        baseline = self.identity()
        reconnected = self.identity("/dev/ttyACM1")
        source = Source()
        monitor = McuPresenceMonitor(
            "/dev/by-id/mcu", Reader([baseline, baseline, reconnected]), source
        )
        monitor.arm()
        source.emit(ACTION="remove", DEVNAME="/dev/ttyACM0", ID_SERIAL_SHORT="abc", ID_PATH="usb-1")
        source.emit(ACTION="add", DEVNAME="/dev/ttyACM1", ID_SERIAL_SHORT="abc", ID_PATH="usb-1")
        actual = monitor.wait_for_present(cancel_event=threading.Event(), timeout=0.01)
        self.assertEqual(actual.device_node, "/dev/ttyACM1")

    def test_different_serial_in_same_usb_path_is_rejected(self):
        baseline = self.identity()
        other = self.identity("/dev/ttyACM1", "other", "usb-1")
        source = Source()
        monitor = McuPresenceMonitor(
            "/dev/by-id/mcu", Reader([baseline, baseline, other]), source
        )
        monitor.arm()
        source.emit(ACTION="remove", DEVNAME="/dev/ttyACM0", ID_SERIAL_SHORT="abc", ID_PATH="usb-1")
        source.emit(ACTION="add", DEVNAME="/dev/ttyACM1", ID_SERIAL_SHORT="other", ID_PATH="usb-1")
        with self.assertRaises(McuIdentityMismatch):
            monitor.wait_for_present(cancel_event=threading.Event(), timeout=0.01)

    def test_indefinite_wait_is_cancelable(self):
        baseline = self.identity()
        monitor = McuPresenceMonitor(
            "/dev/by-id/mcu", Reader([baseline, baseline]), Source()
        )
        monitor.arm()
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(McuMonitorCancelled):
            monitor.wait_for_absent(cancel_event=cancelled, timeout=None)


if __name__ == "__main__":
    unittest.main()
