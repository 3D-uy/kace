"""Custom thermal curves are dependencies, not executable profile features."""
import copy
import json
from unittest.mock import Mock

import pytest

from core.generator import generate_config
from core.exceptions import GenerationError
from core.configuration_review import validate_configuration_plan
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.firmware_workflow import persistable_wizard_data
from core.scraper import parse_config
from tests.unit.test_generator import _parsed, _user
from tests.unit.test_config_transaction import FakeTransport, GENERATED
from tests.unit.test_tmc_uart_review import remote_files


G2 = {"temperature1": "20", "resistance1": "140000", "temperature2": "195",
      "resistance2": "593", "temperature3": "255", "resistance3": "189"}
BETA = {"temperature1": "25", "resistance1": "100000", "beta": "3950"}
BAD = [({}, "temperature1"), ({"temperature1": "nan"}, "temperature1"),
       ({"resistance1": "0"}, "resistance1"), ({"temperature1": "-273.15"}, "temperature1"),
       ({"temperature2": "20"}, "temperature"), ({"resistance2": "140000"}, "resistance"),
       ({"resistance3": "inf"}, "resistance3"), ({"gcode": "M112"}, "gcode"),
       ({"beta": "3950"}, "temperature2"), ({"resistance3": None}, "resistance3")]


def inputs(section="extruder", definition=None):
    board, user = _parsed(), _user()
    board["thermistor g2"] = dict(G2 if definition is None else definition)
    user["hotend_thermistor" if section == "extruder" else "bed_thermistor"] = "G2"
    board[section]["sensor_type"] = "G2"
    return board, user


def render(tmp_path, board, user):
    return generate_config(board, user, output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]


@pytest.mark.parametrize("section", ("extruder", "heater_bed"))
@pytest.mark.parametrize("definition", (G2, BETA))
@pytest.mark.parametrize("source", ("board", "profile", "resume"))
def test_definition_follows_selected_sensor(tmp_path, section, definition, source):
    board, user = inputs(section, definition)
    if source != "board":
        user["_profile_parsed"] = copy.deepcopy(board)
        del board["thermistor g2"]
    if source == "resume":
        user = json.loads(json.dumps(persistable_wizard_data(user)))
    original = copy.deepcopy((board, user))
    text = render(tmp_path, board, user)
    assert parse_config(text)["thermistor g2"] == definition
    assert text.index("[thermistor G2]") < text.index("[extruder]")
    assert (board, user) == original
    plan = build_managed_config_plan(text.encode(), None, {"printer.cfg": text.encode()})
    assert validate_configuration_plan(plan).valid
    assert parse_config(effective_hardware_text(plan))["thermistor g2"] == definition
    remote = {a.remote_name: a.content for a in plan.artifacts}
    assert not build_managed_config_plan(text.encode(), None, remote).changed_artifacts


def test_unselected_curve_is_not_emitted_or_validated(tmp_path):
    board = _parsed()
    board["thermistor unused"] = {"broken": "value"}
    assert "[thermistor unused]" not in render(tmp_path, board, _user())


def test_shared_definition_emitted_once(tmp_path):
    board, user = inputs()
    user["bed_thermistor"] = "G2"
    assert render(tmp_path, board, user).count("[thermistor G2]") == 1


def test_conflicting_profile_curve_blocks_generation(tmp_path):
    board, user = inputs()
    user["_profile_parsed"] = copy.deepcopy(board)
    user["_profile_parsed"]["thermistor g2"]["resistance1"] = "100000"
    with pytest.raises(GenerationError, match="conflicting.*G2"):
        render(tmp_path, board, user)
    assert not (tmp_path / "printer.cfg").exists()


def test_identical_profile_curve_is_unambiguous(tmp_path):
    board, user = inputs()
    user["_profile_parsed"] = copy.deepcopy(board)
    assert render(tmp_path, board, user).count("[thermistor G2]") == 1


@pytest.mark.parametrize("value", (None, "invalid", []))
def test_invalid_definition_container_cannot_be_ignored(tmp_path, value):
    board, user = inputs()
    board["thermistor g2"] = value
    with pytest.raises(GenerationError, match="invalid custom thermistor"):
        render(tmp_path, board, user)


def test_reconciliation_cannot_mix_beta_and_three_point_curves(tmp_path):
    board, user = inputs()
    text = render(tmp_path, board, user)
    previous = text.replace("temperature2: 195", "beta: 3950\ntemperature2: 195")
    plan = build_managed_config_plan(text.encode(), None, {"printer.cfg": previous.encode()})
    result = validate_configuration_plan(plan)
    assert not result.valid
    assert any(error.code == "custom-thermistor" for error in result.errors)


@pytest.mark.parametrize("changes,reason", BAD)
def test_invalid_curve_rejected_before_output(tmp_path, changes, reason):
    definition = {} if not changes else {**G2, **changes}
    if definition.get("resistance3", "present") is None:
        del definition["resistance3"]
    board, user = inputs(definition=definition)
    with pytest.raises(GenerationError, match=reason):
        render(tmp_path, board, user)
    assert not (tmp_path / "printer.cfg").exists()


@pytest.mark.parametrize("beta", ("0", "-1", "nan", "inf", "bad"))
def test_invalid_beta_is_rejected(tmp_path, beta):
    board, user = inputs(definition={**BETA, "beta": beta})
    with pytest.raises(GenerationError, match="beta"):
        render(tmp_path, board, user)


@pytest.mark.parametrize("noop", (False, True))
def test_invalid_definition_in_preserved_include_blocks_transaction(tmp_path, noop):
    remote = remote_files("[thermistor G2]\ntemperature1: 25\nresistance1: 100000\nbeta: 0\n")
    if noop:
        plan = build_managed_config_plan(GENERATED, None, remote)
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        assert not build_managed_config_plan(GENERATED, None, remote).changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, GENERATED, None, activation="none", confirm=confirm,
        snapshot_root=str(tmp_path / "snapshots"), verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "beta" in result.detail
    confirm.assert_not_called()
    assert transport.files == remote
