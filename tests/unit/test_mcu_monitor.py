import threading
import inspect
import unittest
from unittest.mock import patch

from core.mcu_monitor import (
    McuIdentity,
    McuIdentityAmbiguous,
    McuIdentityMismatch,
    McuIdentityReader,
    McuIdentityVerdict,
    McuMonitorCancelled,
    McuMonitorUnavailable,
    McuPresenceMonitor,
    assess_mcu_identity,
)


class Reader:
    def __init__(self, values):
        self.values = list(values)

    def read(self, _path):
        return self.values.pop(0) if self.values else None

    def from_properties(self, props, **_kwargs):
        physical_path = props.get("ID_PATH", "")
        return McuIdentity(
            props.get("DEVNAME", ""),
            props.get("DEVNAME", ""),
            devpath=props.get("DEVPATH", ""),
            serial=props.get("ID_SERIAL_SHORT", ""),
            physical_path=physical_path,
            vendor_id=props.get("ID_VENDOR_ID", ""),
            model_id=props.get("ID_MODEL_ID", ""),
            physical_port=McuIdentityReader._physical_port(
                physical_path, props.get("DEVPATH", "")
            ),
        )


class FailingRaceReader(Reader):
    def read(self, path):
        if len(self.values) == 1:
            raise McuMonitorUnavailable("udev read failed")
        return super().read(path)


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
    EXPECTED = ("1d50:614e",)

    def identity(
        self,
        node="/dev/ttyACM0",
        serial="abc",
        path="pci-0000:00:14.0-usb-0:1:1.0",
        vid_pid="1d50:614e",
        by_path=("/dev/serial/by-path/pci-usb-0:1:1.0",),
    ):
        vendor, model = vid_pid.split(":") if vid_pid else ("", "")
        return McuIdentity(
            node,
            node,
            serial=serial,
            physical_path=path,
            vendor_id=vendor,
            model_id=model,
            physical_port=McuIdentityReader._physical_port(path, ""),
            by_path=by_path,
        )

    @staticmethod
    def remove_event(path="pci-0000:00:14.0-usb-0:1:1.0", serial="abc"):
        return {
            "ACTION": "remove",
            "DEVNAME": "/dev/ttyACM0",
            "ID_SERIAL_SHORT": serial,
            "ID_PATH": path,
        }

    @staticmethod
    def add_event(identity):
        return {
            "ACTION": "add",
            "DEVNAME": identity.device_node,
            "DEVPATH": identity.devpath,
            "ID_SERIAL_SHORT": identity.serial,
            "ID_PATH": identity.physical_path,
            "ID_VENDOR_ID": identity.vendor_id,
            "ID_MODEL_ID": identity.model_id,
        }

    def make(self, values, source=None, **kwargs):
        return McuPresenceMonitor(
            "/dev/by-id/mcu",
            Reader(values),
            source or Source(),
            expected_vid_pids=self.EXPECTED,
            **kwargs,
        )

    def test_disconnect_during_arm_is_latched(self):
        baseline = self.identity()
        source = Source(self.remove_event())
        monitor = self.make([baseline, None], source)
        monitor.arm()
        monitor.wait_for_absent(cancel_event=threading.Event(), timeout=0.01)

    def test_arm_race_read_failure_stops_monitor_and_fails_closed(self):
        baseline = self.identity()
        source = Source()
        monitor = McuPresenceMonitor(
            "/dev/by-id/mcu",
            FailingRaceReader([baseline, baseline]),
            source,
            expected_vid_pids=self.EXPECTED,
        )

        with self.assertRaisesRegex(McuMonitorUnavailable, "after arming"):
            monitor.arm()

        self.assertTrue(source.stopped)
        self.assertFalse(monitor._armed)

    def test_tty_change_preserves_physical_identity_with_expected_vid_pid(self):
        baseline = self.identity()
        reconnected = self.identity("/dev/ttyACM1")
        source = Source()
        monitor = self.make([baseline, baseline, reconnected], source)
        monitor.arm()
        source.emit(**self.remove_event())
        source.emit(**self.add_event(reconnected))

        actual = monitor.wait_for_present(cancel_event=threading.Event(), timeout=0.01)

        self.assertEqual(actual.device_node, "/dev/ttyACM1")
        self.assertIs(monitor.last_assessment.verdict, McuIdentityVerdict.MATCH)
        self.assertEqual(monitor.last_assessment.score, 100)
        self.assertFalse(monitor.manual_confirmation_used)

    def test_same_port_and_vid_pid_without_serial_is_an_automatic_match(self):
        baseline = self.identity(serial="")
        reconnected = self.identity("/dev/ttyACM1", serial="")
        assessment = assess_mcu_identity(
            baseline, reconnected, expected_vid_pids=self.EXPECTED
        )
        self.assertIs(assessment.verdict, McuIdentityVerdict.MATCH)
        self.assertEqual(assessment.score, 90)
        self.assertIn("serial evidence is unavailable", assessment.describe())

    def test_changed_serial_in_same_port_requires_manual_confirmation(self):
        baseline = self.identity()
        other_serial = self.identity("/dev/ttyACM1", serial="other")
        source = Source()
        assessments = []
        monitor = self.make(
            [baseline, baseline, other_serial],
            source,
            ambiguity_resolver=lambda value: assessments.append(value) or True,
        )
        monitor.arm()
        source.emit(**self.remove_event())
        source.emit(**self.add_event(other_serial))
        self.assertEqual(assessments, [], "udev callback must never prompt the user")

        actual = monitor.wait_for_present(cancel_event=threading.Event(), timeout=0.01)

        self.assertEqual(actual.serial, "other")
        self.assertEqual(len(assessments), 1)
        self.assertEqual(assessments[0].score, 70)
        self.assertTrue(monitor.manual_confirmation_used)

    def test_ambiguous_candidate_without_resolver_fails_closed(self):
        baseline = self.identity()
        other_serial = self.identity("/dev/ttyACM1", serial="other")
        source = Source()
        monitor = self.make([baseline, baseline, other_serial], source)
        monitor.arm()
        source.emit(**self.remove_event())
        source.emit(**self.add_event(other_serial))

        with self.assertRaises(McuIdentityAmbiguous):
            monitor.wait_for_present(cancel_event=threading.Event(), timeout=0.01)

    def test_declined_ambiguous_candidate_is_cancelled(self):
        baseline = self.identity()
        other_serial = self.identity("/dev/ttyACM1", serial="other")
        source = Source()
        monitor = self.make(
            [baseline, baseline, other_serial],
            source,
            ambiguity_resolver=lambda _assessment: False,
        )
        monitor.arm()
        source.emit(**self.remove_event())
        source.emit(**self.add_event(other_serial))

        with self.assertRaises(McuMonitorCancelled):
            monitor.wait_for_present(cancel_event=threading.Event(), timeout=0.01)

    def test_wrong_vid_pid_in_same_physical_port_is_rejected(self):
        baseline = self.identity()
        wrong = self.identity("/dev/ttyACM1", vid_pid="2341:0042")
        source = Source()
        monitor = self.make([baseline, baseline, wrong], source)
        monitor.arm()
        source.emit(**self.remove_event())
        source.emit(**self.add_event(wrong))

        with self.assertRaisesRegex(McuIdentityMismatch, "not allowed"):
            monitor.wait_for_present(cancel_event=threading.Event(), timeout=0.01)

    def test_same_serial_and_vid_pid_on_different_port_is_ambiguous(self):
        baseline = self.identity()
        moved = self.identity(
            "/dev/ttyACM1",
            path="pci-0000:00:14.0-usb-0:3:1.0",
            by_path=("/dev/serial/by-path/pci-usb-0:3:1.0",),
        )

        assessment = assess_mcu_identity(
            baseline, moved, expected_vid_pids=self.EXPECTED
        )

        self.assertIs(assessment.verdict, McuIdentityVerdict.AMBIGUOUS)
        self.assertEqual(assessment.score, 40)
        self.assertIn("cannot override", assessment.describe())

    def test_declared_bootloader_identity_is_transient_until_application_returns(self):
        baseline = self.identity()
        bootloader = self.identity("/dev/ttyACM1", vid_pid="2e8a:0003", serial="")
        application = self.identity("/dev/ttyACM2")
        source = Source()
        monitor = self.make(
            [baseline, baseline, bootloader, application],
            source,
            bootloader_vid_pids=("2e8a:0003",),
        )
        monitor.arm()
        source.emit(**self.remove_event())
        source.emit(**self.add_event(bootloader))
        self.assertFalse(monitor._present.is_set())
        source.emit(**self.add_event(application))

        actual = monitor.wait_for_present(cancel_event=threading.Event(), timeout=0.01)

        self.assertEqual(actual.device_node, "/dev/ttyACM2")

    def test_later_strong_match_supersedes_an_earlier_ambiguous_event(self):
        baseline = self.identity()
        ambiguous = self.identity("/dev/ttyACM1", serial="other")
        accepted = self.identity("/dev/ttyACM2")
        source = Source()
        prompts = []
        monitor = self.make(
            [baseline, baseline, ambiguous, accepted],
            source,
            ambiguity_resolver=lambda value: prompts.append(value) or True,
        )
        monitor.arm()
        source.emit(**self.remove_event())
        source.emit(**self.add_event(ambiguous))
        source.emit(**self.add_event(accepted))

        actual = monitor.wait_for_present(cancel_event=threading.Event(), timeout=0.01)

        self.assertEqual(actual.device_node, "/dev/ttyACM2")
        self.assertEqual(prompts, [])
        self.assertFalse(monitor.manual_confirmation_used)

    def test_by_path_can_anchor_identity_when_id_path_is_unavailable(self):
        baseline = self.identity(path="", by_path=("/dev/serial/by-path/port-a",))
        candidate = self.identity(
            "/dev/ttyACM1", path="", by_path=("/dev/serial/by-path/port-a",)
        )
        assessment = assess_mcu_identity(
            baseline, candidate, expected_vid_pids=self.EXPECTED
        )
        self.assertIs(assessment.verdict, McuIdentityVerdict.MATCH)
        self.assertIn("by_path", assessment.topology_evidence)

    def test_topology_without_expected_vid_pid_never_auto_matches(self):
        baseline = self.identity()
        candidate = self.identity("/dev/ttyACM1")

        assessment = assess_mcu_identity(baseline, candidate)

        self.assertIs(assessment.verdict, McuIdentityVerdict.AMBIGUOUS)
        self.assertIn("no application VID:PID contract", assessment.describe())

    def test_arm_rejects_device_node_as_the_only_identity_evidence(self):
        incomplete = self.identity(serial="", path="", vid_pid="", by_path=())
        monitor = self.make([incomplete], Source())
        with self.assertRaises(McuMonitorUnavailable):
            monitor.arm()

    def test_default_monitor_waits_have_a_finite_deadline(self):
        for method in (McuPresenceMonitor.wait_for_absent, McuPresenceMonitor.wait_for_present):
            default = inspect.signature(method).parameters["timeout"].default
            self.assertIsInstance(default, (int, float))
            self.assertGreater(default, 0)

    def test_bounded_wait_is_cancelable(self):
        baseline = self.identity()
        monitor = self.make([baseline, baseline], Source())
        monitor.arm()
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(McuMonitorCancelled):
            monitor.wait_for_absent(cancel_event=cancelled, timeout=1.0)

    @patch("core.mcu_monitor.os.path.realpath")
    @patch("core.mcu_monitor.glob.glob")
    def test_reader_collects_all_by_path_aliases_for_device(self, mock_glob, mock_realpath):
        mock_glob.return_value = [
            "/dev/serial/by-path/port-a",
            "/dev/serial/by-path/port-b",
        ]
        mock_realpath.side_effect = lambda value: (
            "/dev/ttyACM0" if value.endswith(("port-a", "port-b")) else value
        )

        aliases = McuIdentityReader._by_path_aliases("/dev/ttyACM0")

        self.assertEqual(
            aliases,
            ("/dev/serial/by-path/port-a", "/dev/serial/by-path/port-b"),
        )

    def test_physical_port_normalization_removes_interface_and_serial_port_suffix(self):
        self.assertEqual(
            McuIdentityReader._physical_port(
                "platform-fd500000.pcie-usb-0:1.3:1.0-port0", ""
            ),
            "platform-fd500000.pcie-usb-0:1.3",
        )


if __name__ == "__main__":
    unittest.main()
