"""SKR Pro mandatory hotend cooling without enabling commented examples."""
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
from core.managed_config import build_managed_config_plan, _section_options
from core.profile_values import extract_profile_values, mark_profile_values
from core.scraper import parse_config
from core.wizard.steps.hardware import _step_fan_assignment
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_generator import _user
from tests.unit.test_required_board_cooling import FIXTURES

PROFILE = "generic-bigtreetech-skr-pro.cfg"
FAN = "heater_fan fan1"


def inputs(tmp_path):
    raw = (FIXTURES / PROFILE).read_text(encoding="utf-8")
    board = parse_config(raw, PROFILE, keep_comments=True)
    user = _user(board=PROFILE, board_raw_config=raw, board_parsed=board, printer_profile=PROFILE,
        _profile_parsed=board, raw_config=raw, profile_loaded=True, driver_type="None (Standard)", driver_mode="Standalone",
        fan_part_cooling_pin="default", fan_hotend_pin="none", mcu_type="stm32f407",
        mcu_path="/dev/serial/by-id/test")
    user.update(extract_profile_values(board))
    mark_profile_values(user, board)
    return raw, board, user


def render(tmp_path, **changes):
    _, board, user = inputs(tmp_path)
    user.update(changes)
    text = generate_config(board, user, output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]
    saved = json.loads(json.dumps(persistable_wizard_data(user)))
    context = selected_board_electrical_source({"workflow_checkpoint": {"wizard_data": saved}})
    return text, context


@pytest.mark.parametrize("choice", [None, "none", "PE5"])
def test_cooling_and_active_circuit_survive_every_choice(tmp_path, choice):
    text, context = render(tmp_path, fan_hotend_pin=choice)
    sections = _section_options(text)
    assert text.count(f"[{FAN}]") == 1 and sections[FAN] == {"pin": "PE5"}
    assert sections["heater_bed"]["control"] == "watermark"
    assert sections["fan"] == {"pin": "PC8"}
    assert "heater_fan fan2" not in sections
    assert not any(name.startswith("tmc") or name in ("extruder1", "extruder2") for name in sections)
    validate_board_electrical_artifact(context, text)
    transport = FakeTransport()
    for _ in range(2):
        result = ConfigDeploymentTransaction(transport, text.encode(), None, selected_board=context,
            activation="none", snapshot_root=str(tmp_path / "snapshots")).run()
        assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION


def test_saved_configuration_without_required_resource_rejects(tmp_path):
    section = FAN
    text, context = render(tmp_path)
    changed = re.sub(r"(?ms)^\[" + re.escape(section) + r"\]\n.*?(?=^\[|\Z)", "", text)
    assert section not in _section_options(changed)
    with pytest.raises(GenerationError):
        validate_board_electrical_artifact(context, changed)


@pytest.mark.parametrize("override", ["pin: !PE5", "heater: heater_bed", "fan_speed: 0",
                                      "heater_temp: 200", "shutdown_speed: 0"])
@pytest.mark.parametrize("noop", [False, True])
def test_effective_includes_reject_changes_before_any_write(tmp_path, override, noop):
    text, context = render(tmp_path)
    data = text.encode()
    remote = {"printer.cfg": data + b"\n[include user.cfg]\n", "user.cfg": f"[{FAN}]\n{override}\n".encode()}
    if noop:
        remote.update({a.remote_name: a.content for a in build_managed_config_plan(data, None, remote).artifacts})
        assert not build_managed_config_plan(data, None, remote).changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, data, None, selected_board=context, activation="none",
        confirm=confirm, snapshot_root=str(tmp_path / "snapshots"), verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED and "cooling" in result.detail
    confirm.assert_not_called()
    assert transport.files == remote and all(c[0] == "read" for c in transport.calls)


@pytest.mark.parametrize("change", ["source", "missing_evidence", "active_pin", "heater"])
def test_changed_source_and_old_parsed_checkpoints_reject(tmp_path, change):
    raw, board, user = inputs(tmp_path)
    if change == "source":
        board = parse_config(raw + "\n# changed source\n", PROFILE)
    elif change == "active_pin":
        board[FAN]["pin"] = "PE7"
    elif change == "heater":
        board["extruder"]["heater_pin"] = "PB0"
    else:
        board.pop(SOURCE)
        with pytest.raises(GenerationError, match="cooling"):
            selected_board_electrical_source({"board": PROFILE, "board_parsed": board})
    with pytest.raises(GenerationError, match="cooling"):
        generate_config(board, user, output_path=str(tmp_path / "printer.cfg"), verbose=False)
    assert not (tmp_path / "printer.cfg").exists()


def test_pe5_cannot_be_manual_part_fan_or_reserved_output(tmp_path):
    _, board, user = inputs(tmp_path)
    user["fan_part_cooling_pin"] = "PE5"
    with pytest.raises(GenerationError, match="fan|cooling"):
        generate_config(board, user, output_path=str(tmp_path / "printer.cfg"), verbose=False)
    assert not (tmp_path / "printer.cfg").exists()
    text, context = render(tmp_path)
    with pytest.raises(GenerationError, match="cooling"):
        validate_board_electrical_artifact(context, text + "\n[output_pin custom]\npin: PE5\nvalue: 0\n")
    review = validate_configuration_plan(build_managed_config_plan(text.encode(), None, {}), selected_board=context,
        firmware_reservation_reader=lambda hardware: {"mcu": {"PE5": "reserved transport"}})
    assert any(e.code == "board-cooling" and "reserved transport" in e.message for e in review.errors)


def test_wizard_keeps_required_cooling_out_of_manual_part_choices(tmp_path, capsys):
    _, _, user = inputs(tmp_path)
    with patch("core.wizard.steps.hardware.numbered_select", side_effect=["default", "none"]) as select:
        assert _step_fan_assignment(user) == "success"
    offered = [c.get("value") for c in select.call_args_list[0].kwargs["choices"] if isinstance(c, dict)]
    assert "PE5" not in offered and FAN in capsys.readouterr().out


def test_separate_mechanical_profile_cannot_import_board_fan(tmp_path):
    from tests.unit.test_generator import _parsed
    _, profile, _ = inputs(tmp_path)
    text = generate_config(_parsed(), _user(_profile_parsed=profile, fan_hotend_pin="none",
        x_size="200", y_size="200", z_size="200"),
        output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]
    assert FAN not in _section_options(text)
