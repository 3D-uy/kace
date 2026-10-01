"""Present selected fan resources cannot lose source settings during publication."""
from unittest.mock import Mock, patch

import pytest

from core.board_auxiliary import selected_board_electrical_source, validate_board_electrical_artifact
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.exceptions import GenerationError
from core.generator import generate_config
from core.managed_config import build_managed_config_plan, effective_hardware_text, _section_options
from core.scraper import parse_config
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_generator import _parsed, _user


CASES = [
    ("fan", "max_power: 0.6", "max_power: 1"),
    ("fan", "kick_start_time: 1", "kick_start_time: 0.1"),
    ("fan", "off_below: 0.2", "off_below: 0"),
    ("fan", "cycle_time: 0.02", "cycle_time: 0.01"),
    ("fan", "hardware_pwm: True", "hardware_pwm: False"),
    ("fan", "shutdown_speed: 0.4", "shutdown_speed: 0"),
    ("heater_fan HeatBreak", "heater: heater_bed", "heater: extruder"),
    ("heater_fan HeatBreak", "heater_temp: 40", "heater_temp: 50"),
    ("heater_fan HeatBreak", "fan_speed: 0.8", "fan_speed: 1"),
    ("heater_fan HeatBreak", "max_power: 0.6", "max_power: 1"),
]


def source(name, options=""):
    raw = f"[{name}]\npin: PC5\n{options}\n"
    return selected_board_electrical_source({"board": "test.cfg", "board_raw_config": raw})


def generated(tmp_path, name, options=""):
    parsed = _parsed()
    parsed.pop("fan")
    parsed.update(source(name, options))
    user = _user(fan_part_cooling_pin="default" if name == "fan" else "none",
                 fan_hotend_pin="none" if name == "fan" else "PC5")
    return generate_config(parsed, user, output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]


@pytest.mark.parametrize("name,original,replacement", CASES)
def test_old_artifact_cannot_drop_active_options(name, original, replacement):
    with pytest.raises(GenerationError, match="fan.*(source|settings)"):
        validate_board_electrical_artifact(source(name, original), f"[{name}]\npin: PC5\n")


@pytest.mark.parametrize("name,original,replacement", CASES)
@pytest.mark.parametrize("noop", [False, True])
def test_effective_override_rejected_before_confirmation(tmp_path, name, original, replacement, noop):
    selected = source(name, original)
    content = generated(tmp_path, name, original).encode()
    initial = build_managed_config_plan(content, None, {})
    remote = {a.remote_name: a.content for a in initial.artifacts}
    remote["printer.cfg"] += b"[include user.cfg]\n"
    remote["user.cfg"] = f"[{name}]\n{replacement}\n".encode()
    if noop:
        plan = build_managed_config_plan(content, None, remote)
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        assert not build_managed_config_plan(content, None, remote).changed_artifacts
    plan = build_managed_config_plan(content, None, remote)
    option, value = replacement.split(": ", 1)
    assert _section_options(effective_hardware_text(plan))[name][option] == value
    # Valid scalar ranges alone do not establish equivalence to selected hardware.
    from core.configuration_review import validate_configuration_plan
    assert validate_configuration_plan(plan).valid
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, content, None, selected_board=selected, activation="none", confirm=confirm,
        snapshot_root=str(tmp_path / "snapshots"), verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "fan" in result.detail
    confirm.assert_not_called()
    assert not any(c[0] in ("upload", "delete", "restart") for c in transport.calls)


@pytest.mark.parametrize("kind", ["heater_fan heatbreak", "controller_fan drivers", "temperature_fan electronics"])
def test_old_automatic_resource_cannot_become_manual(kind):
    with pytest.raises(GenerationError, match="fan.*role"):
        validate_board_electrical_artifact(source(kind), "[fan]\npin: PC5\n")


