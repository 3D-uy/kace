"""Probe reset is an output, a literal macro and a pre-probe callback contract."""
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from core.board_probe_reset import (SOURCE_RESET, RESET_OUTPUT, RESET_MACRO, RESET_COMMANDS,
    selected_probe_reset, validate_probe_reset_artifact)
from core.board_auxiliary import selected_board_digital_outputs, validate_board_electrical_artifact
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.custom_probe import parse_custom_probe_config
from core.exceptions import GenerationError
from core.generator import generate_config
from core.managed_config import build_managed_config_plan
from core.pin_validator import _read_pin_config
from core.scraper import parse_config
from tests.unit.test_generator import _user
from tests.unit.test_config_transaction import FakeTransport

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PROFILES = ("printer-anycubic-vyper-2021.cfg", "printer-anycubic-kobra-plus-2022.cfg")


def reset_case(profile, mode="Custom Probe"):
    raw = (FIXTURES / ("fixed-pwm-beepers" if "vyper" in profile else "probe-reset") / profile).read_bytes().decode()
    board = parse_config(raw, profile, keep_comments=True)
    choices = _user(board=profile, x_size="180", y_size="180", z_size="180", probe=mode)
    # The reset circuit fixture must also satisfy its active controller fan's
    # motor dependencies; dropping Z1 would prevent reaching the reset test.
    active = _read_pin_config(raw)[0]
    choices['z_motors'] = str(1 + sum(f'stepper_z{i}' in active for i in range(1, 4)))
    # The reset circuit fixture must also satisfy its active controller fan's
    # motor dependencies; dropping Z1 would prevent reaching the reset test.
    active = _read_pin_config(raw)[0]
    choices['z_motors'] = str(1 + sum(f'stepper_z{i}' in active for i in range(1, 4)))
    if mode == "Custom Probe":
        fields = _read_pin_config(raw)[0]["probe"]
        fields.update(x_offset="0", y_offset="0")  # Explicit fixture geometry choices.
        choices["custom_probe"] = parse_custom_probe_config("[probe]\n"+"".join(
            f"{k}: "+v.replace("\n", "\n    ")+"\n" for k, v in fields.items()))
    return raw, board, choices


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("mode", ["Custom Probe", "Inductive"])
def test_real_source_hook_macro_outputs_and_repeat_publication(tmp_path, profile, mode):
    raw, board, choices = reset_case(profile, mode)
    expected = _read_pin_config(raw)[0]
    text = generate_config(board, choices, output_path=str(tmp_path / "printer.cfg"), include_macros=True, verbose=False)["content"]
    actual = _read_pin_config(text)[0]
    for name in (RESET_OUTPUT, "output_pin LED"):
        assert actual[name] == expected[name]
    assert actual["probe"]["activate_gcode"].strip() == "probe_reset"
    assert tuple(line.strip() for line in actual[RESET_MACRO]["gcode"].splitlines() if line.strip()) == RESET_COMMANDS
    assert text.count("["+RESET_MACRO+"]") == 1
    proof = json.loads((tmp_path / "printer.cfg.provenance.json").read_text())
    assert proof["sources"]["probe_reset"] == board[SOURCE_RESET]
    validate_board_electrical_artifact(board, text)
    dest = FakeTransport()
    for _ in range(2):
        outcome = ConfigDeploymentTransaction(dest, text.encode(), None, selected_board=board,
            activation="none", snapshot_root=str(tmp_path / "snapshots"), poll_interval=0).run()
        assert outcome.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION, outcome.detail


def test_no_probe_choice_keeps_standalone_reset_without_inventing_probe(tmp_path):
    _, board, choices = reset_case(PROFILES[0], "None")
    text = generate_config(board, choices, output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]
    sections = _read_pin_config(text)[0]
    assert "probe" not in sections and RESET_MACRO in sections and RESET_OUTPUT in sections
    validate_board_electrical_artifact(board, text)


@pytest.mark.parametrize("mutation", ["missing_source", "missing_macro", "delay", "reversed", "hook", "deactivate", "template", "duplicate_case"])
def test_unreviewed_source_never_replaces_artifacts(tmp_path, mutation):
    _, board, choices = reset_case(PROFILES[0])
    if mutation == "missing_source": board.pop(SOURCE_RESET)
    elif mutation == "missing_macro": board[SOURCE_RESET]["macros"] = {}
    elif mutation == "hook": board[SOURCE_RESET]["probe"]["activate_gcode"] = "other"
    elif mutation == "deactivate": board[SOURCE_RESET]["probe"]["deactivate_gcode"] = "SET_PIN PIN=probe_reset_pin VALUE=0"
    elif mutation == "duplicate_case": board[SOURCE_RESET]["macros"]["gcode_macro PROBE_RESET"] = {"gcode": "\n".join(RESET_COMMANDS)}
    else:
        old = board[SOURCE_RESET]["macros"][RESET_MACRO]["gcode"]
        board[SOURCE_RESET]["macros"][RESET_MACRO]["gcode"] = (old.replace("P300", "P200") if mutation == "delay"
            else "\n".join(reversed(RESET_COMMANDS)) if mutation == "reversed" else old+"\n{ action_emergency_stop('x') }")
    paths = [tmp_path / n for n in ("printer.cfg", "printer.cfg.provenance.json", "macros.cfg")]
    for p in paths: p.write_bytes(b"existing")
    with pytest.raises(GenerationError):
        generate_config(board, choices, output_path=str(paths[0]), include_macros=True, verbose=False)
    assert all(p.read_bytes() == b"existing" for p in paths)


