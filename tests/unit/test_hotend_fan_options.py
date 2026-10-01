"""Selected heater fan retains its identity, cooling settings and heater binding."""
import json
from unittest.mock import Mock, patch

import pytest

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.exceptions import GenerationError
from core.generator import generate_config
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.configuration_review import validate_configuration_plan
from core.scraper import parse_config
from core.wizard.steps.hardware import _step_fan_assignment
from tests.unit.test_config_transaction import FakeTransport, GENERATED
from tests.unit.test_generator import _parsed, _user
from tests.unit.test_part_fan_options import OPTIONS, INVALID
from tests.unit.test_tmc_uart_review import remote_files


SOURCE = "heater_fan heatbreak"
FIELDS = {"pin": "PC7", **OPTIONS, "heater": "extruder, heater_bed", "heater_temp": "40.0", "fan_speed": "0.8"}


def board(fields=None, name=SOURCE):
    raw = f"[{name}]\n" + "\n".join(f"{k}: {v}" for k, v in (FIELDS if fields is None else fields).items())
    parsed = _parsed()
    parsed.update(parse_config(raw, keep_comments=True))
    return parsed, raw


def render(tmp_path, parsed, **choices):
    return generate_config(parsed, _user(**choices), output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]


def test_wizard_selected_heater_fan_preserves_binding_after_resume(tmp_path):
    parsed, raw = board()
    user = _user(board_raw_config=raw)
    with patch("core.wizard.steps.hardware.numbered_select", side_effect=["none", "PC7"]):
        assert _step_fan_assignment(user) == "success"
    user = json.loads(json.dumps(user))
    parsed = json.loads(json.dumps(parsed))
    text = generate_config(parsed, user, output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]
    assert parse_config(text)[SOURCE] == FIELDS
    assert "heater_fan hotend_fan" not in parse_config(text)
    plan = build_managed_config_plan(text.encode(), None, {"printer.cfg": text.encode()})
    assert validate_configuration_plan(plan).valid
    assert parse_config(effective_hardware_text(plan))[SOURCE] == FIELDS
    remote = {a.remote_name: a.content for a in plan.artifacts}
    assert not build_managed_config_plan(text.encode(), None, remote).changed_artifacts


def test_active_settings_only(tmp_path):
    parsed, _ = board({"pin": "PC7", "heater_temp": "40"})
    parsed.update(parse_config("[heater_fan heatbreak]\npin: PC7\nheater_temp: 40\n# fan_speed: 0.2\n# enable_pin: PA8\n", keep_comments=True))
    fields = parse_config(render(tmp_path, parsed, fan_hotend_pin="PC7"))[SOURCE]
    assert fields == {"pin": "PC7", "heater_temp": "40"}


def test_none_removes_legacy_canonical_fan(tmp_path):
    parsed, _ = board(name="heater_fan hotend_fan")
    assert "heater_fan hotend_fan" not in parse_config(render(tmp_path, parsed, fan_hotend_pin="none"))


def test_custom_pin_does_not_inherit_another_fan(tmp_path):
    parsed, _ = board()
    fields = parse_config(render(tmp_path, parsed, fan_hotend_pin="PA8"))["heater_fan hotend_fan"]
    assert fields == {"pin": "PA8", "heater": "extruder", "heater_temp": "50.0"}


def test_case_sensitive_source_name_survives_generation_and_publication(tmp_path):
    name = "heater_fan HeatBreak"
    parsed, _ = board(name=name)
    text = render(tmp_path, parsed, fan_hotend_pin="PC7")
    assert parse_config(text)[name] == FIELDS
    plan = build_managed_config_plan(text.encode(), None, {"printer.cfg": text.encode()})
    assert parse_config(effective_hardware_text(plan))[name] == FIELDS


def test_comment_only_fan_uses_explicit_custom_defaults(tmp_path):
    parsed = _parsed()
    parsed.update(parse_config("#[heater_fan hotend_fan]\n#pin: PC7\n#fan_speed: 0.2\n", keep_comments=True))
    assert "heater_fan hotend_fan" not in parse_config(render(tmp_path, parsed))
    fields = parse_config(render(tmp_path, parsed, fan_hotend_pin="PC7"))["heater_fan hotend_fan"]
    assert fields == {"pin": "PC7", "heater": "extruder", "heater_temp": "50.0"}


@pytest.mark.parametrize("choice", ["!PC7", "mcu:PC7", "FAN_HEADER"])
def test_alias_or_polarity_change_cannot_drop_source_options(tmp_path, choice):
    parsed, _ = board()
    parsed["board_pins fans"] = {"aliases": "FAN_HEADER=PC7"}
    with pytest.raises(GenerationError, match="alias/polarity"):
        render(tmp_path, parsed, fan_hotend_pin=choice)


@pytest.mark.parametrize("speed,temperature", [("0", "-10"), ("1", "0"), ("0.5", "70")])
def test_klipper_valid_values_are_not_arbitrarily_restricted(tmp_path, speed, temperature):
    fields = {"pin": "PC7", "fan_speed": speed, "heater_temp": temperature}
    parsed, _ = board(fields)
    assert parse_config(render(tmp_path, parsed, fan_hotend_pin="PC7"))[SOURCE] == fields


