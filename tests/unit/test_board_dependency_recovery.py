"""A saved/generated CFG cannot bypass selected-board electrical requirements."""
import copy
import contextlib
import hashlib
import os
from unittest.mock import Mock, patch

import pytest

from core.board_auxiliary import selected_board_electrical_source, validate_board_electrical_artifact
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.exceptions import GenerationError
from core.managed_config import build_managed_config_plan
from core.scraper import parse_config
from tests.unit.test_config_transaction import FakeTransport, GENERATED

STATIC = b"[static_digital_output power]\npins: !PG1\n"
GOOD = GENERATED + STATIC


@pytest.mark.parametrize("state", ["CONFIG_GENERATED", "READY_TO_DEPLOY", "DEPLOYING"])
@pytest.mark.parametrize("missing", [True, False])
def test_persisted_board_source_rejects_missing_or_rewired_artifact(state, missing):
    user = {"workflow_checkpoint": {"state": state, "wizard_data": {
        "board": "selected.cfg", "board_raw_config": STATIC.decode(),
        "board_parsed": {"static_digital_output power": {"pins": "!PG1"}},
    }}}
    source = selected_board_electrical_source(user)
    before = copy.deepcopy(user)
    validate_board_electrical_artifact(source, GOOD)
    with pytest.raises(GenerationError, match="missing or changed"):
        validate_board_electrical_artifact(source, GENERATED if missing else GOOD.replace(b"!PG1", b"PG2"))
    assert user == before


@pytest.mark.parametrize("user", [
    {"board": "selected.cfg"}, {"board": "selected.cfg", "board_parsed": {}},
    {"board_raw_config": 42}, {"workflow_checkpoint": {}},
    {"board": "new.cfg", "workflow_checkpoint": {"wizard_data": {"board": "old.cfg", "board_raw_config": STATIC.decode()}}},
])
def test_missing_malformed_or_wrong_board_source_rejects(user):
    with pytest.raises(GenerationError):
        selected_board_electrical_source(user)


def test_profile_is_not_board_authority_and_parsed_input_is_not_shared():
    board = parse_config(STATIC.decode())
    user = {"board": "selected.cfg", "board_parsed": board,
            "raw_config": "[output_pin motor_power]\npin: PC13\nvalue: 1\n",
            "_profile_parsed": {"static_digital_output power": {"pins": "PG2"}}}
    source = selected_board_electrical_source(user)
    validate_board_electrical_artifact(source, GOOD)
    board["static_digital_output power"]["pins"] = "PG3"
    validate_board_electrical_artifact(source, GOOD)
    assert selected_board_electrical_source({}) is None


def test_commented_old_example_is_recovered_from_raw_source_without_enabling_it():
    source = selected_board_electrical_source({"board": "selected.cfg", "board_raw_config": "#[static_digital_output example]\n#pins: PG1\n",
        "board_parsed": {"static_digital_output example": {"pins": "PG1"}}})
    validate_board_electrical_artifact(source, GENERATED)


@pytest.mark.parametrize("pins", ["PG1", "!PG2", "!aux:PG1"])
def test_changed_polarity_gpio_or_mcu_is_not_equivalent(pins):
    source = parse_config(STATIC.decode())
    with pytest.raises(GenerationError, match="missing or changed"):
        validate_board_electrical_artifact(source, GENERATED+b"[mcu aux]\nserial: /tmp/aux\n"+STATIC.replace(b"!PG1", pins.encode()))


def test_alias_rewrite_compares_physical_pin_not_spelling():
    source = parse_config("[board_pins]\naliases: POWER=PG1\n"+STATIC.decode().replace("!PG1", "!POWER"))
    validate_board_electrical_artifact(source, GOOD)
    with pytest.raises(GenerationError, match="missing or changed"):
        validate_board_electrical_artifact(source, GENERATED+b"[board_pins]\naliases: POWER=PG2\n"+STATIC.replace(b"!PG1", b"!POWER"))


