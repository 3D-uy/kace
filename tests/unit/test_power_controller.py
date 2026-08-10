import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from core.power_controller import (
    MoonrakerPowerController,
    PowerControllerError,
    load_power_config,
)
from firmware.artifacts import BuildProvenance
from firmware.deployment import DeploymentStrategyId
from firmware.identity import FirmwareBuildInputs, ToolchainIdentity


def test_get_status_selects_the_configured_power_device():
    devices = [
        {"device": "lights", "status": "off"},
        {"device": "main_psu", "status": "on"},
    ]
    with patch("core.power_controller.get_power_devices", return_value=(True, "OK", devices)):
        controller = MoonrakerPowerController("main_psu")
        assert controller.get_status() == "on"


def test_power_on_uses_moonraker_and_confirms_final_state():
    states = [
        (True, "OK", [{"device": "main_psu", "status": "off"}]),
        (True, "OK", [{"device": "main_psu", "status": "on"}]),
    ]
    with patch("core.power_controller.get_power_devices", side_effect=states), patch(
        "core.power_controller.set_power_device", return_value=(True, "OK")
    ) as set_device:
        controller = MoonrakerPowerController("main_psu", poll_interval=0)
        assert controller.power_on(timeout=1) == "on"
    set_device.assert_called_once_with(
        "localhost", 7125, "main_psu", "on", api_key=None
    )


def test_wait_until_ready_fails_when_moonraker_reports_error():
    with patch(
        "core.power_controller.get_power_devices",
        return_value=(True, "OK", [{"device": "main_psu", "status": "error"}]),
    ):
        with pytest.raises(PowerControllerError, match="entered error state"):
            MoonrakerPowerController("main_psu").wait_until_ready(timeout=1)


def test_missing_configured_device_is_a_clear_error():
    with patch(
        "core.power_controller.get_power_devices",
        return_value=(True, "OK", [{"device": "lights", "status": "on"}]),
    ):
        with pytest.raises(PowerControllerError, match="main_psu.*not configured"):
            MoonrakerPowerController("main_psu").get_status()


def test_power_device_identity_is_loaded_from_bootstrap_config(tmp_path):
    config = tmp_path / "power.json"
    config.write_text(
        json.dumps({"schema": 1, "enabled": True, "device": "main_psu"}),
        encoding="utf-8",
    )
    loaded = load_power_config(str(config))
    assert loaded["enabled"] is True
    assert loaded["device"] == "main_psu"
    assert loaded["legacy"] is True


def test_invalid_power_config_shape_fails_clearly(tmp_path):
    config = tmp_path / "power.json"
    config.write_text("[]", encoding="utf-8")
    with pytest.raises(PowerControllerError, match="JSON object"):
        load_power_config(str(config))


def test_firmware_installation_reuses_the_configured_controller(monkeypatch):
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
            assert self.kwargs["identity_confirmation_prompt"](assessment) is True
            assert self.kwargs["power_cycle_prompt"]() is True
            events.append("power_off_confirmed")
            self.kwargs["power_off"]()
            assert self.kwargs["media_installation_prompt"]() is True
            events.append("media_installed")
            self.kwargs["power_on"]()
            events.append("firmware")
            return "done"

    monkeypatch.setattr(
        "core.power_controller.configured_power_controller",
        lambda **_kwargs: controller,
    )
    monkeypatch.setattr("core.moonraker_deployer.Deployer", FakeDeployer)
    monitor_args = {}

    def make_monitor(_path, **kwargs):
        monitor_args.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr("core.mcu_monitor.McuPresenceMonitor", make_monitor)
    monkeypatch.setattr(
        deployer,
        "_generated_config_bytes",
        lambda: ("generated.cfg", b"[mcu]\n[printer]\n", None),
    )
    monkeypatch.setattr(deployer, "_preflight_check", lambda *_args: True)
    monkeypatch.setattr(
        "core.config_transaction.MoonrakerConfigTransport.read_files",
        lambda *_args: {},
    )
    monkeypatch.setattr("core.menu.yes_no", lambda *_args, **_kwargs: True)
    monkeypatch.setattr("core.snapshot.create_snapshot", lambda *_args, **_kwargs: None)

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
    assert deployer.deploy_firmware_installation(user_data) == "done"
    assert events == [
        "on",
        "power_off_confirmed",
        "off",
        "media_installed",
        "on",
        "firmware",
    ]
    assert controller.power_on.call_count == 2
    controller.power_off.assert_called_once_with()
    assert monitor_args["expected_vid_pids"] == ("1d50:614e",)
