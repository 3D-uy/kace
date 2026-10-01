"""Explicit review must survive rendering and fail when its inputs change."""
import copy
import json
from unittest.mock import Mock, patch

import pytest

from core.board_auxiliary import selected_board_electrical_source, validate_board_electrical_artifact
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.exceptions import GenerationError, WizardExit
from core.firmware_workflow import persistable_wizard_data
from core.generator import generate_config
from core.managed_config import build_managed_config_plan, effective_hardware_text, _section_options
from core.scraper import parse_config
from core.thermal_review import RECEIPT, ARTIFACT_REVIEW
from core.wizard.steps.thermal import review_thermal_policy
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_generator import _parsed, _user
from tests.unit.test_verify_heater_source import POLICIES


def selection(options, origin="board"):
    parsed, user = _parsed(), _user()
    raw = "[verify_heater heater_bed]\n" + options + "\n"
    parsed_policy = parse_config(raw)
    if origin == "board":
        parsed.update(parsed_policy)
    else:
        user.update(_profile_parsed=parsed_policy, raw_config=raw, profile_loaded=True,
                    printer_profile="separate.cfg")
    user["board_parsed"] = parsed
    return parsed, user


def approve(board, user):
    with patch.dict("os.environ", {"KACE_AUTO": "0"}), \
         patch("core.wizard.steps.thermal.yes_no", return_value=True) as confirm:
        review_thermal_policy(board, user)
    confirm.assert_called_once()
    assert confirm.call_args.kwargs["default"] is False


@pytest.mark.parametrize("options", POLICIES)
@pytest.mark.parametrize("origin", ["board", "profile"])
def test_explicit_review_generates_and_recovers_policy_without_retuning(options, origin, tmp_path):
    board, user = selection(options, origin)
    with patch("core.reconciler.write_text_atomically") as write, \
         patch("core.generator.generate_starter_macros") as macros:
        preview = generate_config(board, user, output_path=str(tmp_path / "preview/printer.cfg"),
                                  include_macros=True, thermal_review_only=True, verbose=False)
        assert set(preview) == {"thermal_review"}
        assert not (tmp_path / "preview").exists()
        write.assert_not_called()
        macros.assert_not_called()
    approve(board, user)
    path = tmp_path / "printer.cfg"
    result = generate_config(board, user, output_path=str(path), verbose=False)
    actual = _section_options(result["content"])
    assert actual["verify_heater heater_bed"] == parse_config(f"[verify_heater heater_bed]\n{options}")["verify_heater heater_bed"]
    assert result["content"].count("[verify_heater heater_bed]") == 1
    provenance = json.loads((tmp_path / "printer.cfg.provenance.json").read_text())
    assert provenance["sources"]["thermal_policy_confirmation"] == user[RECEIPT]
    saved = json.loads(json.dumps(persistable_wizard_data(user)))
    source = selected_board_electrical_source({"workflow_checkpoint": {"wizard_data": saved}})
    validate_board_electrical_artifact(source, path.read_bytes())
    transport = FakeTransport()
    for _ in range(2):
        deployment = ConfigDeploymentTransaction(transport, path.read_bytes(), None, selected_board=source,
            activation="none", snapshot_root=str(tmp_path / "snapshots"), poll_interval=0).run()
        assert deployment.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION, deployment.detail


@pytest.mark.parametrize("decision", [False, None, "interrupt"])
def test_declining_or_interrupting_review_does_not_confirm_or_write(decision):
    board, user = selection(POLICIES[0])
    before = copy.deepcopy(user)
    with patch.dict("os.environ", {"KACE_AUTO": "0"}), \
         patch("core.wizard.steps.thermal.yes_no", side_effect=WizardExit() if decision == "interrupt" else None,
               return_value=decision), patch("core.reconciler.write_text_atomically") as write:
        with pytest.raises((GenerationError, WizardExit)):
            review_thermal_policy(board, user)
    assert user == before
    write.assert_not_called()


def test_automatic_mode_cannot_create_consent_but_can_reuse_current_confirmation():
    board, user = selection(POLICIES[0])
    with patch.dict("os.environ", {"KACE_AUTO": "1"}), patch("core.wizard.steps.thermal.yes_no") as confirm:
        with pytest.raises(GenerationError, match="automatic mode"):
            review_thermal_policy(board, user)
        confirm.assert_not_called()
    approve(board, user)
    with patch.dict("os.environ", {"KACE_AUTO": "1"}), patch("core.wizard.steps.thermal.yes_no") as confirm:
        review_thermal_policy(board, user)
        confirm.assert_not_called()


