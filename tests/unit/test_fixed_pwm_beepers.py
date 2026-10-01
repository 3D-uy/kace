"""Three reviewed sources: fixed beeper PWM survives generation and recovery."""
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from core.board_pwm import (SOURCE_FIXED_PWM, reviewed_beepers, selected_fixed_pwm_beepers,
    fixed_pwm_settings, validate_fixed_pwm_outputs)
from core.board_auxiliary import (SOURCE_ACTIVITY, SOURCE_OPTIONS, unresolved_pwm_outputs,
    selected_board_electrical_source, validate_board_electrical_artifact)
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.custom_probe import parse_custom_probe_config
from core.exceptions import GenerationError
from core.generator import generate_config
from core.managed_config import build_managed_config_plan
from core.pin_validator import _read_pin_config
from core.scraper import parse_config
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_generator import _user

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/fixed-pwm-beepers"


def board_case(profile):
    raw = (FIXTURES / profile).read_bytes().decode("utf-8")
    board = parse_config(raw, profile, keep_comments=True)
    # Exercise board PWM with the explicit no-display wizard choice.
    # The source LCD is not evidence of electrical compatibility.
    choices = _user(board=profile, x_size="180", y_size="180", z_size="180", display_choice="none")
    # Keep the active source motors required by controller fans. Commented
    # examples are not additional motors, and the product guard stays enabled.
    active = _read_pin_config(raw)[0]
    choices['z_motors'] = str(1 + sum(f'stepper_z{i}' in active for i in range(1, 4)))
    if profile == "printer-biqu-bx-2021.cfg":
        choices.update(probe="Custom Probe", driver_type="TMC2209", driver_mode="UART", z_motors="2")
        probe = _read_pin_config(raw)[0]["probe"]
        choices["custom_probe"] = parse_custom_probe_config("[probe]\n"+"".join(f"{k}: {v}\n" for k, v in probe.items()))
    return raw, board, choices


@pytest.fixture(params=list(reviewed_beepers()))
def case(request):
    raw, board, choices = board_case(request.param)
    return request.param, raw, board, choices, reviewed_beepers()[request.param]


def test_real_generation_provenance_and_repeat_publication(tmp_path, case):
    profile, raw, board, choices, entry = case
    assert selected_fixed_pwm_beepers(board) == {entry["section"]: entry["options"]}
    assert unresolved_pwm_outputs(board) == []
    result = generate_config(board, choices, output_path=str(tmp_path / "printer.cfg"), include_macros=True, verbose=False)
    generated = result["content"].encode()
    assert _read_pin_config(result["content"])[0][entry["section"]] == entry["options"]
    proof = json.loads((tmp_path / "printer.cfg.provenance.json").read_text())
    assert proof["sources"]["fixed_pwm_beepers"] == {entry["section"]: entry["options"]}
    source = selected_board_electrical_source({"workflow_checkpoint": {"wizard_data": {
        "board": profile, "board_raw_config": raw, "board_parsed": {}}}})
    validate_board_electrical_artifact(source, generated)
    dest = FakeTransport()
    for _ in range(2):
        outcome = ConfigDeploymentTransaction(dest, generated, None, selected_board=source,
            activation="none", snapshot_root=str(tmp_path / "snapshots"), poll_interval=0).run()
        assert outcome.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION, outcome.detail
    assert entry["section"].encode() in dest.files["printer.cfg"]


@pytest.mark.parametrize("mutation", ["no_source", "no_activity", "no_options", "pin", "name", "source_hash"])
def test_old_or_changed_parsed_source_cannot_enable_pwm(tmp_path, case, mutation):
    _, _, board, choices, entry = case
    name = entry["section"]
    if mutation == "no_source": board.pop(SOURCE_FIXED_PWM)
    elif mutation == "no_activity": board.pop(SOURCE_ACTIVITY)
    elif mutation == "no_options": board.pop(SOURCE_OPTIONS)
    elif mutation == "pin": board[name]["pin"] = "PG1"
    elif mutation == "name": board[name.swapcase()] = board.pop(name)
    else: board[SOURCE_FIXED_PWM]["source_sha256"] = "0"*64
    paths = [tmp_path / p for p in ("printer.cfg", "printer.cfg.provenance.json", "macros.cfg")]
    for p in paths: p.write_bytes(b"existing")
    with pytest.raises(GenerationError):
        generate_config(board, choices, output_path=str(paths[0]), include_macros=True, verbose=False)
    assert all(p.read_bytes() == b"existing" for p in paths)


