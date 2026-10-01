"""Selected BX panel survives generation and every effective publication review."""
import json
from unittest.mock import Mock, patch

import pytest

from core.board_bx_panel import (SOURCE_PANEL, PROFILE, reviewed_panel, selected_bx_panel,
    render_bx_panel, validate_bx_panel)
from core.board_auxiliary import validate_board_electrical_artifact, selected_board_electrical_source
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.exceptions import GenerationError
from core.generator import generate_config
from core.managed_config import build_managed_config_plan
from core.pin_validator import _read_pin_config
from core.scraper import parse_config
from tests.unit.test_fixed_pwm_beepers import board_case
from tests.unit.test_config_transaction import FakeTransport


@pytest.mark.parametrize("display", [None, "none"])
@pytest.mark.parametrize("macros", [False, True])
def test_board_panel_is_preserved_independently_of_optional_display_and_starter_macros(tmp_path, display, macros):
    raw, board, choices = board_case(PROFILE)
    choices["display_choice"] = display
    text = generate_config(board, choices, output_path=str(tmp_path / "printer.cfg"),
                           include_macros=macros, verbose=False)["content"]
    actual, expected = _read_pin_config(text)[0], _read_pin_config(raw)[0]
    for name in reviewed_panel()["sections"]:
        assert actual[name] == expected[name]
        assert sum(line.strip() == "["+name+"]" for line in text.splitlines()) == 1
    proof = json.loads((tmp_path / "printer.cfg.provenance.json").read_text())
    assert proof["sources"]["bx_panel"] == board[SOURCE_PANEL]
    assert render_bx_panel(board, text) == text
    recovered = selected_board_electrical_source({"board": PROFILE, "board_raw_config": raw})
    validate_board_electrical_artifact(recovered, text)
    dest = FakeTransport()
    for _ in range(2):
        result = ConfigDeploymentTransaction(dest, text.encode(), None, selected_board=recovered,
            activation="none", snapshot_root=str(tmp_path / "snapshots"), poll_interval=0).run()
        assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION, result.detail


@pytest.mark.parametrize("change", ["missing", "hash", "command", "led", "button", "screen", "invalid_button"])
def test_changed_or_old_source_never_overwrites_existing_artifacts(tmp_path, change):
    _, board, choices = board_case(PROFILE)
    if change == "missing": board.pop(SOURCE_PANEL)
    elif change == "hash": board[SOURCE_PANEL]["source_sha256"] = "0"*64
    elif change == "command": board[SOURCE_PANEL]["sections"]["idle_timeout"]["gcode"] += "\nM112"
    elif change == "led": board["neopixel led"]["pin"] = "PH7"
    elif change == "screen": board["output_pin screen"]["pin"] = "PH7"
    elif change == "invalid_button": board["gcode_button lcd_button"] = None
    else: board["gcode_button lcd_button"]["pin"] = "PH7"
    paths = [tmp_path / n for n in ("printer.cfg", "macros.cfg", "printer.cfg.provenance.json")]
    for p in paths: p.write_bytes(b"original")
    with pytest.raises(GenerationError, match="BX panel"):
        generate_config(board, choices, output_path=str(paths[0]), include_macros=True, verbose=False)
    assert all(p.read_bytes() == b"original" for p in paths)


@pytest.mark.parametrize("section", list(reviewed_panel()["sections"]))
def test_saved_artifact_cannot_omit_any_panel_dependency(tmp_path, section):
    _, board, choices = board_case(PROFILE)
    text = generate_config(board, choices, output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]
    start = text.index("\n["+section+"]")+1
    end = text.find("\n[", start+1)
    text = text[:start]+(text[end:] if end >= 0 else "")
    dest = FakeTransport()
    result = ConfigDeploymentTransaction(dest, text.encode(), None, selected_board=board,
        activation="firmware", snapshot_root=str(tmp_path / "snapshots")).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED and not dest.calls


@pytest.mark.parametrize("override", [
    "[neopixel led]\npin: PH7\n", "[neopixel led]\nchain_count: 1\n",
    "[neopixel led]\ncolor_order: RGB\n", "[neopixel knob]\ninitial_BLUE: 1\n",
    "[gcode_button lcd_button]\npin: ^PH8\n",
    "[gcode_button lcd_button]\npress_gcode:\n  SET_PIN PIN=screen VALUE=0\n",
    "[gcode_button lcd_button]\nrelease_gcode: M112\n",
    "[idle_timeout]\ngcode:\n  M84\n", "[idle_timeout]\ntimeout: 0\n",
    "[delayed_gcode welcome]\ninitial_duration: 0\n",
    "[delayed_gcode welcome]\ngcode:\n  G4 P100\n",
    "[output_pin other]\npin: PH3\n", "[output_pin other]\npin: PH8\n"])
