"""Selected probe/screen outputs share the proven digital power contract."""
import json
from unittest.mock import Mock, patch

import pytest

from core.board_auxiliary import (SOURCE_ACTIVITY, SOURCE_OPTIONS, selected_board_digital_outputs,
    selected_board_electrical_source, validate_board_electrical_artifact, validate_board_digital_outputs)
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.exceptions import GenerationError
from core.generator import generate_config
from core.managed_config import build_managed_config_plan
from core.pin_validator import _read_pin_config
from core.scraper import parse_config
from tests.unit.test_generator import _parsed, _user
from tests.unit.test_config_transaction import FakeTransport, GENERATED


@pytest.fixture(params=["output_pin probe_enable", "output_pin screen"])
def section(request):
    return request.param


def output(section, pin="PG1", value="1", extra=""):
    return f"[{section}]\npin: {pin}\nvalue: {value}\n{extra}"


def test_generation_provenance_and_checkpoint_ignore_foreign_profile(tmp_path, section):
    raw = output(section, "!PG1", extra="shutdown_value: 1\npwm: false\n")
    board = {**_parsed(), **parse_config(raw, keep_comments=True)}
    result = generate_config(board, _user(_profile_parsed={section: {"pin": "PG2", "value": "0"}}),
        output_path=str(tmp_path / "printer.cfg"), verbose=False)
    expected = parse_config(raw)[section]
    assert parse_config(result["content"])[section] == expected
    provenance = json.loads((tmp_path / "printer.cfg.provenance.json").read_text())
    assert provenance["sources"]["auxiliary_digital_outputs"] == {section: expected}
    source = selected_board_electrical_source({"workflow_checkpoint": {"wizard_data": {
        "board": "test.cfg", "board_raw_config": raw, "board_parsed": {section: expected}}}})
    validate_board_electrical_artifact(source, result["content"])


def test_active_values_win_and_commented_options_are_not_enabled(tmp_path, section):
    raw = output(section)+"#shutdown_value: 1\n#pwm: true\n#scale: 255\n"+f"#[{section}]\n#value: 0\n"
    board = {**_parsed(), **parse_config(raw, keep_comments=True)}
    generated = generate_config(board, _user(), output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]
    assert parse_config(generated)[section] == {"pin": "PG1", "value": "1"}
    commented = "\n".join("#"+line for line in output(section).splitlines())
    assert selected_board_digital_outputs(parse_config(commented, keep_comments=True)) == {}


@pytest.mark.parametrize("fields", [{"pin": "PG1"}, {"pin": "PG1", "value": ".5"},
    {"pin": "PG1", "value": "1", "pwm": "true"},
    {"pin": "PG1", "value": "1", "shutdown_value": "nan"},
    {"pin": "PG1", "value": "1", "static_value": "1"}, {"pin": "^PG1", "value": "1"}])
def test_unsupported_output_never_replaces_artifacts(tmp_path, section, fields):
    board = _parsed(**{section: fields, SOURCE_ACTIVITY: {section: True}, SOURCE_OPTIONS: {section: list(fields)}})
    paths = [tmp_path / n for n in ("printer.cfg", "printer.cfg.provenance.json", "macros.cfg")]
    for p in paths:
        p.write_bytes(b"existing")
    with pytest.raises(GenerationError, match=section):
        generate_config(board, _user(), output_path=str(paths[0]), include_macros=True, verbose=False)
    assert all(p.read_bytes() == b"existing" for p in paths)


def test_old_parsed_checkpoint_requires_raw_source_or_reload(section):
    old = {section: {"pin": "PG1", "value": "1"}}
    with pytest.raises(GenerationError, match="active-source"):
        selected_board_digital_outputs(old)
    source = selected_board_electrical_source({"board": "test.cfg", "board_parsed": old, "board_raw_config": output(section)})
    assert selected_board_digital_outputs(source) == old


@pytest.mark.parametrize("other", ["[output_pin motor_power]\npin: PG1\nvalue: 1\n",
    "[static_digital_output x]\npins: !PG1\n", "[fan]\npin: PG1\n",
    "[board_pins]\naliases: SAME=PG1\n[probe]\npin: SAME\n",
    "[duplicate_pin_override]\npins: PG1\n[fan]\npin: PG1\n"])