def test_modified_source_or_added_consumer_stays_blocked(case):
    profile, raw, _, _, entry = case
    raw += "\n[gcode_macro M300]\ngcode:\n    SET_PIN PIN=" + entry["section"].split()[1] + " VALUE=.5 CYCLE_TIME=.002\n"
    changed = parse_config(raw, profile)
    assert SOURCE_FIXED_PWM not in changed
    assert entry["section"] in unresolved_pwm_outputs(changed)


@pytest.mark.parametrize("override", ["pin: PG1", "pin: !PG1", "value: .5", "shutdown_value: .5",
    "scale: 2", "cycle_time: .002", "pwm: False", "hardware_pwm: True", "static_value: 0"])
@pytest.mark.parametrize("noop", [False, True])
def test_effective_override_fails_before_writes_even_for_noop(tmp_path, override, noop):
    _, board, choices = board_case("printer-biqu-bx-2021.cfg")
    generated = generate_config(board, choices, output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"].encode()
    remote = {"printer.cfg": generated+b"\n[include user.cfg]\n",
              "user.cfg": ("[output_pin beeper]\n"+override+"\n").encode()}
    if noop:
        remote.update({a.remote_name: a.content for a in build_managed_config_plan(generated, None, remote).artifacts})
        assert not build_managed_config_plan(generated, None, remote).changed_artifacts
    dest, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(dest, generated, None, selected_board=board, confirm=confirm,
        activation="firmware", snapshot_root=str(tmp_path / "snapshots"), poll_interval=0).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "beeper" in result.detail
    assert all(call[0] == "read" for call in dest.calls) and dest.files == remote
    confirm.assert_not_called()
    assert not (tmp_path / "snapshots").exists()


@pytest.mark.parametrize("alteration", ["missing", "case", "cycle", "scale"])
def test_saved_artifact_change_blocks_before_transport(tmp_path, case, alteration):
    _, _, board, choices, entry = case
    text = generate_config(board, choices, output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]
    section = entry["section"]
    if alteration == "missing": text = text[:text.index("["+section+"]")]
    elif alteration == "case": text = text.replace("["+section+"]", "["+section.swapcase()+"]")
    else: text += f"\n[{section}]\n{alteration if alteration == 'scale' else 'cycle_time'}: 2\n"
    dest = FakeTransport()
    outcome = ConfigDeploymentTransaction(dest, text.encode(), None, selected_board=board,
        activation="firmware", snapshot_root=str(tmp_path / "snapshots")).run()
    assert outcome.state == ConfigTransactionState.PRECONDITION_FAILED and not dest.calls


def test_generation_and_review_enforce_reserved_gpio(tmp_path, case):
    _, _, board, choices, entry = case
    reserved = {"mcu": {entry["physical_pin"]: "USB"}}
    with patch("core.firmware_workflow.generation_pin_reservations", return_value=reserved):
        with pytest.raises(GenerationError, match="reserved for USB"):
            generate_config(board, choices, output_path=str(tmp_path / "printer.cfg"), verbose=False)
    assert not (tmp_path / "printer.cfg").exists()
    text = generate_config(board, choices, output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]
    reader = Mock(return_value=reserved)
    review = validate_configuration_plan(build_managed_config_plan(text.encode(), None, {}),
        selected_board=board, firmware_reservation_reader=reader)
    reader.assert_called_once()
    assert any(e.code == "fixed-pwm-output" and "reserved for USB" in e.message for e in review.errors)


@pytest.mark.parametrize("extra", ["[fan]\npin: PG1\n", "[static_digital_output enable]\npins: !PG1\n",
    "[duplicate_pin_override]\npins: PG1\n[fan]\npin: PG1\n", "[board_pins]\naliases: SAME=PG1\n[probe]\npin: SAME\n"])
def test_physical_collision_cannot_be_bypassed(extra):
    sections = _read_pin_config("[mcu]\nserial: /tmp/mcu\n[output_pin beeper]\npin: PG1\npwm: true\ncycle_time: .001\n"+extra)[0]
    with pytest.raises(GenerationError, match="conflicts"):
        validate_fixed_pwm_outputs(sections, {"output_pin beeper": {}})


@pytest.mark.parametrize("option,value", [("cycle_time", "0"), ("cycle_time", "3.001"), ("cycle_time", "nan"),
    ("scale", "0"), ("scale", "inf"), ("value", "1.1"), ("shutdown_value", "-1"),
    ("value", "nan"), ("hardware_pwm", "true"), ("pwm", "false"), ("pin", "^PG1"), ("static_value", "0")])
def test_pwm_numeric_and_option_boundary(option, value):
    fields = {"pin": "PG1", "pwm": "true", "cycle_time": ".001", option: value}
    with pytest.raises(GenerationError): fixed_pwm_settings(fields, "output_pin beeper")


def test_semantic_defaults_alias_and_scale_contract(tmp_path):
    _, board, choices = board_case("printer-eryone-thinker-series-v2-2020.cfg")
    generated = generate_config(board, choices, output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]
    equivalent = generated.replace("pin: EXP1_1", "pin: PE6").replace("pwm: True", "pwm: on")
    validate_board_electrical_artifact(board, equivalent)
    with pytest.raises(GenerationError, match="missing or changed"):
        validate_board_electrical_artifact(board, equivalent.replace("scale: 1000", "scale: 1"))
    board["board_pins"]["aliases"] = board["board_pins"]["aliases"].replace("EXP1_1=PE6", "EXP1_1=PE7")
    with pytest.raises(GenerationError, match="alias"):
        selected_fixed_pwm_beepers(board)


def test_live_export_and_firmware_adapters_reject_missing_qualified_beeper(tmp_path):
    from core.deployer import _run_config_transaction, _copy_artifacts, deploy_firmware_installation
    from core.workflow_outcome import WorkflowOutcome
    from core.moonraker_deployer import DeployState
    from tests.unit.test_deployer import FirmwareInstallationPreconditionTests
    raw, board, choices = board_case("printer-biqu-bx-2021.cfg")
    text = generate_config(board, choices, output_path=str(tmp_path / "generated.cfg"), verbose=False)["content"]
    missing = text[:text.index("[output_pin beeper]")].encode()
    user = FirmwareInstallationPreconditionTests()._user()
    user.update(board=choices["board"], board_raw_config=raw)
    dest = FakeTransport()
    with patch("core.deployer._generated_config_bytes", return_value=("unused", missing, None)), \
         patch("core.config_transaction.configuration_transport", return_value=dest), \
         patch("core.deployer.shutil.copy2") as copy:
        result = _run_config_transaction(dest, user, "none", generated=("unused", missing, None))
        assert result.outcome == WorkflowOutcome.PRECONDITION_FAILED and "beeper" in result.detail
        assert not _copy_artifacts(user, str(tmp_path), "all")
        assert deploy_firmware_installation(user).state == DeployState.FAILED_PRECONDITION
    assert not dest.calls
    copy.assert_not_called()
    user["firmware_deployment_service"].execute.assert_not_called()


def test_mechanical_profile_cannot_qualify_or_add_board_pwm(tmp_path):
    from tests.unit.test_generator import _parsed
    _, foreign, _ = board_case("printer-biqu-bx-2021.cfg")
    text = generate_config(_parsed(), _user(_profile_parsed=foreign),
        output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]
    assert "[output_pin beeper]" not in text


def test_automatic_source_display_still_requires_hardware_evidence(tmp_path):
    _, board, user = board_case("printer-eryone-thinker-series-v2-2020.cfg")
    assert "display" in board
    user["display_choice"] = None
    user["display_risk_accepted"] = True
    target = tmp_path / "printer.cfg"
    target.write_text("existing config")
    with pytest.raises(GenerationError, match="Unknown display hardware"):
        generate_config(board, user, output_path=str(target), verbose=False)
    assert target.read_text() == "existing config"
    assert not (tmp_path / "printer.cfg.provenance.json").exists()
