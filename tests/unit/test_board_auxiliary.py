"""Unsupported selected-board electrical functions cannot become a deployable CFG."""
import copy
import json

import pytest

from core.board_auxiliary import (SOURCE_ACTIVITY, SOURCE_OPTIONS, unresolved_electrical_dependencies,
                                  selected_static_digital_outputs, validate_static_pin_usage,
                                  selected_motor_power)
from core.exceptions import GenerationError
from core.generator import generate_config
from core.scraper import parse_config
from core.firmware_workflow import persistable_wizard_data
from tests.unit.test_generator import _parsed, _user

SECTIONS = ("dac084s085 currents", "ad5206 currents",
            "mcp4451 currents", "mcp4018 currents")


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("existing", [False, True])
def test_generation_stops_before_artifact_publication(tmp_path, section, existing):
    paths = [tmp_path / n for n in ("printer.cfg", "printer.cfg.provenance.json", "macros.cfg")]
    if existing:
        for path in paths:
            path.write_bytes(b"existing content")
    board = _parsed(**{section: {"pin": "PC13"}})
    before = copy.deepcopy(board)
    with pytest.raises(GenerationError, match="unsupported electrical dependencies") as exc:
        generate_config(board, _user(), output_path=str(paths[0]), include_macros=True, verbose=False)
    assert section in str(exc.value)
    assert board == before
    for path in paths:
        assert path.read_bytes() == b"existing content" if existing else not path.exists()


@pytest.mark.parametrize("section", SECTIONS)
def test_commented_examples_are_not_active_dependencies(tmp_path, section):
    example = parse_config(f"#[{section}]\n#pin: PC13\n", keep_comments=True)
    assert example[SOURCE_ACTIVITY][section] is False
    assert unresolved_electrical_dependencies(example) == []
    result = generate_config({**_parsed(), **example}, _user(), output_path=str(tmp_path / "printer.cfg"), verbose=False)
    assert f"\n[{section}]" not in result["content"]


@pytest.mark.parametrize("comments", [False, True])
def test_active_section_is_not_hidden_by_later_commented_example(comments):
    board = parse_config("[output_pin motor_power]\npin: PC13\nvalue: 1\n"
                         "#[output_pin motor_power]\n#value: 0\n", keep_comments=comments)
    assert board[SOURCE_ACTIVITY]["output_pin motor_power"] is True
    assert unresolved_electrical_dependencies(board) == []
    assert selected_motor_power(board) == {"output_pin motor_power": {"pin": "PC13", "value": "1"}}


@pytest.mark.parametrize("metadata", [None, [], {}, {"output_pin motor_power": "false"}])
def test_absent_or_malformed_activity_fails_closed(metadata):
    board = {"output_pin motor_power": {}, SOURCE_ACTIVITY: metadata}
    with pytest.raises(GenerationError, match="active-source"):
        selected_motor_power(board)


def test_new_section_after_parsing_cannot_hide_behind_other_comment_metadata():
    board = parse_config("#[ad5206 currents]\n#enable_pin: PB1\n", keep_comments=True)
    board["output_pin motor_power"] = {"pin": "PC13", "value": "1"}
    with pytest.raises(GenerationError, match="active-source"):
        selected_motor_power(board)


def test_separate_unselected_profile_does_not_supply_board_electrical_functions(tmp_path):
    profile = {"output_pin motor_power": {"pin": "PC13", "value": "1"}}
    text = generate_config(_parsed(), _user(_profile_parsed=profile), output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]
    assert "[output_pin motor_power]" not in text


def test_checkpoint_retains_selected_board_activity(tmp_path):
    board = {**_parsed(), **parse_config("[output_pin motor_power]\npin: PC13\nvalue: 1\n", keep_comments=True)}
    user = json.loads(json.dumps(persistable_wizard_data(_user(board_parsed=board))))
    assert user["board_parsed"][SOURCE_ACTIVITY]["output_pin motor_power"] is True
    result = generate_config(user["board_parsed"], user, output_path=str(tmp_path / "printer.cfg"), verbose=False)
    assert parse_config(result["content"])["output_pin motor_power"] == {"pin": "PC13", "value": "1"}


