"""BLTouch electrical mode/timing are hardware settings, not print strategy."""
from unittest.mock import Mock
import pytest
from core.exceptions import GenerationError
from core.generator import generate_config
from core.pin_validator import _read_pin_config
from core.scraper import parse_config
from core.board_auxiliary import validate_board_electrical_artifact
from core.managed_config import build_managed_config_plan
from tests.unit.test_bltouch_flags import board
from tests.unit.test_generator import _user


def generate(tmp_path, options, **overrides):
    return generate_config(board(**options), _user(probe="BLTouch", **overrides),
                           output_path=str(tmp_path / "printer.cfg"), verbose=False)


@pytest.mark.parametrize("kind", ["BLTouch", "CR-Touch"])
@pytest.mark.parametrize("mode", ["5V", "OD"])
def test_source_hardware_options_survive_generation(tmp_path, kind, mode):
    result = generate_config(board(set_output_mode=mode, pin_move_time="0.4"), _user(probe=kind),
                             output_path=str(tmp_path / "printer.cfg"), verbose=False)
    section = _read_pin_config(result["content"])[0]["bltouch"]
    assert section["set_output_mode"] == mode
    assert float(section["pin_move_time"]) == 0.4


@pytest.mark.parametrize("option,value", [("set_output_mode", "5v"), ("set_output_mode", "auto"),
    ("set_output_mode", ""), ("pin_move_time", "0"), ("pin_move_time", "-1"),
    ("pin_move_time", "nan"), ("pin_move_time", "inf"), ("pin_move_time", "bad")])
def test_invalid_option_cannot_replace_existing_artifact(tmp_path, option, value):
    target = tmp_path / "printer.cfg"
    target.write_bytes(b"prior artifact")
    with pytest.raises(GenerationError, match=option):
        generate(tmp_path, {option: value})
    assert target.read_bytes() == b"prior artifact"
    assert not (tmp_path / "printer.cfg.provenance.json").exists()


@pytest.mark.parametrize("option,value", [("set_output_mode", "5V"), ("pin_move_time", "0.4")])
def test_profile_cannot_transfer_hardware_setting_without_board_agreement(tmp_path, option, value):
    with pytest.raises(GenerationError, match="board|source"):
        generate(tmp_path, {}, _profile_parsed={"bltouch": {option: value}})
    assert not (tmp_path / "printer.cfg").exists()


def test_matching_profile_and_board_are_allowed(tmp_path):
    generate(tmp_path, {"set_output_mode": "OD", "pin_move_time": "0.4"},
             _profile_parsed={"bltouch": {"set_output_mode": "OD", "pin_move_time": "0.400"}})


@pytest.mark.parametrize("field,value", [("bltouch_sensor_pin", "^PF1"), ("bltouch_control_pin", "PF2")])
def test_output_mode_cannot_move_to_another_connection(tmp_path, field, value):
    with pytest.raises(GenerationError, match="wiring|pin|connection"):
        generate(tmp_path, {"set_output_mode": "5V"}, **{field: value})
    assert not (tmp_path / "printer.cfg").exists()


@pytest.mark.parametrize("mode", ["5V", "OD"])
def test_saved_source_artifact_cannot_drop_or_change_options(tmp_path, mode):
    source = board(set_output_mode=mode, pin_move_time="0.4")
    text = generate(tmp_path, {})["content"]
    with pytest.raises(GenerationError, match="set_output_mode|pin_move_time"):
        validate_board_electrical_artifact(source, text)


@pytest.mark.parametrize("option,value", [("set_output_mode", "invalid"), ("pin_move_time", "0")])
@pytest.mark.parametrize("noop", [False, True])
def test_invalid_preserved_include_blocks_before_writes(tmp_path, option, value, noop):
    from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
    from tests.unit.test_config_transaction import FakeTransport
    generated = generate(tmp_path, {})["content"].encode()
    remote = {"printer.cfg": generated + b"\n[include user.cfg]\n", "user.cfg": b"[include nested.cfg]\n",
              "nested.cfg": f"[bltouch]\n{option}: {value}\n".encode()}
    if noop:
        remote.update({a.remote_name: a.content for a in build_managed_config_plan(generated, None, remote).artifacts})
        assert not build_managed_config_plan(generated, None, remote).changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, generated, None, activation="none", confirm=confirm,
        output=lambda _: None, snapshot_root=str(tmp_path / "snapshots"), poll_interval=0).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert option in result.detail
    confirm.assert_not_called()
    assert not any(c[0] in ("upload", "delete", "restart", "restart_moonraker") for c in transport.calls)


