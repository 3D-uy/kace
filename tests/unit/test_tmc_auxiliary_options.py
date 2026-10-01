"""Optional TMC settings are validated without inventing defaults."""
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


MODELS = ("tmc2208", "tmc2209", "tmc2130", "tmc5160")
BOOLEAN_CASES = [(None, True), ("true", True), ("FALSE", True), ("yes", True),
    ("NO", True), ("on", True), ("OFF", True), ("0", True), ("1", True),
    ("2", False), ("", False), ("none", False), ("1.0", False)]
THRESHOLD_CASES = [(None, True), ("0", True), ("-0.0", True), ("0.5", True),
    ("100", True), ("1e3", True), ("1e30", True), ("-1", False), ("", False),
    ("invalid", False), ("nan", False), ("inf", False), ("-inf", False)]


def cases():
    for model in MODELS:
        for value, valid in BOOLEAN_CASES:
            yield model, "interpolate", value, valid
        for option in ("coolstep_threshold", "high_velocity_threshold"):
            supported = model in (("tmc2209", "tmc2130", "tmc5160") if option == "coolstep_threshold" else ("tmc2130", "tmc5160"))
            for value, valid in THRESHOLD_CASES:
                yield model, option, value, valid and (supported or value is None)


@pytest.mark.parametrize("model,option,value,valid", list(cases()))
def test_selected_optional_setting(model, option, value, valid):
    board, _, user, name = inputs(model)
    if value is not None:
        board[name][option] = value
    if valid:
        result = resolve_tmc_sections(board, user)[name]
        assert (result[option] == value) if value is not None else (option not in result)
    else:
        with pytest.raises(GenerationError):
            resolve_tmc_sections(board, user)


@pytest.mark.parametrize("model,option,value,valid", list(cases()))
def test_effective_optional_setting(model, option, value, valid):
    pin = "uart_pin" if model in ("tmc2208", "tmc2209") else "cs_pin"
    config = f"[{model} stepper_x]\n{pin}: PC11\nrun_current: .580\n"
    if value is not None:
        config += f"{option}: {value}\n"
    result = validate_configuration_plan(build_managed_config_plan(GENERATED, None, remote_files(config)))
    assert result.valid == valid, result
    if not valid:
        assert any(error.code == "tmc-auxiliary-options" and option in error.message for error in result.errors)


@pytest.mark.parametrize("noop", (False, True))
def test_preserved_invalid_setting_blocks_publication(tmp_path, noop):
    remote = remote_files("[tmc2209 stepper_x]\nuart_pin: PC11\nrun_current: .580\ninterpolate: 2\n")
    if noop:
        plan = build_managed_config_plan(GENERATED, None, remote)
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        assert not build_managed_config_plan(GENERATED, None, remote).changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, GENERATED, None, activation="none", confirm=confirm,
        snapshot_root=str(tmp_path / "snapshots"), verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "interpolate" in result.detail
    confirm.assert_not_called()
    assert transport.files == remote
    assert not any(call[0] in ("upload", "delete", "restart") for call in transport.calls)


def test_migrated_interpolation_is_reviewed():
    generated = GENERATED + b"\n[tmc2209 stepper_x]\nuart_pin: PC11\nrun_current: .580\ninterpolate: True\n"
    remote = {"printer.cfg": generated.replace(b"interpolate: True", b"interpolate: 2")}
    plan = build_managed_config_plan(generated, None, remote)
    assert any(b"interpolate: 2" in a.content for a in plan.artifacts)
    assert not validate_configuration_plan(plan).valid


def test_final_render_cannot_inject_invalid_threshold(tmp_path):
    from jinja2 import Template
    render = Template.render
    board, _, user, name = inputs()
    user["z_motors"] = "1"
    board[name]["coolstep_threshold"] = "100"
    def inject(template, *args, **kwargs):
        return render(template, *args, **kwargs).replace("coolstep_threshold: 100", "coolstep_threshold: -1")
    output = tmp_path / "printer.cfg"
    with patch.object(Template, "render", inject), pytest.raises(GenerationError, match="coolstep_threshold"):
        generate_config(board, user, output_path=str(output), verbose=False)
    assert not output.exists()
