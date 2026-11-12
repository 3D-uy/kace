import copy
import pytest
from core.exceptions import GenerationError
from core.pwm_output import validate_pwm_outputs
from core.sx1509_pwm import validate_sx1509_pwm
FAMILIES=['fan_generic','heater_fan','controller_fan','temperature_fan']
@pytest.mark.parametrize('family',FAMILIES)
@pytest.mark.parametrize('provider',['mcu','sx1509'])
def test_tabbed_fan_rejects_provider_mismatch(family,provider):
    fields={'pin':'PA1','shutdown_speed':'.5'} if provider=='mcu' else {'pin':'sx1509_Expander:PIN_0','hardware_pwm':'false'}
    sections={'mcu':{},'sx1509 Expander':{},family+'\tAudit':fields}
    with pytest.raises(GenerationError,match='shutdown|SX1509'):
        (validate_pwm_outputs if provider=='mcu' else validate_sx1509_pwm)(sections)
@pytest.mark.parametrize('family',FAMILIES)
@pytest.mark.parametrize('provider',['mcu','sx1509'])
def test_tabbed_fan_preserves_compatible_provider(family,provider):
    fields={'pin':'PA1','shutdown_speed':'0'} if provider=='mcu' else {'pin':'sx1509_Expander:PIN_0','hardware_pwm':'true'}
    sections={'mcu':{},'sx1509 Expander':{},family+'\tAudit':fields}; original=copy.deepcopy(sections)
    (validate_pwm_outputs if provider=='mcu' else validate_sx1509_pwm)(sections)
    assert sections==original
