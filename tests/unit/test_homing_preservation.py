"""Primary rail homing values survive selection, resume and effective review."""
import copy
import json
from unittest.mock import Mock

import pytest

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.exceptions import GenerationError
from core.firmware_workflow import persistable_wizard_data
from core.generator import generate_config
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.profile_values import mark_profile_values, mark_user_override
from core.scraper import extract_profile_defaults, parse_config
from tests.unit.test_config_transaction import FakeTransport, GENERATED
from tests.unit.test_generator import _parsed, _user
from tests.unit.test_tmc_uart_review import remote_files


OPTIONS = ("homing_speed", "second_homing_speed", "homing_retract_speed", "homing_retract_dist")


def render(tmp_path, board, user=None):
    return generate_config(board, user or _user(), output_path=str(tmp_path / "printer.cfg"), verbose=False)


@pytest.mark.parametrize("axis", "xyz")
@pytest.mark.parametrize("values", [("1", "0.4", "2.5", "0"), ("2.5", "1.25", "2.5", "5"), ("5", "2.5", "5", "5")])
def test_homing_conserved_and_idempotent(tmp_path, axis, values):
    board = _parsed()
    section = "stepper_" + axis
    board[section].update(zip(OPTIONS, values))
    result = render(tmp_path, board)
    for option, value in zip(OPTIONS, values):
        assert parse_config(result["content"])[section][option] == value
        assert result["value_provenance"][option + "_" + axis] == "PROFILE"
    remote = {"printer.cfg": result["content"].encode()}
    plan = build_managed_config_plan(result["content"].encode(), None, remote)
    assert validate_configuration_plan(plan).valid
    for option, value in zip(OPTIONS, values):
        assert parse_config(effective_hardware_text(plan))[section][option] == value
    remote.update({a.remote_name: a.content for a in plan.artifacts})
    assert not build_managed_config_plan(result["content"].encode(), None, remote).changed_artifacts


def test_omissions_keep_existing_xy_policy_and_klipper_dependent_defaults(tmp_path):
    result = parse_config(render(tmp_path, _parsed())["content"])
    assert result["stepper_x"]["homing_speed"] == result["stepper_y"]["homing_speed"] == "50"
    assert "homing_speed" not in result["stepper_z"]
    for axis in "xyz":
        assert not set(OPTIONS[1:]).intersection(result["stepper_" + axis])


@pytest.mark.parametrize("axis", "xyz")
def test_profile_authority_override_and_resume(tmp_path, axis):
    board = _parsed()
    board["stepper_" + axis]["homing_speed"] = "40"
    profile = copy.deepcopy(board)
    profile["stepper_" + axis].update(dict(zip(OPTIONS, ("2.5", "1", "3", "0"))))
    user = _user(_profile_parsed=profile)
    user.update(extract_profile_defaults(profile))
    mark_profile_values(user, profile)
    key = "second_homing_speed_" + axis
    user[key] = "0.5"
    mark_user_override(user, key)
    user = json.loads(json.dumps(persistable_wizard_data(user)))
    result = render(tmp_path, board, user)
    final = parse_config(result["content"])["stepper_" + axis]
    assert final["homing_speed"] == "2.5"
    assert final["second_homing_speed"] == "0.5"
    assert result["value_provenance"][key] == "USER_OVERRIDE"


def test_switching_profile_drops_old_optional_homing_values(tmp_path):
    board = _parsed()
    first = copy.deepcopy(board)
    first["stepper_z"].update(dict(zip(OPTIONS, ("2.5", "1", "3", "0"))))
    user = _user(_profile_parsed=first)
    user.update(extract_profile_defaults(first))
    mark_profile_values(user, first)
    user["_profile_parsed"] = board
    user.update(extract_profile_defaults(board))
    mark_profile_values(user, board)
    final = parse_config(render(tmp_path, board, user)["content"])
    assert not set(OPTIONS).intersection(final["stepper_z"])


def test_explicit_unresolved_homing_cannot_authorize_fallback(tmp_path):
    user = _user(_value_provenance={"homing_speed_z": "UNRESOLVED"})
    with pytest.raises(GenerationError, match="homing_speed_z"):
        render(tmp_path, _parsed(), user)


@pytest.mark.parametrize("option", OPTIONS)
@pytest.mark.parametrize("value", ("-1", "nan", "inf", "", None, True, "bad"))
@pytest.mark.parametrize("source", ("profile", "override"))
def test_invalid_values_fail_before_writing(tmp_path, option, value, source):
    board, user = _parsed(), _user()
    if source == "profile":
        board["stepper_z"][option] = value
    else:
        key = option + "_z"
        user[key] = value
        mark_user_override(user, key)
    path = tmp_path / "printer.cfg"
    path.write_text("untouched")
    with pytest.raises(GenerationError, match=option):
        render(tmp_path, board, user)
    assert path.read_text() == "untouched"
    assert not (tmp_path / "printer.cfg.provenance.json").exists()


@pytest.mark.parametrize("option", OPTIONS[:3])
def test_speed_zero_is_invalid_even_when_retract_is_disabled(tmp_path, option):
    board = _parsed()
    board["stepper_z"].update({option: "0", "homing_retract_dist": "0"})
    with pytest.raises(GenerationError, match=option):
        render(tmp_path, board)


@pytest.mark.parametrize("option", OPTIONS)
@pytest.mark.parametrize("noop", (False, True))
def test_nested_invalid_override_blocks_before_confirmation(tmp_path, option, noop):
    remote = remote_files(f"[stepper_x]\n{option}: -1\n")
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
    assert not any(call[0] in ("upload", "delete", "restart") for call in transport.calls)