def test_commented_mode_is_not_promoted_to_active_voltage(tmp_path):
    source = board()
    source.update(parse_config("[bltouch]\nsensor_pin: ^PB8\ncontrol_pin: PB9\n# set_output_mode: 5V\n# pin_move_time: 0.4\n", keep_comments=True))
    result = generate_config(source, _user(probe="BLTouch"), output_path=str(tmp_path / "printer.cfg"), verbose=False)
    section = _read_pin_config(result["content"])[0]["bltouch"]
    assert "set_output_mode" not in section and "pin_move_time" not in section


def test_omission_does_not_invent_an_electrical_mode_or_timing(tmp_path):
    section = _read_pin_config(generate(tmp_path, {})["content"])[0]["bltouch"]
    assert "set_output_mode" not in section and "pin_move_time" not in section


@pytest.mark.parametrize("option,value", [("set_output_mode", "OD"), ("pin_move_time", "0.7")])
def test_profile_disagreement_is_not_silently_chosen(tmp_path, option, value):
    with pytest.raises(GenerationError, match=option):
        generate(tmp_path, {"set_output_mode": "5V", "pin_move_time": "0.4"},
                 _profile_parsed={"bltouch": {option: value}})


def test_active_options_and_checkpoint_roundtrip_keep_authority(tmp_path):
    import json
    from core.firmware_workflow import persistable_wizard_data
    source = board()
    source.update(parse_config("[bltouch]\nsensor_pin: ^PB8\ncontrol_pin: PB9\nset_output_mode: OD\npin_move_time: 0.7\n", keep_comments=True))
    user = json.loads(json.dumps(persistable_wizard_data(_user(probe="CR-Touch"))))
    source = json.loads(json.dumps(source))
    result = generate_config(source, user, output_path=str(tmp_path / "printer.cfg"), verbose=False)
    validate_board_electrical_artifact(source, result["content"])
    proof = json.loads((tmp_path / "printer.cfg.provenance.json").read_text(encoding="utf-8"))
    assert proof["sources"]["bltouch_hardware"]["set_output_mode"] == {"value": "OD", "sources": ["board"]}


@pytest.mark.parametrize("kind", ["None", "Inductive"])
def test_unselected_bltouch_does_not_transfer_electrical_mode(tmp_path, kind):
    result = generate_config(board(set_output_mode="invalid"), _user(probe=kind),
                             output_path=str(tmp_path / "printer.cfg"), verbose=False)
    assert "set_output_mode" not in result["content"]


@pytest.mark.parametrize("replacement", ["", "pin_move_time: 0.7"])
def test_missing_or_changed_rendered_setting_is_rejected(tmp_path, replacement):
    from unittest.mock import patch
    from jinja2 import Template
    render = Template.render
    def alter(template, *args, **kwargs):
        return render(template, *args, **kwargs).replace("pin_move_time: 0.4", replacement)
    with patch.object(Template, "render", alter), pytest.raises(GenerationError, match="pin_move_time"):
        generate(tmp_path, {"pin_move_time": "0.4"})
    assert not (tmp_path / "printer.cfg").exists()


@pytest.mark.parametrize("option,value", [("set_output_mode", "OD"), ("pin_move_time", "0.7")])
@pytest.mark.parametrize("noop", [False, True])
def test_valid_but_changed_include_cannot_override_selected_hardware(tmp_path, option, value, noop):
    from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
    from tests.unit.test_config_transaction import FakeTransport
    source = board(set_output_mode="5V", pin_move_time="0.4")
    generated = generate(tmp_path, {"set_output_mode": "5V", "pin_move_time": "0.4"})["content"].encode()
    remote = {"printer.cfg": generated + b"\n[include user.cfg]\n", "user.cfg": b"[include nested.cfg]\n",
              "nested.cfg": f"[bltouch]\n{option}: {value}\n".encode()}
    if noop:
        remote.update({a.remote_name: a.content for a in build_managed_config_plan(generated, None, remote).artifacts})
        assert not build_managed_config_plan(generated, None, remote).changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, generated, None, selected_board=source,
        activation="none", confirm=confirm, output=lambda _: None,
        snapshot_root=str(tmp_path / "snapshots"), poll_interval=0).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert option in result.detail
    confirm.assert_not_called()
    assert not any(c[0] in ("upload", "delete", "restart", "restart_moonraker") for c in transport.calls)
