"""Board power survives generation, saved artifacts and effective includes."""
import json
from unittest.mock import Mock, patch

import pytest

from core.board_auxiliary import (MOTOR_POWER, SOURCE_ACTIVITY, SOURCE_OPTIONS,
    selected_motor_power, validate_motor_power, validate_board_electrical_artifact)
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.exceptions import GenerationError
from core.generator import generate_config
from core.managed_config import build_managed_config_plan
from core.pin_validator import _read_pin_config
from core.scraper import parse_config
from tests.unit.test_generator import _parsed, _user
from tests.unit.test_config_transaction import FakeTransport, GENERATED

POWER = "[output_pin motor_power]\npin: PG1\nvalue: 1\n"


@pytest.mark.parametrize("pin", ["PC13", "PI11", "!PG1"])
@pytest.mark.parametrize("extra", ["", "shutdown_value: 1\npwm: false\n"])
def test_generation_preserves_selected_power_not_foreign_profile(tmp_path, pin, extra):
    raw = POWER.replace("PG1", pin) + extra
    board = {**_parsed(), **parse_config(raw)}
    result = generate_config(board, _user(_profile_parsed={MOTOR_POWER: {"pin": "PG2", "value": "0"}}),
        output_path=str(tmp_path / "printer.cfg"), verbose=False)
    expected = parse_config(raw)[MOTOR_POWER]
    assert parse_config(result["content"])[MOTOR_POWER] == expected
    provenance = json.loads((tmp_path / "printer.cfg.provenance.json").read_text())
    assert provenance["sources"]["motor_power"] == {MOTOR_POWER: expected}
    validate_board_electrical_artifact(board, result["content"])


@pytest.mark.parametrize("raw", ["#[output_pin motor_power]\n#pin: PG1\n#value: 1\n",
    POWER + "#shutdown_value: 1\n#pwm: true\n#scale: 255\n"])
def test_commented_outputs_or_options_do_not_become_active(tmp_path, raw):
    board = {**_parsed(), **parse_config(raw, keep_comments=True)}
    result = generate_config(board, _user(), output_path=str(tmp_path / "printer.cfg"), verbose=False)
    actual = parse_config(result["content"]).get(MOTOR_POWER)
    assert actual == (None if raw.startswith("#") else {"pin": "PG1", "value": "1"})


@pytest.mark.parametrize("fields", [{"pin": "PG1"}, {"value": "1"},
    {"pin": "PG1", "value": "nan"}, {"pin": "PG1", "value": "inf"},
    {"pin": "PG1", "value": ".5"}, {"pin": "PG1", "value": "1", "shutdown_value": "2"},
    {"pin": "PG1", "value": "1", "pwm": "true"},
    {"pin": "PG1", "value": "1", "scale": "1"},
    {"pin": "^PG1", "value": "1"}, {"pin": "~PG1", "value": "1"},
    {"pin": "PG1,PG2", "value": "1"}, {"pin": "PG1\n[evil]", "value": "1"},
    {"pin": None, "value": "1"}])
def test_invalid_power_never_replaces_config_provenance_or_macros(tmp_path, fields):
    board = _parsed(**{MOTOR_POWER: fields, SOURCE_ACTIVITY: {MOTOR_POWER: True},
        SOURCE_OPTIONS: {MOTOR_POWER: list(fields)}})
    paths = [tmp_path / n for n in ("printer.cfg", "printer.cfg.provenance.json", "macros.cfg")]
    for p in paths:
        p.write_bytes(b"existing")
    with pytest.raises(GenerationError, match="motor_power"):
        generate_config(board, _user(), output_path=str(paths[0]), include_macros=True, verbose=False)
    assert all(p.read_bytes() == b"existing" for p in paths)


@pytest.mark.parametrize("options", [None, {}, ["pin"], ["pin", "value", "missing"], [[]]])
def test_incomplete_active_option_evidence_rejects(options):
    source = parse_config(POWER)
    source[SOURCE_OPTIONS][MOTOR_POWER] = options
    with pytest.raises(GenerationError, match="active pin/value"):
        selected_motor_power(source)


@pytest.mark.parametrize("extra", ["[fan]\npin: PG1\n",
    "[static_digital_output power]\npins: !PG1\n",
    "[board_pins]\naliases: LED=PG1\n[fan]\npin: LED\n",
    "[duplicate_pin_override]\npins: PG1\n[fan]\npin: PG1\n"])
def test_exclusive_pin_cannot_be_shared_or_bypassed(extra):
    with pytest.raises(GenerationError, match="conflicts"):
        validate_motor_power(_read_pin_config("[mcu]\nserial: /tmp/mcu\n"+POWER+extra)[0])


