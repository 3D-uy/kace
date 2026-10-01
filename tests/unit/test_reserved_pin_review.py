"""Destination includes cannot bypass compiled BLTouch pin reservations."""
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.deployer import _run_config_transaction, _copy_artifacts
from core.firmware_workflow import generation_pin_reservations
from core.managed_config import build_managed_config_plan
from core.workflow_outcome import WorkflowOutcome
from tests.unit.test_config_transaction import FakeTransport, GENERATED
from tests.unit.test_firmware_pin_reservations import artifact, resumed_user, FINGERPRINT

PROBE = (GENERATED + b"# PROBE_CALIBRATE\n[stepper_z]\nendstop_pin: probe:z_virtual_endstop\n"
         b"[bltouch]\nsensor_pin: ^PB8\ncontrol_pin: PB9\n")


def files(pin=b"PB14"):
    return {"printer.cfg": GENERATED + b"[include user.cfg]\n",
            "user.cfg": b"[bltouch]\ncontrol_pin: " + pin + b"\n"}


def assert_untouched(transport, original):
    assert transport.files == original
    assert not any(call[0] in ("upload", "delete", "restart", "restart_moonraker")
                   for call in transport.calls)


def test_live_adapter_rejects_reserved_include_before_every_write(tmp_path):
    built = artifact(tmp_path, {"RESERVE_PINS_USB1": "PB14,PB15"})
    transport = FakeTransport(files())
    original = dict(transport.files)
    with patch("core.deployer._preflight_check", return_value=True), patch(
        "core.deployer._interactive_configuration_review", return_value=True
    ):
        result = _run_config_transaction(transport, {"firmware_artifact": built}, "none",
                                         generated=(str(tmp_path / "source.cfg"), PROBE, None))
    assert result.outcome == WorkflowOutcome.PRECONDITION_FAILED
    assert "USB1" in result.detail
    assert_untouched(transport, original)


@pytest.mark.parametrize("resume", [False, True])
def test_nested_include_reservation_survives_reconciliation_and_resume(tmp_path, resume):
    built = artifact(tmp_path, {"RESERVE_PINS_USB1": "PB14,PB15"})
    user = resumed_user(built) if resume else {"firmware_artifact": built}
    remote = files(b"HEADER")
    remote["user.cfg"] = b"[include pins.cfg]\n" + remote["user.cfg"]
    remote["pins.cfg"] = b"[board_pins custom]\naliases: HEADER=PB14\n"
    transport = FakeTransport(remote)
    original = dict(transport.files)
    confirm = Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, PROBE, None, activation="none", confirm=confirm,
        snapshot_root=str(tmp_path / "snapshots"),
        firmware_reservation_reader=lambda hardware: generation_pin_reservations(user, config=hardware)).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "USB1" in result.detail
    confirm.assert_not_called()
    assert_untouched(transport, original)


def test_include_only_bltouch_still_requests_evidence(tmp_path):
    built = artifact(tmp_path, {"RESERVE_PINS_USB1": "PB14,PB15"})
    remote = {"printer.cfg": GENERATED + b"[include user.cfg]\n",
              "user.cfg": b"[bltouch]\nsensor_pin: ^PB8\ncontrol_pin: PB14\n"}
    reader = Mock(side_effect=lambda hardware: generation_pin_reservations({"firmware_artifact": built}, config=hardware))
    plan = build_managed_config_plan(GENERATED, None, remote)
    result = validate_configuration_plan(plan, firmware_reservation_reader=reader)
    reader.assert_called_once()
    assert any(item.code == "bltouch-pin-conflict" and "USB1" in item.message for item in result.errors)


def test_valid_reservations_allow_publication(tmp_path):
    built = artifact(tmp_path, {"RESERVE_PINS_USB": "PA11,PA12"})
    transport = FakeTransport(files())
    result = ConfigDeploymentTransaction(transport, PROBE, None, activation="none",
        snapshot_root=str(tmp_path / "snapshots"),
        firmware_reservation_reader=lambda hardware: generation_pin_reservations({"firmware_artifact": built}, config=hardware)).run()
    assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    assert any(call[0] == "upload" for call in transport.calls)
    assert not any(call[0] == "restart" for call in transport.calls)


