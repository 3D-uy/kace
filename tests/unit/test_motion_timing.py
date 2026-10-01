"""Board pulse timing and mechanical cruise ratio survive publication."""
import copy
import json
from unittest.mock import Mock, patch

import pytest

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.exceptions import GenerationError
from core.firmware_workflow import persistable_wizard_data
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.profile_values import mark_profile_values, mark_user_override
from core.scraper import extract_profile_defaults, parse_config
from core.wizard.steps import hardware
from tests.unit.test_config_transaction import FakeTransport, GENERATED
from tests.unit.test_full_steps_preservation import multi_board, render, TARGETS
from tests.unit.test_generator import _user
from tests.unit.test_tmc_uart_review import remote_files


@pytest.mark.parametrize("section", TARGETS.values())
@pytest.mark.parametrize("pulse", ("0", "0.000004", "0.001"))
def test_pulse_per_socket_and_idempotence(tmp_path, section, pulse):
    board = multi_board()
    board[section]["step_pulse_duration"] = pulse
    result = render(tmp_path, board)
    assert parse_config(result["content"])[section]["step_pulse_duration"] == pulse
    sidecar = json.loads((tmp_path / "printer.cfg.provenance.json").read_text())
    assert sidecar["sources"]["hardware_options"][section]["step_pulse_duration"] == pulse
    remote = {"printer.cfg": result["content"].encode()}
    plan = build_managed_config_plan(result["content"].encode(), None, remote)
    assert validate_configuration_plan(plan).valid
    assert parse_config(effective_hardware_text(plan))[section]["step_pulse_duration"] == pulse
    remote.update({a.remote_name: a.content for a in plan.artifacts})
    assert not build_managed_config_plan(result["content"].encode(), None, remote).changed_artifacts


@pytest.mark.parametrize("ratio", ("0", "0.0", "0.5", "0.999"))
def test_cruise_ratio_preserved(tmp_path, ratio):
    board = multi_board()
    board.setdefault("printer", {})["minimum_cruise_ratio"] = ratio
    result = render(tmp_path, board)
    assert parse_config(result["content"])["printer"]["minimum_cruise_ratio"] == ratio
    plan = build_managed_config_plan(result["content"].encode(), None, {"printer.cfg": result["content"].encode()})
    assert validate_configuration_plan(plan).valid
    assert parse_config(effective_hardware_text(plan))["printer"]["minimum_cruise_ratio"] == ratio
    assert result["value_provenance"]["minimum_cruise_ratio"] == "PROFILE"


def test_omissions_remain_klipper_owned(tmp_path):
    final = parse_config(render(tmp_path, multi_board())["content"])
    assert "minimum_cruise_ratio" not in final["printer"]
    assert all("step_pulse_duration" not in final[s] for s in TARGETS.values())


@pytest.mark.parametrize("board_has_pulse", (False, True))
def test_profile_owns_cruise_but_cannot_replace_board_pulse_after_resume(tmp_path, board_has_pulse):
    board = multi_board()
    if board_has_pulse:
        board["stepper_z"]["step_pulse_duration"] = "0.000004"
    profile = copy.deepcopy(board)
    profile["stepper_z"]["step_pulse_duration"] = "0.000001"
    profile.setdefault("printer", {})["minimum_cruise_ratio"] = "0.25"
    user = _user(z_motors="4", _profile_parsed=profile)
    user.update(extract_profile_defaults(profile))
    mark_profile_values(user, profile)
    user["minimum_cruise_ratio"] = "0"
    mark_user_override(user, "minimum_cruise_ratio")
    user = json.loads(json.dumps(persistable_wizard_data(user)))
    result = parse_config(render(tmp_path, board, user)["content"])
    assert result["stepper_z"].get("step_pulse_duration") == ("0.000004" if board_has_pulse else None)
    assert result["printer"]["minimum_cruise_ratio"] == "0"