@pytest.mark.parametrize("change", ["pin", "sensor_pin", "sensor", "max_temp", "pid", "mcu", "board", "profile", "source", "policy", "alias", "sensor_definition"])
def test_changed_inputs_invalidate_confirmation_before_file_write(change, tmp_path):
    board, user = selection(POLICIES[0])
    approve(board, user)
    if change in ("pin", "sensor_pin"):
        board["heater_bed"]["heater_pin" if change == "pin" else "sensor_pin"] = "PF3"
    elif change == "sensor":
        user["bed_thermistor"] = "Generic 3950"
    elif change == "max_temp":
        user["bed_max_temp"] = "115"
    elif change == "pid":
        user["bed_pid_kp"] = "70"
    elif change == "mcu":
        user["mcu_path"] = "/dev/serial/by-id/changed"
    elif change in ("board", "profile"):
        user["board" if change == "board" else "printer_profile"] = "changed.cfg"
    elif change == "source":
        user["board_raw_config"] = "# source changed\n"
    elif change == "policy":
        from core.heater_verification import SOURCE
        board["verify_heater heater_bed"]["check_gain_time"] = "121"
        board[SOURCE]["verify_heater heater_bed"]["check_gain_time"] = "121"
    elif change == "alias":
        board["board_pins"] = {"aliases": "BED=PA6"}
    else:
        # Publication additionally protects definitions shadowing a sensor type;
        # exercise that boundary rather than adding an unused generation preset.
        content = generate_config(board, user, output_path=str(tmp_path / "good.cfg"), verbose=False)["content"]
        source = selected_board_electrical_source(user)
        with pytest.raises(GenerationError, match="Reviewed thermal hardware"):
            validate_board_electrical_artifact(source, content + "\n[thermistor injected]\ntemperature1: 25\nresistance1: 100000\n")
        return
    output = tmp_path / "printer.cfg"
    output.write_text("existing")
    with pytest.raises(GenerationError, match="selected-source protection.*review"):
        generate_config(board, user, output_path=str(output), verbose=False)
    assert output.read_text() == "existing"


def test_inputs_changed_during_confirmation_are_not_approved():
    board, user = selection(POLICIES[0])
    def change(*args, **kwargs):
        user["bed_max_temp"] = "115"
        return True
    with patch.dict("os.environ", {"KACE_AUTO": "0"}), patch("core.wizard.steps.thermal.yes_no", side_effect=change):
        with pytest.raises(GenerationError, match="changed during"):
            review_thermal_policy(board, user)
    assert RECEIPT not in user


@pytest.mark.parametrize("noop", [False, True])
def test_include_cannot_rewire_a_reviewed_heater(noop, tmp_path):
    board, user = selection(POLICIES[0])
    approve(board, user)
    content = generate_config(board, user, output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"].encode()
    remote = {a.remote_name: a.content for a in build_managed_config_plan(content, None, {}).artifacts}
    remote["printer.cfg"] += b"[include user.cfg]\n"
    remote["user.cfg"] = b"[heater_bed]\nheater_pin: PF3\n"
    if noop:
        remote.update({a.remote_name: a.content for a in build_managed_config_plan(content, None, remote).artifacts})
    plan = build_managed_config_plan(content, None, remote)
    assert _section_options(effective_hardware_text(plan))["heater_bed"]["heater_pin"] == "PF3"
    if noop:
        assert not plan.changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, content, None, selected_board=selected_board_electrical_source(user),
        activation="none", confirm=confirm, snapshot_root=str(tmp_path / "snapshots"), verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "Reviewed thermal hardware" in result.detail
    confirm.assert_not_called()
    assert transport.calls and all(call[0] == "read" for call in transport.calls)
    assert transport.files == remote


def test_saved_receipt_cannot_be_removed_by_current_data():
    board, user = selection(POLICIES[0])
    approve(board, user)
    with pytest.raises(GenerationError, match="differs from the saved"):
        selected_board_electrical_source({"workflow_checkpoint": {"wizard_data": user}, RECEIPT: None})


def test_default_only_selection_needs_no_new_prompt():
    board, user = selection("check_gain_time: 60")
    with patch("core.wizard.steps.thermal.yes_no") as confirm:
        review_thermal_policy(board, user)
    confirm.assert_not_called()
    assert RECEIPT not in user


@pytest.mark.parametrize("stop", [WizardExit, KeyboardInterrupt, GenerationError])
def test_cli_handles_review_stop_before_generation_or_deployment(stop, tmp_path):
    import kace
    from tests.regression.test_main_integration import _WIZARD_USER_DATA_WITH_PARSED
    user = copy.deepcopy(_WIZARD_USER_DATA_WITH_PARSED)
    error = GenerationError("thermal review declined") if stop is GenerationError else stop()
    with patch.dict("os.environ", {"KACE_AUTO": "1", "KACE_FIRMWARE_WORKFLOW_PATH": str(tmp_path / "workflow.json")}), \
         patch("kace.run_wizard", return_value=user), patch("kace.print_kace_banner"), \
         patch("kace.check_display_compatibility", return_value=[]), patch("kace.has_todo_pins", return_value=[]), \
         patch("kace.yes_no", return_value=False), patch("kace.print_workflow_result") as terminal, \
         patch("core.wizard.steps.thermal.review_thermal_policy", side_effect=error) as review, \
         patch("kace.generate_config") as generate, patch("kace.deploy_moonraker") as deploy:
        with pytest.raises(SystemExit) as result:
            kace.main()
    assert result.value.code == (20 if stop is GenerationError else 2)
    review.assert_called_once()
    assert terminal.called
    generate.assert_not_called()
    deploy.assert_not_called()
