"""Required peripheral auxiliary pins must survive rendering and includes."""
from unittest.mock import Mock, patch

import pytest

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.exceptions import GenerationError
from core.generator import generate_config
from core.managed_config import build_managed_config_plan
from core.tmc_spi import validate_spi_config
from tests.unit.test_config_transaction import FakeTransport, GENERATED
from tests.unit.test_generator import _parsed, _user
from tests.unit.test_tmc_spi_auxiliary import AUXILIARIES, auxiliary_sections
from tests.unit.test_tmc_spi_chain import config_text
from tests.unit.test_tmc_uart_review import remote_files


REQUIRED = [(section, options, field) for section, options, field in AUXILIARIES
            if field not in ("rst_pin", "reset_pin")]


@pytest.mark.parametrize("model", ("tmc2130", "tmc5160"))
@pytest.mark.parametrize("section,options,field", REQUIRED)
@pytest.mark.parametrize("present", (False, True))
def test_required_auxiliary_presence(model, section, options, field, present):
    sections = auxiliary_sections(section, options, field, "PC8", model)
    if not present:
        del sections[section][field]
        with pytest.raises(GenerationError, match=field):
            validate_spi_config(config_text(sections))
    else:
        validate_spi_config(config_text(sections))


@pytest.mark.parametrize("lcd,required,optional", (("uc1701", "a0_pin", "rst_pin"),
    ("ssd1306", "dc_pin", "reset_pin"), ("sh1106", "dc_pin", "reset_pin")))
@pytest.mark.parametrize("present", (False, True))
def test_reset_stays_optional(lcd, required, optional, present):
    sections = auxiliary_sections("display", {"lcd_type": lcd}, required, "PC8")
    if present:
        sections["display"][optional] = "PC9"
    validate_spi_config(config_text(sections))


@pytest.mark.parametrize("noop", (False, True))
def test_missing_included_auxiliary_blocks_before_writes(tmp_path, noop):
    sections = auxiliary_sections("display", {"lcd_type": "uc1701"}, "a0_pin", "PC8")
    del sections["display"]["a0_pin"]
    remote = remote_files(config_text(sections))
    if noop:
        plan = build_managed_config_plan(GENERATED, None, remote)
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        assert not build_managed_config_plan(GENERATED, None, remote).changed_artifacts
    transport = FakeTransport(remote)
    confirm = Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, GENERATED, None, activation="none", confirm=confirm,
        snapshot_root=str(tmp_path / "snapshots"), verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "a0_pin" in result.detail
    confirm.assert_not_called()
    assert transport.files == remote
    assert not any(call[0] in ("upload", "delete", "restart") for call in transport.calls)


def test_include_can_supply_required_auxiliary():
    sections = auxiliary_sections("display", {"lcd_type": "uc1701"}, "a0_pin", "PC8")
    del sections["display"]["a0_pin"]
    remote = remote_files(config_text(sections) + "[include pins.cfg]\n")
    remote["pins.cfg"] = b"[display]\na0_pin: PC8\n"
    result = validate_configuration_plan(build_managed_config_plan(GENERATED, None, remote))
    assert result.valid, result


def test_final_render_cannot_omit_required_auxiliary(tmp_path):
    from jinja2 import Template
    render = Template.render
    def inject(template, *args, **kwargs):
        sections = auxiliary_sections("display", {"lcd_type": "uc1701"}, "a0_pin", "PC8")
        del sections["display"]["a0_pin"]
        return render(template, *args, **kwargs) + config_text(sections)
    output = tmp_path / "printer.cfg"
    with patch.object(Template, "render", inject), pytest.raises(GenerationError, match="a0_pin"):
        generate_config(_parsed(), _user(), output_path=str(output), verbose=False)
    assert not output.exists()
