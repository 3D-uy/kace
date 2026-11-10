import pytest
from core.config_sections import section_identity
from core.exceptions import GenerationError
from core.part_fan import validate_part_fan_options
from core.fan_auxiliary import validate_fan_auxiliary
from core.fan_consumers import validate_fan_consumers
from core.controller_fan_references import validate_controller_fan_references

@pytest.mark.parametrize('kind',['fan_generic','heater_fan','controller_fan','temperature_fan'])
def test_common_fan_bounds(kind):
    with pytest.raises(GenerationError,match='max_power'): validate_part_fan_options({kind+'\tAudit':{'max_power':'2'}})

@pytest.mark.parametrize('kind',['fan_generic','heater_fan','controller_fan','temperature_fan'])
def test_auxiliary_pin(kind):
    with pytest.raises(GenerationError,match='enable_pin'): validate_fan_auxiliary({kind+'\tAudit':{'enable_pin':'^PA1'}})

def test_controller_bad_speed():
    with pytest.raises(GenerationError,match='fan_speed'): validate_fan_consumers({'controller_fan\tAudit':{'fan_speed':'2'}})

def test_controller_bad_list():
    with pytest.raises(GenerationError,match='empty reference'): validate_controller_fan_references({'controller_fan\tAudit':{'heater':'extruder,'}})

@pytest.mark.parametrize('kind',['fan_generic','heater_fan','controller_fan','temperature_fan'])
def test_section_identity(kind):
    assert section_identity(kind+'\tAudit') == kind+'\tAudit'
