"""Sunlu's source hotend fan is a dependency, not an optional fan selection."""
import json
import re
from unittest.mock import Mock, patch

import pytest

from core.board_auxiliary import selected_board_electrical_source, validate_board_electrical_artifact
from core.board_cooling import SOURCE
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.exceptions import GenerationError
from core.firmware_workflow import persistable_wizard_data
from core.generator import generate_config
from core.managed_config import build_managed_config_plan
from core.profile_values import extract_profile_values
from core.scraper import parse_config
from core.wizard.steps.hardware import _step_fan_assignment
from core.wizard.steps.thermal import review_thermal_policy
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_generator import _user
from tests.unit.test_required_board_cooling import FIXTURES

PROFILE = "printer-sunlu-s8-2020.cfg"
FAN = "heater_fan fan1"


def inputs():
    raw = (FIXTURES / PROFILE).read_text(encoding="utf-8")
    board = parse_config(raw, PROFILE, keep_comments=True)
    user = _user(board=PROFILE, printer_profile=PROFILE, board_raw_config=raw,
                 board_parsed=board, fan_part_cooling_pin="default", display_choice="none")
    user.update(extract_profile_values(board))
    return raw, board, user


def render(tmp_path, **changes):
    _, board, user = inputs()
    user.update(changes)
    with patch.dict("os.environ", {"KACE_AUTO": "0"}), patch("core.wizard.steps.thermal.yes_no", return_value=True):
        review_thermal_policy(board, user)
    text = generate_config(board, user, output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]
    saved = json.loads(json.dumps(persistable_wizard_data(user)))
    context = selected_board_electrical_source({"workflow_checkpoint": {"wizard_data": saved}})
    return text, context


@pytest.mark.parametrize("choice", [None, "none", "PH4"])
def test_required_fan_survives_omission_and_selection(tmp_path, choice):
    text, context = render(tmp_path, fan_hotend_pin=choice)
    assert text.count(f"[{FAN}]") == 1
    assert parse_config(text)[FAN] == {"pin": "PH4"}
    validate_board_electrical_artifact(context, text)
    transport = FakeTransport()
    for _ in range(2):
        result = ConfigDeploymentTransaction(transport, text.encode(), None, selected_board=context,
            activation="none", snapshot_root=str(tmp_path / "snapshots")).run()
        assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION


def test_saved_cfg_without_fan_cannot_resume(tmp_path):
    text, context = render(tmp_path, fan_hotend_pin="none")
    broken = re.sub(r"(?ms)^\[heater_fan fan1\]\n.*?(?=^\[|\Z)", "", text)
    assert FAN not in parse_config(broken)
    with pytest.raises(GenerationError, match="cooling"):
        validate_board_electrical_artifact(context, broken)


@pytest.mark.parametrize("override", ["pin: !PH4", "heater: heater_bed", "fan_speed: 0",
                                      "heater_temp: 200", "shutdown_speed: 0"])
@pytest.mark.parametrize("noop", [False, True])
def test_changed_effective_fan_blocks_before_write(tmp_path, override, noop):
    text, context = render(tmp_path, fan_hotend_pin="none")
    content = text.encode()
    remote = {"printer.cfg": content + b"[include user.cfg]\n", "user.cfg": f"[{FAN}]\n{override}\n".encode()}
    if noop:
        remote.update({a.remote_name: a.content for a in build_managed_config_plan(content, None, remote).artifacts})
        assert not build_managed_config_plan(content, None, remote).changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, content, None, selected_board=context,
        activation="none", confirm=confirm, snapshot_root=str(tmp_path / "snapshots"), verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "cooling" in result.detail
    confirm.assert_not_called()
    assert transport.files == remote
    assert all(c[0] == "read" for c in transport.calls)


@pytest.mark.parametrize("change", ["hash", "active", "heater", "legacy"])
def test_changed_or_old_source_is_rejected_before_generation(tmp_path, change):
    raw, board, user = inputs()
    if change == "hash":
        board = parse_config(raw + "\n# new unreviewed source\n", PROFILE)
    elif change == "active":
        board[FAN]["pin"] = "PH3"
    elif change == "heater":
        board["extruder"]["heater_pin"] = "PB5"
    else:
        board.pop(SOURCE)
        with pytest.raises(GenerationError, match="cooling"):
            selected_board_electrical_source({"board": PROFILE, "board_parsed": board})
    with pytest.raises(GenerationError, match="cooling"):
        generate_config(board, user, output_path=str(tmp_path / "printer.cfg"), verbose=False)
    assert not (tmp_path / "printer.cfg").exists()


def test_wizard_explains_required_cooling_and_excludes_part_fan_reuse(capsys):
    _, _, user = inputs()
    with patch("core.wizard.steps.hardware.numbered_select", side_effect=["default", "none"]) as select:
        assert _step_fan_assignment(user) == "success"
    offered = [c.get("value") for c in select.call_args_list[0].kwargs["choices"] if isinstance(c, dict)]
    assert "PH4" not in offered
    assert FAN in capsys.readouterr().out


def test_separate_sunlu_profile_does_not_import_ph4_on_other_board():
    raw, profile, _ = inputs()
    name = "generic-bigtreetech-skr-mini-e3-v3.0.cfg"
    board_raw = (FIXTURES / name).read_text(encoding="utf-8")
    context = selected_board_electrical_source({"board": name, "board_raw_config": board_raw,
        "printer_profile": PROFILE, "raw_config": raw, "_profile_parsed": profile, "profile_loaded": True})
    from core.board_cooling import required_board_fans
    assert FAN not in required_board_fans(context)
    assert len(required_board_fans(context)) == 2


def test_required_pin_cannot_be_repurposed_or_reserved(tmp_path):
    text, context = render(tmp_path, fan_hotend_pin="none")
    with pytest.raises(GenerationError, match="cooling"):
        validate_board_electrical_artifact(context, text + "\n[output_pin custom]\npin: PH4\nvalue: 0\n")
    plan = build_managed_config_plan(text.encode(), None, {})
    review = validate_configuration_plan(plan, selected_board=context,
        firmware_reservation_reader=lambda hardware: {"mcu": {"PH4": "reserved transport"}})
    assert any(e.code == "board-cooling" and "reserved transport" in e.message for e in review.errors)


def test_automatic_source_display_still_requires_hardware_evidence(tmp_path):
    _, board, user = inputs()
    assert "display" in board
    user["display_choice"] = None
    user["display_risk_accepted"] = True
    target = tmp_path / "printer.cfg"
    target.write_text("existing config")
    with pytest.raises(GenerationError, match="Unknown display hardware"):
        generate_config(board, user, output_path=str(target), verbose=False)
    assert target.read_text() == "existing config"
    assert not (tmp_path / "printer.cfg.provenance.json").exists()
