import json
from contextlib import ExitStack
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from core.power_controller import (
    MoonrakerPowerController,
    PowerControllerError,
    load_power_config,
)
from firmware.artifacts import BuildProvenance
from firmware.deployment import DeploymentStrategyId
from firmware.identity import FirmwareBuildInputs, ToolchainIdentity


class PowerControllerTests(TestCase):
    def test_get_status_selects_the_configured_power_device(self):
        devices = [
            {"device": "lights", "status": "off"},
            {"device": "main_psu", "status": "on"},
        ]
        with patch(
            "core.power_controller.get_power_devices", return_value=(True, "OK", devices)
        ):
            controller = MoonrakerPowerController("main_psu")
            self.assertEqual(controller.get_status(), "on")

    def test_power_on_uses_moonraker_and_confirms_final_state(self):
        states = [
            (True, "OK", [{"device": "main_psu", "status": "off"}]),
            (True, "OK", [{"device": "main_psu", "status": "on"}]),
        ]
        with patch(
            "core.power_controller.get_power_devices", side_effect=states
        ), patch(
            "core.power_controller.set_power_device", return_value=(True, "OK")
        ) as set_device:
            controller = MoonrakerPowerController("main_psu", poll_interval=0)
            self.assertEqual(controller.power_on(timeout=1), "on")
        set_device.assert_called_once_with(
            "localhost", 7125, "main_psu", "on", api_key=None
        )

    def test_wait_until_ready_fails_when_moonraker_reports_error(self):
        with patch(
            "core.power_controller.get_power_devices",
            return_value=(True, "OK", [{"device": "main_psu", "status": "error"}]),
        ):
            with self.assertRaisesRegex(PowerControllerError, "entered error state"):
                MoonrakerPowerController("main_psu").wait_until_ready(timeout=1)

    def test_missing_configured_device_is_a_clear_error(self):
        with patch(
            "core.power_controller.get_power_devices",
            return_value=(True, "OK", [{"device": "lights", "status": "on"}]),
        ):
            with self.assertRaisesRegex(
                PowerControllerError, "main_psu.*not configured"
            ):
                MoonrakerPowerController("main_psu").get_status()

    def test_power_device_identity_is_loaded_from_bootstrap_config(self):
        with TemporaryDirectory() as directory:
            config = f"{directory}/power.json"
            with open(config, "w", encoding="utf-8") as output:
                json.dump({"schema": 1, "enabled": True, "device": "main_psu"}, output)
            loaded = load_power_config(config)
        self.assertTrue(loaded["enabled"])
        self.assertEqual(loaded["device"], "main_psu")
        self.assertTrue(loaded["legacy"])

    def test_invalid_power_config_shape_fails_clearly(self):
        with TemporaryDirectory() as directory:
            config = f"{directory}/power.json"
            with open(config, "w", encoding="utf-8") as output:
                output.write("[]")
            with self.assertRaisesRegex(PowerControllerError, "JSON object"):
                load_power_config(config)

    def test_firmware_installation_reuses_the_configured_controller(self):
        from core import deployer

        events = []
        controller = Mock()
        controller.power_on.side_effect = lambda: events.append("on") or "on"
        controller.power_off.side_effect = lambda: events.append("off") or "off"

        class FakeDeployer:
            def __init__(self, _client, _manifest, **kwargs):
                self.kwargs = kwargs

            def run(self):
                identity = SimpleNamespace(
                    physical_port="usb-1",
                    physical_path="usb-1:1.0",
                    by_path=("/dev/serial/by-path/usb-1",),
                    vid_pid="1d50:614e",
                    serial="stable",
                )
                assessment = SimpleNamespace(
                    baseline=identity,
                    candidate=identity,
                    reasons=("manual confirmation test",),
                    score=80,
                    automatic_threshold=90,
                )
                self_test.assertTrue(
                    self.kwargs["identity_confirmation_prompt"](assessment)
                )
                self_test.assertTrue(self.kwargs["power_cycle_prompt"]())
                events.append("power_off_confirmed")
                self.kwargs["power_off"]()
                self_test.assertTrue(self.kwargs["media_installation_prompt"]())
                events.append("media_installed")
                self.kwargs["power_on"]()
                events.append("firmware")
                return "done"

        self_test = self
        monitor_args = {}

        def make_monitor(_path, **kwargs):
            monitor_args.update(kwargs)
            return SimpleNamespace()

        digest = "a" * 64
        identity = FirmwareBuildInputs.create(
            klipper_commit="1" * 40,
            canonical_config='CONFIG_MCU="stm32"\n',
            toolchain=ToolchainIdentity("make", "GNU Make 4.4", "gcc", "gcc 13"),
            build_id="2" * 32,
        ).complete(
            artifact_sha256=digest,
            artifact_size=4096,
            artifact_format="bin",
        )
        artifact = SimpleNamespace(
            firmware_identity=identity,
            sha256=digest,
            provenance=BuildProvenance.REAL,
            flashable=True,
        )
        user_data = {
            "mcu_path": "/dev/serial/by-id/test",
            "prepared_firmware_deployment": SimpleNamespace(
                plan=SimpleNamespace(
                    method=SimpleNamespace(value="MANUAL"),
                    artifact=artifact,
                    profile=SimpleNamespace(
                        strategy=DeploymentStrategyId.SD_CARD,
                        usb=SimpleNamespace(
                            application_vid_pids=("1d50:614e",),
                            bootloader_vid_pids=(),
                        ),
                    ),
                ),
                sha256=digest,
            ),
            "firmware_deployment_service": Mock(),
        }

        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "core.power_controller.configured_power_controller",
                    return_value=controller,
                )
            )
            stack.enter_context(patch("core.moonraker_deployer.Deployer", FakeDeployer))
            stack.enter_context(
                patch("core.mcu_monitor.McuPresenceMonitor", side_effect=make_monitor)
            )
            stack.enter_context(
                patch(
                    "core.deployer._generated_config_bytes",
                    return_value=("generated.cfg", b"[mcu]\n[printer]\n", None),
                )
            )
            stack.enter_context(patch("core.deployer._preflight_check", return_value=True))
            stack.enter_context(
                patch(
                    "core.config_transaction.MoonrakerConfigTransport.read_files",
                    return_value={},
                )
            )
            stack.enter_context(patch("core.menu.yes_no", return_value=True))
            stack.enter_context(patch("core.snapshot.create_snapshot", return_value=None))
            self.assertEqual(deployer.deploy_firmware_installation(user_data), "done")

        self.assertEqual(
            events,
            [
                "on",
                "power_off_confirmed",
                "off",
                "media_installed",
                "on",
                "firmware",
            ],
        )
        self.assertEqual(controller.power_on.call_count, 2)
        controller.power_off.assert_called_once_with()
        self.assertEqual(monitor_args["expected_vid_pids"], ("1d50:614e",))
