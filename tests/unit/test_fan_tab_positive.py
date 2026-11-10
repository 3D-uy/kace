"""Positive controls for fan names and options with a tab separator."""
import pytest
from core.config_sections import section_identity
from core.part_fan import validate_part_fan_options
from core.fan_auxiliary import validate_fan_auxiliary
from core.fan_consumers import validate_fan_consumers
from core.controller_fan_references import validate_controller_fan_references
from core.managed_config import _section_options

@pytest.mark.parametrize('kind',['fan_generic','heater_fan','controller_fan','temperature_fan'])
def test_valid_common_options_and_case_identity(kind):
    name=kind+'\tAudit'
    validate_part_fan_options({name:{'max_power':'1','cycle_time':'0.010'}})
    validate_fan_auxiliary({name:{'enable_pin':'!PA1'}})
    assert section_identity(name)==name
    assert section_identity(kind+'\taudit')!=name

def test_valid_controller_options_and_empty_list():
    sections={'controller_fan\tAudit':{'fan_speed':'0.5','heater':''}}
    validate_fan_consumers(sections)
    validate_controller_fan_references(sections)

def test_ownership_keeps_two_case_distinct_tab_sections():
    sections=_section_options('[controller_fan\tAudit]\nfan_speed: 0.2\n[controller_fan\taudit]\nfan_speed: 0.8\n')
    assert sections['controller_fan\tAudit']['fan_speed']=='0.2'
    assert sections['controller_fan\taudit']['fan_speed']=='0.8'