@pytest.mark.parametrize("noop", [False, True])
def test_effective_override_or_collision_rejected_without_writes(tmp_path, override, noop):
    _, board, choices = board_case(PROFILE)
    text = generate_config(board, choices, output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"].encode()
    remote = {"printer.cfg": text+b"\n[include user.cfg]\n", "user.cfg": override.encode()}
    if noop:
        remote.update({a.remote_name: a.content for a in build_managed_config_plan(text, None, remote).artifacts})
        assert not build_managed_config_plan(text, None, remote).changed_artifacts
    dest, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(dest, text, None, selected_board=board, confirm=confirm,
        activation="firmware", snapshot_root=str(tmp_path / "snapshots")).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert all(c[0] == "read" for c in dest.calls) and dest.files == remote
    confirm.assert_not_called()


@pytest.mark.parametrize("pin", ["PH3", "PB1", "PH8"])
def test_known_firmware_reservations_block_generation_and_review(tmp_path, pin):
    from core.configuration_review import validate_configuration_plan
    _, board, choices = board_case(PROFILE)
    text = generate_config(board, choices, output_path=str(tmp_path / "good.cfg"), verbose=False)["content"]
    reserved = {"mcu": {pin: "reserved bus"}}
    with patch("core.firmware_workflow.generation_pin_reservations", return_value=reserved):
        with pytest.raises(GenerationError, match="reserved bus"):
            generate_config(board, choices, output_path=str(tmp_path / "bad.cfg"), verbose=False)
    review = validate_configuration_plan(build_managed_config_plan(text.encode(), None, {}),
        selected_board=board, firmware_reservation_reader=lambda _: reserved)
    assert not review.valid and any("reserved bus" in m.message for m in review.errors)
    assert not (tmp_path / "bad.cfg").exists()


def test_conflicting_supplied_idle_macro_is_not_silently_replaced():
    _, board, _ = board_case(PROFILE)
    with pytest.raises(GenerationError, match="conflicts"):
        render_bx_panel(board, "[idle_timeout]\ngcode: M84\n")


def test_generic_user_panel_and_commented_source_do_not_activate_bx_contract():
    sections = _read_pin_config("[neopixel led]\npin: PA0\nchain_count: 3\n")[0]
    validate_bx_panel(None, sections)
    source = parse_config("#[output_pin screen]\n#pin: PB5\n#value: 1\n#[gcode_button lcd_button]\n#pin: PH8\n", keep_comments=True)
    assert selected_bx_panel(source) == {}


def test_missing_panel_blocks_live_export_and_integrated_firmware_adapters(tmp_path):
    from core.deployer import _run_config_transaction, _copy_artifacts, deploy_firmware_installation
    from core.workflow_outcome import WorkflowOutcome
    from core.moonraker_deployer import DeployState
    from tests.unit.test_deployer import FirmwareInstallationPreconditionTests
    raw, board, choices = board_case(PROFILE)
    text = generate_config(board, choices, output_path=str(tmp_path / "good.cfg"), verbose=False)["content"]
    # Keep every output and only remove the panel block appended after them.
    missing = text[:text.index("\n[neopixel led]")].encode()
    user = FirmwareInstallationPreconditionTests()._user()
    user.update(board=PROFILE, board_raw_config=raw)
    dest = FakeTransport()
    with patch("core.deployer._generated_config_bytes", return_value=("unused", missing, None)), \
         patch("core.config_transaction.configuration_transport", return_value=dest), \
         patch("core.deployer.shutil.copy2") as copy:
        result = _run_config_transaction(dest, user, "none", generated=("unused", missing, None))
        assert result.outcome == WorkflowOutcome.PRECONDITION_FAILED and "BX panel" in result.detail
        assert not _copy_artifacts(user, str(tmp_path), "all")
        assert deploy_firmware_installation(user).state == DeployState.FAILED_PRECONDITION
    assert not dest.calls
    copy.assert_not_called()
    user["firmware_deployment_service"].execute.assert_not_called()


def test_mechanical_profile_cannot_introduce_bx_panel(tmp_path):
    from tests.unit.test_generator import _parsed, _user
    _, foreign, _ = board_case(PROFILE)
    text = generate_config(_parsed(), _user(_profile_parsed=foreign),
        output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]
    actual = _read_pin_config(text)[0]
    assert not set(reviewed_panel()["sections"]) & set(actual)
