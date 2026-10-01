"""Reviewed board cooling must survive omission, recovery and effective includes."""
import copy
import json
from pathlib import Path
import re
from unittest.mock import Mock, patch

import pytest

from core.board_auxiliary import selected_board_electrical_source, validate_board_electrical_artifact
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.exceptions import GenerationError
from core.generator import generate_config
from core.managed_config import build_managed_config_plan
from core.scraper import parse_config
from core.wizard.steps.hardware import _step_fan_assignment
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_generator import _user

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/required-board-cooling"
PROFILES = ("generic-bigtreetech-skr-mini-e3-v3.0.cfg", "generic-bigtreetech-skr-pico-v1.0.cfg")
FANS = ("heater_fan heatbreak_cooling_fan", "heater_fan controller_fan")


def source(profile):
    raw = (FIXTURES / profile).read_text(encoding="utf-8")
    return raw, parse_config(raw, profile, keep_comments=True)


def render(tmp_path, profile, **changes):
    raw, parsed = source(profile)
    user = _user(board=profile, printer_profile=profile, fan_hotend_pin="none", fan_part_cooling_pin="default")
    user.update(changes)
    return generate_config(parsed, user, output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("choice", [None, "none", "selected"])
def test_both_fans_survive_without_ui_selection(tmp_path, profile, choice):
    _, parsed = source(profile)
    if choice == "selected":
        choice = parsed[FANS[0]]["pin"]
    content = render(tmp_path, profile, fan_hotend_pin=choice)
    for name in FANS:
        assert parse_config(content)[name] == parsed[name]
        assert content.count(f"[{name}]") == 1
    validate_board_electrical_artifact(parsed, content)


@pytest.mark.parametrize("profile", PROFILES)
def test_old_parsed_checkpoint_needs_active_source(tmp_path, profile):
    _, parsed = source(profile)
    parsed = {name: fields for name, fields in parsed.items() if not name.startswith("_")}
    with pytest.raises(GenerationError, match="cooling"):
        selected_board_electrical_source({"board": profile, "board_parsed": parsed})
    with pytest.raises(GenerationError, match="cooling"):
        generate_config(parsed, _user(board=profile), output_path=str(tmp_path / "printer.cfg"), verbose=False)
    assert not (tmp_path / "printer.cfg").exists()


@pytest.mark.parametrize("profile", PROFILES)
def test_modified_source_is_not_automatically_qualified(tmp_path, profile):
    raw, parsed = source(profile)
    modified = parse_config(raw.replace(f"pin: {parsed[FANS[1]]['pin']}", "pin: PA8"), profile)
    with pytest.raises(GenerationError, match="cooling"):
        generate_config(modified, _user(board=profile), output_path=str(tmp_path / "printer.cfg"), verbose=False)


def complete_minimal(profile):
    _, parsed = source(profile)
    text = "[mcu]\nserial: /dev/serial/by-id/test\n[printer]\nkinematics: cartesian\n[stepper_x]\nstep_pin: PA1\n[extruder]\nheater_pin: " + parsed["extruder"]["heater_pin"] + "\n"
    for name in FANS:
        text += f"[{name}]\npin: {parsed[name]['pin']}\n"
    return text


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("name", FANS)
def test_saved_artifact_missing_required_fan_cannot_resume(profile, name):
    raw, _ = source(profile)
    restored = selected_board_electrical_source({"workflow_checkpoint": {"wizard_data": {"board": profile, "board_raw_config": raw}}})
    text = re.sub(r"\[" + re.escape(name) + r"\]\npin: [^\n]+\n", "", complete_minimal(profile))
    with pytest.raises(GenerationError, match="cooling"):
        validate_board_electrical_artifact(restored, text)


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("override", ["heater: heater_bed", "fan_speed: 0", "pin: PA8", "heater_temp: 200", "shutdown_speed: 0"])
@pytest.mark.parametrize("noop", [False, True])
def test_effective_override_rejected_before_upload(tmp_path, profile, override, noop):
    _, parsed = source(profile)
    content = complete_minimal(profile).encode()
    remote = {"printer.cfg": content + b"[include user.cfg]\n", "user.cfg": f"[{FANS[1]}]\n{override}\n".encode()}
    if noop:
        plan = build_managed_config_plan(content, None, remote)
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        assert not build_managed_config_plan(content, None, remote).changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, content, None, selected_board=parsed, activation="none", confirm=confirm,
        snapshot_root=str(tmp_path / "snapshots"), verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "cooling" in result.detail
    confirm.assert_not_called()
    assert not any(c[0] in ("upload", "delete", "restart") for c in transport.calls)


@pytest.mark.parametrize("profile", PROFILES)
def test_equivalent_explicit_defaults_and_aliases_are_valid(profile):
    _, parsed = source(profile)
    pin = parsed[FANS[1]]["pin"]
    text = complete_minimal(profile).replace(f"pin: {pin}", "pin: COOLING")
    text += f"[board_pins cooling]\naliases: COOLING={pin}\n[{FANS[1]}]\nheater: extruder\nheater_temp: 50\nfan_speed: 1\nmax_power: 1\nshutdown_speed: 1\n"
    validate_board_electrical_artifact(json.loads(json.dumps(parsed)), text)


@pytest.mark.parametrize("profile", PROFILES)
def test_wizard_does_not_offer_required_fans_for_part_cooling(profile, capsys):
    raw, parsed = source(profile)
    user = _user(board=profile, board_raw_config=raw)
    with patch("core.wizard.steps.hardware.numbered_select", side_effect=["default", "none"]) as select:
        assert _step_fan_assignment(user) == "success"
    offered = [c.get("value") for c in select.call_args_list[0].kwargs["choices"] if isinstance(c, dict)]
    assert not any(parsed[n]["pin"] in offered for n in FANS)
    assert "heatbreak_cooling_fan" in capsys.readouterr().out


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("prefix", ["!", "^", "~"])
def test_invalid_polarity_or_pullup_cannot_pass_artifact_review(profile, prefix):
    _, parsed = source(profile)
    pin = parsed[FANS[0]]["pin"]
    with pytest.raises(GenerationError, match="cooling"):
        validate_board_electrical_artifact(parsed, complete_minimal(profile).replace(f"pin: {pin}", f"pin: {prefix}{pin}"))


@pytest.mark.parametrize("profile", PROFILES)
def test_required_fan_pin_cannot_be_reused_by_output(profile):
    _, parsed = source(profile)
    content = complete_minimal(profile) + f"[output_pin custom]\npin: {parsed[FANS[1]]['pin']}\nvalue: 0\n"
    with pytest.raises(GenerationError, match="cooling"):
        validate_board_electrical_artifact(parsed, content)


@pytest.mark.parametrize("profile", PROFILES)
def test_firmware_reservation_is_checked_during_final_review(profile):
    _, parsed = source(profile)
    content = complete_minimal(profile).encode()
    plan = build_managed_config_plan(content, None, {"printer.cfg": content})
    reader = Mock(return_value={"mcu": {parsed[FANS[1]]["pin"]: "reserved transport"}})
    review = validate_configuration_plan(plan, selected_board=parsed, firmware_reservation_reader=reader)
    reader.assert_called_once()
    assert any("reserved transport" in e.message for e in review.errors if e.code == "board-cooling")


@pytest.mark.parametrize("profile", PROFILES)
def test_other_heater_pin_is_not_accepted(profile):
    _, parsed = source(profile)
    content = complete_minimal(profile).replace("heater_pin: " + parsed["extruder"]["heater_pin"], "heater_pin: PA8")
    with pytest.raises(GenerationError, match="cooling"):
        validate_board_electrical_artifact(parsed, content)


@pytest.mark.parametrize("profile", PROFILES)
def test_successful_publish_remains_idempotent(profile, tmp_path):
    _, parsed = source(profile)
    content = complete_minimal(profile).encode()
    transport = FakeTransport()
    for _ in range(2):
        result = ConfigDeploymentTransaction(transport, content, None, selected_board=parsed, activation="none",
            snapshot_root=str(tmp_path / "snapshots")).run()
        assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    assert all(name.encode() in transport.files["printer.cfg"] for name in FANS)