@pytest.mark.parametrize("section", ["output_pin motor_power", "dac084s085 currents", "ad5206 currents", "mcp4451 currents", "mcp4018 currents"])
def test_old_artifact_with_unsupported_or_missing_dependency_stops_before_transport(section, tmp_path):
    board = parse_config(f"[{section}]\npin: PG1\nvalue: 1\n")
    transport, confirm = FakeTransport({"printer.cfg": GENERATED}), Mock(return_value=True)
    transaction = ConfigDeploymentTransaction(transport, GENERATED, None, selected_board=board,
        activation="firmware", confirm=confirm, snapshot_root=str(tmp_path), poll_interval=0)
    # Later mutation of the caller cannot erase the transaction's source.
    board.clear()
    result = transaction.run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert section in result.detail
    confirm.assert_not_called()
    assert not transport.calls
    assert transport.files == {"printer.cfg": GENERATED}
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("noop", [False, True])
def test_effective_user_include_cannot_change_selected_static_output(noop, tmp_path):
    remote = {"printer.cfg": GOOD+b"[include user.cfg]\n", "user.cfg": STATIC.replace(b"!PG1", b"PG1")}
    if noop:
        remote.update({a.remote_name: a.content for a in build_managed_config_plan(GOOD, None, remote).artifacts})
        assert not build_managed_config_plan(GOOD, None, remote).changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, GOOD, None, selected_board=parse_config(STATIC.decode()),
        activation="firmware", confirm=confirm, snapshot_root=str(tmp_path), poll_interval=0).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "missing or changed" in result.detail
    confirm.assert_not_called()
    assert transport.files == remote
    assert all(c[0] == "read" for c in transport.calls)
    assert not list(tmp_path.iterdir())


def test_valid_static_configuration_publishes_and_repeats(tmp_path):
    transport = FakeTransport()
    for _ in range(2):
        result = ConfigDeploymentTransaction(transport, GOOD, None, selected_board=parse_config(STATIC.decode()),
            activation="none", snapshot_root=str(tmp_path), poll_interval=0).run()
        assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    assert b"pins: !PG1" in transport.files["printer.cfg"]


@pytest.mark.parametrize("output_name", ["motor_power", "probe_enable", "screen"])
def test_live_adapter_and_export_enforce_source_guard(tmp_path, output_name):
    from core.deployer import _run_config_transaction, _copy_artifacts
    from core.workflow_outcome import WorkflowOutcome
    user = {"board": "selected.cfg", "board_raw_config": f"[output_pin {output_name}]\npin: PC13\nvalue: 1\n"}
    transport = FakeTransport()
    with patch("core.deployer._preflight_check", return_value=True), \
         patch("core.deployer._interactive_configuration_review") as review:
        result = _run_config_transaction(transport, user, "none", generated=("unused.cfg", GENERATED, None))
    assert result.outcome == WorkflowOutcome.PRECONDITION_FAILED
    assert output_name in result.detail
    assert not transport.calls
    review.assert_not_called()
    with patch("core.deployer._generated_config_bytes", return_value=("unused.cfg", GENERATED, None)), \
         patch("core.deployer._review_configuration_export") as review:
        assert not _copy_artifacts(user, str(tmp_path), "config")
    review.assert_not_called()
    assert not (tmp_path / "printer.cfg").exists()


@pytest.mark.parametrize("output_name", ["motor_power", "probe_enable", "screen"])
def test_integrated_firmware_gate_precedes_remote_read_and_physical_work(output_name):
    from core.deployer import deploy_firmware_installation
    from core.moonraker_deployer import DeployState
    from tests.unit.test_deployer import FirmwareInstallationPreconditionTests
    user = FirmwareInstallationPreconditionTests()._user()
    user.update(board="selected.cfg", board_raw_config=f"[output_pin {output_name}]\npin: PC13\nvalue: 1\n")
    destination = FakeTransport()
    with patch("core.deployer._generated_config_bytes", return_value=("unused.cfg", GENERATED, None)), \
         patch("core.config_transaction.configuration_transport", return_value=destination):
        result = deploy_firmware_installation(user)
    assert result.state == DeployState.FAILED_PRECONDITION
    assert output_name in result.detail
    assert not destination.calls
    user["firmware_deployment_service"].execute.assert_not_called()


