from unittest.mock import Mock
import pytest
from core.config_transaction import ConfigDeploymentTransaction,ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.managed_config import build_managed_config_plan
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_effective_xy_geometry import _generate,_context,_assert_no_destination_mutations
PROVIDER='[sx1509 Expander]\ni2c_address: 62\ni2c_bus: i2c1\n'
HEADER='\n#*# <---------------------- SAVE_CONFIG ---------------------->\n#*# DO NOT EDIT THIS BLOCK OR BELOW. The contents are auto-generated.\n#*#\n'
@pytest.mark.parametrize('source',['root','include','save'])
@pytest.mark.parametrize('noop',[False,True])
@pytest.mark.parametrize('provider',['mcu','sx1509'])
def test_tabbed_fan_bad_provider_blocks_before_write(tmp_path,source,noop,provider):
    base=_generate(tmp_path);ctx=_context(tmp_path,base)
    pin='PG10' if provider=='mcu' else 'sx1509_Expander:PIN_0'
    option='shutdown_speed: .5\n' if provider=='mcu' else 'hardware_pwm: false\n'
    section='[fan_generic\tAudit]\npin: '+pin+'\n'
    prefix=PROVIDER if provider=='sx1509' else ''
    if source=='root': remote={'printer.cfg':base+b'\n'+(prefix+section+option).encode()}
    elif source=='include':remote={'printer.cfg':base+b'\n[include user.cfg]\n','user.cfg':(prefix+section+option).encode()}
    else:remote={'printer.cfg':base+b'\n'+(prefix+section).encode()+HEADER.encode()+('#*# [fan_generic\tAudit]\n#*# '+option.replace(': ',' = ')).encode()}
    plan=build_managed_config_plan(base,None,remote,geometry_context=ctx)
    if noop:
        remote.update({a.remote_name:a.content for a in plan.artifacts});plan=build_managed_config_plan(base,None,remote,geometry_context=ctx)
        assert not plan.changed_artifacts
    review=validate_configuration_plan(plan)
    assert not review.valid and any(e.code==('pwm-output' if provider=='mcu' else 'sx1509-pwm') for e in review.errors),review.errors
    t=FakeTransport(remote);before=dict(t.files);confirm=Mock(return_value=True)
    result=ConfigDeploymentTransaction(t,base,None,geometry_context=ctx,activation='none',confirm=confirm,output=lambda _:None,poll_interval=0,snapshot_root=str(tmp_path/'snapshots')).run()
    assert result.state==ConfigTransactionState.PRECONDITION_FAILED
    confirm.assert_not_called();_assert_no_destination_mutations(t,before)
