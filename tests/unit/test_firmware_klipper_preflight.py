"""C3 firmware gate: fail closed and bind decisions to reviewed plan bytes."""
from dataclasses import replace
from unittest.mock import Mock

import pytest

from core import config_transaction, deployer, klipper_preflight, managed_config
from core.moonraker_deployer import DeployResult, DeployState
from tests.unit import test_deployer as firmware_fixtures


@pytest.fixture
def firmware_environment(monkeypatch, tmp_path):
    files = {"printer.cfg": b"# original\n"}
    generated = b"[mcu]\nserial: /dev/serial/by-id/test\n[printer]\nkinematics: cartesian\n"
    monkeypatch.setattr(deployer, "_generated_config_bytes", lambda _user: ("generated.cfg", generated, None))
    monkeypatch.setattr(deployer, "_preflight_check", lambda *_args: True)
    transport = config_transaction.MoonrakerConfigTransport
    monkeypatch.setattr(transport, "validate_activation_target", lambda _self: None)
    monkeypatch.setattr(transport, "supports_conditional_write", lambda _self, _prior: True)
    monkeypatch.setattr(transport, "read_files", lambda _self, names: {n: files.get(n) for n in names})
    review = Mock(return_value=True)
    monkeypatch.setattr(deployer, "_interactive_configuration_review", review)
    import core.snapshot as snapshot_module
    real_snapshot = snapshot_module.create_snapshot
    take_snapshot = Mock(side_effect=lambda originals, **kw: real_snapshot(originals, persist_root=str(tmp_path), **kw))
    monkeypatch.setattr(snapshot_module, "create_snapshot", take_snapshot)
    import core.power_controller as power_module
    power = Mock(return_value=None)
    monkeypatch.setattr(power_module, "configured_power_controller", power)
    import core.mcu_monitor as monitor_module
    monkeypatch.setattr(monitor_module, "McuPresenceMonitor", Mock())
    import core.moonraker_deployer as physical_module
    physical = Mock()
    monkeypatch.setattr(physical_module, "Deployer", physical)
    user = firmware_fixtures.FirmwareInstallationPreconditionTests()._user()
    return user, files, review, take_snapshot, power, physical


@pytest.mark.parametrize("status", ["invalid", "unverified"])
@pytest.mark.parametrize("noop", [False, True])
def test_firmware_preflight_failure_precedes_review_power_and_firmware(monkeypatch, firmware_environment, status, noop):
    user, _files, review, snapshot, power, physical = firmware_environment
    if noop:
        original = managed_config.build_managed_config_plan
        def unchanged(*args, **kwargs):
            plan = original(*args, **kwargs)
            return replace(plan, artifacts=tuple(replace(a, previous=a.content) for a in plan.artifacts))
        monkeypatch.setattr(managed_config, "build_managed_config_plan", unchanged)
    called = Mock(side_effect=lambda plan: klipper_preflight.PreflightResult(status, "fixture failure", klipper_preflight.plan_digest(plan)))
    monkeypatch.setattr(klipper_preflight, "validate_plan", called)
    result = deployer.deploy_firmware_installation(user)
    assert result.state == DeployState.FAILED_PRECONDITION
    assert status in result.detail
    called.assert_called_once()
    review.assert_not_called()
    snapshot.assert_not_called()
    power.assert_not_called()
    physical.assert_not_called()
    user["firmware_deployment_service"].execute.assert_not_called()


def test_firmware_rejects_plan_changed_during_review(monkeypatch, firmware_environment):
    user, _files, review, snapshot, power, physical = firmware_environment
    plan_holder = []
    def validate(plan):
        plan_holder.append(plan)
        return klipper_preflight.PreflightResult("valid", "fixture", klipper_preflight.plan_digest(plan))
    monkeypatch.setattr(klipper_preflight, "validate_plan", validate)
    def mutate(_review, _yes_no):
        plan = plan_holder[0]
        artifact = replace(plan.artifacts[0], content=b"# changed after preflight\n")
        object.__setattr__(plan, "artifacts", (artifact,) + plan.artifacts[1:])
        return True
    review.side_effect = mutate
    result = deployer.deploy_firmware_installation(user)
    assert result.state == DeployState.FAILED_PRECONDITION
    assert "plan changed" in result.detail
    snapshot.assert_not_called()
    power.assert_not_called()
    physical.assert_not_called()
    user["firmware_deployment_service"].execute.assert_not_called()


def test_firmware_rechecks_plan_before_upload(monkeypatch, firmware_environment):
    user, _files, _review, _snapshot, _power, physical = firmware_environment
    plan_holder = []
    def validate(plan):
        plan_holder.append(plan)
        return klipper_preflight.PreflightResult("valid", "fixture", klipper_preflight.plan_digest(plan))
    monkeypatch.setattr(klipper_preflight, "validate_plan", validate)
    def simulate_firmware_boundary():
        plan = plan_holder[0]
        object.__setattr__(plan, "artifacts", (replace(plan.artifacts[0], content=b"# stale\n"),) + plan.artifacts[1:])
        try:
            physical.call_args.kwargs["before_config_upload"]()
        except Exception as exc:
            return DeployResult(DeployState.FAILED_PRECONDITION, str(exc))
        return DeployResult(DeployState.DONE, "unexpected upload")
    physical.return_value.run.side_effect = simulate_firmware_boundary
    result = deployer.deploy_firmware_installation(user)
    assert result.state == DeployState.FAILED_PRECONDITION
    assert "plan changed" in result.detail


def test_real_unavailable_receipt_blocks_before_review(monkeypatch, firmware_environment, tmp_path):
    user, _files, review, snapshot, power, physical = firmware_environment
    monkeypatch.setenv("KACE_KLIPPER_PREFLIGHT_RECEIPT", str(tmp_path / "missing-receipt.json"))
    result = deployer.deploy_firmware_installation(user)
    assert result.state == DeployState.FAILED_PRECONDITION
    assert "preflight unverified" in result.detail
    review.assert_not_called()
    snapshot.assert_not_called()
    power.assert_not_called()
    physical.assert_not_called()
    user["firmware_deployment_service"].execute.assert_not_called()


def test_firmware_rechecks_plan_before_service(monkeypatch, firmware_environment):
    user, _files, _review, _snapshot, _power, physical = firmware_environment
    plans = []
    def validate(plan):
        plans.append(plan)
        return klipper_preflight.PreflightResult("valid", "fixture", klipper_preflight.plan_digest(plan))
    monkeypatch.setattr(klipper_preflight, "validate_plan", validate)
    def simulate_boundary():
        plan = plans[0]
        object.__setattr__(plan, "artifacts", (replace(plan.artifacts[0], content=b"# stale\n"),) + plan.artifacts[1:])
        try:
            physical.call_args.kwargs["firmware_deploy"]()
        except Exception as exc:
            return DeployResult(DeployState.FAILED_PRECONDITION, str(exc))
        return DeployResult(DeployState.DONE, "unexpected firmware action")
    physical.return_value.run.side_effect = simulate_boundary
    result = deployer.deploy_firmware_installation(user)
    assert result.state == DeployState.FAILED_PRECONDITION
    assert "plan changed" in result.detail
    user["firmware_deployment_service"].execute.assert_not_called()