def test_conflicts_across_supported_outputs_and_other_consumers(section, other):
    with pytest.raises(GenerationError, match="conflicts"):
        validate_board_digital_outputs(_read_pin_config("[mcu]\nserial: /tmp/mcu\n"+output(section)+other)[0])


def test_generation_and_effective_review_request_firmware_evidence(tmp_path, section):
    from core.configuration_review import validate_configuration_plan
    board = {**_parsed(), **parse_config(output(section))}
    with patch("core.firmware_workflow.generation_pin_reservations", return_value={"mcu": {"PG1": "USB"}}) as reader:
        with pytest.raises(GenerationError, match="reserved for USB"):
            generate_config(board, _user(), output_path=str(tmp_path / "printer.cfg"), verbose=False)
    reader.assert_called_once()
    assert not (tmp_path / "printer.cfg").exists()
    reader = Mock(return_value={"mcu": {"PG1": "USB"}})
    result = validate_configuration_plan(build_managed_config_plan(GENERATED+output(section).encode(), None, {}),
        firmware_reservation_reader=reader)
    reader.assert_called_once()
    assert any(e.code == "board-digital-output" and "reserved for USB" in e.message for e in result.errors)


@pytest.mark.parametrize("override", ["pin: PG2", "pin: !PG1", "value: 0", "shutdown_value: 1", "pwm: true"])
@pytest.mark.parametrize("noop", [False, True])
def test_effective_override_rejects_without_writes_or_activation(tmp_path, section, override, noop):
    good = GENERATED+output(section).encode()
    remote = {"printer.cfg": good+b"[include user.cfg]\n", "user.cfg": f"[{section}]\n{override}\n".encode()}
    if noop:
        remote.update({a.remote_name: a.content for a in build_managed_config_plan(good, None, remote).artifacts})
        assert not build_managed_config_plan(good, None, remote).changed_artifacts
    dest, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(dest, good, None, selected_board=parse_config(output(section)),
        activation="firmware", confirm=confirm, snapshot_root=str(tmp_path / "snapshots"), poll_interval=0).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert section in result.detail
    confirm.assert_not_called()
    assert dest.files == remote and all(c[0] == "read" for c in dest.calls)
    assert not (tmp_path / "snapshots").exists()


def test_alias_equivalence_and_distinct_mcu_identity(section):
    source = parse_config("[board_pins]\naliases: SIGNAL=PG1\n"+output(section, "!SIGNAL"))
    validate_board_electrical_artifact(source, GENERATED+output(section, "!PG1", extra="shutdown_value: 0\npwm: off\n").encode())
    with pytest.raises(GenerationError, match="missing or changed"):
        validate_board_electrical_artifact(source, GENERATED+b"[mcu aux]\nserial: /tmp/aux\n"+output(section, "!aux:PG1").encode())


def test_missing_saved_output_rejects_before_transport(tmp_path, section):
    dest, confirm = FakeTransport(), Mock(return_value=True)
    result = ConfigDeploymentTransaction(dest, GENERATED, None, selected_board=parse_config(output(section)),
        activation="firmware", confirm=confirm, snapshot_root=str(tmp_path), poll_interval=0).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED and section in result.detail
    assert not dest.calls
    confirm.assert_not_called()


def test_combined_outputs_publish_and_repeat(tmp_path):
    raw = output("output_pin motor_power", "PG1")+output("output_pin probe_enable", "PG2")+output("output_pin screen", "PG3")
    dest = FakeTransport()
    for _ in range(2):
        result = ConfigDeploymentTransaction(dest, GENERATED+raw.encode(), None, selected_board=parse_config(raw),
            activation="none", snapshot_root=str(tmp_path), poll_interval=0).run()
        assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    for name, fields in selected_board_digital_outputs(parse_config(raw)).items():
        assert parse_config(dest.files["printer.cfg"].decode())[name] == fields
