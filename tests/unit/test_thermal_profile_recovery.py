"""Carry profile verification policy without importing its electrical circuits."""
import copy
from unittest.mock import Mock, patch

import pytest

from core.board_auxiliary import selected_board_electrical_source, validate_board_electrical_artifact
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.exceptions import GenerationError
from core.heater_verification import PROFILE_SOURCE, SOURCE
from core.managed_config import build_managed_config_plan, effective_hardware_text, _section_options
from core.scraper import parse_config
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_verify_heater_review import GENERATED
from tests.unit.test_verify_heater_source import POLICIES


def user_for(options, *, saved=False):
    raw = ("[heater_bed]\nheater_pin: PA99\nsensor_pin: PB99\n"
           "[output_pin motor_power]\npin: PC99\nvalue: 1\n"
           "[verify_heater heater_bed]\n" + options + "\n")
    user = {"board": "selected-board.cfg", "board_raw_config": GENERATED.decode(),
            "printer_profile": "separate-printer.cfg", "profile_loaded": True,
            "raw_config": raw, "_profile_parsed": parse_config(raw)}
    return {"workflow_checkpoint": {"wizard_data": user}} if saved else user


@pytest.mark.parametrize("options", POLICIES)
@pytest.mark.parametrize("saved", [False, True])
def test_separate_profile_policy_survives_selection_and_checkpoint_without_gpio_authority(options, saved):
    user = user_for(options, saved=saved)
    before = copy.deepcopy(user)
    selected = selected_board_electrical_source(user)
    assert selected["heater_bed"]["heater_pin"] == "PA6"
    assert "output_pin motor_power" not in selected
    assert set(selected[PROFILE_SOURCE]) == {SOURCE, "verify_heater heater_bed"}
    assert "PA99" not in repr(selected) and "PC99" not in repr(selected)
    with pytest.raises(GenerationError, match="selected-source protection"):
        validate_board_electrical_artifact(selected, GENERATED)
    validate_board_electrical_artifact(selected, GENERATED + f"\n[verify_heater heater_bed]\n{options}\n".encode())
    assert user == before


@pytest.mark.parametrize("options", POLICIES)
@pytest.mark.parametrize("noop", [False, True])
def test_profile_loss_is_rejected_before_remote_operations(options, noop, tmp_path):
    remote = {}
    if noop:
        remote = {a.remote_name: a.content for a in build_managed_config_plan(GENERATED, None, {}).artifacts}
    selected = selected_board_electrical_source(user_for(options, saved=True))
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    transaction = ConfigDeploymentTransaction(transport, GENERATED, None, selected_board=selected,
        activation="none", confirm=confirm, snapshot_root=str(tmp_path), verify_existing_ready=noop)
    selected.clear()  # The transaction owns its source snapshot.
    result = transaction.run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "selected-source protection" in result.detail
    confirm.assert_not_called()
    assert not transport.calls and transport.files == remote
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("options", POLICIES)
@pytest.mark.parametrize("noop", [False, True])
def test_effective_include_cannot_replace_profile_policy(options, noop, tmp_path):
    generated = GENERATED + f"\n[verify_heater heater_bed]\n{options}\n".encode()
    remote = {a.remote_name: a.content for a in build_managed_config_plan(generated, None, {}).artifacts}
    remote["printer.cfg"] += b"[include user.cfg]\n"
    remote["user.cfg"] = b"[verify_heater heater_bed]\ncheck_gain_time: 999\n"
    if noop:
        remote.update({a.remote_name: a.content for a in build_managed_config_plan(generated, None, remote).artifacts})
    plan = build_managed_config_plan(generated, None, remote)
    assert _section_options(effective_hardware_text(plan))["verify_heater heater_bed"]["check_gain_time"] == "999"
    if noop:
        assert not plan.changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, generated, None,
        selected_board=selected_board_electrical_source(user_for(options, saved=True)), activation="none",
        confirm=confirm, snapshot_root=str(tmp_path), verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "selected-source protection" in result.detail
    assert transport.calls and all(c[0] == "read" for c in transport.calls)
    assert transport.files == remote
    confirm.assert_not_called()


@pytest.mark.parametrize("options", POLICIES)
def test_matching_profile_policy_publishes_and_repeats_without_retuning(options, tmp_path):
    generated = GENERATED + f"\n[verify_heater heater_bed]\n{options}\n".encode()
    selected = selected_board_electrical_source(user_for(options))
    transport = FakeTransport()
    for _ in range(2):
        result = ConfigDeploymentTransaction(transport, generated, None, selected_board=selected,
            activation="none", snapshot_root=str(tmp_path), poll_interval=0).run()
        assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION, result.detail
    effective = effective_hardware_text(build_managed_config_plan(generated, None, transport.files))
    assert _section_options(effective)["verify_heater heater_bed"] == parse_config(f"[verify_heater heater_bed]\n{options}")["verify_heater heater_bed"]