def test_firmware_changed_during_confirmation_blocks_publication(tmp_path):
    built = artifact(tmp_path, {"RESERVE_PINS_USB": "PA11,PA12"})
    transport = FakeTransport(files())
    original = dict(transport.files)
    def confirm(_):
        Path(built.path).write_bytes(b"tampered after review")
        return True
    result = ConfigDeploymentTransaction(transport, PROBE, None, activation="none", confirm=confirm,
        snapshot_root=str(tmp_path / "snapshots"),
        firmware_reservation_reader=lambda hardware: generation_pin_reservations({"firmware_artifact": built}, config=hardware)).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "firmware" in result.detail
    assert_untouched(transport, original)


def test_unavailable_metadata_is_reported_as_an_error_not_no_reservations(tmp_path):
    built = artifact(tmp_path, payload=FINGERPRINT.encode())
    plan = build_managed_config_plan(PROBE, None, files())
    result = validate_configuration_plan(plan,
        firmware_reservation_reader=lambda hardware: generation_pin_reservations({"firmware_artifact": built}, config=hardware))
    assert any(item.code == "firmware-pin-evidence" for item in result.errors)


def test_no_bltouch_does_not_require_probe_firmware_evidence():
    reader = Mock(side_effect=AssertionError("irrelevant firmware read"))
    result = validate_configuration_plan(build_managed_config_plan(GENERATED, None, {}),
                                          firmware_reservation_reader=reader)
    assert result.valid
    reader.assert_not_called()


def test_local_export_adapter_rejects_reserved_include(tmp_path):
    built = artifact(tmp_path, {"RESERVE_PINS_USB1": "PB14,PB15"})
    destination = tmp_path / "export"
    destination.mkdir()
    for name, content in files().items():
        (destination / name).write_bytes(content)
    original = {p.name: p.read_bytes() for p in destination.iterdir()}
    with patch("core.deployer._generated_config_bytes", return_value=("source.cfg", PROBE, None)), patch(
        "core.deployer._review_configuration_export", return_value=True
    ):
        assert not _copy_artifacts({"firmware_artifact": built}, str(destination), "config")
    assert {p.name: p.read_bytes() for p in destination.iterdir()} == original


def test_noop_retry_cannot_skip_reserved_pin_review(tmp_path):
    built = artifact(tmp_path, {"RESERVE_PINS_USB1": "PB14,PB15"})
    remote = files()
    initial = build_managed_config_plan(PROBE, None, remote)
    remote.update({item.remote_name: item.content for item in initial.artifacts})
    assert not build_managed_config_plan(PROBE, None, remote).changed_artifacts
    transport = FakeTransport(remote)
    result = ConfigDeploymentTransaction(transport, PROBE, None, activation="none",
        snapshot_root=str(tmp_path / "snapshots"), verify_existing_ready=True,
        firmware_reservation_reader=lambda hardware: generation_pin_reservations({"firmware_artifact": built}, config=hardware)).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "USB1" in result.detail
    assert_untouched(transport, remote)


@pytest.mark.parametrize("tamper_during_review", [False, True])
def test_physical_adapter_rejects_before_power_or_flash(tmp_path, tamper_during_review):
    from core.deployer import deploy_firmware_installation
    from core.moonraker_deployer import DeployState
    from tests.unit.test_deployer import FirmwareInstallationPreconditionTests

    constants = {"RESERVE_PINS_USB": "PA11,PA12"} if tamper_during_review else {"RESERVE_PINS_USB1": "PB14,PB15"}
    built = artifact(tmp_path, constants)
    user = FirmwareInstallationPreconditionTests()._user()
    prepared = user["prepared_firmware_deployment"]
    prepared.plan.artifact = built
    prepared.sha256 = built.sha256
    prepared.staged_path = built.path
    transport = FakeTransport(files())
    original = dict(transport.files)
    def review(*_):
        if tamper_during_review:
            Path(built.path).write_bytes(b"changed after review")
        return True
    with patch("core.config_transaction.configuration_transport", return_value=transport), patch(
        "core.deployer._preflight_check", return_value=True
    ), patch("core.deployer._generated_config_bytes", return_value=("source.cfg", PROBE, None)), patch(
        "core.deployer._interactive_configuration_review", side_effect=review
    ), patch("core.power_controller.configured_power_controller") as power:
        result = deploy_firmware_installation(user)
    assert result.state == DeployState.FAILED_PRECONDITION
    user["firmware_deployment_service"].execute.assert_not_called()
    power.assert_not_called()
    assert_untouched(transport, original)
