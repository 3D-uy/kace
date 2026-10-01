"""SPI parameter contracts, independent of cross-device chain topology."""
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


MODELS = ("tmc2130", "tmc5160")
CASES = [
    ("defaults", {}, True),
    ("minimum-speed", {"spi_speed": "100000"}, True),
    ("explicit-speed", {"spi_speed": "4000000"}, True),
    ("slow", {"spi_speed": "99999"}, False),
    ("zero-speed", {"spi_speed": "0"}, False),
    ("negative-speed", {"spi_speed": "-1"}, False),
    ("float-speed", {"spi_speed": "100000.0"}, False),
    ("exponent-speed", {"spi_speed": "1e6"}, False),
    ("empty-speed", {"spi_speed": ""}, False),
    ("nan-speed", {"spi_speed": "nan"}, False),
    ("infinite-speed", {"spi_speed": "inf"}, False),
    ("hex-speed", {"spi_speed": "0x100000"}, False),
    ("chain-first", {"chain_length": "2", "chain_position": "1"}, True),
    ("chain-last", {"chain_length": "4", "chain_position": "4"}, True),
    ("position-only", {"chain_position": "1"}, False),
    ("position-missing", {"chain_length": "2"}, False),
    ("chain-one", {"chain_length": "1", "chain_position": "1"}, False),
    ("chain-zero", {"chain_length": "0", "chain_position": "1"}, False),
    ("chain-negative", {"chain_length": "-1", "chain_position": "1"}, False),
    ("chain-float", {"chain_length": "2.0", "chain_position": "1"}, False),
    ("chain-empty", {"chain_length": "", "chain_position": "1"}, False),
    ("position-zero", {"chain_length": "2", "chain_position": "0"}, False),
    ("position-negative", {"chain_length": "2", "chain_position": "-1"}, False),
    ("position-too-large", {"chain_length": "2", "chain_position": "3"}, False),
    ("position-float", {"chain_length": "2", "chain_position": "1.0"}, False),
    ("position-empty", {"chain_length": "2", "chain_position": ""}, False),
]


def extra(model, options, target="stepper_x"):
    settings = {"cs_pin": "PC11", "run_current": "0.580", **options}
    return f"[{model} {target}]\n" + "".join(f"{key}: {value}\n" for key, value in settings.items())


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("name,options,valid", CASES, ids=[case[0] for case in CASES])
def test_selected_spi_section(model, name, options, valid):
    board, _, user, section = inputs(model)
    board[section].update(options)
    if valid:
        selected = resolve_tmc_sections(board, user)
        assert all(selected[section][key] == value for key, value in options.items())
    else:
        with pytest.raises(GenerationError, match="SPI"):
            resolve_tmc_sections(board, user)


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("name,options,valid", CASES, ids=[case[0] for case in CASES])
def test_effective_include_spi_section(model, name, options, valid):
    plan = build_managed_config_plan(GENERATED, None, remote_files(extra(model, options)))
    result = validate_configuration_plan(plan)
    assert result.valid == valid, result
    if not valid:
        assert any(e.code == "tmc-spi-options" for e in result.errors)


@pytest.mark.parametrize("target", ("stepper_x", "stepper_y", "stepper_z", "stepper_z1", "stepper_z2", "stepper_z3", "extruder", "extruder1", "manual_stepper auxiliary"))
@pytest.mark.parametrize("model", MODELS)
def test_every_effective_target_is_checked(model, target):
    plan = build_managed_config_plan(GENERATED, None, remote_files(extra(model, {"spi_speed": "0"}, target)))
    assert any(e.code == "tmc-spi-options" for e in validate_configuration_plan(plan).errors)


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("options", ({"spi_speed": "0"}, {"chain_length": "2"}, {"chain_position": "1"}))
@pytest.mark.parametrize("noop", (False, True))
def test_rejection_precedes_confirmation_or_writes(tmp_path, model, options, noop):
    remote = remote_files(extra(model, options))
    if noop:
        plan = build_managed_config_plan(GENERATED, None, remote)
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        assert not build_managed_config_plan(GENERATED, None, remote).changed_artifacts
    transport = FakeTransport(remote)
    confirm = Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, GENERATED, None, activation="none", confirm=confirm,
        snapshot_root=str(tmp_path / "snapshots"), verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "SPI" in result.detail
    confirm.assert_not_called()
    assert transport.files == remote
    assert not any(c[0] in ("upload", "delete", "restart") for c in transport.calls)


@pytest.mark.parametrize("model", MODELS)
def test_generation_does_not_invent_spi_defaults(tmp_path, model):
    from core.pin_validator import _read_pin_config
    board, _, user, section = inputs(model)
    user["z_motors"] = "1"
    output = tmp_path / "printer.cfg"
    result = generate_config(board, user, output_path=str(output), verbose=False)
    actual = _read_pin_config(result["content"])[0][section]
    assert not any(key in actual for key in ("spi_speed", "chain_length", "chain_position"))


def test_final_render_rejects_spi_options_before_writing(tmp_path):
    from jinja2 import Template
    from tests.unit.test_generator import _parsed, _user
    render = Template.render
    def inject(template, *args, **kwargs):
        return render(template, *args, **kwargs) + "\n" + extra("tmc5160", {"spi_speed": "0"})
    output = tmp_path / "printer.cfg"
    with patch.object(Template, "render", inject), pytest.raises(GenerationError, match="SPI"):
        generate_config(_parsed(), _user(), output_path=str(output), verbose=False)
    assert not output.exists()


def test_inactive_driver_does_not_block_selection():
    board, _, user, section = inputs("tmc2130", "z3")
    user["z_motors"] = "1"
    board[section]["spi_speed"] = "0"
    assert section not in resolve_tmc_sections(board, user)


def test_macro_metadata_is_not_spi_configuration():
    plan = build_managed_config_plan(GENERATED, None, remote_files(
        "[gcode_macro SPI]\nvariable_chain_length: 0\ngcode:\n  M118 example\n"))
    assert validate_configuration_plan(plan).valid
