"""Selected-board ADC resistors must survive generation and publication."""
import copy
import json
from unittest.mock import Mock, patch

import pytest

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.exceptions import GenerationError
from core.firmware_workflow import persistable_wizard_data
from core.generator import generate_config
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.profile_values import mark_profile_values
from core.scraper import extract_profile_defaults, parse_config
from tests.unit.test_config_transaction import FakeTransport, GENERATED
from tests.unit.test_generator import _parsed, _user
from tests.unit.test_tmc_uart_review import remote_files


SECTIONS = ("extruder", "heater_bed")
OPTIONS = ("pullup_resistor", "inline_resistor")
INVALID = [("pullup_resistor", value) for value in ("0", "-1", "nan", "inf", "", None, True, "bad")]
INVALID += [("inline_resistor", value) for value in ("-1", "nan", "inf", "", None, True, "bad")]


def render(tmp_path, board, user=None):
    return generate_config(board, user or _user(), output_path=str(tmp_path / "printer.cfg"), verbose=False)


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("pullup,inline", [("2000", "0"), ("2200", "0"), ("4700", "4700"), ("2200.5", "1.5")])
def test_circuit_survives_generation_reconciliation_and_noop(tmp_path, section, pullup, inline):
    board = _parsed()
    board[section].update(pullup_resistor=pullup, inline_resistor=inline)
    result = render(tmp_path, board)
    text = result["content"]
    provenance = json.loads((tmp_path / "printer.cfg.provenance.json").read_text())
    for option, value in zip(OPTIONS, (pullup, inline)):
        assert parse_config(text)[section][option] == value
        assert provenance["sources"]["hardware_options"][section][option] == value
    remote = {"printer.cfg": text.encode()}
    plan = build_managed_config_plan(text.encode(), None, remote)
    assert validate_configuration_plan(plan).valid
    for option in OPTIONS:
        assert parse_config(effective_hardware_text(plan))[section][option] == board[section][option]
    remote.update({a.remote_name: a.content for a in plan.artifacts})
    assert not build_managed_config_plan(text.encode(), None, remote).changed_artifacts


def test_omitted_resistors_remain_omitted(tmp_path):
    final = parse_config(render(tmp_path, _parsed())["content"])
    for section in SECTIONS:
        assert not set(OPTIONS).intersection(final[section])


@pytest.mark.parametrize("board_has_circuit", (False, True))
@pytest.mark.parametrize("resume", (False, True))
def test_printer_profile_cannot_supply_board_resistors(tmp_path, board_has_circuit, resume):
    board = _parsed()
    if board_has_circuit:
        board["extruder"].update(pullup_resistor="2200", inline_resistor="4700")
    profile = copy.deepcopy(board)
    profile["extruder"].update(pullup_resistor="1000", inline_resistor="100")
    user = _user(_profile_parsed=profile)
    user.update(extract_profile_defaults(profile))
    mark_profile_values(user, profile)
    if resume:
        user = json.loads(json.dumps(persistable_wizard_data(user)))
    final = parse_config(render(tmp_path, board, user)["content"])
    for option in OPTIONS:
        assert final["extruder"].get(option) == board["extruder"].get(option)


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("option,value", INVALID)
def test_invalid_source_circuit_fails_before_writing(tmp_path, section, option, value):
    board = _parsed()
    board[section][option] = value
    output = tmp_path / "printer.cfg"
    output.write_text("unchanged")
    with pytest.raises(GenerationError, match=option):
        render(tmp_path, board)
    assert output.read_text() == "unchanged"
    assert not (tmp_path / "printer.cfg.provenance.json").exists()


@pytest.mark.parametrize("option,value", INVALID)
def test_preserved_include_circuit_is_reviewed(option, value):
    remote = remote_files(f"[temperature_sensor chamber]\nsensor_type: Generic 3950\nsensor_pin: PC11\n{option}: {value}\n")
    validation = validate_configuration_plan(build_managed_config_plan(GENERATED, None, remote))
    assert not validation.valid
    assert any(error.code == "sensor-resistor" and option in error.message for error in validation.errors)


@pytest.mark.parametrize("noop", (False, True))
def test_invalid_circuit_blocks_transaction_before_confirmation(tmp_path, noop):
    remote = remote_files("[temperature_sensor chamber]\nsensor_type: Generic 3950\nsensor_pin: PC11\npullup_resistor: 0\n")
    if noop:
        plan = build_managed_config_plan(GENERATED, None, remote)
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        assert not build_managed_config_plan(GENERATED, None, remote).changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, GENERATED, None, activation="none", confirm=confirm,
        snapshot_root=str(tmp_path / "snapshots"), verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "pullup_resistor" in result.detail
    confirm.assert_not_called()
    assert transport.files == remote
    assert not any(call[0] in ("upload", "delete", "restart") for call in transport.calls)


def test_rendered_invalid_circuit_cannot_bypass_source_validation(tmp_path):
    from jinja2 import Template
    original = Template.render
    def inject(template, *args, **kwargs):
        return original(template, *args, **kwargs) + "\n[temperature_sensor test]\nsensor_type: Generic 3950\npullup_resistor: 0\n"
    with patch.object(Template, "render", inject), pytest.raises(GenerationError, match="pullup_resistor"):
        render(tmp_path, _parsed())
    assert not (tmp_path / "printer.cfg").exists()
