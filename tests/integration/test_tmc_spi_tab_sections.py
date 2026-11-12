"""Duplicate SPI chain positions block publication for tabbed sections."""
from unittest.mock import Mock
import pytest
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.managed_config import build_managed_config_plan
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_effective_xy_geometry import _generate, _context, _assert_no_destination_mutations

def initial_sections():
    return ('\n[tmc2130\tstepper_x]\ncs_pin: PG13\nrun_current: .580\nchain_length: 2\nchain_position: 1\n'
            '[tmc2130\tstepper_y]\ncs_pin: PG13\nrun_current: .580\nchain_length: 2\n')

@pytest.mark.parametrize('source',['root','include','save'])
@pytest.mark.parametrize('noop',[False,True])
def test_duplicate_position_blocks_before_confirmation_and_write(tmp_path,source,noop):
    base=_generate(tmp_path);ctx=_context(tmp_path,base); body=initial_sections().encode()
    if source=='root':remote={'printer.cfg':base+body+b'chain_position: 1\n'}
    elif source=='include':remote={'printer.cfg':base+b'\n[include user.cfg]\n','user.cfg':body+b'chain_position: 1\n'}
    else:remote={'printer.cfg':base+body+b'\n#*# <---------------------- SAVE_CONFIG ---------------------->\n#*# DO NOT EDIT THIS BLOCK OR BELOW. The contents are auto-generated.\n#*#\n#*# [tmc2130\tstepper_y]\n#*# chain_position = 1\n'}
    plan=build_managed_config_plan(base,None,remote,geometry_context=ctx)
    if noop:
        remote.update({a.remote_name:a.content for a in plan.artifacts})
        plan=build_managed_config_plan(base,None,remote,geometry_context=ctx)
        assert not plan.changed_artifacts
    review=validate_configuration_plan(plan)
    assert not review.valid and any('chain_position' in e.message for e in review.errors),review.errors
    t=FakeTransport(remote);before=dict(t.files);confirm=Mock(return_value=True)
    result=ConfigDeploymentTransaction(t,base,None,geometry_context=ctx,activation='none',confirm=confirm,output=lambda _:None,poll_interval=0,snapshot_root=str(tmp_path/'snapshots')).run()
    assert result.state==ConfigTransactionState.PRECONDITION_FAILED
    confirm.assert_not_called();_assert_no_destination_mutations(t,before)
