"""Explicit probe motion/sampling policy must not disappear behind loader defaults."""
from unittest.mock import Mock
import pytest
from core.exceptions import GenerationError
from core.generator import generate_config
from core.board_auxiliary import selected_board_electrical_source, validate_board_electrical_artifact
from core.managed_config import build_managed_config_plan
from core.pin_validator import _read_pin_config
from core.scraper import parse_config
from tests.unit.test_bltouch_flags import board
from tests.unit.test_generator import _user

OPTIONS = {"speed": "3", "lift_speed": "7", "samples": "4", "sample_retract_dist": "1.5",
           "samples_result": "median", "samples_tolerance": "0.02", "samples_tolerance_retries": "5"}


def generate(tmp_path, options=None, **kwargs):
    return generate_config(board(**(options or {})), _user(probe="BLTouch", **kwargs),
                           output_path=str(tmp_path / "printer.cfg"), verbose=False)


@pytest.mark.parametrize("kind", ["BLTouch", "CR-Touch"])
def test_all_active_options_are_preserved(tmp_path, kind):
    result = generate_config(board(**OPTIONS), _user(probe=kind), output_path=str(tmp_path / "printer.cfg"), verbose=False)
    section = _read_pin_config(result["content"])[0]["bltouch"]
    for key, value in OPTIONS.items():
        assert key in section
        assert section[key] == value if key == "samples_result" else float(section[key]) == float(value)


@pytest.mark.parametrize("option,value", [("speed", "0"), ("lift_speed", "-1"), ("sample_retract_dist", "0"),
    ("speed", "nan"), ("lift_speed", "inf"), ("samples", "0"), ("samples", "2.0"),
    ("samples_tolerance", "-0.1"), ("samples_tolerance_retries", "-1"), ("samples_tolerance_retries", "1.5"),
    ("samples_result", "Median"), ("samples_result", "invalid")])
def test_invalid_policy_never_replaces_existing_artifact(tmp_path, option, value):
    target = tmp_path / "printer.cfg"
    target.write_bytes(b"prior")
    with pytest.raises(GenerationError, match=option):
        generate(tmp_path, {option: value})
    assert target.read_bytes() == b"prior"
    assert not (tmp_path / "printer.cfg.provenance.json").exists()


@pytest.mark.parametrize("option", OPTIONS)
def test_conflicting_profile_and_board_require_resolution(tmp_path, option):
    other = "average" if option == "samples_result" else "8"
    with pytest.raises(GenerationError, match=option):
        generate(tmp_path, OPTIONS, _profile_parsed={"bltouch": {option: other}})


def test_profile_only_settings_survive_recovery_context(tmp_path):
    profile = {"bltouch": dict(OPTIONS)}
    user = _user(probe="BLTouch", board_parsed=board(), _profile_parsed=profile)
    text = generate_config(board(), user, output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]
    saved = {"workflow_checkpoint": {"wizard_data": user}}
    source = selected_board_electrical_source(saved)
    validate_board_electrical_artifact(source, text)
    with pytest.raises(GenerationError, match="samples_tolerance"):
        validate_board_electrical_artifact(source, text.replace("samples_tolerance: 0.02", "samples_tolerance: 0.5"))


def test_checkpoint_profile_policy_cannot_be_silently_changed(tmp_path):
    saved = _user(probe="BLTouch", board_parsed=board(), _profile_parsed={"bltouch": dict(OPTIONS)})
    with pytest.raises(GenerationError, match="profile|policy"):
        selected_board_electrical_source({"workflow_checkpoint": {"wizard_data": saved}, "_profile_parsed": {}})


def test_comments_do_not_supply_sampling_policy(tmp_path):
    parsed = board()
    parsed.update(parse_config("[bltouch]\nsensor_pin: ^PB8\ncontrol_pin: PB9\n# speed: 30\n# samples: 5\n", keep_comments=True))
    text = generate_config(parsed, _user(probe="BLTouch"), output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]
    section = _read_pin_config(text)[0]["bltouch"]
    assert "speed" not in section and "samples" not in section


@pytest.mark.parametrize("noop", [False, True])
@pytest.mark.parametrize("value", ["0.5", "-1"])
def test_late_include_cannot_override_source_policy(tmp_path, noop, value):
    from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
    from tests.unit.test_config_transaction import FakeTransport
    text = generate(tmp_path, OPTIONS)["content"].encode()
    remote = {"printer.cfg": text + b"\n[include user.cfg]\n", "user.cfg": b"[include nested.cfg]\n",
              "nested.cfg": f"[bltouch]\nsamples_tolerance: {value}\n".encode()}
    if noop:
        remote.update({a.remote_name: a.content for a in build_managed_config_plan(text, None, remote).artifacts})
        assert not build_managed_config_plan(text, None, remote).changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, text, None, selected_board=board(**OPTIONS),
        activation="none", confirm=confirm, output=lambda _: None,
        snapshot_root=str(tmp_path / "snapshots"), poll_interval=0).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "samples_tolerance" in result.detail
    confirm.assert_not_called()
    assert not any(c[0] in ("upload", "delete", "restart", "restart_moonraker") for c in transport.calls)


