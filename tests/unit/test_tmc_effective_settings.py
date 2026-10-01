"""Effective includes must not bypass the guided TMC numeric contract."""
from unittest.mock import Mock, patch

import pytest

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.exceptions import GenerationError
from core.generator import generate_config
from core.managed_config import build_managed_config_plan
from tests.unit.test_config_transaction import FakeTransport, GENERATED
from tests.unit.test_tmc_uart_review import remote_files


MODELS = ("tmc2208", "tmc2209", "tmc2130", "tmc5160")
OPTIONS = ("run_current", "hold_current", "stealthchop_threshold")


def driver_config(model, overrides=None, target="stepper_x"):
    options = {"uart_pin" if model in MODELS[:2] else "cs_pin": "PC11", "run_current": "0.580"}
    for key, value in (overrides or {}).items():
        if value is None:
            options.pop(key, None)
        else:
            options[key] = value
    return f"[{model} {target}]\n" + "".join(f"{key}: {value}\n" for key, value in options.items())


def review(model, overrides=None, target="stepper_x"):
    return validate_configuration_plan(build_managed_config_plan(
        GENERATED, None, remote_files(driver_config(model, overrides, target))))


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("option", OPTIONS)
@pytest.mark.parametrize("value", ("", "bad", "-0.1", "nan", "inf", "-inf", "1e999"))
def test_invalid_effective_value_is_rejected(model, option, value):
    errors = review(model, {option: value}).errors
    assert any(e.code == "tmc-current-settings" and option in e.message for e in errors), errors


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("target", ("stepper_x", "stepper_y", "stepper_z", "stepper_z1", "stepper_z2", "stepper_z3", "extruder", "extruder1", "manual_stepper auxiliary"))
def test_current_required_for_each_effective_driver_not_only_wizard_targets(model, target):
    assert any(e.code == "tmc-current-settings" and "run_current" in e.message
               for e in review(model, {"run_current": None}, target).errors)


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("option", ("run_current", "hold_current"))
@pytest.mark.parametrize("value", ("0", "over_limit"))
def test_effective_current_limits(model, option, value):
    if value == "over_limit":
        value = "10.001" if model == "tmc5160" else "2.001"
    assert any(e.code == "tmc-current-settings" for e in review(model, {option: value}).errors)


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("mode", ("omitted", "zero", "positive", "limits"))
def test_valid_settings_and_optional_omissions(model, mode):
    maximum = "10" if model == "tmc5160" else "2"
    options = {} if mode == "omitted" else {"stealthchop_threshold": "0" if mode == "zero" else "25"}
    if mode == "limits":
        options.update(run_current=maximum, hold_current=maximum)
    elif mode == "positive":
        options["hold_current"] = "0.300"
    assert review(model, options).valid


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("option", OPTIONS)
@pytest.mark.parametrize("noop", (False, True))
def test_transaction_rejects_before_confirmation_writes_and_restart(tmp_path, model, option, noop):
    remote = remote_files(driver_config(model, {option: "nan"}))
    if noop:
        plan = build_managed_config_plan(GENERATED, None, remote)
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        assert not build_managed_config_plan(GENERATED, None, remote).changed_artifacts
    transport = FakeTransport(remote)
    confirm = Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, GENERATED, None, activation="none", confirm=confirm,
        snapshot_root=str(tmp_path / "snapshots"), verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert option in result.detail
    confirm.assert_not_called()
    assert transport.files == remote
    assert not any(c[0] in ("upload", "delete", "restart") for c in transport.calls)


@pytest.mark.parametrize("option", OPTIONS)
def test_rendered_values_are_checked_before_files_are_written(tmp_path, option):
    from jinja2 import Template
    from tests.unit.test_generator import _parsed, _user
    render = Template.render
    def inject(template, *args, **kwargs):
        return render(template, *args, **kwargs) + "\n" + driver_config("tmc5160", {option: "nan"})
    output = tmp_path / "printer.cfg"
    with patch.object(Template, "render", inject), pytest.raises(GenerationError, match=option):
        generate_config(_parsed(), _user(), output_path=str(output), verbose=False)
    assert not output.exists()
    assert not output.with_suffix(".cfg.provenance.json").exists()


@pytest.mark.parametrize("invalid_last", (False, True))
def test_repeated_sections_follow_effective_include_order(invalid_last):
    first, last = ("0.580", "0") if invalid_last else ("0", "0.580")
    remote = remote_files(driver_config("tmc2209", {"run_current": first})
                          + "[include last.cfg]\n")
    remote["last.cfg"] = f"[tmc2209 stepper_x]\nrun_current: {last}\n".encode()
    result = validate_configuration_plan(build_managed_config_plan(GENERATED, None, remote))
    assert result.valid is not invalid_last


def test_edit_after_confirmation_remains_blocked(tmp_path):
    # Existing transaction byte rechecks must also cover the numeric source.
    transport = FakeTransport(remote_files(driver_config("tmc2209")))
    def edit(_):
        transport.files["wiring.cfg"] = driver_config("tmc2209", {"run_current": "0"}).encode()
        return True
    result = ConfigDeploymentTransaction(transport, GENERATED, None, activation="none", confirm=edit,
        snapshot_root=str(tmp_path / "snapshots")).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert not any(c[0] in ("upload", "delete", "restart") for c in transport.calls)


def test_macro_variables_are_not_driver_settings():
    remote = remote_files("[gcode_macro TMC_TEST]\nvariable_run_current: 0\ngcode:\n  M118 test\n")
    assert validate_configuration_plan(build_managed_config_plan(GENERATED, None, remote)).valid
