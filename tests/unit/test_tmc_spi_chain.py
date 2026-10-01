"""Shared-CS identity and ownership follow effective configuration order."""
from unittest.mock import Mock, patch

import pytest

from core.configuration_review import validate_configuration_plan
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.exceptions import GenerationError
from core.generator import generate_config
from core.managed_config import build_managed_config_plan
from tests.unit.test_config_transaction import FakeTransport, GENERATED
from tests.unit.test_tmc_uart_review import remote_files


CASES = [
    ("valid-chain", {}, True),
    ("duplicate-position", {"second": {"chain_position": "1"}}, False),
    ("different-length", {"second": {"chain_length": "3"}}, False),
    ("qualified-cs", {"second": {"cs_pin": "mcu:PC11"}}, True),
    ("mixed-model", {"model_y": "tmc5160"}, True),
    ("mixed-model-duplicate", {"model_y": "tmc5160", "second": {"chain_position": "1"}}, False),
    ("independent-cs", {"second": {"cs_pin": "PC12", "chain_position": "1"}}, True),
    ("independent-mcu", {"second": {"cs_pin": "tool:PC11", "chain_position": "1"}, "extra": {"mcu tool": {"serial": "/dev/tool"}}}, True),
    ("unknown-mcu", {"second": {"cs_pin": "missing:PC11"}}, False),
    ("inverted-cs", {"second": {"cs_pin": "!PC11"}}, False),
    ("pullup-cs", {"second": {"cs_pin": "^PC11"}}, False),
    ("alias-shared", {"first": {"cs_pin": "CS"}, "second": {"cs_pin": "CS"}, "extra": {"board_pins aliases": {"aliases": "CS=PC11"}}}, True),
    ("alias-mixed", {"second": {"cs_pin": "CS"}, "extra": {"board_pins aliases": {"aliases": "CS=PC11"}}}, False),
    ("alias-reserved", {"second": {"cs_pin": "CS"}, "extra": {"board_pins aliases": {"aliases": "CS=<reserved>"}}}, False),
    ("first-speed", {"first": {"spi_speed": "1000000"}}, True),
    ("later-speed", {"second": {"spi_speed": "1000000"}}, False),
    ("same-speed-repeated", {"first": {"spi_speed": "1000000"}, "second": {"spi_speed": "1000000"}}, False),
    ("first-bus", {"first": {"spi_bus": "spi1"}}, True),
    ("later-bus", {"second": {"spi_bus": "spi1"}}, False),
    ("later-software", {"second": {"spi_software_sclk_pin": "PB13", "spi_software_mosi_pin": "PB15", "spi_software_miso_pin": "PB14"}}, False),
    ("first-unchained", {"first": {"chain_length": None, "chain_position": None}}, False),
    ("second-unchained", {"second": {"chain_length": None, "chain_position": None}}, False),
    ("both-unchained", {"first": {"chain_length": None, "chain_position": None}, "second": {"chain_length": None, "chain_position": None}}, False),
    ("separate-unchained", {"first": {"chain_length": None, "chain_position": None}, "second": {"cs_pin": "PC12", "chain_length": None, "chain_position": None}}, True),
    ("no-cs-unchained", {"first": {"cs_pin": "None", "chain_length": None, "chain_position": None}, "second": {"cs_pin": "None", "chain_length": None, "chain_position": None}}, True),
    ("reversed-owner", {"first": {"spi_speed": "1000000"}, "reverse": True}, False),
]


def case_sections(changes, model="tmc2130"):
    result = dict(changes.get("extra", {}))
    pair = []
    for index, key in enumerate(("first", "second")):
        options = {"cs_pin": "PC11", "run_current": "0.580", "chain_length": "2", "chain_position": str(index + 1)}
        for field, value in changes.get(key, {}).items():
            if value is None:
                options.pop(field, None)
            else:
                options[field] = value
        name = f"{model if index == 0 else changes.get('model_y', model)} stepper_{'x' if index == 0 else 'y'}"
        pair.append((name, options))
    result.update(reversed(pair) if changes.get("reverse") else pair)
    return result


def config_text(sections):
    return "".join(f"[{name}]\n" + "".join(f"{key}: {value}\n" for key, value in options.items()) for name, options in sections.items())


@pytest.mark.parametrize("model", ("tmc2130", "tmc5160"))
@pytest.mark.parametrize("name,changes,valid", CASES, ids=[c[0] for c in CASES])
def test_effective_chain_contract(model, name, changes, valid):
    plan = build_managed_config_plan(GENERATED, None, remote_files(config_text(case_sections(changes, model))))
    result = validate_configuration_plan(plan)
    assert result.valid == valid, result
    if not valid:
        assert any(e.code == "tmc-spi-chain" for e in result.errors)


@pytest.mark.parametrize("noop", (False, True))
@pytest.mark.parametrize("changes", ({"second": {"chain_position": "1"}}, {"second": {"chain_length": "3"}}, {"second": {"spi_speed": "1000000"}}))
def test_chain_errors_block_before_confirmation_and_writes(tmp_path, noop, changes):
    remote = remote_files(config_text(case_sections(changes)))
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
    assert not any(call[0] in ("upload", "delete", "restart") for call in transport.calls)


def test_final_render_catches_conflict_before_writing(tmp_path):
    from jinja2 import Template
    from tests.unit.test_generator import _parsed, _user
    render = Template.render
    def inject(template, *args, **kwargs):
        return render(template, *args, **kwargs) + "\n" + config_text(case_sections({"second": {"chain_position": "1"}}))
    output = tmp_path / "printer.cfg"
    with patch.object(Template, "render", inject), pytest.raises(GenerationError, match="SPI"):
        generate_config(_parsed(), _user(), output_path=str(output), verbose=False)
    assert not output.exists()


@pytest.mark.parametrize("position", ("1", "2"))
def test_later_include_defines_effective_position(position):
    remote = remote_files(config_text(case_sections({})) + "[include override.cfg]\n")
    remote["override.cfg"] = f"[tmc2130 stepper_y]\nchain_position: {position}\n".encode()
    result = validate_configuration_plan(build_managed_config_plan(GENERATED, None, remote))
    assert result.valid == (position == "2")


def test_valid_chain_publishes_without_restart(tmp_path):
    transport = FakeTransport(remote_files(config_text(case_sections({"first": {"spi_speed": "1000000"}}))))
    result = ConfigDeploymentTransaction(transport, GENERATED, None, activation="none",
        snapshot_root=str(tmp_path / "snapshots")).run()
    assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION


@pytest.mark.parametrize("model", ("tmc2130", "tmc5160"))
def test_generated_chain_preserves_one_transport_owner(tmp_path, model):
    from tests.unit.test_tmc_electrical_authority import inputs
    from core.pin_validator import _read_pin_config
    board, _, user, section = inputs(model)
    user["z_motors"] = "1"
    board[section].update(chain_length="2", chain_position="1", spi_speed="1000000",
                          spi_software_sclk_pin="PB13", spi_software_mosi_pin="PB15", spi_software_miso_pin="PB14")
    second = f"{model} stepper_y"
    board[second] = {"cs_pin": "PC11", "run_current": "0.580", "chain_length": "2", "chain_position": "2"}
    output = tmp_path / "printer.cfg"
    actual = _read_pin_config(generate_config(board, user, output_path=str(output), verbose=False)["content"])[0]
    assert actual[section]["spi_speed"] == "1000000"
    assert "spi_speed" not in actual[second]
    assert actual[second]["chain_position"] == "2"
