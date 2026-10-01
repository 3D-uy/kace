"""Reviewed BX cooling remains mandatory without importing its print strategy."""
import json
import re
from unittest.mock import Mock, patch

import pytest

from core.board_bx_panel import PROFILE
from core.board_auxiliary import validate_board_electrical_artifact
from core.configuration_review import validate_configuration_plan
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.exceptions import GenerationError
from core.generator import generate_config
from core.managed_config import build_managed_config_plan, effective_hardware_text, _section_options
from core.wizard.steps.hardware import _step_fan_assignment
from tests.unit.test_fixed_pwm_beepers import board_case
from tests.unit.test_config_transaction import FakeTransport

FANS = {"heater_fan extruder_fan": {"pin": "PA6", "heater": "extruder"},
        "controller_fan controller_fan": {"pin": "PA7", "idle_timeout": "300"}}


def render(tmp_path, **choices):
    raw, board, user = board_case(PROFILE)
    user.update(choices)
    text = generate_config(board, user, output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]
    return board, text


@pytest.mark.parametrize("choice", [None, "none", "PA6"])
def test_bx_cooling_survives_optional_selection(tmp_path, choice):
    board, text = render(tmp_path, fan_hotend_pin=choice)
    sections = _section_options(text)
    for name, fields in FANS.items():
        assert sections[name] == fields
        assert sum(line.strip() == f"[{name}]" for line in text.splitlines()) == 1
    assert "gcode_macro PRINT_START" not in sections
    assert json.loads((tmp_path / "printer.cfg.provenance.json").read_text())["sources"]["bx_cooling"] == FANS
    validate_board_electrical_artifact(board, text)


@pytest.mark.parametrize("name", FANS)
def test_saved_artifact_missing_fan_cannot_deploy(tmp_path, name):
    board, text = render(tmp_path)
    text = re.sub(r"(?ms)^\[" + re.escape(name) + r"\][^\n]*\n.*?(?=^\[|\Z)", "", text)
    transport, confirm = FakeTransport(), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, text.encode(), None, selected_board=board,
        activation="none", confirm=confirm, snapshot_root=str(tmp_path / "snapshots")).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "BX cooling" in result.detail
    assert not transport.calls
    confirm.assert_not_called()


@pytest.mark.parametrize("name,option,value", [
    ("heater_fan extruder_fan", "heater", "heater_bed"),
    ("heater_fan extruder_fan", "pin", "PA8"),
    ("controller_fan controller_fan", "idle_timeout", "0"),
    ("controller_fan controller_fan", "stepper", "stepper_x"),
    ("controller_fan controller_fan", "heater", "heater_bed"),
    ("controller_fan controller_fan", "pin", "!PA7"),
    ("controller_fan controller_fan", "fan_speed", "0"),
])
@pytest.mark.parametrize("noop", [False, True])
def test_effective_cooling_changes_rejected(tmp_path, name, option, value, noop):
    board, text = render(tmp_path)
    content = text.encode()
    first = build_managed_config_plan(content, None, {})
    remote = {a.remote_name: a.content for a in first.artifacts}
    remote["printer.cfg"] += b"[include user.cfg]\n"
    remote["user.cfg"] = f"[{name}]\n{option}: {value}\n".encode()
    if noop:
        remote.update({a.remote_name: a.content for a in build_managed_config_plan(content, None, remote).artifacts})
        assert not build_managed_config_plan(content, None, remote).changed_artifacts
    assert _section_options(effective_hardware_text(build_managed_config_plan(content, None, remote)))[name][option] == value
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, content, None, selected_board=board, activation="none", confirm=confirm,
        snapshot_root=str(tmp_path / "snapshots")).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    confirm.assert_not_called()
    assert all(call[0] == "read" for call in transport.calls)


@pytest.mark.parametrize("pin", ["PA6", "PA7"])
def test_cooling_gpio_is_exclusive_and_checks_firmware_reservations(tmp_path, pin):
    board, text = render(tmp_path)
    with pytest.raises(GenerationError, match="conflict"):
        validate_board_electrical_artifact(board, text + f"\n[output_pin other]\npin: {pin}\n")
    review = validate_configuration_plan(build_managed_config_plan(text.encode(), None, {}), selected_board=board,
        firmware_reservation_reader=lambda _: {"mcu": {pin: "reserved peripheral"}})
    assert not review.valid and any("reserved peripheral" in m.message for m in review.errors)
    _, source, choices = board_case(PROFILE)
    with patch("core.firmware_workflow.generation_pin_reservations", return_value={"mcu": {pin: "reserved peripheral"}}):
        with pytest.raises(GenerationError, match="reserved peripheral"):
            generate_config(source, choices, output_path=str(tmp_path / "bad.cfg"), verbose=False)
    assert not (tmp_path / "bad.cfg").exists()


def test_wizard_explains_mandatory_cooling(capsys):
    raw, _, choices = board_case(PROFILE)
    choices.update(board=PROFILE, board_raw_config=raw)
    with patch("core.wizard.steps.hardware.numbered_select", side_effect=["default", "none"]) as menu:
        _step_fan_assignment(choices)
    output = capsys.readouterr().out
    assert "extruder_fan" in output and "controller_fan" in output
    values = [c.get("value") for c in menu.call_args_list[0].kwargs["choices"] if isinstance(c, dict)]
    assert not {"PA6", "PA7"} & set(values)
    hotend = [c.get("value") for c in menu.call_args_list[1].kwargs["choices"] if isinstance(c, dict)]
    assert "PA7" not in hotend and "PA6" in hotend


@pytest.mark.parametrize("name", FANS)
def test_changed_parsed_source_rejected_before_write(tmp_path, name):
    _, board, choices = board_case(PROFILE)
    board[name]["pin"] = "PA8"
    with pytest.raises(GenerationError, match="BX cooling"):
        generate_config(board, choices, output_path=str(tmp_path / "printer.cfg"), verbose=False)
    assert not (tmp_path / "printer.cfg").exists()


@pytest.mark.parametrize("name", FANS)
def test_missing_cooling_blocks_export_and_firmware_adapters(tmp_path, name):
    from core.deployer import _run_config_transaction, _copy_artifacts, deploy_firmware_installation
    from core.workflow_outcome import WorkflowOutcome
    from core.moonraker_deployer import DeployState
    from tests.unit.test_deployer import FirmwareInstallationPreconditionTests
    raw, _, _ = board_case(PROFILE)
    _, text = render(tmp_path)
    missing = re.sub(r"(?ms)^\[" + re.escape(name) + r"\][^\n]*\n.*?(?=^\[|\Z)", "", text).encode()
    user = FirmwareInstallationPreconditionTests()._user()
    user.update(board=PROFILE, board_raw_config=raw)
    dest = FakeTransport()
    with patch("core.deployer._generated_config_bytes", return_value=("unused", missing, None)), \
         patch("core.config_transaction.configuration_transport", return_value=dest), \
         patch("core.deployer.shutil.copy2") as copy:
        result = _run_config_transaction(dest, user, "none", generated=("unused", missing, None))
        assert result.outcome == WorkflowOutcome.PRECONDITION_FAILED and "BX cooling" in result.detail
        assert not _copy_artifacts(user, str(tmp_path), "all")
        result = deploy_firmware_installation(user)
        assert result.state == DeployState.FAILED_PRECONDITION
        copy.assert_not_called()
        assert not dest.calls
        user["firmware_deployment_service"].execute.assert_not_called()
