"""Validate preserved heater protection without importing upstream tuning."""
from unittest.mock import Mock

import pytest

from core.configuration_review import validate_configuration_plan
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.managed_config import build_managed_config_plan, effective_hardware_text, _section_options
from tests.unit.test_config_transaction import FakeTransport, GENERATED as BASE

GENERATED = BASE + b"""[extruder]
heater_pin: PA4
sensor_pin: PA5
sensor_type: EPCOS 100K B57560G104F
control: watermark
min_temp: 0
max_temp: 250
[heater_bed]
heater_pin: PA6
sensor_pin: PA7
sensor_type: EPCOS 100K B57560G104F
control: watermark
min_temp: 0
max_temp: 130
"""

INVALID = [(key, value) for key in ("max_error", "hysteresis", "heating_gain", "check_gain_time")
           for value in ("nan", "inf", "-inf", "invalid")]
INVALID += [("max_error", "-1"), ("hysteresis", "-1"), ("heating_gain", "0"),
            ("check_gain_time", "0.99"), ("unknown_option", "1")]


def remote_plan(options, name="verify_heater heater_bed", noop=False):
    initial = build_managed_config_plan(GENERATED, None, {})
    remote = {a.remote_name: a.content for a in initial.artifacts}
    remote["printer.cfg"] += b"[include user.cfg]\n"
    remote["user.cfg"] = f"[{name}]\n{options}\n".encode()
    if noop:
        remote.update({a.remote_name: a.content for a in build_managed_config_plan(GENERATED, None, remote).artifacts})
    plan = build_managed_config_plan(GENERATED, None, remote)
    if noop:
        assert not plan.changed_artifacts
    return remote, plan


@pytest.mark.parametrize("option,value", INVALID)
@pytest.mark.parametrize("noop", [False, True])
def test_invalid_preserved_protection_stops_before_confirm_or_write(tmp_path, option, value, noop):
    remote, plan = remote_plan(f"{option}: {value}", noop=noop)
    assert _section_options(effective_hardware_text(plan))["verify_heater heater_bed"][option] == value
    review = validate_configuration_plan(plan)
    assert not review.valid and any(m.code == "verify-heater" and option in m.message
                                   and "reference" not in m.message for m in review.errors)
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, GENERATED, None, activation="none", confirm=confirm,
        snapshot_root=str(tmp_path / "snapshots"), verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "verify_heater" in result.detail
    confirm.assert_not_called()
    assert all(call[0] == "read" for call in transport.calls)
    assert transport.files == remote


@pytest.mark.parametrize("name", ["verify_heater missing", "verify_heater Heater_Bed", "verify_heater extruder0", "verify_heater"])
def test_unknown_or_misspelled_heater_is_not_repaired_by_case_folding(name):
    _, plan = remote_plan("max_error: 120", name=name)
    assert f"[{name}]" in effective_hardware_text(plan)
    review = validate_configuration_plan(plan)
    assert not review.valid and any(m.code == "verify-heater" for m in review.errors)


@pytest.mark.parametrize("options", ["", "max_error: 0\nhysteresis: 0\nheating_gain: .1\ncheck_gain_time: 1",
                                    "heating_gain: 1\ncheck_gain_time: 120", "check_gain_time: 240", "check_gain_time: 600"])
@pytest.mark.parametrize("noop", [False, True])
def test_finite_upstream_valid_user_settings_are_preserved_without_retuning(options, noop):
    remote, plan = remote_plan(options, noop=noop)
    before = remote["user.cfg"]
    review = validate_configuration_plan(plan)
    assert review.valid, review.errors
    assert remote["user.cfg"] == before
    assert _section_options(effective_hardware_text(plan))["verify_heater heater_bed"] == _section_options(before.decode())["verify_heater heater_bed"]


def test_exact_custom_heater_reference_is_recognized_without_certifying_its_circuit():
    _, plan = remote_plan("max_error: 120\n[heater_generic Chamber]\nheater_pin: PA8\n", name="verify_heater Chamber")
    review = validate_configuration_plan(plan)
    assert not any(m.code == "verify-heater" for m in review.errors)


def test_commented_example_does_not_create_an_active_verifier():
    remote, _ = remote_plan("")
    remote["user.cfg"] = b"#[verify_heater missing]\n#max_error: nan\n"
    review = validate_configuration_plan(build_managed_config_plan(GENERATED, None, remote))
    assert review.valid, review.errors
