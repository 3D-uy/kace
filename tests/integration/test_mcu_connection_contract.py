"""Effective MCU settings reject before confirmation/publication or render writes."""
from unittest.mock import Mock
import pytest
from core.config_transaction import ConfigDeploymentTransaction,ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.exceptions import GenerationError
from core.generator import generate_config
from core.managed_config import build_managed_config_plan
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_generator import _parsed,_user
from tests.unit.test_effective_xy_geometry import _assert_no_destination_mutations


def generated(tmp_path):
    return generate_config(_parsed(),_user(),output_path=str(tmp_path/'printer.cfg'),verbose=False)['content'].encode()


BAD=[('mcu','baud','0'),('mcu aux','restart_method','invalid')]


def destination(base,source,section,option,value):
    header=f'[{section}]\n'+('serial: /dev/fixture\n' if section!='mcu' else '')
    text=(header+f'{option}: {value}\n').encode()
    if source=='include':return {'printer.cfg':base+b'\n[include user.cfg]\n','user.cfg':text}
    if source=='save':
        return {'printer.cfg':base+b'\n'+header.encode()+(
            '\n#*# <---------------------- SAVE_CONFIG ---------------------->\n'
            '#*# DO NOT EDIT THIS BLOCK OR BELOW. The contents are auto-generated.\n#*#\n'
            f'#*# [{section}]\n#*# {option} = {value}\n').encode()}
    return {'printer.cfg':base+b'\n'+text}


@pytest.mark.parametrize('section,option,value',BAD)
@pytest.mark.parametrize('source',['root','include','save'])
@pytest.mark.parametrize('noop',[False,True])
def test_bad_mcu_options_stop_before_confirmation_and_writes(tmp_path,section,option,value,source,noop):
    base=generated(tmp_path);remote=destination(base,source,section,option,value)
    plan=build_managed_config_plan(base,None,remote)
    if noop:
        remote.update({a.remote_name:a.content for a in plan.artifacts})
        plan=build_managed_config_plan(base,None,remote)
        assert not plan.changed_artifacts
    review=validate_configuration_plan(plan)
    assert not review.valid
    assert any(e.code=='mcu-connection' for e in review.errors)
    transport=FakeTransport(remote);before=dict(transport.files);confirm=Mock(return_value=True)
    result=ConfigDeploymentTransaction(transport,base,None,activation='none',confirm=confirm,
        snapshot_root=str(tmp_path/'snapshots'),output=lambda _:None).run()
    assert result.state==ConfigTransactionState.PRECONDITION_FAILED
    confirm.assert_not_called()
    _assert_no_destination_mutations(transport,before)


@pytest.mark.parametrize('section,option,value',BAD)
def test_postrender_mcu_options_fail_before_existing_cfg_and_sidecar_write(tmp_path,monkeypatch,section,option,value):
    import core.generator as generator
    original=generator._postprocess_generated_output
    override=f'\n[{section}]\n'+('serial: /dev/fixture\n' if section!='mcu' else '')+f'{option}: {value}\n'
    monkeypatch.setattr(generator,'_postprocess_generated_output',lambda text:original(text)+override)
    cfg=tmp_path/'printer.cfg';sidecar=tmp_path/'printer.cfg.provenance.json'
    cfg.write_bytes(b'old cfg');sidecar.write_bytes(b'old sidecar')
    with pytest.raises(GenerationError,match=option):generated(tmp_path)
    assert cfg.read_bytes()==b'old cfg' and sidecar.read_bytes()==b'old sidecar'


@pytest.mark.parametrize('section,option,value',[('mcu','baud','2400'),('mcu','baud','10000000'),('mcu aux','restart_method','command')])
def test_compatible_mcu_options_remain_publishable(tmp_path,section,option,value):
    base=generated(tmp_path);remote=destination(base,'include',section,option,value)
    assert validate_configuration_plan(build_managed_config_plan(base,None,remote)).valid
    result=ConfigDeploymentTransaction(FakeTransport(remote),base,None,activation='none',
        snapshot_root=str(tmp_path/'snapshots'),output=lambda _:None).run()
    assert result.state==ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION


@pytest.mark.parametrize('connection',['canbus_uuid: aabbccddeeff','serial: /tmp/klipper_host_aux','serial: /dev/rpmsg_pru30'])
@pytest.mark.parametrize('unused',['baud: 250000','restart_method: command'])
def test_preserved_non_uart_unused_options_reject_before_writes(tmp_path,connection,unused):
    base=generated(tmp_path)
    remote={'printer.cfg':base+b'\n[include user.cfg]\n',
        'user.cfg':f'[mcu aux]\n{connection}\n{unused}\n'.encode()}
    review=validate_configuration_plan(build_managed_config_plan(base,None,remote))
    assert not review.valid and any(e.code=='mcu-connection' for e in review.errors)
    transport=FakeTransport(remote);before=dict(transport.files);confirm=Mock(return_value=True)
    result=ConfigDeploymentTransaction(transport,base,None,activation='none',confirm=confirm,
        snapshot_root=str(tmp_path/'snapshots'),output=lambda _:None).run()
    assert result.state==ConfigTransactionState.PRECONDITION_FAILED
    confirm.assert_not_called()
    _assert_no_destination_mutations(transport,before)


@pytest.mark.parametrize('connection',['canbus_uuid: aabbccddeeff','serial: /tmp/klipper_host_aux','serial: /dev/rpmsg_pru30'])
def test_non_uart_preserved_defaults_have_no_invented_options(tmp_path,connection):
    base=generated(tmp_path)
    remote={'printer.cfg':base+b'\n[include user.cfg]\n','user.cfg':f'[mcu aux]\n{connection}\n'.encode()}
    plan=build_managed_config_plan(base,None,remote)
    assert validate_configuration_plan(plan).valid