def test_names_are_matched_as_section_families_not_substrings():
    board = {"gcode_macro DAC084S085": {}, "output_pin motor_power_led": {}, "static_digital_output_helper example": {}}
    assert unresolved_electrical_dependencies(board) == []


def test_selected_static_outputs_preserve_polarity_multiline_and_source(tmp_path):
    raw = "[static_digital_output controls]\npins: !PG1,\n    PG2\n"
    board = {**_parsed(), **parse_config(raw, keep_comments=True)}
    target = tmp_path / "printer.cfg"
    text = generate_config(board, _user(_profile_parsed={"static_digital_output controls": {"pins": "PG3"}}),
                           output_path=str(target), verbose=False)["content"]
    assert parse_config(text)["static_digital_output controls"] == {"pins": "!PG1, PG2"}
    provenance = json.loads((tmp_path / "printer.cfg.provenance.json").read_text())
    assert provenance["sources"]["static_digital_outputs"]["static_digital_output controls"]["pins"] == "!PG1, PG2"


@pytest.mark.parametrize("fields", [{}, {"pins": ""}, {"pins": "^PG1"}, {"pins": "~PG1"},
    {"pins": "PG1,"}, {"pins": "PG1\n[evil]"}, {"pins": "PG1", "value": "1"}])
def test_invalid_static_outputs_cannot_replace_artifacts(tmp_path, fields):
    target = tmp_path / "printer.cfg"
    target.write_bytes(b"existing")
    board = _parsed(**{"static_digital_output power": fields})
    board[SOURCE_ACTIVITY] = {"static_digital_output power": True}
    board[SOURCE_OPTIONS] = {"static_digital_output power": ["pins"]}
    with pytest.raises(GenerationError, match="static_digital_output"):
        generate_config(board, _user(), output_path=str(target), verbose=False)
    assert target.read_bytes() == b"existing"


def test_commented_pin_in_active_static_section_cannot_be_enabled(tmp_path):
    board = {**_parsed(), **parse_config("[static_digital_output power]\n#pins: PG1\n", keep_comments=True)}
    with pytest.raises(GenerationError, match="no active pins"):
        generate_config(board, _user(), output_path=str(tmp_path / "printer.cfg"), verbose=False)


def test_commented_static_section_is_not_enabled(tmp_path):
    board = {**_parsed(), **parse_config("#[static_digital_output power]\n#pins: PG1\n", keep_comments=True)}
    text = generate_config(board, _user(), output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]
    assert "static_digital_output power" not in parse_config(text)


def test_static_pin_collision_is_not_hidden_by_new_section(tmp_path):
    board = {**_parsed(), **parse_config("[static_digital_output power]\npins: PA1\n")}
    with pytest.raises(GenerationError, match="(?i)(pin|conflict|collision)"):
        generate_config(board, _user(),
                        output_path=str(tmp_path / "printer.cfg"), verbose=False)


@pytest.mark.parametrize("metadata", [{}, {SOURCE_ACTIVITY: None},
    {SOURCE_ACTIVITY: {"static_digital_output power": True}, SOURCE_OPTIONS: {"static_digital_output power": None}}])
def test_old_or_malformed_static_provenance_cannot_enable_outputs(metadata):
    with pytest.raises(GenerationError, match="active"):
        selected_static_digital_outputs({"static_digital_output power": {"pins": "PG1"}, **metadata})


