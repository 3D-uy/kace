"""Probe modes are explicit configuration, never inferred from a device label."""
import copy
import itertools
from unittest.mock import Mock

import pytest

from core.configuration_review import validate_configuration_plan
from core.exceptions import GenerationError
from core.generator import generate_config
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.pin_validator import _read_pin_config
from tests.unit.test_generator import _parsed, _user


FLAGS = ("pin_up_touch_mode_reports_triggered", "probe_with_touch_mode",
         "pin_up_reports_not_triggered", "stow_on_each_sample")


def board(**flags):
    return _parsed(bltouch={"sensor_pin": "^PB8", "control_pin": "PB9", **flags})


def generate(tmp_path, flags=None, **user):
    return generate_config(board(**(flags or {})), _user(probe="BLTouch", **user),
                           output_path=str(tmp_path / "printer.cfg"), verbose=False)


@pytest.mark.parametrize("probe", ["BLTouch", "CR-Touch"])
@pytest.mark.parametrize("values", list(itertools.product((None, "True", "False"), repeat=4)))
def test_all_explicit_boolean_combinations_and_omissions(tmp_path, probe, values):
    flags = {key: value for key, value in zip(FLAGS, values) if value is not None}
    parsed, user = board(**flags), _user(probe=probe)
    before = copy.deepcopy((parsed, user))
    result = generate_config(parsed, user, output_path=str(tmp_path / "printer.cfg"), verbose=False)
    section = _read_pin_config(result["content"])[0]["bltouch"]
    assert {key: section[key] for key in FLAGS if key in section} == flags
    assert (parsed, user) == before


@pytest.mark.parametrize("flag", FLAGS)
@pytest.mark.parametrize("value", ["", "maybe", "2", "None", None])
def test_invalid_explicit_flag_cannot_replace_output(tmp_path, flag, value):
    target = tmp_path / "printer.cfg"
    target.write_bytes(b"existing configuration")
    with pytest.raises(GenerationError, match=flag):
        generate(tmp_path, {flag: value})
    assert target.read_bytes() == b"existing configuration"
    assert not (tmp_path / "printer.cfg.provenance.json").exists()


@pytest.mark.parametrize("flag", FLAGS)
@pytest.mark.parametrize("value,expected", [(True, "True"), (False, "False"),
    ("yes", "True"), ("no", "False"), ("ON", "True"), ("off", "False"),
    ("1", "True"), ("0", "False")])
def test_official_boolean_spellings(tmp_path, flag, value, expected):
    result = generate(tmp_path, {flag: value})
    assert _read_pin_config(result["content"])[0]["bltouch"][flag] == expected


def test_profile_flag_selection_keeps_board_pins_and_records_sources(tmp_path):
    result = generate(tmp_path, _profile_parsed={"bltouch": {
        "sensor_pin": "^INVALID", "control_pin": "INVALID", FLAGS[0]: "True", FLAGS[1]: "False"}})
    section = _read_pin_config(result["content"])[0]["bltouch"]
    assert section["sensor_pin"] == "^PB8"
    assert section["control_pin"] == "PB9"
    assert section[FLAGS[0]] == "True" and section[FLAGS[1]] == "False"
    import json
    provenance = json.loads((tmp_path / "printer.cfg.provenance.json").read_text())
    assert provenance["sources"]["bltouch_flags"][FLAGS[0]] == {
        "value": "True", "sources": ["printer_profile"]}


@pytest.mark.parametrize("flag", FLAGS)
def test_conflicting_sources_require_resolution(tmp_path, flag):
    with pytest.raises(GenerationError, match="conflicting.*" + flag):
        generate(tmp_path, {flag: "True"}, _profile_parsed={"bltouch": {flag: "False"}})
    assert not (tmp_path / "printer.cfg").exists()


def test_semantically_equal_sources_do_not_conflict(tmp_path):
    result = generate(tmp_path, {FLAGS[0]: "yes"}, _profile_parsed={"bltouch": {FLAGS[0]: "1"}})
    assert _read_pin_config(result["content"])[0]["bltouch"][FLAGS[0]] == "True"


def test_changing_profile_does_not_reuse_old_flags(tmp_path):
    user = _user(probe="BLTouch", _profile_parsed={"bltouch": {FLAGS[0]: "False"}})
    first = generate_config(board(), user, output_path=str(tmp_path / "printer.cfg"), verbose=False)
    assert _read_pin_config(first["content"])[0]["bltouch"][FLAGS[0]] == "False"
    user["_profile_parsed"] = {}
    second = generate_config(board(), user, output_path=str(tmp_path / "printer.cfg"), verbose=False)
    assert FLAGS[0] not in _read_pin_config(second["content"])[0]["bltouch"]


