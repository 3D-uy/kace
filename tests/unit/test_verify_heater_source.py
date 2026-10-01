"""Source-loss guards: no automatic thermal tuning or physical certification."""
import copy
from unittest.mock import Mock

import pytest

from core.board_auxiliary import selected_board_electrical_source, validate_board_electrical_artifact
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.exceptions import GenerationError
from core.generator import generate_config
from core.heater_verification import SOURCE, validate_source_verification
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.scraper import parse_config
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_generator import _parsed, _user
from tests.unit.test_verify_heater_review import GENERATED


POLICIES = ["heating_gain: 1\ncheck_gain_time: 120", "check_gain_time: 240", "check_gain_time: 600"]


def source(options, heater="heater_bed"):
    return parse_config(GENERATED.decode() + f"\n[verify_heater {heater}]\n{options}\n", keep_comments=True)


@pytest.mark.parametrize("options", POLICIES)
@pytest.mark.parametrize("origin", ["board", "printer_profile"])
def test_generation_cannot_discard_source_policy_or_overwrite_existing_files(tmp_path, options, origin):
    parsed, user = _parsed(), _user()
    selected = source(options)
    if origin == "board":
        for name in ("verify_heater heater_bed", SOURCE):
            parsed[name] = selected[name]
    else:
        user["_profile_parsed"] = selected
    before = copy.deepcopy((parsed, user))
    output = tmp_path / "printer.cfg"
    provenance = tmp_path / "printer.cfg.provenance.json"
    output.write_text("existing config")
    provenance.write_text("existing provenance")
    with pytest.raises(GenerationError, match="selected-source protection.*check_gain_time"):
        generate_config(parsed, user, output_path=str(output), verbose=False)
    assert output.read_text() == "existing config"
    assert provenance.read_text() == "existing provenance"
    assert (parsed, user) == before


@pytest.mark.parametrize("options", POLICIES)
@pytest.mark.parametrize("changed", [None, "check_gain_time: 60", "check_gain_time: 900"])
@pytest.mark.parametrize("noop", [False, True])
def test_saved_artifact_recovery_rejects_missing_or_changed_policy_before_io(tmp_path, options, changed, noop):
    generated = GENERATED
    if changed is not None:
        generated += f"\n[verify_heater heater_bed]\n{changed}\n".encode()
    remote = {}
    if noop:
        remote = {a.remote_name: a.content for a in build_managed_config_plan(generated, None, {}).artifacts}
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, generated, None, selected_board=source(options),
        activation="none", confirm=confirm, snapshot_root=str(tmp_path / "snapshots"),
        verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "selected-source protection" in result.detail
    confirm.assert_not_called()
    assert transport.calls == []
    assert transport.files == remote