@pytest.mark.parametrize("field,value", [("samples_tolerance", "0"), ("samples_tolerance_retries", "0"),
    ("samples", "1"), ("samples_result", "average")])
def test_official_valid_boundaries_are_preserved(tmp_path, field, value):
    section = _read_pin_config(generate(tmp_path, {field: value})["content"])[0]["bltouch"]
    assert section[field] == value if field == "samples_result" else float(section[field]) == float(value)


def test_omitted_policy_retains_upstream_defaults(tmp_path):
    section = _read_pin_config(generate(tmp_path)["content"])[0]["bltouch"]
    assert not set(OPTIONS).intersection(section)


def test_equivalent_numeric_sources_and_provenance(tmp_path):
    import json
    generate(tmp_path, {"speed": "3.0"}, _profile_parsed={"bltouch": {"speed": "3"}})
    proof = json.loads((tmp_path / "printer.cfg.provenance.json").read_text(encoding="utf-8"))
    assert proof["sources"]["bltouch_sampling"]["speed"] == {"value": "3.0", "sources": ["board", "printer_profile"]}


def test_saved_raw_profile_recovers_policy_without_parsed_cache(tmp_path):
    source = selected_board_electrical_source(_user(probe="BLTouch", board_parsed=board(),
        raw_config="[bltouch]\nspeed: 3\n", profile_loaded=True))
    with pytest.raises(GenerationError, match="speed"):
        validate_board_electrical_artifact(source, generate(tmp_path)["content"])


def test_raw_profile_activity_wins_over_legacy_commented_cache(tmp_path):
    source = selected_board_electrical_source(_user(probe="BLTouch", board_parsed=board(),
        raw_config="[bltouch]\n# speed: 30\n", _profile_parsed={"bltouch": {"speed": "30"}}))
    validate_board_electrical_artifact(source, generate(tmp_path)["content"])


def test_changed_raw_profile_cannot_override_captured_policy(tmp_path):
    profile = parse_config("[bltouch]\nspeed: 3\n")
    with pytest.raises(GenerationError, match="profile"):
        selected_board_electrical_source(_user(probe="BLTouch", board_parsed=board(),
            _profile_parsed=profile, raw_config="[bltouch]\nspeed: 5\n"))


@pytest.mark.parametrize("kind", ["None", "Inductive"])
def test_bltouch_policy_is_not_applied_to_other_strategies(tmp_path, kind):
    text = generate_config(board(**OPTIONS), _user(probe=kind), output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]
    sections = _read_pin_config(text)[0]
    assert "bltouch" not in sections
    assert not set(OPTIONS).intersection(sections.get("probe", {}))


@pytest.mark.parametrize("invalid", [False, True])
def test_custom_probe_policy_remains_explicit_and_is_validated(tmp_path, invalid):
    from core.custom_probe import parse_custom_probe_config
    raw = "[probe]\npin: ^PB8\nx_offset: 0\ny_offset: 0\nz_offset: 0\nspeed: " + ("0" if invalid else "2") + "\n"
    user = _user(probe="Custom Probe", custom_probe=parse_custom_probe_config(raw))
    if invalid:
        with pytest.raises(GenerationError, match="speed"):
            generate_config(board(**OPTIONS), user, output_path=str(tmp_path / "printer.cfg"), verbose=False)
        assert not (tmp_path / "printer.cfg").exists()
    else:
        text = generate_config(board(**OPTIONS), user, output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]
        assert raw.rstrip() in text
        validate_board_electrical_artifact(board(**OPTIONS), text)


def test_rendered_policy_loss_is_caught_before_writing(tmp_path):
    from unittest.mock import patch
    from jinja2 import Template
    render = Template.render
    def alter(template, *args, **kwargs):
        return render(template, *args, **kwargs).replace("samples_tolerance: 0.02", "")
    with patch.object(Template, "render", alter), pytest.raises(GenerationError, match="samples_tolerance"):
        generate(tmp_path, OPTIONS)
    assert not (tmp_path / "printer.cfg").exists()



def test_generation_recovers_active_policy_from_saved_profile_text(tmp_path):
    result = generate(tmp_path, raw_config="[bltouch]\nspeed: 3\n# lift_speed: 30\n")
    section = _read_pin_config(result["content"])[0]["bltouch"]
    assert float(section["speed"]) == 3
    assert "lift_speed" not in section


def test_changed_active_source_cannot_reuse_cached_policy(tmp_path):
    parsed = board()
    parsed.update(parse_config("[bltouch]\nsensor_pin: ^PB8\ncontrol_pin: PB9\nspeed: 3\n"))
    parsed["bltouch"]["speed"] = "8"
    with pytest.raises(GenerationError, match="source changed"):
        generate_config(parsed, _user(probe="BLTouch"), output_path=str(tmp_path / "printer.cfg"), verbose=False)
    assert not (tmp_path / "printer.cfg").exists()