@pytest.mark.parametrize("mutation", ["old_parsed", "missing_parsed"])
def test_saved_raw_text_recovers_activity_only_when_consistent(mutation):
    user = user_for("check_gain_time: 600")
    if mutation == "old_parsed":
        user["_profile_parsed"].pop(SOURCE)
    else:
        user.pop("_profile_parsed")
    selected = selected_board_electrical_source(user)
    assert selected[PROFILE_SOURCE][SOURCE] == {"verify_heater heater_bed": {"check_gain_time": "600"}}


@pytest.mark.parametrize("change", ["rename", "different_policy", "clear_policy", "disable", "parsed_mismatch", "raw_mismatch"])
def test_live_and_saved_profile_conflicts_cannot_erase_requirement(change):
    user = user_for("check_gain_time: 600", saved=True)
    if change == "rename":
        user["printer_profile"] = "other.cfg"
    elif change == "different_policy":
        replacement = user_for("check_gain_time: 120")
        user.update({key: replacement[key] for key in ("_profile_parsed", "raw_config")})
    elif change == "clear_policy":
        user.update(_profile_parsed={}, raw_config="", profile_loaded=False)
    elif change == "disable":
        user["profile_loaded"] = False
    elif change == "parsed_mismatch":
        user["_profile_parsed"] = parse_config("[verify_heater heater_bed]\ncheck_gain_time: 120\n")
    else:
        user["raw_config"] = "[heater_bed]\nheater_pin: PA99\n"
    with pytest.raises(GenerationError, match="[Tt]hermal profile"):
        selected_board_electrical_source(user)


@pytest.mark.parametrize("parsed", [None, [], {}, {"verify_heater heater_bed": {"check_gain_time": "600"}}])
def test_no_proof_is_not_permission_to_discard_policy(parsed):
    user = user_for("check_gain_time: 600")
    user.update(raw_config="", _profile_parsed=parsed)
    with pytest.raises(GenerationError, match="source"):
        selected_board_electrical_source(user)


@pytest.mark.parametrize("cleared", [None, {}])
def test_comment_only_profile_and_custom_build_do_not_create_requirements(cleared):
    user = user_for("check_gain_time: 600")
    raw = "#[verify_heater heater_bed]\n#check_gain_time: 600\n"
    user.update(raw_config=raw, _profile_parsed=parse_config(raw, keep_comments=True))
    assert PROFILE_SOURCE not in selected_board_electrical_source(user)
    user.update(profile_loaded=False, _profile_parsed=cleared)  # Stale raw text is not a selected profile.
    assert PROFILE_SOURCE not in selected_board_electrical_source(user)
    assert selected_board_electrical_source({}) is None


@pytest.mark.parametrize("deadline", [120, 600])
def test_conflicting_board_and_profile_policies_require_resolution_not_precedence(deadline):
    user = user_for("check_gain_time: 120")
    user["board_raw_config"] += "\n[verify_heater heater_bed]\ncheck_gain_time: 600\n"
    selected = selected_board_electrical_source(user)
    with pytest.raises(GenerationError, match="selected-source protection"):
        validate_board_electrical_artifact(selected, GENERATED +
            f"\n[verify_heater heater_bed]\ncheck_gain_time: {deadline}\n".encode())


@pytest.mark.parametrize("options", POLICIES)
def test_live_export_and_firmware_adapters_enforce_separate_profile_before_side_effects(options, tmp_path):
    from core.deployer import _run_config_transaction, _copy_artifacts, deploy_firmware_installation
    from core.workflow_outcome import WorkflowOutcome
    from core.moonraker_deployer import DeployState
    from tests.unit.test_deployer import FirmwareInstallationPreconditionTests
    user, transport = user_for(options), FakeTransport()
    with patch("core.deployer._preflight_check") as preflight:
        result = _run_config_transaction(transport, user, "none", generated=("unused.cfg", GENERATED, None))
    assert result.outcome == WorkflowOutcome.PRECONDITION_FAILED
    assert "selected-source protection" in result.detail
    assert not transport.calls
    preflight.assert_not_called()
    with patch("core.deployer._generated_config_bytes", return_value=("unused.cfg", GENERATED, None)), \
         patch("core.deployer.shutil.copy2") as copy_file, \
         patch("core.deployer._review_configuration_export") as review:
        assert not _copy_artifacts(user, str(tmp_path), "all")
    review.assert_not_called()
    copy_file.assert_not_called()
    assert not (tmp_path / "printer.cfg").exists()
    firmware_user = FirmwareInstallationPreconditionTests()._user()
    firmware_user.update(user)
    with patch("core.deployer._generated_config_bytes", return_value=("unused.cfg", GENERATED, None)), \
         patch("core.config_transaction.configuration_transport", return_value=transport):
        result = deploy_firmware_installation(firmware_user)
    assert result.state == DeployState.FAILED_PRECONDITION
    assert "selected-source protection" in result.detail
    assert not transport.calls
    firmware_user["firmware_deployment_service"].execute.assert_not_called()