@pytest.mark.parametrize("options", POLICIES)
@pytest.mark.parametrize("noop", [False, True])
def test_effective_user_include_cannot_override_retained_source_policy(tmp_path, options, noop):
    generated = GENERATED + f"\n[verify_heater heater_bed]\n{options}\n".encode()
    initial = build_managed_config_plan(generated, None, {})
    remote = {a.remote_name: a.content for a in initial.artifacts}
    remote["printer.cfg"] += b"[include user.cfg]\n"
    remote["user.cfg"] = b"[verify_heater heater_bed]\ncheck_gain_time: 999\n"
    if noop:
        remote.update({a.remote_name: a.content for a in build_managed_config_plan(generated, None, remote).artifacts})
    plan = build_managed_config_plan(generated, None, remote)
    if noop:
        assert not plan.changed_artifacts
    assert "check_gain_time: 999" in effective_hardware_text(plan)
    review = validate_configuration_plan(plan, selected_board=source(options))
    assert any("selected-source protection" in e.message for e in review.errors)
    confirm, transport = Mock(return_value=True), FakeTransport(remote)
    result = ConfigDeploymentTransaction(transport, generated, None, selected_board=source(options),
        activation="none", confirm=confirm, snapshot_root=str(tmp_path / "snapshots"),
        verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "selected-source protection" in result.detail
    confirm.assert_not_called()
    assert all(call[0] == "read" for call in transport.calls)
    assert transport.files == remote


@pytest.mark.parametrize("options", POLICIES)
def test_already_present_exact_policy_is_accepted_without_retuning(options):
    content = GENERATED.decode() + f"\n[verify_heater heater_bed]\n{options}\n"
    selected = source(options)
    before = copy.deepcopy(selected)
    validate_board_electrical_artifact(selected, content)
    plan = build_managed_config_plan(content.encode(), None, {})
    review = validate_configuration_plan(plan, selected_board=selected)
    assert review.valid, review.errors
    assert selected == before


@pytest.mark.parametrize("heater,time", [("extruder", 20), ("heater_bed", 60)])
def test_implicit_defaults_and_numeric_spellings_are_equivalent(heater, time):
    selected = source(f"max_error: 120.0\nhysteresis: 5e0\nheating_gain: 2.0\ncheck_gain_time: {time}.0", heater)
    validate_source_verification(selected, GENERATED.decode())
    validate_source_verification(selected, GENERATED.decode() + f"\n[verify_heater {heater}]\n")


@pytest.mark.parametrize("options", ["", "#check_gain_time: 600", "check_gain_time: 60.0"])
def test_generation_can_use_equivalent_implicit_defaults(tmp_path, options):
    parsed = _parsed()
    selected = source(options)
    for name in ("verify_heater heater_bed", SOURCE):
        parsed[name] = selected[name]
    result = generate_config(parsed, _user(), output_path=str(tmp_path / "printer.cfg"), verbose=False)
    assert "[verify_heater heater_bed]" not in result["content"]
    assert (tmp_path / "printer.cfg").read_text(encoding="utf-8") == result["content"]


@pytest.mark.parametrize("option,value", [("max_error", "121"), ("hysteresis", "6"),
                                         ("heating_gain", "3"), ("check_gain_time", "61")])
def test_each_changed_effective_option_is_detected(option, value):
    with pytest.raises(GenerationError, match=f"selected-source protection.*{option}"):
        validate_source_verification(source(f"{option}: {value}"), GENERATED.decode())


@pytest.mark.parametrize("keep_comments", [False, True])
def test_comments_do_not_activate_tuning(keep_comments):
    raw = GENERATED.decode() + "\n#[verify_heater heater_bed]\n#check_gain_time: 600\n"
    selected = parse_config(raw, keep_comments=keep_comments)
    validate_source_verification(selected, GENERATED.decode())
    if keep_comments:
        assert selected[SOURCE] == {"verify_heater heater_bed": None}
    raw = GENERATED.decode() + "\n[verify_heater heater_bed]\n#check_gain_time: 600\n"
    selected = parse_config(raw, keep_comments=keep_comments)
    assert selected[SOURCE] == {"verify_heater heater_bed": {}}
    validate_source_verification(selected, GENERATED.decode())


@pytest.mark.parametrize("mutation", ["old_checkpoint", "change_value", "delete_section", "unknown_section"])
def test_missing_or_inconsistent_source_evidence_fails_closed(mutation):
    selected = source("check_gain_time: 600")
    if mutation == "old_checkpoint":
        selected.pop(SOURCE)
    elif mutation == "change_value":
        selected["verify_heater heater_bed"]["check_gain_time"] = "60"
    elif mutation == "delete_section":
        selected.pop("verify_heater heater_bed")
    else:
        selected["verify_heater extruder"] = {}
    with pytest.raises(GenerationError, match="source.*changed|source activity"):
        validate_source_verification(selected, GENERATED.decode())


def test_checkpoint_raw_source_recovers_activity_without_using_mechanical_profile():
    selected = selected_board_electrical_source({"workflow_checkpoint": {"wizard_data": {
        "board": "test-board.cfg", "board_raw_config": GENERATED.decode() +
        "\n[verify_heater heater_bed]\ncheck_gain_time: 600\n",
        "_profile_parsed": source("check_gain_time: 120")}}})
    assert selected[SOURCE]["verify_heater heater_bed"] == {"check_gain_time": "600"}
    with pytest.raises(GenerationError, match="selected-source protection"):
        validate_board_electrical_artifact(selected, GENERATED)


@pytest.mark.parametrize("heater", ["missing", "Heater_Bed", "extruder0"])
def test_source_reference_must_exist_exactly_in_artifact(heater):
    with pytest.raises(GenerationError, match="exact name"):
        validate_source_verification(source("", heater), GENERATED.decode())


@pytest.mark.parametrize("option", ["max_error", "hysteresis", "heating_gain", "check_gain_time"])
def test_invalid_source_is_not_hidden_by_valid_artifact_defaults(option):
    with pytest.raises(GenerationError, match=option):
        validate_source_verification(source(f"{option}: nan"), GENERATED.decode())