@pytest.mark.parametrize("option", ["enable_pin", "tachometer_pin"])
def test_old_artifact_cannot_bypass_unimplemented_source_dependency(option):
    with pytest.raises(GenerationError, match=option):
        validate_board_electrical_artifact(source("fan", f"{option}: PA8"), "[fan]\npin: PC5\n")


@pytest.mark.parametrize("pin", ["!PC5", "^PC5", "~PC5"])
def test_changed_electrical_polarity_or_mode_rejected(pin):
    with pytest.raises(GenerationError, match="fan"):
        validate_board_electrical_artifact(source("fan"), f"[fan]\npin: {pin}\n")


def test_source_name_cannot_silently_be_replaced():
    with pytest.raises(GenerationError, match="fan.*(identity|name)"):
        validate_board_electrical_artifact(source("heater_fan HeatBreak"), "[heater_fan hotend_fan]\npin: PC5\n")


@pytest.mark.parametrize("name", ["fan", "heater_fan HeatBreak"])
def test_equivalent_defaults_aliases_and_numeric_formatting_allowed(name):
    text = f"[{name}]\npin: COOLING\nmax_power: 6e-1\nhardware_pwm: 0\ncycle_time: .010\n"
    # Klipper clamps shutdown to max_power; both forms give the same output.
    if name != "fan":
        text += "shutdown_speed: .6\nheater: extruder\nheater_temp: 50.0\nfan_speed: 1\n"
    text += "[board_pins names]\naliases: COOLING=PC5\n"
    validate_board_electrical_artifact(source(name, "max_power: 0.6"), text)


def test_pin_only_manual_to_hotend_keeps_existing_supported_policy():
    validate_board_electrical_artifact(source("fan"), "[heater_fan hotend_fan]\npin: PC5\nheater: extruder\nheater_temp: 50\n")


def test_optional_absence_and_different_custom_gpio_do_not_infer_required_cooling():
    selected = source("fan", "max_power: 0.6")
    validate_board_electrical_artifact(selected, "[mcu]\nserial: test\n")
    validate_board_electrical_artifact(selected, "[fan]\npin: toolhead:PC5\n")


def test_metadata_free_generic_api_keeps_existing_boundary():
    validate_board_electrical_artifact(None, "[fan]\npin: PC5\n")


@pytest.mark.parametrize("name", ["fan", "heater_fan HeatBreak"])
def test_valid_generation_publishes_and_retries_idempotently(tmp_path, name):
    selected = source(name, "max_power: 0.6")
    content = generated(tmp_path, name, "max_power: 0.6").encode()
    transport = FakeTransport({"printer.cfg": content})
    for _ in range(2):
        result = ConfigDeploymentTransaction(transport, content, None, selected_board=selected, activation="none",
            confirm=lambda _: True, snapshot_root=str(tmp_path / "snapshots")).run()
        assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION


@pytest.mark.parametrize("name", ["fan", "heater_fan HeatBreak"])
def test_live_adapter_and_local_export_reject_old_settings(tmp_path, name):
    from core.deployer import _run_config_transaction, _copy_artifacts
    from core.workflow_outcome import WorkflowOutcome
    content = generated(tmp_path, name).encode()
    user = {"board": "test.cfg", "board_raw_config": f"[{name}]\npin: PC5\nmax_power: 0.6\n"}
    transport = FakeTransport()
    with patch("core.deployer._interactive_configuration_review") as review:
        result = _run_config_transaction(transport, user, "none", generated=("unused.cfg", content, None))
    assert result.outcome == WorkflowOutcome.PRECONDITION_FAILED
    assert "fan source" in result.detail
    review.assert_not_called()
    assert not transport.calls
    destination = tmp_path / "export"
    destination.mkdir()
    with patch("core.deployer._generated_config_bytes", return_value=("unused.cfg", content, None)), \
         patch("core.deployer._review_configuration_export") as review:
        assert not _copy_artifacts(user, str(destination), "config")
    review.assert_not_called()
    assert not list(destination.iterdir())
