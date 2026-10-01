"""Selected part fan settings survive generation and final plan review."""
import copy
import json
from unittest.mock import Mock

import pytest

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.exceptions import GenerationError
from core.generator import generate_config
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.scraper import parse_config
from tests.unit.test_config_transaction import FakeTransport, GENERATED
from tests.unit.test_generator import _parsed, _user
from tests.unit.test_tmc_uart_review import remote_files


OPTIONS = {"max_power": "0.6", "kick_start_time": "1.0", "off_below": "0.15",
           "cycle_time": "0.02", "hardware_pwm": "False", "shutdown_speed": "0.4"}


def render(tmp_path, board, **choices):
    return generate_config(board, _user(**choices), output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]


@pytest.mark.parametrize("choice", [None, "default", "PC5"])
def test_selected_source_options_survive_publish_and_noop(tmp_path, choice):
    board = _parsed(fan={"pin": "PC5", **OPTIONS})
    before = copy.deepcopy(board)
    content = render(tmp_path, board, fan_part_cooling_pin=choice)
    assert parse_config(content)["fan"] == board["fan"]
    assert board == before
    provenance = json.loads((tmp_path / "printer.cfg.provenance.json").read_text())
    assert provenance["sources"]["hardware_options"]["fan"] == board["fan"]
    remote = {"printer.cfg": content.encode()}
    plan = build_managed_config_plan(content.encode(), None, remote)
    assert validate_configuration_plan(plan).valid
    assert parse_config(effective_hardware_text(plan))["fan"] == board["fan"]
    remote.update({a.remote_name: a.content for a in plan.artifacts})
    assert not build_managed_config_plan(content.encode(), None, remote).changed_artifacts


@pytest.mark.parametrize("choice", ["none", "PA8"])
def test_other_socket_does_not_inherit_source_tuning(tmp_path, choice):
    result = parse_config(render(tmp_path, _parsed(fan={"pin": "PC5", **OPTIONS}), fan_part_cooling_pin=choice))
    assert result.get("fan") == (None if choice == "none" else {"pin": "PA8"})


def test_active_options_only_even_when_loading_commented_examples(tmp_path):
    raw = "[fan]\npin: PC5\nkick_start_time: 1.0\n# max_power: 0.3\n# enable_pin: PA8\n"
    source = parse_config(raw, keep_comments=True)
    board = _parsed()
    board.update(source)
    result = parse_config(render(tmp_path, board))
    assert result["fan"] == {"pin": "PC5", "kick_start_time": "1.0"}


def test_commented_fan_is_not_activated_implicitly(tmp_path):
    board = _parsed()
    board.update(parse_config("#[fan]\n#pin: PC5\n#max_power: 0.3\n", keep_comments=True))
    assert "fan" not in parse_config(render(tmp_path, board))
    assert parse_config(render(tmp_path, board, fan_part_cooling_pin="PC5"))["fan"] == {"pin": "PC5"}


@pytest.mark.parametrize("option,value", [
    ("max_power", "1"), ("kick_start_time", "0"), ("off_below", "0"),
    ("off_below", "1"), ("shutdown_speed", "0"), ("shutdown_speed", "1"),
    ("hardware_pwm", "True"), ("hardware_pwm", "on"), ("hardware_pwm", "0"),
])
def test_valid_scalar_boundaries_survive_resume(tmp_path, option, value):
    raw = f"[fan]\npin: PC5\n{option}: {value}\n"
    board = _parsed()
    board.update(parse_config(raw, keep_comments=True))
    board = json.loads(json.dumps(board))
    result = parse_config(render(tmp_path, board))
    assert result["fan"] == {"pin": "PC5", option: value}


def test_omission_leaves_defaults_to_klipper(tmp_path):
    assert parse_config(render(tmp_path, _parsed()))["fan"] == {"pin": "PC5"}


INVALID = [("max_power", "0"), ("max_power", "1.1"), ("kick_start_time", "-1"),
           ("off_below", "-0.1"), ("off_below", "1.1"), ("cycle_time", "0"),
           ("shutdown_speed", "1.1"), ("hardware_pwm", "maybe"),
           ("max_power", "nan"), ("cycle_time", "inf")]


@pytest.mark.parametrize("option,value", INVALID)
def test_invalid_source_stops_before_writing(tmp_path, option, value):
    with pytest.raises(GenerationError, match="fan.*" + option):
        render(tmp_path, _parsed(fan={"pin": "PC5", option: value}))
    assert not (tmp_path / "printer.cfg").exists()


@pytest.mark.parametrize("option,value", INVALID)
@pytest.mark.parametrize("noop", [False, True])
def test_invalid_effective_include_stops_transaction(tmp_path, option, value, noop):
    remote = remote_files(f"[fan]\n{option}: {value}\n")
    if noop:
        plan = build_managed_config_plan(GENERATED, None, remote)
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        assert not build_managed_config_plan(GENERATED, None, remote).changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, GENERATED, None, activation="none", confirm=confirm,
        snapshot_root=str(tmp_path / "snapshots"), verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert option in result.detail
    confirm.assert_not_called()
    assert transport.files == remote
    assert not any(c[0] in ("upload", "delete", "restart") for c in transport.calls)


@pytest.mark.parametrize("option", ["enable_pin", "tachometer_pin", "unknown_option"])
def test_unimplemented_selected_dependency_is_not_silently_lost(tmp_path, option):
    with pytest.raises(GenerationError, match="fan.*" + option):
        render(tmp_path, _parsed(fan={"pin": "PC5", option: "PA8"}))
    assert not (tmp_path / "printer.cfg").exists()
