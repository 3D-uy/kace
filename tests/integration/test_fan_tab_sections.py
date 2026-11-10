from unittest.mock import Mock
import pytest
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.managed_config import build_managed_config_plan
from tests.integration.test_heater_options_contract import destination
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_effective_xy_geometry import _generate, _context, _assert_no_destination_mutations
SECTION='controller_fan\tAudit'
EXTRA=f'\n[{SECTION}]\npin: PG10\n'
@pytest.mark.parametrize('source',['root','include','save'])
@pytest.mark.parametrize('noop',[False,True])
def test_invalid_speed_rejected(tmp_path,source,noop):
    base=_generate(tmp_path); ctx=_context(tmp_path,base)
    remote=destination(base+EXTRA.encode(),SECTION,'fan_speed','2',source)
    plan=build_managed_config_plan(base,None,remote,geometry_context=ctx)
    if noop:
        remote.update({a.remote_name:a.content for a in plan.artifacts})
        plan=build_managed_config_plan(base,None,remote,geometry_context=ctx)
        assert not plan.changed_artifacts
    review=validate_configuration_plan(plan)
    assert not review.valid and any('fan_speed' in e.message for e in review.errors)
    t=FakeTransport(remote); before=dict(t.files); confirm=Mock(return_value=True)
    result=ConfigDeploymentTransaction(t,base,None,geometry_context=ctx,activation='none',confirm=confirm,output=lambda _:None,poll_interval=0,snapshot_root=str(tmp_path/'snapshots')).run()
    assert result.state==ConfigTransactionState.PRECONDITION_FAILED
    confirm.assert_not_called(); _assert_no_destination_mutations(t,before)