def test_checkpoint_roundtrip_preserves_explicit_flags(tmp_path):
    import json
    from core.firmware_workflow import persistable_wizard_data
    user = _user(probe="CR-Touch", _profile_parsed={"bltouch": {
        FLAGS[0]: "True", FLAGS[1]: "False"}})
    restored = json.loads(json.dumps(persistable_wizard_data(user)))
    result = generate_config(board(), restored, output_path=str(tmp_path / "printer.cfg"), verbose=False)
    section = _read_pin_config(result["content"])[0]["bltouch"]
    assert section[FLAGS[0]] == "True" and section[FLAGS[1]] == "False"


def test_custom_probe_is_not_given_bltouch_flags(tmp_path):
    from core.custom_probe import parse_custom_probe_config
    raw = "[probe]\npin: ^PB8\nx_offset: 0\ny_offset: 0\nz_offset: 0\n"
    result = generate_config(board(**{FLAGS[0]: "invalid"}),
        _user(probe="Custom Probe", custom_probe=parse_custom_probe_config(raw)),
        output_path=str(tmp_path / "printer.cfg"), verbose=False)
    assert raw.rstrip() in result["content"]
    assert not any(flag in result["content"] for flag in FLAGS)


@pytest.mark.parametrize("probe", ["None", "Inductive"])
def test_unused_bltouch_options_are_not_applied_to_other_probes(tmp_path, probe):
    result = generate_config(board(**{FLAGS[0]: "invalid"}), _user(probe=probe),
        output_path=str(tmp_path / "printer.cfg"), verbose=False)
    assert "[bltouch]" not in result["content"]
    assert not any(flag in result["content"] for flag in FLAGS)


def test_existing_explicit_flags_survive_omission_and_second_plan_is_noop(tmp_path):
    generated = generate(tmp_path)["content"].encode()
    current = {"printer.cfg": generated.replace(b"[bltouch]", b"[bltouch]\n" +
        b"pin_up_touch_mode_reports_triggered: False\nprobe_with_touch_mode: True"),
        "moonraker.conf": None}
    first = build_managed_config_plan(generated, None, current)
    section = _read_pin_config(effective_hardware_text(first))[0]["bltouch"]
    assert section[FLAGS[0]] == "False" and section[FLAGS[1]] == "True"
    assert not any(e.code == "bltouch-flags" for e in validate_configuration_plan(first).errors)
    current.update({a.remote_name: a.content for a in first.artifacts})
    assert not build_managed_config_plan(generated, None, current).changed_artifacts


@pytest.mark.parametrize("flag", FLAGS)
@pytest.mark.parametrize("noop", [False, True])
def test_invalid_late_include_blocks_transaction_before_confirmation(tmp_path, flag, noop):
    from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
    from tests.unit.test_config_transaction import FakeTransport

    generated = generate(tmp_path)["content"].encode()
    current = {"printer.cfg": generated + b"\n[include user.cfg]\n",
               "user.cfg": b"[include nested.cfg]\n",
               "nested.cfg": f"[bltouch]\n{flag}: invalid\n".encode(), "moonraker.conf": None}
    if noop:
        plan = build_managed_config_plan(generated, None, current)
        current.update({a.remote_name: a.content for a in plan.artifacts})
        assert not build_managed_config_plan(generated, None, current).changed_artifacts
    transport = FakeTransport({k: v for k, v in current.items() if v is not None})
    before, confirm = dict(transport.files), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, generated, None, activation="none", confirm=confirm,
        output=lambda _: None, snapshot_root=str(tmp_path / "snapshots"), poll_interval=0).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert flag in result.detail
    confirm.assert_not_called()
    assert transport.files == before
    assert not any(call[0] in ("upload", "delete", "restart", "restart_moonraker") for call in transport.calls)


def test_rendered_invalid_flag_is_checked_before_writing(tmp_path, monkeypatch):
    import core.generator as generator
    original = generator._postprocess_generated_output
    monkeypatch.setattr(generator, "_postprocess_generated_output", lambda text:
        original(text).replace("[bltouch]", "[bltouch]\nprobe_with_touch_mode: invalid"))
    with pytest.raises(GenerationError, match="probe_with_touch_mode"):
        generate(tmp_path)
    assert not (tmp_path / "printer.cfg").exists()


def test_valid_late_include_wins_over_generated_flag(tmp_path):
    generated = generate(tmp_path, {FLAGS[0]: "True"})["content"].encode()
    current = {"printer.cfg": generated + b"\n[include user.cfg]\n",
               "user.cfg": b"[bltouch]\npin_up_touch_mode_reports_triggered: False\n"}
    plan = build_managed_config_plan(generated, None, current)
    assert _read_pin_config(effective_hardware_text(plan))[0]["bltouch"][FLAGS[0]] == "False"
    assert not any(e.code == "bltouch-flags" for e in validate_configuration_plan(plan).errors)
