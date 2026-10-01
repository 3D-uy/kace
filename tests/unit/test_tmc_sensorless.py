"""Native virtual endstop dependencies must hold before publication."""
from unittest.mock import Mock, patch

import pytest

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.exceptions import GenerationError
from core.generator import generate_config
from core.managed_config import build_managed_config_plan
from tests.unit.test_config_transaction import FakeTransport, GENERATED
from tests.unit.test_tmc_electrical_authority import inputs
from tests.unit.test_tmc_spi_chain import config_text
from tests.unit.test_tmc_uart_review import remote_files


def sections(model="tmc2209", diag="^PC6", reference=None, extra=None):
    options = {"run_current": ".580", "uart_pin" if model in ("tmc2208", "tmc2209") else "cs_pin": "PC11"}
    if diag is not None:
        options["diag_pin" if model in ("tmc2208", "tmc2209") else "diag1_pin"] = diag
    result = {f"{model} stepper_x": options,
              "stepper_x": {"endstop_pin": reference or f"{model}_stepper_x:virtual_endstop"}}
    result.update(extra or {})
    return result


CASES = [
    ("valid", "^PC6", None, {}, True),
    ("missing-diag", None, None, {}, False),
    ("empty-diag", "", None, {}, False),
    ("inverted-diag", "^!PC6", None, {}, True),
    ("pulldown-diag", "~PC6", None, {}, True),
    ("wrong-modifier-order", "!^PC6", None, {}, False),
    ("unknown-mcu", "tool:PC6", None, {}, False),
    ("secondary-mcu", "^tool:PC6", None, {"mcu tool": {"serial": "/dev/tool"}}, True),
    ("pullup-virtual", "PC6", "^{model}_stepper_x:virtual_endstop", {}, False),
    ("invert-virtual", "PC6", "!{model}_stepper_x:virtual_endstop", {}, False),
    ("pulldown-virtual", "PC6", "~{model}_stepper_x:virtual_endstop", {}, False),
    ("wrong-virtual-name", "PC6", "{model}_stepper_x:other", {}, False),
    ("missing-driver", "PC6", "{model}_stepper_y:virtual_endstop", {}, False),
    ("fan-conflict", "PC6", None, {"fan": {"pin": "PC6"}}, False),
    ("physical-endstop-conflict", "PC6", None, {"stepper_y": {"endstop_pin": "PC6"}}, False),
    ("alias-conflict", "STOP", None, {"board_pins aliases": {"aliases": "STOP=PC6"}, "fan": {"pin": "PC6"}}, False),
    ("inactive-diag", "unparsed pin!", "PB0", {}, True),
]


@pytest.mark.parametrize("model", ("tmc2209", "tmc2130", "tmc5160"))
@pytest.mark.parametrize("case,diag,reference,extra,valid", CASES)
def test_effective_sensorless_contract(model, case, diag, reference, extra, valid):
    data = sections(model, diag, reference.format(model=model) if reference else None, extra)
    result = validate_configuration_plan(build_managed_config_plan(GENERATED, None, remote_files(config_text(data))))
    assert result.valid == valid, result


@pytest.mark.parametrize("model", ("tmc2130", "tmc5160"))
def test_both_diag_options_are_not_consumed(model):
    data = sections(model)
    data[f"{model} stepper_x"]["diag0_pin"] = "PC7"
    result = validate_configuration_plan(build_managed_config_plan(GENERATED, None, remote_files(config_text(data))))
    assert not result.valid
    assert any("diag1_pin" in error.message for error in result.errors)


def test_2208_does_not_register_sensorless_chip():
    result = validate_configuration_plan(build_managed_config_plan(GENERATED, None, remote_files(config_text(sections("tmc2208", None)))))
    assert not result.valid


@pytest.mark.parametrize("model", ("tmc2209", "tmc2130", "tmc5160"))
@pytest.mark.parametrize("consumer,field,valid", [("stepper_x1", "endstop_pin", True),
    ("stepper_y", "endstop_pin", False), ("output_pin invalid", "pin", False)])
def test_virtual_reference_sharing_and_role(model, consumer, field, valid):
    from core.tmc_sensorless import validate_tmc_virtual_endstops
    data = sections(model, extra={consumer: {field: f"{model}_stepper_x:virtual_endstop"}})
    if valid:
        validate_tmc_virtual_endstops(data)
    else:
        with pytest.raises(GenerationError):
            validate_tmc_virtual_endstops(data)


@pytest.mark.parametrize("model", ("tmc2130", "tmc5160"))
def test_diag0_is_a_valid_alternative(model):
    from core.tmc_sensorless import validate_tmc_virtual_endstops
    data = sections(model)
    options = data[f"{model} stepper_x"]
    options["diag0_pin"] = options.pop("diag1_pin")
    validate_tmc_virtual_endstops(data)


@pytest.mark.parametrize("model", ("tmc2209", "tmc2130", "tmc5160"))
@pytest.mark.parametrize("shared", (False, True))
def test_two_active_diag_pins_must_be_distinct(model, shared):
    from core.tmc_sensorless import validate_tmc_virtual_endstops
    data = sections(model, "PC6")
    option = "diag_pin" if model == "tmc2209" else "diag1_pin"
    data[f"{model} stepper_y"] = {option: "PC6" if shared else "PC7"}
    data["stepper_y"] = {"endstop_pin": f"{model}_stepper_y:virtual_endstop"}
    if shared:
        with pytest.raises(GenerationError, match="DIAG conflicts"):
            validate_tmc_virtual_endstops(data)
    else:
        validate_tmc_virtual_endstops(data)


@pytest.mark.parametrize("noop", (False, True))
def test_missing_diag_blocks_before_publication(tmp_path, noop):
    remote = remote_files(config_text(sections(diag=None)))
    if noop:
        plan = build_managed_config_plan(GENERATED, None, remote)
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        assert not build_managed_config_plan(GENERATED, None, remote).changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, GENERATED, None, activation="none", confirm=confirm,
        snapshot_root=str(tmp_path / "snapshots"), verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "DIAG" in result.detail
    confirm.assert_not_called()
    assert transport.files == remote
    assert not any(call[0] in ("upload", "delete", "restart") for call in transport.calls)


def test_final_render_requires_diag(tmp_path):
    from jinja2 import Template
    render = Template.render
    board, _, user, name = inputs()
    user["z_motors"] = "1"
    board[name]["diag_pin"] = "^PC6"
    board["stepper_x"]["endstop_pin"] = "tmc2209_stepper_x:virtual_endstop"
    def inject(template, *args, **kwargs):
        return render(template, *args, **kwargs).replace("diag_pin: ^PC6", "# removed DIAG: ^PC6")
    output = tmp_path / "printer.cfg"
    with patch.object(Template, "render", inject), pytest.raises(GenerationError, match="DIAG"):
        generate_config(board, user, output_path=str(output), verbose=False)
    assert not output.exists()