@pytest.mark.parametrize("pin", ["unknown:PG1", "multi_pin:power", "PA1"])
def test_generation_rejects_undeclared_nonphysical_or_occupied_pin(tmp_path, pin):
    board = {**_parsed(), **parse_config(POWER.replace("PG1", pin))}
    with pytest.raises(GenerationError):
        generate_config(board, _user(), output_path=str(tmp_path / "printer.cfg"), verbose=False)
    assert not (tmp_path / "printer.cfg").exists()


def test_generation_checks_firmware_pin_reservations_before_writing(tmp_path):
    board = {**_parsed(), **parse_config(POWER)}
    with patch("core.firmware_workflow.generation_pin_reservations", return_value={"mcu": {"PG1": "USB"}}) as reader:
        with pytest.raises(GenerationError, match="reserved for USB"):
            generate_config(board, _user(), output_path=str(tmp_path / "printer.cfg"), verbose=False)
    reader.assert_called_once()
    assert not (tmp_path / "printer.cfg").exists()


def test_distinct_physical_mcus_can_reuse_gpio_name():
    sections = _read_pin_config("[mcu]\nserial: /tmp/mcu\n[mcu aux]\nserial: /tmp/aux\n"+POWER+
        "[fan]\npin: aux:PG1\n")[0]
    validate_motor_power(sections)


def test_board_virtual_z_with_no_selected_probe_cannot_replace_artifact(tmp_path):
    board = {**_parsed(), **parse_config(POWER)}
    board["stepper_z"]["endstop_pin"] = "probe:z_virtual_endstop"
    path = tmp_path / "printer.cfg"
    path.write_bytes(b"existing")
    with pytest.raises(GenerationError, match="requires a generated probe"):
        generate_config(board, _user(probe="None"), output_path=str(path), verbose=False)
    assert path.read_bytes() == b"existing"


@pytest.mark.parametrize("changed", ["", POWER.replace("PG1", "!PG1"), POWER.replace("PG1", "PG2"),
    POWER.replace("PG1", "aux:PG1"), POWER.replace("value: 1", "value: 0"), POWER+"shutdown_value: 1\n"])
def test_saved_artifact_cannot_omit_or_change_signal(changed):
    content = GENERATED+b"[mcu aux]\nserial: /tmp/aux\n"+changed.encode()
    with pytest.raises(GenerationError, match="missing or changed"):
        validate_board_electrical_artifact(parse_config(POWER), content)


def test_alias_equivalence_and_explicit_defaults_are_semantically_preserved():
    source = parse_config("[board_pins]\naliases: POWER=PG1\n"+POWER.replace("PG1", "POWER"))
    validate_board_electrical_artifact(source, GENERATED+(POWER+"shutdown_value: 0\npwm: off\n").encode())
    with pytest.raises(GenerationError, match="missing or changed"):
        validate_board_electrical_artifact(source, GENERATED+
            ("[board_pins]\naliases: POWER=PG2\n"+POWER.replace("PG1", "POWER")).encode())


@pytest.mark.parametrize("noop", [False, True])
@pytest.mark.parametrize("override", ["pin: PG2", "pin: !PG1", "value: 0", "shutdown_value: 1", "pwm: true"])
def test_effective_include_change_rejects_before_confirmation_or_writes(tmp_path, noop, override):
    good = GENERATED+POWER.encode()
    remote = {"printer.cfg": good+b"[include user.cfg]\n",
        "user.cfg": ("[output_pin motor_power]\n"+override+"\n").encode()}
    if noop:
        remote.update({a.remote_name: a.content for a in build_managed_config_plan(good, None, remote).artifacts})
        assert not build_managed_config_plan(good, None, remote).changed_artifacts
    dest, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(dest, good, None, selected_board=parse_config(POWER),
        activation="firmware", confirm=confirm, snapshot_root=str(tmp_path / "snapshots"), poll_interval=0).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "motor_power" in result.detail
    confirm.assert_not_called()
    assert dest.files == remote and all(c[0] == "read" for c in dest.calls)
    assert not (tmp_path / "snapshots").exists()


def test_effective_review_checks_motor_firmware_reservation(tmp_path):
    from core.configuration_review import validate_configuration_plan
    good = GENERATED+POWER.encode()
    plan = build_managed_config_plan(good, None, {})
    reader = Mock(return_value={"mcu": {"PG1": "USB"}})
    result = validate_configuration_plan(plan, firmware_reservation_reader=reader)
    reader.assert_called_once()
    assert any(e.code == "board-digital-output" and "reserved for USB" in e.message for e in result.errors)


def test_valid_power_publishes_and_repeats_without_rewrite(tmp_path):
    dest = FakeTransport()
    for _ in range(2):
        result = ConfigDeploymentTransaction(dest, GENERATED+POWER.encode(), None, selected_board=parse_config(POWER),
            activation="none", snapshot_root=str(tmp_path), poll_interval=0).run()
        assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    assert POWER.encode() in dest.files["printer.cfg"]