@pytest.mark.parametrize("extra", [
    "[output_pin other]\npin: PG1\n",
    "[static_digital_output other]\npins: !PG1\n",
    "[board_pins]\naliases: LED=PG1\n[fan]\npin: LED\n",
    "[duplicate_pin_override]\npins: PG1\n[fan]\npin: PG1\n",
    "[adc_scaled scaled]\nvref_pin: PG2\nvssa_pin: PG3\n[extruder]\nsensor_pin: scaled:PG1\n",
])
def test_static_output_is_exclusive_across_consumers(extra):
    from core.pin_validator import _read_pin_config
    sections = _read_pin_config("[mcu]\nserial: /tmp/mcu\n[static_digital_output power]\npins: PG1\n" + extra)[0]
    with pytest.raises(GenerationError, match="conflicts"):
        validate_static_pin_usage(sections)


@pytest.mark.parametrize("pins", ["PG1, !PG1", "unknown:PG1", "scaled:PG1"])
def test_duplicate_or_nonphysical_static_pins_are_rejected(pins):
    with pytest.raises(GenerationError):
        validate_static_pin_usage({"mcu": {}, "static_digital_output power": {"pins": pins}})


def test_static_firmware_reservation_and_distinct_mcu_identity():
    sections = {"mcu": {}, "mcu aux": {}, "static_digital_output power": {"pins": "PG1, !aux:PG1"}}
    validate_static_pin_usage(sections)
    with pytest.raises(GenerationError, match="reserved for USB"):
        validate_static_pin_usage(sections, firmware_reservations={"aux": {"PG1": "USB"}})


def test_namespaced_pin_continuation_remains_a_list_not_an_option():
    raw = "[static_digital_output controls]\npins: PG1,\n    aux:PG1\n"
    outputs = selected_static_digital_outputs(parse_config(raw, keep_comments=True))
    assert outputs == {"static_digital_output controls": {"pins": "PG1, aux:PG1"}}


@pytest.mark.parametrize("noop", [False, True])
@pytest.mark.parametrize("pin", ["^PG1", "PA1"])
def test_invalid_static_output_in_user_include_blocks_before_confirmation(tmp_path, noop, pin):
    from unittest.mock import Mock
    from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
    from core.managed_config import build_managed_config_plan
    from tests.unit.test_config_transaction import FakeTransport
    hardware = generate_config(_parsed(), _user(), output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"].encode()
    remote = {"printer.cfg": hardware+b"\n[include extra.cfg]\n", "extra.cfg": f"[static_digital_output user]\npins: {pin}\n".encode()}
    if noop:
        plan = build_managed_config_plan(hardware, None, remote)
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        assert not build_managed_config_plan(hardware, None, remote).changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    before = dict(transport.files)
    result = ConfigDeploymentTransaction(transport, hardware, None, activation="none", confirm=confirm,
        output=lambda _: None, snapshot_root=str(tmp_path / "snapshots"), poll_interval=0).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    confirm.assert_not_called()
    assert transport.files == before


def test_generation_checks_firmware_evidence_for_static_outputs(tmp_path):
    from unittest.mock import patch
    board = {**_parsed(), **parse_config("[static_digital_output power]\npins: PG1\n")}
    with patch("core.firmware_workflow.generation_pin_reservations", return_value={"mcu": {"PG1": "USB"}}) as reader:
        with pytest.raises(GenerationError, match="reserved for USB"):
            generate_config(board, _user(), output_path=str(tmp_path / "printer.cfg"), verbose=False)
    reader.assert_called_once()
    assert not (tmp_path / "printer.cfg").exists()


def test_effective_review_checks_firmware_evidence_for_static_user_include(tmp_path):
    from unittest.mock import Mock
    from core.configuration_review import validate_configuration_plan
    from core.managed_config import build_managed_config_plan
    hardware = generate_config(_parsed(), _user(), output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"].encode()
    remote = {"printer.cfg": hardware+b"\n[include extra.cfg]\n",
              "extra.cfg": b"[static_digital_output user]\npins: PG1\n"}
    plan = build_managed_config_plan(hardware, None, remote)
    reader = Mock(return_value={"mcu": {"PG1": "USB"}})
    result = validate_configuration_plan(plan, firmware_reservation_reader=reader)
    reader.assert_called_once()
    assert any(e.code == "static-digital-output" and "reserved for USB" in e.message for e in result.errors)