@pytest.mark.parametrize("output_name", ["motor_power", "probe_enable", "screen"])
def test_combined_export_does_not_copy_firmware_after_config_rejection(tmp_path, output_name):
    from core.deployer import _copy_artifacts
    firmware = tmp_path / "firmware.bin"
    firmware.write_bytes(b"existing firmware artifact")
    destination = tmp_path / "card"
    destination.mkdir()
    user = {"board": "selected.cfg", "board_raw_config": f"[output_pin {output_name}]\npin: PC13\nvalue: 1\n",
            "firmware_path": str(firmware)}
    with patch("core.deployer._generated_config_bytes", return_value=("unused.cfg", GENERATED, None)), \
         patch("core.deployer.shutil.copy2") as copy_file:
        assert not _copy_artifacts(user, str(destination), "all")
    copy_file.assert_not_called()
    assert not (destination / "printer.cfg").exists()
    assert not (destination / "firmware.bin").exists()
    assert firmware.read_bytes() == b"existing firmware artifact"


@pytest.mark.parametrize("state", ["CONFIG_GENERATED", "READY_TO_DEPLOY", "DEPLOYING"])
@pytest.mark.parametrize("raw,reason", [(STATIC.decode(), "missing or changed"),
    ("[output_pin motor_power]\npin: PC13\nvalue: 1\n", "motor_power"),
    ("[output_pin probe_enable]\npin: PE5\nvalue: 1\n", "probe_enable"),
    ("[output_pin screen]\npin: PB5\nvalue: 1\n", "screen"),
    ("[output_pin beeper]\npin: PA14\npwm: True\ncycle_time: .001\n", "beeper"),
    ("[fan]\npin: PC5\nmax_power: 0.6\n", "fan source"),
    ("[heater_fan HeatBreak]\npin: PC5\nmax_power: 0.6\n", "fan source"),
    ("BX", "heater_fan extruder_fan"), ("BX", "controller_fan controller_fan"),
    ("[verify_heater heater_bed]\nheating_gain: 1\ncheck_gain_time: 120\n", "selected-source protection"),
    ("[verify_heater heater_bed]\ncheck_gain_time: 240\n", "selected-source protection"),
    ("[verify_heater heater_bed]\ncheck_gain_time: 600\n", "selected-source protection"),
    ("PROFILE:heating_gain: 1\ncheck_gain_time: 120", "selected-source protection"),
    ("PROFILE:check_gain_time: 240", "selected-source protection"),
    ("PROFILE:check_gain_time: 600", "selected-source protection")])