@pytest.mark.parametrize("override", ["[probe]\nactivate_gcode: other\n", "[probe]\npin: PB12\n",
    "[probe]\npin: ^!PB12\n", "[probe]\ndeactivate_gcode: probe_reset\n",
    "[gcode_macro probe_reset]\ngcode:\n  SET_PIN PIN=probe_reset_pin VALUE=1\n",
    "[gcode_macro PROBE_RESET]\ngcode:\n  G4 P100\n",
    "[output_pin probe_reset_pin]\npin: PB14\n", "[output_pin probe_reset_pin]\nvalue: 1\n",
    "[output_pin LED]\nvalue: 1\n"])
@pytest.mark.parametrize("noop", [False, True])
def test_effective_override_cannot_bypass_binding(tmp_path, override, noop):
    _, board, choices = reset_case(PROFILES[0])
    text = generate_config(board, choices, output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"].encode()
    remote = {"printer.cfg": text+b"\n[include user.cfg]\n", "user.cfg": override.encode()}
    if noop:
        remote.update({a.remote_name: a.content for a in build_managed_config_plan(text, None, remote).artifacts})
        assert not build_managed_config_plan(text, None, remote).changed_artifacts
    dest, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(dest, text, None, selected_board=board, confirm=confirm,
        activation="firmware", snapshot_root=str(tmp_path / "snapshots")).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert all(call[0] == "read" for call in dest.calls) and dest.files == remote
    confirm.assert_not_called()
    assert not (tmp_path / "snapshots").exists()


@pytest.mark.parametrize("mode", ["missing_macro", "missing_hook", "changed_macro", "changed_pin"])
def test_saved_artifact_fails_before_transport(tmp_path, mode):
    _, board, choices = reset_case(PROFILES[0])
    text = generate_config(board, choices, output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]
    if mode == "missing_macro": text = text[:text.index("["+RESET_MACRO+"]")]
    elif mode == "missing_hook": text = text.replace("probe_reset\n", "\n", 1)
    elif mode == "changed_macro": text = text.replace("G4 P300", "G4 P200")
    else: text = text.replace("pin: PB13", "pin: PB14")
    dest = FakeTransport()
    result = ConfigDeploymentTransaction(dest, text.encode(), None, selected_board=board,
        activation="firmware", snapshot_root=str(tmp_path / "snapshots")).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED and not dest.calls


@pytest.mark.parametrize("change", ["hook", "macro", "probe_pin"])
def test_custom_probe_conflicts_are_rejected_instead_of_overwritten(tmp_path, change):
    _, board, choices = reset_case(PROFILES[0])
    raw = choices["custom_probe"].config_text
    if change == "hook": raw = raw.replace("probe_reset", "other")
    elif change == "probe_pin": raw = raw.replace("!PB12", "!PB14")
    else: raw += "\n[gcode_macro probe_reset]\ngcode:\n  G4 P200\n"
    choices["custom_probe"] = parse_custom_probe_config(raw)
    with pytest.raises(GenerationError):
        generate_config(board, choices, output_path=str(tmp_path / "printer.cfg"), verbose=False)
    assert not (tmp_path / "printer.cfg").exists()


def test_commented_reset_cannot_activate_and_old_source_requires_reload():
    raw = "#[output_pin probe_reset_pin]\n#pin: PB13\n"
    assert selected_probe_reset(parse_config(raw, keep_comments=True)) is None
    with pytest.raises(GenerationError, match="source evidence"):
        selected_probe_reset({RESET_OUTPUT: {"pin": "PB13"}})


@pytest.mark.parametrize("section", [RESET_OUTPUT, "output_pin LED"])
def test_new_outputs_enforce_conflicts_and_firmware_reservations(tmp_path, section):
    _, board, choices = reset_case(PROFILES[0])
    pin = board[section]["pin"].split(":")[-1]
    with patch("core.firmware_workflow.generation_pin_reservations", return_value={"mcu": {pin: "JTAG"}}):
        with pytest.raises(GenerationError, match="reserved for JTAG"):
            generate_config(board, choices, output_path=str(tmp_path / "printer.cfg"), verbose=False)
    board[section]["pin"] = board["fan"]["pin"]
    with pytest.raises(GenerationError, match="conflicts"):
        generate_config(board, choices, output_path=str(tmp_path / "printer.cfg"), verbose=False)
    assert not (tmp_path / "printer.cfg").exists()


@pytest.mark.parametrize("commented", [False, True])
def test_unrelated_user_led_pwm_is_not_treated_as_selected_board_signal(tmp_path, commented):
    from tests.unit.test_config_transaction import GENERATED
    from core.configuration_review import validate_configuration_plan
    user_pwm = b"[output_pin LED]\npin: PG1\npwm: True\ncycle_time: .001\n"
    source = parse_config("#[output_pin LED]\n#pin: PG1\n#pwm: True\n", keep_comments=True) if commented else None
    remote = {"printer.cfg": GENERATED+b"\n[include user.cfg]\n", "user.cfg": user_pwm}
    reader = Mock(side_effect=AssertionError("unselected LED must not require firmware evidence"))
    review = validate_configuration_plan(build_managed_config_plan(GENERATED, None, remote),
        selected_board=source, firmware_reservation_reader=reader)
    assert review.valid
    reader.assert_not_called()
    dest = FakeTransport(remote)
    result = ConfigDeploymentTransaction(dest, GENERATED, None, selected_board=source,
        activation="none", snapshot_root=str(tmp_path), poll_interval=0).run()
    assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION, result.detail
    assert dest.files["user.cfg"] == user_pwm
