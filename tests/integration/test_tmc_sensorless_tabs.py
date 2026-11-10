"""Sensorless checks run before simulated publication for tabbed drivers."""
from unittest.mock import Mock

import pytest

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.managed_config import build_managed_config_plan
from tests.unit.test_config_transaction import FakeTransport, GENERATED
from tests.unit.test_sensorless_homing_enforcement import _sensorless
from tests.unit.test_tmc_spi_chain import config_text


@pytest.mark.parametrize("source", ("root", "include", "save"))
@pytest.mark.parametrize("noop", (False, True))
def test_tabbed_driver_valid_sensorless_not_falsely_rejected(tmp_path, source, noop):
    data = _sensorless()
    data["tmc2209\tstepper_x"] = data.pop("tmc2209 stepper_x")
    text = config_text(data).encode()
    if source == "root":
        remote = {"printer.cfg": GENERATED + b"\n" + text}
    elif source == "include":
        remote = {"printer.cfg": GENERATED + b"\n[include user.cfg]\n", "user.cfg": text}
    else:
        text = text.replace(b"diag_pin: ^PC6\n", b"")
        remote = {"printer.cfg": GENERATED + b"\n" + text +
                  b"\n#*# <---------------------- SAVE_CONFIG ---------------------->\n"
                  b"#*# DO NOT EDIT THIS BLOCK OR BELOW. The contents are auto-generated.\n#*#\n"
                  b"#*# [tmc2209\tstepper_x]\n#*# diag_pin = ^PC6\n"}
    plan = build_managed_config_plan(GENERATED, None, remote)
    if noop:
        remote.update({item.remote_name: item.content for item in plan.artifacts})
        plan = build_managed_config_plan(GENERATED, None, remote)
        assert not plan.changed_artifacts
    review = validate_configuration_plan(plan)
    assert review.valid, review.errors
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, GENERATED, None, activation="none",
        confirm=confirm, snapshot_root=str(tmp_path / "snapshots"), output=lambda _: None).run()
    assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    assert confirm.call_count == 1
    if noop:
        assert not [c for c in transport.calls if c[0] in ("upload", "delete")]


@pytest.mark.parametrize("separator", (" ", "\t", "  "))
@pytest.mark.parametrize("source", ("root", "include", "save"))
@pytest.mark.parametrize("noop", (False, True))
def test_corexy_other_motor_hold_current_blocks_publication(tmp_path, separator, source, noop):
    generated = GENERATED.replace(b"kinematics: cartesian", b"kinematics: corexy")
    data = _sensorless(kinematics="corexy")
    data["stepper_y"] = {"endstop_pin": "PB3"}
    section = "tmc2209" + separator + "stepper_y"
    data[section] = {"uart_pin": "PC12", "run_current": ".580"}
    if source != "save":
        data[section]["hold_current"] = ".4"
    text = config_text(data).encode()
    if source == "root":
        remote = {"printer.cfg": generated + b"\n" + text}
    elif source == "include":
        remote = {"printer.cfg": generated + b"\n[include user.cfg]\n", "user.cfg": text}
    else:
        remote = {"printer.cfg": generated + b"\n" + text +
                  b"\n#*# <---------------------- SAVE_CONFIG ---------------------->\n"
                  b"#*# DO NOT EDIT THIS BLOCK OR BELOW. The contents are auto-generated.\n#*#\n" +
                  ("#*# [" + section + "]\n#*# hold_current = .4\n").encode()}
    plan = build_managed_config_plan(generated, None, remote)
    if noop:
        remote.update({item.remote_name: item.content for item in plan.artifacts})
        plan = build_managed_config_plan(generated, None, remote)
        assert not plan.changed_artifacts
    review = validate_configuration_plan(plan)
    assert not review.valid and any(e.code == "tmc-sensorless" and "hold_current" in e.message for e in review.errors)
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    before = dict(transport.files)
    result = ConfigDeploymentTransaction(transport, generated, None, activation="none",
        confirm=confirm, snapshot_root=str(tmp_path / "snapshots"), output=lambda _: None).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    confirm.assert_not_called()
    assert transport.files == before
    assert not [c for c in transport.calls if c[0] in ("upload", "delete", "restart")]
