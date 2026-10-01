"""Preserved driver registers must satisfy their official parser contracts."""
from unittest.mock import Mock, patch

import pytest

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.exceptions import GenerationError
from core.generator import generate_config
from core.managed_config import build_managed_config_plan
from core.profile_values import resolve_tmc_sections
from tests.unit.test_config_transaction import FakeTransport, GENERATED
from tests.unit.test_tmc_electrical_authority import inputs
from tests.unit.test_tmc_uart_review import remote_files


CASES = [
    ("tmc2209", "sgthrs", "0", True), ("tmc2209", "sgthrs", "255", True),
    ("tmc2209", "sgthrs", "256", False), ("tmc2209", "sgthrs", "-1", False),
    ("tmc2130", "sgt", "-64", True), ("tmc2130", "sgt", "63", True),
    ("tmc2130", "sgt", "-65", False), ("tmc5160", "sgt", "64", False),
    ("tmc2208", "toff", "15", True), ("tmc2208", "toff", "16", False),
    ("tmc2208", "hstrt", "8", False), ("tmc5160", "bbmtime", "32", False),
    ("tmc2130", "w0", "4", False), ("tmc5160", "mslut7", "4294967295", True),
    ("tmc5160", "mslut7", "4294967296", False),
    ("tmc2209", "pwm_autoscale", "yes", True), ("tmc2208", "pwm_autoscale", "OFF", True),
    ("tmc5160", "fd3", "2", False), ("tmc2130", "sfilt", "invalid", False),
    ("tmc2209", "sgthrs", "1.0", False), ("tmc2209", "sgthrs", "1e2", False),
    ("tmc2209", "sgthrs", "nan", False), ("tmc2209", "sgthrs", "0xff", False),
]


@pytest.mark.parametrize("model,field,value,accepted", CASES)
def test_selected_register_value(model, field, value, accepted):
    board, _, user, name = inputs(model)
    board[name]["driver_" + field.upper()] = value
    if accepted:
        assert resolve_tmc_sections(board, user)[name]["driver_" + field] == value
    else:
        with pytest.raises(GenerationError, match="driver_" + field):
            resolve_tmc_sections(board, user)


@pytest.mark.parametrize("model,field,value,accepted", CASES)
def test_effective_included_register_value(model, field, value, accepted):
    pin = "uart_pin" if model in ("tmc2208", "tmc2209") else "cs_pin"
    remote = remote_files(f"[{model} stepper_x]\n{pin}: PC11\nrun_current: .580\ndriver_{field}: {value}\n")
    result = validate_configuration_plan(build_managed_config_plan(GENERATED, None, remote))
    assert result.valid == accepted, result
    if not accepted:
        assert any(e.code == "tmc-register-value" and field in e.message for e in result.errors)


@pytest.mark.parametrize("noop", (False, True))
def test_invalid_preserved_register_blocks_before_writes(tmp_path, noop):
    remote = remote_files("[tmc2209 stepper_x]\nuart_pin: PC11\nrun_current: .580\ndriver_SGTHRS: 256\n")
    if noop:
        plan = build_managed_config_plan(GENERATED, None, remote)
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        assert not build_managed_config_plan(GENERATED, None, remote).changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, GENERATED, None, activation="none", confirm=confirm,
        snapshot_root=str(tmp_path / "snapshots"), verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "sgthrs" in result.detail
    confirm.assert_not_called()
    assert transport.files == remote
    assert not any(call[0] in ("upload", "delete", "restart") for call in transport.calls)


def test_render_override_is_checked_before_output(tmp_path):
    from jinja2 import Template
    render = Template.render
    board, _, user, name = inputs()
    user["z_motors"] = "1"
    board[name]["driver_sgthrs"] = "255"
    def inject(template, *args, **kwargs):
        return render(template, *args, **kwargs).replace("driver_sgthrs: 255", "driver_sgthrs: 256")
    output = tmp_path / "printer.cfg"
    with patch.object(Template, "render", inject), pytest.raises(GenerationError, match="sgthrs"):
        generate_config(board, user, output_path=str(output), verbose=False)
    assert not output.exists()


@pytest.mark.parametrize("value,accepted", [("255", True), ("256", False)])
def test_migrated_register_is_reviewed(value, accepted):
    generated = GENERATED + b"\n[tmc2209 stepper_x]\nuart_pin: PC11\nrun_current: .580\n"
    remote = {"printer.cfg": generated + f"driver_SGTHRS: {value}\n".encode()}
    plan = build_managed_config_plan(generated, None, remote)
    assert any(f"driver_sgthrs: {value}" in a.content.decode().lower() for a in plan.artifacts)
    result = validate_configuration_plan(plan)
    assert result.valid == accepted, result


@pytest.mark.parametrize("value,accepted", [("yes", True), ("2", False)])
def test_tmc2225_uses_native_2208_register_contract(value, accepted):
    board, _, user, name = inputs("tmc2208")
    user["driver_type"] = "TMC2225"
    board[name]["driver_pwm_autoscale"] = value
    if accepted:
        assert resolve_tmc_sections(board, user)[name]["driver_pwm_autoscale"] == value
    else:
        with pytest.raises(GenerationError, match="driver_pwm_autoscale"):
            resolve_tmc_sections(board, user)