@pytest.mark.parametrize("reference,valid", [("Chamber", True), ("chamber", False)])
def test_preserved_custom_heater_reference_is_case_sensitive(reference, valid):
    content = GENERATED + f"[heater_generic Chamber]\nheater_pin: PA8\n[heater_fan HeatBreak]\npin: PC7\nheater: {reference}\n".encode()
    plan = build_managed_config_plan(content, None, {"printer.cfg": content})
    result = validate_configuration_plan(plan)
    assert (not any(e.code == "heater-fan-options" for e in result.errors)) is valid


def test_multiline_heaters_survive_without_dropping_the_second_heater(tmp_path):
    parsed, _ = board({"pin": "PC7", "heater": "extruder,\n    heater_bed"})
    text = render(tmp_path, parsed, fan_hotend_pin="PC7")
    from core.managed_config import _section_options
    assert _section_options(text)[SOURCE]["heater"].replace("\n", "").replace(" ", "") == "extruder,heater_bed"
    plan = build_managed_config_plan(text.encode(), None, {"printer.cfg": text.encode()})
    assert validate_configuration_plan(plan).valid


def test_effective_multiline_reference_checks_every_heater():
    text = GENERATED + b"[extruder]\nheater_pin: PA4\n[heater_fan hotend]\npin: PC7\nheater:\n    extruder,\n    missing\n"
    plan = build_managed_config_plan(text, None, {"printer.cfg": text})
    assert any("missing" in e.message for e in validate_configuration_plan(plan).errors if e.code == "heater-fan-options")


@pytest.mark.parametrize("old_pin", ["PC7", "!mcu:PC7", "FAN_HEADER"])
def test_old_canonical_name_cannot_create_two_fans_on_same_gpio(tmp_path, old_pin):
    parsed, _ = board()
    text = render(tmp_path, parsed, fan_hotend_pin="PC7")
    remote = {"printer.cfg": (f"[include user.cfg]\n[heater_fan hotend_fan]\npin: {old_pin}\n").encode(),
              "user.cfg": b"[board_pins fan]\naliases: FAN_HEADER=PC7\n"}
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, text.encode(), None, activation="none", confirm=confirm,
        snapshot_root=str(tmp_path / "snapshots")).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "fan" in result.detail and "GPIO" in result.detail
    confirm.assert_not_called()
    assert not any(c[0] in ("upload", "delete", "restart") for c in transport.calls)


def test_custom_part_and_hotend_cannot_share_gpio(tmp_path):
    parsed, _ = board()
    with pytest.raises(GenerationError, match="GPIO"):
        render(tmp_path, parsed, fan_hotend_pin="PC7", fan_part_cooling_pin="!PC7")


@pytest.mark.parametrize("option,value", INVALID + [("heater_temp", "nan"), ("fan_speed", "-1"), ("fan_speed", "1.1")])
def test_invalid_source_rejected_before_write(tmp_path, option, value):
    parsed, _ = board({**FIELDS, option: value})
    with pytest.raises(GenerationError, match=option):
        render(tmp_path, parsed, fan_hotend_pin="PC7")
    assert not (tmp_path / "printer.cfg").exists()


@pytest.mark.parametrize("heater", ["extruder1", "Extruder", "chamber"])
def test_missing_heater_is_not_silently_replaced(tmp_path, heater):
    parsed, _ = board({**FIELDS, "heater": heater})
    with pytest.raises(GenerationError, match="heater"):
        render(tmp_path, parsed, fan_hotend_pin="PC7")
    assert not (tmp_path / "printer.cfg").exists()


@pytest.mark.parametrize("option", ["tachometer_pin", "enable_pin"])
def test_auxiliary_dependency_is_blocked_not_dropped(tmp_path, option):
    parsed, _ = board({**FIELDS, option: "PA8"})
    with pytest.raises(GenerationError, match=option):
        render(tmp_path, parsed, fan_hotend_pin="PC7")


def test_ambiguous_source_pin_is_rejected(tmp_path):
    parsed, _ = board()
    parsed.update(parse_config("[heater_fan heatbreak]\npin: PC7\n[heater_fan other]\npin: PC7\n", keep_comments=True))
    with pytest.raises(GenerationError, match="ambiguous"):
        render(tmp_path, parsed, fan_hotend_pin="PC7")


@pytest.mark.parametrize("name", ["controller_fan board", "temperature_fan board"])
def test_other_automatic_role_not_reinterpreted(tmp_path, name):
    parsed, _ = board({"pin": "PC7"}, name=name)
    with pytest.raises(GenerationError, match="role"):
        render(tmp_path, parsed, fan_hotend_pin="PC7")


@pytest.mark.parametrize("noop", [False, True])
@pytest.mark.parametrize("option,value", [("heater", "missing"), ("heater_temp", "inf"), ("fan_speed", "2"), ("max_power", "0")])
def test_effective_include_rejected_before_upload(tmp_path, noop, option, value):
    base = GENERATED + b"[extruder]\nheater_pin: PA4\n[heater_fan heatbreak]\npin: PC7\n"
    remote = remote_files(f"[heater_fan heatbreak]\n{option}: {value}\n")
    if noop:
        plan = build_managed_config_plan(base, None, remote)
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        assert not build_managed_config_plan(base, None, remote).changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, base, None, activation="none", confirm=confirm,
        snapshot_root=str(tmp_path / "snapshots"), verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert option in result.detail
    confirm.assert_not_called()
    assert not any(c[0] in ("upload", "delete", "restart") for c in transport.calls)
