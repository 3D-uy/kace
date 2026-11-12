"""Preserved heaters with a tab separator reach fan review correctly."""
from unittest.mock import Mock
import pytest
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.managed_config import build_managed_config_plan
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_effective_xy_geometry import _generate, _context

HEATER='[heater_generic\tAux]\nheater_pin: PG11\nsensor_type: Generic 3950\nsensor_pin: PG10\ncontrol: watermark\nmin_temp: 0\nmax_temp: 100\n'
FAN='[heater_fan Audit]\npin: PG9\nheater: Aux\n'
HEADER='\n#*# <---------------------- SAVE_CONFIG ---------------------->\n#*# DO NOT EDIT THIS BLOCK OR BELOW. The contents are auto-generated.\n#*#\n'

@pytest.mark.parametrize('source', ['root','include','save'])
@pytest.mark.parametrize('noop', [False,True])
def test_tab_heater_and_fan_survive_review_and_publication(tmp_path, source, noop):
    base=_generate(tmp_path); context=_context(tmp_path,base)
    if source=='root': remote={'printer.cfg': base+b'\n'+(HEATER+FAN).encode()}
    elif source=='include': remote={'printer.cfg':base+b'\n[include user.cfg]\n','user.cfg':b'[include nested.cfg]\n','nested.cfg':(HEATER+FAN).encode()}
    else: remote={'printer.cfg':base+b'\n'+HEATER.encode()+HEADER.encode()+b'#*# [heater_fan Audit]\n#*# pin = PG9\n#*# heater = Aux\n'}
    plan=build_managed_config_plan(base,None,remote,geometry_context=context)
    if noop:
        remote.update({a.remote_name:a.content for a in plan.artifacts})
        plan=build_managed_config_plan(base,None,remote,geometry_context=context)
        assert not plan.changed_artifacts
    review=validate_configuration_plan(plan)
    assert review.valid, review.errors
    t=FakeTransport(remote); confirm=Mock(return_value=True)
    result=ConfigDeploymentTransaction(t,base,None,geometry_context=context,activation='none',confirm=confirm,output=lambda _:None,poll_interval=0,snapshot_root=str(tmp_path/'snapshots')).run()
    assert result.state==ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    assert confirm.call_count==1
    if noop: assert not [x for x in t.calls if x[0] in ('upload','delete')]