def test_changed_profile_drops_old_cruise_ratio(tmp_path):
    board = multi_board()
    first = copy.deepcopy(board)
    first.setdefault("printer", {})["minimum_cruise_ratio"] = "0"
    user = _user(z_motors="4", _profile_parsed=first)
    user.update(extract_profile_defaults(first))
    mark_profile_values(user, first)
    user["_profile_parsed"] = board
    mark_profile_values(user, board)
    assert "minimum_cruise_ratio" not in parse_config(render(tmp_path, board, user)["content"])["printer"]


@pytest.mark.parametrize("option,section,bad", [
    (option, section, value)
    for option, section, values in (
        ("step_pulse_duration", "stepper_z", ("-1", "0.0011", "nan", "inf", "bad", "", None, True)),
        ("minimum_cruise_ratio", "printer", ("-0.1", "1", "nan", "inf", "bad", "", None, True)),
    ) for value in values
])
def test_invalid_source_cannot_write(tmp_path, option, section, bad):
    board = multi_board()
    board.setdefault(section, {})[option] = bad
    output = tmp_path / "printer.cfg"
    output.write_text("untouched")
    with pytest.raises(GenerationError, match=option):
        render(tmp_path, board)
    assert output.read_text() == "untouched"


@pytest.mark.parametrize("option,section", (("step_pulse_duration", "stepper_x"), ("minimum_cruise_ratio", "printer")))
@pytest.mark.parametrize("noop", (False, True))
def test_invalid_include_blocks_before_confirmation(tmp_path, option, section, noop):
    remote = remote_files(f"[{section}]\n{option}: -1\n")
    if noop:
        plan = build_managed_config_plan(GENERATED, None, remote)
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        assert not build_managed_config_plan(GENERATED, None, remote).changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, GENERATED, None, activation="none", confirm=confirm,
        snapshot_root=str(tmp_path / "snapshots"), verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert option in result.detail
    confirm.assert_not_called()
    assert transport.files == remote
    assert not any(c[0] in ("upload", "delete", "restart") for c in transport.calls)


def test_reused_socket_transfers_its_pulse(tmp_path):
    board = multi_board()
    socket = board.pop("stepper_z1")
    socket["step_pulse_duration"] = "0.000004"
    board["extruder1"] = socket
    user = _user(z_motors="2", board_parsed=board, board_raw_config="[extruder1]\n")
    with patch.object(hardware, "get_reusable_driver_sockets", return_value=[("extruder1", "E1")]), \
            patch.object(hardware, "numbered_select", return_value="extruder1"):
        assert hardware._step_z_socket_assignment(user) == "done"
    assert board["stepper_z1"]["step_pulse_duration"] == "0.000004"
    assert parse_config(render(tmp_path, board, user)["content"])["stepper_z1"]["step_pulse_duration"] == "0.000004"


def test_unselected_motor_does_not_block_or_emit(tmp_path):
    board = multi_board()
    board["stepper_z3"]["step_pulse_duration"] = "bad-unused"
    assert "[stepper_z3]" not in render(tmp_path, board, _user(z_motors="1"))["content"]


@pytest.mark.parametrize("section", ("stepper_x1", "stepper_z4", "extruder1", "extruder_stepper feeder", "manual_stepper feeder"))
def test_preserved_additional_stepper_pulse_is_validated(section):
    remote = remote_files(f"[{section}]\nstep_pulse_duration: -1\n")
    result = validate_configuration_plan(build_managed_config_plan(GENERATED, None, remote))
    assert any(e.code == "motion-timing" and "step_pulse_duration" in e.message for e in result.errors)


@pytest.mark.parametrize("pulse", (None, "0.000004"))
def test_native_tmc_does_not_force_or_replace_pulse(tmp_path, pulse):
    board = multi_board()
    for i, section in enumerate(("stepper_x", "stepper_y", "stepper_z", "extruder")):
        board["tmc2209 " + section] = {"uart_pin": f"PG{i}", "run_current": "0.8"}
        if pulse is not None:
            board[section]["step_pulse_duration"] = pulse
    user = _user(z_motors="1", driver_type="TMC2209", driver_mode="UART")
    final = parse_config(render(tmp_path, board, user)["content"])
    for section in ("stepper_x", "stepper_y", "stepper_z", "extruder"):
        assert "tmc2209 " + section in final
        assert final[section].get("step_pulse_duration") == pulse
