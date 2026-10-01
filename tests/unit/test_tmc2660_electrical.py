"""Electrical requirements of externally preserved TMC2660 sections."""
from unittest.mock import Mock, patch

import pytest

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.exceptions import GenerationError
from core.generator import generate_config
from core.managed_config import build_managed_config_plan
from core.profile_values import resolve_tmc_sections
from tests.unit.test_config_transaction import FakeTransport, GENERATED
from tests.unit.test_generator import _parsed, _user
from tests.unit.test_tmc_uart_review import remote_files


CASES = [
    ("valid", {}, True),
    ("missing-current", {"run_current": None}, False),
    ("missing-resistor", {"sense_resistor": None}, False),
    ("minimum-current", {"run_current": "0.1"}, True),
    ("maximum-current", {"run_current": "2.4"}, True),
    ("below-current", {"run_current": "0.099"}, False),
    ("above-current", {"run_current": "2.401"}, False),
    ("zero-current", {"run_current": "0"}, False),
    ("nan-current", {"run_current": "nan"}, False),
    ("infinite-current", {"run_current": "inf"}, False),
    ("empty-current", {"run_current": ""}, False),
    ("zero-resistor", {"sense_resistor": "0"}, False),
    ("negative-resistor", {"sense_resistor": "-0.1"}, False),
    ("nan-resistor", {"sense_resistor": "nan"}, False),
    ("infinite-resistor", {"sense_resistor": "inf"}, False),
    ("empty-resistor", {"sense_resistor": ""}, False),
    ("explicit-resistor", {"sense_resistor": ".051"}, True),
    ("idle-zero", {"idle_current_percent": "0"}, True),
    ("idle-half", {"idle_current_percent": "50"}, True),
    ("idle-full", {"idle_current_percent": "100"}, True),
    ("idle-negative", {"idle_current_percent": "-1"}, False),
    ("idle-excess", {"idle_current_percent": "101"}, False),
    ("idle-float", {"idle_current_percent": "50.0"}, False),
    ("idle-empty", {"idle_current_percent": ""}, False),
    ("idle-nan", {"idle_current_percent": "nan"}, False),
    ("foreign-hold", {"hold_current": ".2"}, False),
    ("foreign-stealth", {"stealthchop_threshold": "0"}, False),
    ("foreign-coolstep", {"coolstep_threshold": "10"}, False),
    ("foreign-high-velocity", {"high_velocity_threshold": "100"}, False),
]


def options_for(changes=None):
    options = {"run_current": ".580", "sense_resistor": ".100", **(changes or {})}
    return {key: value for key, value in options.items() if value is not None}


def config_for(changes=None):
    return "[tmc2660 stepper_x]\ncs_pin: PC11\n" + "\n".join(f"{key}: {value}" for key, value in options_for(changes).items()) + "\n"


@pytest.mark.parametrize("case,changes,valid", CASES)
def test_effective_electrical_contract(case, changes, valid):
    result = validate_configuration_plan(build_managed_config_plan(GENERATED, None, remote_files(config_for(changes))))
    assert result.valid == valid, result
    if not valid:
        assert any("tmc2660" in error.message for error in result.errors)


@pytest.mark.parametrize("noop", (False, True))
def test_missing_resistor_blocks_before_publication(tmp_path, noop):
    remote = remote_files(config_for({"sense_resistor": None}))
    if noop:
        plan = build_managed_config_plan(GENERATED, None, remote)
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        assert not build_managed_config_plan(GENERATED, None, remote).changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, GENERATED, None, activation="none", confirm=confirm,
        snapshot_root=str(tmp_path / "snapshots"), verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "sense_resistor" in result.detail
    confirm.assert_not_called()
    assert transport.files == remote
    assert not any(call[0] in ("upload", "delete", "restart") for call in transport.calls)


def test_include_supplies_resistor_without_default():
    remote = remote_files(config_for({"sense_resistor": None}) + "[include resistance.cfg]\n")
    remote["resistance.cfg"] = b"[tmc2660 stepper_x]\nsense_resistor: .051\n"
    assert validate_configuration_plan(build_managed_config_plan(GENERATED, None, remote)).valid


def test_preserves_valid_external_values():
    remote = remote_files(config_for({"run_current": "2.4", "sense_resistor": ".051", "idle_current_percent": "0"}))
    plan = build_managed_config_plan(GENERATED, None, remote)
    assert validate_configuration_plan(plan).valid
    from core.managed_config import effective_hardware_text
    text = effective_hardware_text(plan)
    for line in ("run_current: 2.4", "sense_resistor: .051", "idle_current_percent: 0"):
        assert line in text


def test_render_cannot_inject_missing_resistor(tmp_path):
    from jinja2 import Template
    render = Template.render
    def inject(template, *args, **kwargs):
        return render(template, *args, **kwargs) + config_for({"sense_resistor": None})
    output = tmp_path / "printer.cfg"
    with patch.object(Template, "render", inject), pytest.raises(GenerationError, match="sense_resistor"):
        generate_config(_parsed(), _user(), output_path=str(output), verbose=False)
    assert not output.exists()


def test_does_not_add_tmc2660_to_guided_generation():
    with pytest.raises(GenerationError, match="Unsupported TMC model"):
        resolve_tmc_sections({}, _user(driver_type="TMC2660", driver_mode="SPI"))
