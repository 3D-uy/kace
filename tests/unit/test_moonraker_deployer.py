"""Tests for the end-to-end KACE installation transaction."""

import os
import tempfile
import threading
import unittest
from types import SimpleNamespace

from core.mcu_monitor import (
    McuIdentity,
    McuIdentityAmbiguous,
    McuIdentityMismatch,
    McuMonitorCancelled,
)
from core.moonraker_deployer import (
    ConfigArtifact, Deployer, DeploymentManifest, DeploymentTimeouts, DeployState, McuTarget,
)
from core.snapshot import DeploymentSnapshot
from core.terminal_progress import WorkflowEventEmitter
from firmware.identity import FirmwareBuildInputs, ToolchainIdentity


class Monitor:
    def __init__(self, *, mismatch=False, cancel=False):
        self.calls = []
        self.mismatch = mismatch
        self.cancel = cancel

    def arm(self):
        self.calls.append("arm")

    def wait_for_absent(self, **kwargs):
        self.calls.append(("absent", kwargs["timeout"]))
        if self.cancel:
            raise McuMonitorCancelled("cancelled")

    def wait_for_present(self, **kwargs):
        self.calls.append(("present", kwargs["timeout"]))
        if self.mismatch:
            raise McuIdentityMismatch("different MCU")
        return McuIdentity("/dev/serial/by-id/mcu", "/dev/ttyACM1", serial="same")

    def close(self):
        self.calls.append("close")


class Client:
    def __init__(self, payloads, *, online=None, states=None, versions=None):
        self.payloads = payloads
        self.online = list(online or [True])
        self.states = list(states or ["ready", "ready"])
        self.versions = list(versions or [{"mcu": "kace-good"}])
        self.calls = []
        self.remote = {}
        self.rollback = False

    @staticmethod
    def _next(values, default):
        return values.pop(0) if values else default

    def is_moonraker_online(self):
        self.calls.append("moonraker")
        return self._next(self.online, True)

    def get_klippy_state(self):
        self.calls.append("klipper")
        return self._next(self.states, "ready")

    def get_mcu_versions(self):
        self.calls.append("versions")
        return self._next(self.versions, {"mcu": "kace-good"})

    def upload_config(self, path, name):
        self.calls.append(("upload", name))
        with open(path, "rb") as source:
            self.remote[name] = source.read()

    def download_config(self, name):
        self.calls.append(("download", name))
        return (name in self.remote, self.remote.get(name, b""))

    def firmware_restart(self):
        self.calls.append("restart")

    def restart_moonraker(self):
        self.calls.append("restart_moonraker")

    def restore_snapshot(self, snapshot):
        self.calls.append("rollback")
        self.rollback = True
        self.remote = dict(snapshot.config_files)
        return []


class InstallationWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.printer = os.path.join(self.tmp.name, "printer.cfg")
        self.macros = os.path.join(self.tmp.name, "macros.cfg")
        with open(self.printer, "wb") as stream:
            stream.write(b"[printer]\n")
        with open(self.macros, "wb") as stream:
            stream.write(b"[gcode_macro TEST]\n")
        self.manifest = DeploymentManifest(
            [McuTarget("mcu", "kace-good")], self.printer, self.macros
        )
        self.snapshot = DeploymentSnapshot(
            "id", "now", "board", "version", "", ("mcu",), False,
            {"printer.cfg": b"[printer]\nold: true\n"},
        )

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, client=None, monitor=None, events=None, prompt=None):
        deployer = Deployer(
            client or Client({}), self.manifest, snapshot=self.snapshot,
            mcu_monitor=monitor or Monitor(),
            power_cycle_prompt=prompt or (lambda: True),
            event_sink=(events if events is not None else []).append,
            firmware_already_copied=True,
        )
        deployer.POLL_INTERVAL_S = 0.001
        deployer.POLL_BACKOFF_MAX_S = 0.002
        return deployer

    def test_quick_disconnect_is_not_lost_and_monitor_is_armed_before_prompt(self):
        monitor = Monitor()
        observed = []
        deployer = self.make(
            monitor=monitor,
            prompt=lambda: observed.append(list(monitor.calls)) or True,
        )
        result = deployer.run()
        self.assertEqual(result.state, DeployState.DONE)
        self.assertEqual(observed, [["arm"]])
        self.assertIn(("absent", deployer.timeouts.mcu_disconnect_s), monitor.calls)

    def test_moonraker_power_cycle_wraps_the_existing_mcu_monitor_states(self):
        order = []
        monitor = Monitor()
        original_absent = monitor.wait_for_absent
        original_present = monitor.wait_for_present
        monitor.wait_for_absent = lambda **kwargs: (
            order.append("mcu_absent"), original_absent(**kwargs)
        )[1]
        monitor.wait_for_present = lambda **kwargs: (
            order.append("mcu_present"), original_present(**kwargs)
        )[1]
        deployer = Deployer(
            Client({}), self.manifest, snapshot=self.snapshot,
            mcu_monitor=monitor,
            power_cycle_prompt=lambda: order.append("confirmed") or True,
            media_installation_prompt=lambda: order.append("media_installed") or True,
            power_off=lambda: order.append("off"),
            power_on=lambda: order.append("on"),
            event_sink=lambda _event: None,
            firmware_already_copied=True,
        )
        deployer.POLL_INTERVAL_S = 0.001
        deployer.POLL_BACKOFF_MAX_S = 0.002

        self.assertEqual(deployer.run().state, DeployState.DONE)
        self.assertEqual(
            order,
            [
                "confirmed",
                "off",
                "mcu_absent",
                "media_installed",
                "on",
                "mcu_present",
            ],
        )

    def test_relay_cannot_cycle_before_media_installation_confirmation(self):
        order = []
        monitor = Monitor()
        events = []
        deployer = Deployer(
            Client({}),
            self.manifest,
            snapshot=self.snapshot,
            mcu_monitor=monitor,
            power_cycle_prompt=lambda: order.append("confirmation") or False,
            power_off=lambda: order.append("off"),
            power_on=lambda: order.append("on"),
            event_sink=events.append,
            firmware_already_copied=True,
        )

        result = deployer.run()

        self.assertEqual(result.state, DeployState.CANCELLED)
        self.assertEqual(order, ["confirmation"])
        self.assertFalse(any(call[0] == "absent" for call in monitor.calls if isinstance(call, tuple)))
        self.assertEqual(events[-1]["state"], "CANCELLED")

    def test_cancel_while_relay_is_off_never_powers_back_on(self):
        order = []
        deployer = Deployer(
            Client({}),
            self.manifest,
            snapshot=self.snapshot,
            mcu_monitor=Monitor(),
            power_cycle_prompt=lambda: True,
            media_installation_prompt=lambda: order.append("media_prompt") or False,
            power_off=lambda: order.append("off"),
            power_on=lambda: order.append("on"),
            event_sink=lambda _event: None,
            firmware_already_copied=True,
        )

        result = deployer.run()

        self.assertEqual(result.state, DeployState.CANCELLED)
        self.assertEqual(order, ["off", "media_prompt"])

    def test_manual_relay_emits_physical_states_in_safe_order(self):
        events = []
        deployer = Deployer(
            Client({}),
            self.manifest,
            snapshot=self.snapshot,
            mcu_monitor=Monitor(),
            power_cycle_prompt=lambda: True,
            media_installation_prompt=lambda: True,
            power_off=lambda: None,
            power_on=lambda: None,
            event_sink=events.append,
            firmware_already_copied=True,
        )
        deployer.POLL_INTERVAL_S = 0.001
        deployer.POLL_BACKOFF_MAX_S = 0.002

        self.assertEqual(deployer.run().state, DeployState.DONE)
        states = [event["state"] for event in events]
        expected = [
            "MEDIA_PREPARED",
            "AWAITING_POWER_CYCLE",
            "AWAITING_MEDIA_INSTALLATION",
            "AWAITING_BOOTLOADER",
            "FLASHING",
            "AWAITING_REENUMERATION",
            "VERIFYING_FIRMWARE",
        ]
        self.assertEqual(
            [state for state in states if state in expected],
            expected,
        )

    def test_action_required_strategy_result_cannot_continue_as_success(self):
        monitor = Monitor()
        outcome = SimpleNamespace(
            status=SimpleNamespace(value="ACTION_REQUIRED"),
            detail="operator action is unresolved",
        )
        deployer = Deployer(
            Client({}),
            self.manifest,
            snapshot=self.snapshot,
            mcu_monitor=monitor,
            firmware_deploy=lambda: outcome,
            event_sink=lambda _event: None,
        )

        result = deployer.run()

        self.assertEqual(result.state, DeployState.FAILED_PRECONDITION)
        self.assertNotIn("arm", monitor.calls)

    def test_copy_is_inside_transaction_and_precedes_monitor(self):
        order = []
        monitor = Monitor()
        original_arm = monitor.arm
        monitor.arm = lambda: (order.append("arm"), original_arm())[1]
        deployer = Deployer(
            Client({}), self.manifest, snapshot=self.snapshot,
            mcu_monitor=monitor,
            firmware_copy=lambda: order.append("copy") or True,
            power_cycle_prompt=lambda: True,
            event_sink=lambda _event: None,
        )
        deployer.POLL_INTERVAL_S = 0.001
        deployer.POLL_BACKOFF_MAX_S = 0.002
        self.assertEqual(deployer.run().state, DeployState.DONE)
        self.assertEqual(order, ["copy", "arm"])

    def test_failed_required_backup_aborts_before_firmware_action(self):
        action = []
        deployer = Deployer(
            Client({}),
            self.manifest,
            snapshot_loader=lambda: None,
            firmware_deploy=lambda: action.append("firmware") or True,
            event_sink=lambda _event: None,
        )
        result = deployer.run()
        self.assertEqual(result.state, DeployState.FAILED_PRECONDITION)
        self.assertEqual(action, [])

    def test_moonraker_config_is_restarted_before_klipper(self):
        moonraker = os.path.join(self.tmp.name, "moonraker.conf")
        with open(moonraker, "wb") as stream:
            stream.write(b"[server]\nport: 7125\n")
        manifest = DeploymentManifest(
            [McuTarget("mcu", "kace-good")],
            self.printer,
            config_artifacts=[
                ConfigArtifact(moonraker, "moonraker.conf"),
                ConfigArtifact(self.printer, "printer.cfg"),
            ],
        )
        client = Client({})
        deployer = Deployer(
            client,
            manifest,
            snapshot=self.snapshot,
            event_sink=lambda _event: None,
        )
        deployer.POLL_INTERVAL_S = 0.001
        deployer.POLL_BACKOFF_MAX_S = 0.002
        self.assertEqual(deployer.run().state, DeployState.DONE)
        self.assertLess(client.calls.index("restart_moonraker"), client.calls.index("restart"))

    def test_usb_style_deployment_arms_monitor_before_flash(self):
        order = []
        monitor = Monitor()
        original_arm = monitor.arm
        monitor.arm = lambda: (order.append("arm"), original_arm())[1]
        deployer = Deployer(
            Client({}), self.manifest, snapshot=self.snapshot,
            mcu_monitor=monitor,
            firmware_deploy=lambda: order.append("flash") or SimpleNamespace(
                status=SimpleNamespace(value="FLASHED"), detail="flashed"
            ),
            monitor_before_firmware=True,
            event_sink=lambda _event: None,
        )
        deployer.POLL_INTERVAL_S = 0.001
        deployer.POLL_BACKOFF_MAX_S = 0.002

        self.assertEqual(deployer.run().state, DeployState.DONE)
        self.assertEqual(order, ["arm", "flash"])

    def test_copy_failure_is_structured_and_never_arms_monitor(self):
        monitor = Monitor()
        deployer = Deployer(
            Client({}), self.manifest, mcu_monitor=monitor,
            firmware_copy=lambda: False, event_sink=lambda _event: None,
        )
        result = deployer.run()
        self.assertEqual(result.state, DeployState.FAILED_FLASH)
        self.assertNotIn("arm", monitor.calls)

    def test_physical_waits_use_distinct_finite_stage_timeouts(self):
        monitor = Monitor()
        deployer = self.make(monitor=monitor)
        deployer.timeouts = DeploymentTimeouts(
            mcu_disconnect_s=11,
            mcu_reenumeration_s=12,
            moonraker_s=13,
            klipper_ready_s=14,
            mcu_registration_s=15,
        )
        deployer.run()
        self.assertIn(("absent", 11), monitor.calls)
        self.assertIn(("present", 12), monitor.calls)

    def test_cancellation_returns_aborted_without_upload(self):
        monitor = Monitor(cancel=True)
        client = Client({})
        result = self.make(client, monitor).run()
        self.assertEqual(result.state, DeployState.CANCELLED)
        self.assertFalse(any(isinstance(c, tuple) and c[0] == "upload" for c in client.calls))

    def test_keyboard_interrupt_emits_terminal_aborted_event(self):
        monitor = Monitor()
        def interrupt_wait(**_kwargs):
            raise KeyboardInterrupt
        monitor.wait_for_absent = interrupt_wait
        events = []

        result = self.make(monitor=monitor, events=events).run()

        self.assertEqual(result.state, DeployState.CANCELLED)
        self.assertEqual(events[-1]["state"], "CANCELLED")
        self.assertEqual(events[-1]["detail"], "cancelled by user")

    def test_renderer_failure_does_not_change_workflow_result(self):
        events = []
        deployer = self.make(events=events)

        def broken_renderer(_event):
            raise RuntimeError("terminal unavailable")

        deployer.event_sink = WorkflowEventEmitter(events.append, broken_renderer)
        result = deployer.run()

        self.assertEqual(result.state, DeployState.DONE)
        self.assertEqual(events[-1]["state"], "DONE")

    def test_moonraker_outage_is_not_usb_disconnect(self):
        monitor = Monitor()
        client = Client({}, online=[False, False, True])
        result = self.make(client, monitor).run()
        self.assertEqual(result.state, DeployState.DONE)
        self.assertEqual([c for c in monitor.calls if isinstance(c, tuple)][0][0], "absent")
        self.assertGreaterEqual(client.calls.count("moonraker"), 6)

    def test_different_physical_mcu_is_rejected(self):
        result = self.make(monitor=Monitor(mismatch=True)).run()
        self.assertEqual(result.state, DeployState.FAILED_MONITOR)

    def test_unresolved_ambiguous_mcu_is_rejected(self):
        monitor = Monitor()
        monitor.wait_for_present = lambda **_kwargs: (_ for _ in ()).throw(
            McuIdentityAmbiguous("insufficient topology evidence")
        )

        result = self.make(monitor=monitor).run()

        self.assertEqual(result.state, DeployState.FAILED_MONITOR)
        self.assertIn("insufficient topology", result.detail)

    def test_accepted_identity_evidence_is_emitted_for_audit(self):
        monitor = Monitor()
        assessment = SimpleNamespace(
            to_dict=lambda: {
                "verdict": "AMBIGUOUS",
                "score": 80,
                "reasons": ["serial changed"],
            }
        )
        monitor.last_assessment = assessment
        monitor.manual_confirmation_used = False
        identity = McuIdentity(
            "/dev/serial/by-id/mcu", "/dev/ttyACM1", serial="same"
        )

        def wait_for_present(**_kwargs):
            self.assertTrue(monitor.ambiguity_resolver(assessment))
            monitor.manual_confirmation_used = True
            return identity

        monitor.wait_for_present = wait_for_present
        events = []
        deployer = Deployer(
            Client({}),
            self.manifest,
            snapshot=self.snapshot,
            mcu_monitor=monitor,
            power_cycle_prompt=lambda: True,
            identity_confirmation_prompt=lambda value: value is assessment,
            event_sink=events.append,
            firmware_already_copied=True,
        )
        deployer.POLL_INTERVAL_S = 0.001
        deployer.POLL_BACKOFF_MAX_S = 0.002

        result = deployer.run()

        self.assertEqual(result.state, DeployState.DONE)
        states = [event["state"] for event in events]
        self.assertLess(
            states.index("AWAITING_MCU_CONFIRMATION"),
            states.index("MCU_IDENTITY_CONFIRMED"),
        )
        self.assertLess(
            states.index("MCU_IDENTITY_CONFIRMED"), states.index("MCU_PRESENT")
        )
        present = next(event for event in events if event["state"] == "MCU_PRESENT")
        self.assertTrue(present["data"]["manually_confirmed"])
        self.assertEqual(present["data"]["identity_assessment"]["score"], 80)
        self.assertEqual(present["data"]["identity"]["serial"], "same")

    def test_no_upload_before_fingerprint_and_each_file_once(self):
        events = []
        client = Client({})
        result = self.make(client, events=events).run()
        self.assertEqual(result.state, DeployState.DONE)
        states = [event["state"] for event in events]
        self.assertLess(states.index("FIRMWARE_VERIFIED"), states.index("APPLYING_CONFIG"))
        self.assertEqual(client.calls.count(("upload", "printer.cfg")), 1)
        self.assertEqual(client.calls.count(("upload", "macros.cfg")), 1)
        self.assertEqual(client.calls.count("restart"), 1)
        self.assertEqual(states[-1], "DONE")
        self.assertEqual([e["sequence"] for e in events], list(range(1, len(events) + 1)))

    def test_wrong_fingerprint_never_uploads(self):
        client = Client({}, versions=[{"mcu": "some-other-build"}])
        result = self.make(client).run()
        self.assertEqual(result.state, DeployState.FAILED_FLASH)
        self.assertFalse(any(isinstance(c, tuple) and c[0] == "upload" for c in client.calls))

    def test_previous_firmware_with_same_config_cannot_verify_after_failed_flash(self):
        toolchain = ToolchainIdentity("make", "GNU Make 4.4", "gcc", "gcc 13")
        config = 'CONFIG_MCU="stm32"\nCONFIG_USB=y\n'
        previous = FirmwareBuildInputs.create(
            klipper_commit="1" * 40,
            canonical_config=config,
            toolchain=toolchain,
            build_id="a" * 32,
        )
        desired = FirmwareBuildInputs.create(
            klipper_commit="2" * 40,
            canonical_config=config,
            toolchain=toolchain,
            build_id="b" * 32,
        ).complete(
            artifact_sha256="c" * 64,
            artifact_size=4096,
            artifact_format="bin",
        )
        self.assertEqual(previous.config_sha256, desired.config_sha256)
        self.assertNotEqual(previous.input_sha256, desired.input_sha256)

        manifest = DeploymentManifest(
            [McuTarget("mcu", desired.reported_version, desired.to_dict())],
            self.printer,
            self.macros,
        )
        client = Client({}, versions=[{"mcu": previous.reported_version}])
        deployer = Deployer(
            client,
            manifest,
            snapshot=self.snapshot,
            mcu_monitor=Monitor(),
            power_cycle_prompt=lambda: True,
            event_sink=lambda _event: None,
            firmware_already_copied=True,
        )
        deployer.POLL_INTERVAL_S = 0.001
        deployer.POLL_BACKOFF_MAX_S = 0.002

        result = deployer.run()
        self.assertEqual(result.state, DeployState.FAILED_FLASH)
        self.assertFalse(
            any(isinstance(call, tuple) and call[0] == "upload" for call in client.calls)
        )

    def test_restart_and_second_ready(self):
        client = Client({}, states=["ready", "ready", "startup", "ready", "ready"])
        result = self.make(client).run()
        self.assertEqual(result.state, DeployState.DONE)
        self.assertEqual(client.calls.count("restart"), 1)
        self.assertGreaterEqual(client.calls.count("klipper"), 3)

    def test_config_error_rolls_back_and_validates_ready(self):
        client = Client({}, states=["ready", "ready", "error", "ready", "ready"])
        result = self.make(client).run()
        self.assertEqual(result.state, DeployState.CONFIG_ERROR)
        self.assertTrue(result.rollback_succeeded)
        self.assertTrue(client.rollback)
        self.assertEqual(client.calls[-1], "klipper")

    def test_upload_checksum_mismatch_rolls_back(self):
        client = Client({})
        original_download = client.download_config
        def corrupt(name):
            ok, data = original_download(name)
            return ok, data + b"corrupt"
        client.download_config = corrupt
        result = self.make(client).run()
        self.assertEqual(result.state, DeployState.FAILED_UPLOAD)
        self.assertTrue(result.rollback_succeeded)


if __name__ == "__main__":
    unittest.main()