def test_real_cli_resume_rechecks_saved_artifact_before_deployment(state, raw, reason, tmp_path):
    import kace
    from core.firmware_workflow import (create_checkpoint, transition_checkpoint, write_checkpoint,
                                        load_checkpoint, FirmwareWorkflowState as State)
    from tests.regression.test_main_integration import _WIZARD_USER_DATA_WITH_PARSED
    user = {**copy.deepcopy(_WIZARD_USER_DATA_WITH_PARSED), "mcu_type": "lpc1769",
            "mcu_path": "/dev/serial/by-id/test", "board_raw_config": raw}
    saved_artifact = GENERATED
    if reason == "selected-source protection":
        from tests.unit.test_verify_heater_review import GENERATED as THERMAL_GENERATED
        saved_artifact = THERMAL_GENERATED
        if raw.startswith("PROFILE:"):
            from core.profile_values import HARDWARE_SOURCE_POLICY
            profile_raw = "[verify_heater heater_bed]\n" + raw.removeprefix("PROFILE:") + "\n"
            user.update(board_raw_config=THERMAL_GENERATED.decode(), raw_config=profile_raw,
                        _profile_parsed=parse_config(profile_raw), profile_loaded=True,
                        printer_profile="separate-printer.cfg", hardware_source_policy=HARDWARE_SOURCE_POLICY)
    if raw == "BX":
        import re
        from core.generator import generate_config
        from core.board_bx_panel import PROFILE
        from tests.unit.test_fixed_pwm_beepers import board_case
        raw, board, choices = board_case(PROFILE)
        user.update(choices, board_raw_config=raw, board_parsed=board, mcu_type="stm32h743")
        content = generate_config(board, choices, output_path=str(tmp_path / "good.cfg"), verbose=False)["content"]
        saved_artifact = re.sub(r"(?ms)^\[" + re.escape(reason) + r"\][^\n]*\n.*?(?=^\[|\Z)", "", content).encode()
    firmware = tmp_path / "firmware.bin"
    firmware.write_bytes(b"firmware")
    evidence = {
        "path": str(firmware), "final_filename": "firmware.bin", "sha256": hashlib.sha256(b"firmware").hexdigest(),
        "size_bytes": 8, "method": "MANUAL", "strategy": "SD_CARD", "instructions": [], "build": {"mcu": user["mcu_type"]}}
    if user["board"] == "printer-biqu-bx-2021.cfg":
        from tests.unit.test_bx_startup import artifact
        built = artifact(tmp_path)
        evidence.update(path=built.path, sha256=built.sha256, size_bytes=built.size_bytes, build=built.to_dict())
    checkpoint = transition_checkpoint(create_checkpoint(user), State.ARTIFACT_READY, artifact=evidence)
    checkpoint = transition_checkpoint(checkpoint, State.VERIFYING_MCU)
    checkpoint = transition_checkpoint(checkpoint, State.MCU_VERIFIED,
        verified_serial_path=user["mcu_path"], flash_evidence_recorded_at=1)
    for next_state in (State.CONFIG_GENERATED, State.READY_TO_DEPLOY, State.DEPLOYING):
        checkpoint = transition_checkpoint(checkpoint, next_state)
        if next_state.value == state:
            break
    checkpoint_path = str(tmp_path / "workflow.json")
    write_checkpoint(checkpoint, checkpoint_path)
    assert load_checkpoint(checkpoint_path, current_hardware={}, verify_artifact=True)["state"] == state
    cfg = tmp_path / "printer.cfg"
    if reason == "fan source":
        saved_artifact += raw.replace("max_power: 0.6\n", "").encode()
    cfg.write_bytes(saved_artifact)
    expanduser = os.path.expanduser
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, {"KACE_AUTO": "1", "KACE_FIRMWARE_WORKFLOW_PATH": checkpoint_path}))
        stack.enter_context(patch("kace.os.path.expanduser", side_effect=lambda p:
            str(cfg) if p == "~/kace/printer.cfg" else expanduser(p)))
        stack.enter_context(patch("firmware.detector.discover_mcu_hardware", return_value={}))
        for name in ("print_kace_banner", "print_summary", "time.sleep"):
            stack.enter_context(patch("kace."+name))
        stack.enter_context(patch("kace.check_display_compatibility", return_value=[]))
        generated = stack.enter_context(patch("kace.generate_config"))
        stack.enter_context(patch("kace.run_wizard", side_effect=AssertionError("Must resume the valid checkpoint")))
        menu = stack.enter_context(patch("kace.numbered_select"))
        deployment = stack.enter_context(patch("kace.deploy_moonraker"))
        terminal = stack.enter_context(patch("kace.print_workflow_result"))
        with pytest.raises(SystemExit) as result:
            kace.main()
    assert result.value.code != 0
    assert reason in terminal.call_args.args[0].detail
    generated.assert_not_called()
    menu.assert_not_called()
    deployment.assert_not_called()
    assert cfg.read_bytes() == saved_artifact
    assert load_checkpoint(checkpoint_path)["state"] != "COMPLETE"
