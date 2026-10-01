"""Explicit sense resistors must survive validation without inventing a circuit."""
import json
from unittest.mock import Mock, patch

import pytest

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.exceptions import GenerationError
from core.generator import generate_config
from core.managed_config import build_managed_config_plan
from core.profile_values import resolve_tmc_sections
from tests.unit.test_config_transaction import FakeTransport, GENERATED
from tests.unit.test_tmc_electrical_authority import inputs
from tests.unit.test_tmc_uart_review import remote_files


MODELS = ("tmc2208", "tmc2209", "tmc2130", "tmc5160")
INVALID = ("", "bad", "0", "-0.1", "nan", "inf", "-inf", "1e999")


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("value", INVALID)
def test_selected_board_rejects_invalid_resistor(model, value):
    board, _, user, section = inputs(model)
    board[section]["sense_resistor"] = value
    with pytest.raises(GenerationError, match="sense_resistor"):
        resolve_tmc_sections(board, user)


@pytest.mark.parametrize("target", ("x", "y", "z", "z1", "z2", "z3", "e"))
@pytest.mark.parametrize("model", MODELS)
def test_invalid_resistor_is_checked_on_every_selected_motor(model, target):
    board, _, user, section = inputs(model, target)
    board[section]["sense_resistor"] = "nan"
    with pytest.raises(GenerationError, match="sense_resistor"):
        resolve_tmc_sections(board, user)


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("value", (None, "0.150", "1e-2"))
def test_generation_preserves_value_or_records_omission(tmp_path, model, value):
    board, _, user, section = inputs(model)
    user["z_motors"] = "1"
    if value is None:
        del board[section]["sense_resistor"]
    else:
        board[section]["sense_resistor"] = value
    output = tmp_path / "printer.cfg"
    generate_config(board, user, output_path=str(output), verbose=False)
    trace = json.loads(output.with_suffix(".cfg.provenance.json").read_text())["sources"]["tmc_options"][section]
    if value is None:
        assert "sense_resistor" not in trace["options"]
        assert "sense_resistor" in trace["omitted_options"]
        assert "sense_resistor:" not in output.read_text(encoding="utf-8")
    else:
        assert trace["options"]["sense_resistor"] == {"value": value, "origin": "SELECTED_BOARD", "input_value": value}
        assert "sense_resistor" not in trace["omitted_options"]


@pytest.mark.parametrize("model", MODELS)
def test_invalid_resistor_cannot_overwrite_existing_generated_files(tmp_path, model):
    board, _, user, section = inputs(model)
    user["z_motors"] = "1"
    output = tmp_path / "printer.cfg"
    generate_config(board, user, output_path=str(output), verbose=False)
    before = {p: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    board[section]["sense_resistor"] = "0"
    with pytest.raises(GenerationError, match="sense_resistor"):
        generate_config(board, user, output_path=str(output), verbose=False)
    assert {p: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()} == before


def test_final_render_is_checked_independently_of_selected_sections(tmp_path):
    from tests.unit.test_generator import _parsed, _user
    output = tmp_path / "printer.cfg"
    board = _parsed()
    # A renderer can introduce a section absent from the selected board map.
    from jinja2 import Template
    render = Template.render
    def inject(template, *args, **kwargs):
        return render(template, *args, **kwargs) + "\n[tmc5160 stepper_x]\nsense_resistor: nan\n"
    with patch.object(Template, "render", inject), pytest.raises(GenerationError, match="sense_resistor"):
        generate_config(board, _user(), output_path=str(output), verbose=False)
    assert not output.exists()


def extra_config(model, value):
    pin = "uart_pin" if model in ("tmc2208", "tmc2209") else "cs_pin"
    return f"[{model} stepper_x]\n{pin}: PC11\nrun_current: 0.580\nsense_resistor: {value}\n"


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("value", INVALID)
def test_review_rejects_invalid_resistor_in_nested_destination_include(model, value):
    plan = build_managed_config_plan(GENERATED, None, remote_files(extra_config(model, value)))
    validation = validate_configuration_plan(plan)
    assert any(e.code == "tmc-sense-resistor" for e in validation.errors), validation


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("noop", (False, True))
def test_transaction_rejects_invalid_resistor_before_confirmation_or_writes(tmp_path, model, noop):
    remote = remote_files(extra_config(model, "0"))
    if noop:
        initial = build_managed_config_plan(GENERATED, None, remote)
        remote.update({a.remote_name: a.content for a in initial.artifacts})
        assert not build_managed_config_plan(GENERATED, None, remote).changed_artifacts
    transport = FakeTransport(remote)
    confirm = Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, GENERATED, None, activation="none", confirm=confirm,
        snapshot_root=str(tmp_path / "snapshots"), verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "sense_resistor" in result.detail
    confirm.assert_not_called()
    assert transport.files == remote
    assert not any(c[0] in ("upload", "delete", "restart") for c in transport.calls)


@pytest.mark.parametrize("model", MODELS)
def test_valid_preserved_resistor_can_publish_without_restart(tmp_path, model):
    transport = FakeTransport(remote_files(extra_config(model, "0.150")))
    result = ConfigDeploymentTransaction(transport, GENERATED, None, activation="none",
        snapshot_root=str(tmp_path / "snapshots")).run()
    assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION


def test_similarly_named_macro_option_is_not_a_driver():
    plan = build_managed_config_plan(GENERATED, None, remote_files(
        "[gcode_macro TMC]\nvariable_sense_resistor: 0\ngcode:\n  M118 example\n"))
    assert not any(e.code == "tmc-sense-resistor" for e in validate_configuration_plan(plan).errors)


def test_tmc2225_alias_uses_2208_resistor_validation():
    board, _, user, section = inputs("tmc2208")
    user["driver_type"] = "TMC2225"
    board[section]["sense_resistor"] = "nan"
    with pytest.raises(GenerationError, match="sense_resistor"):
        resolve_tmc_sections(board, user)
