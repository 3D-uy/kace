"""Primary extruder policy by behavior, independent of board identity."""
import json
from unittest.mock import Mock

import pytest

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.exceptions import GenerationError
from core.firmware_workflow import persistable_wizard_data
from core.generator import generate_config
from core.managed_config import _section_options, build_managed_config_plan, effective_hardware_text
from core.profile_values import mark_profile_values, mark_user_override, validate_primary_extruder_options
from tests.unit.test_config_transaction import FakeTransport, GENERATED
from tests.unit.test_generator import _parsed, _user


OPTIONS = {'max_extrude_only_distance': '120', 'max_extrude_only_velocity': '25',
           'max_extrude_only_accel': '500', 'instantaneous_corner_velocity': '0',
           'min_extrude_temp': '180', 'smooth_time': '2'}


@pytest.mark.parametrize('option,value', OPTIONS.items())
@pytest.mark.parametrize('origin', ['board', 'profile'])
def test_explicit_primary_option_survives_generation_and_recovery(tmp_path, option, value, origin):
    board, user = _parsed(), _user()
    if origin == 'board':
        board['extruder'][option] = value
    else:
        user['_profile_parsed'] = {'extruder': {option: value}}
    user = json.loads(json.dumps(persistable_wizard_data(user)))
    content = generate_config(board,user,output_path=str(tmp_path/'printer.cfg'),verbose=False)['content']
    assert _section_options(content)['extruder'][option] == value
    remote = {}
    for _ in range(2):
        plan = build_managed_config_plan(content.encode(),None,remote)
        assert _section_options(effective_hardware_text(plan))['extruder'][option]==value
        remote.update({a.remote_name:a.content for a in plan.artifacts})
    assert not plan.changed_artifacts


def test_absent_options_remain_absent_for_official_dependent_defaults(tmp_path):
    content = generate_config(_parsed(),_user(),output_path=str(tmp_path/'printer.cfg'),verbose=False)['content']
    assert not set(OPTIONS).intersection(_section_options(content)['extruder'])


@pytest.mark.parametrize('option', OPTIONS)
def test_profile_switch_clears_stale_optional_values(tmp_path, option):
    user = _user(_profile_parsed={'extruder':{option:OPTIONS[option]}}, **{'extruder_'+option:OPTIONS[option]})
    mark_profile_values(user,user['_profile_parsed'])
    user['_profile_parsed'] = {}
    mark_profile_values(user,{})
    content=generate_config(_parsed(),user,output_path=str(tmp_path/'printer.cfg'),verbose=False)['content']
    assert option not in _section_options(content)['extruder']


@pytest.mark.parametrize('option', OPTIONS)
def test_explicit_override_and_existing_destination_tuning_remain_authoritative(tmp_path, option):
    user = _user(_profile_parsed={'extruder':{option:OPTIONS[option]}}, **{'extruder_'+option:'1'})
    mark_user_override(user,'extruder_'+option)
    content=generate_config(_parsed(),user,output_path=str(tmp_path/'printer.cfg'),verbose=False)['content']
    assert _section_options(content)['extruder'][option]=='1'
    plan=build_managed_config_plan(content.encode(),None,{'printer.cfg':f'[extruder]\n{option}: 2\n'.encode()})
    assert _section_options(effective_hardware_text(plan))['extruder'][option]=='2'


@pytest.mark.parametrize('option', OPTIONS)
@pytest.mark.parametrize('value', ['nan','inf','-1','bad',None,'',True])
def test_invalid_source_values_reject_before_write(tmp_path,option,value):
    board=_parsed()
    board['extruder'][option]=value
    target=tmp_path/'printer.cfg'
    target.write_text('unchanged')
    with pytest.raises(GenerationError,match=option):
        generate_config(board,_user(),output_path=str(target),verbose=False)
    assert target.read_text()=='unchanged'


@pytest.mark.parametrize('option,value', [('max_extrude_only_distance','-1'),('max_extrude_only_velocity','0'),
    ('max_extrude_only_accel','0'),('instantaneous_corner_velocity','nan'),('min_extrude_temp','300'),('smooth_time','0')])
@pytest.mark.parametrize('noop',[False,True])
def test_invalid_effective_include_rejects_even_on_repeat(tmp_path,option,value,noop):
    generated = GENERATED + b'\n[extruder]\nmin_temp: 0\nmax_temp: 250\n'
    remote={'printer.cfg':generated+b'\n[include user.cfg]\n','user.cfg':f'[extruder]\n{option}: {value}\n'.encode()}
    if noop:
        remote.update({a.remote_name:a.content for a in build_managed_config_plan(generated,None,remote).artifacts})
        assert not build_managed_config_plan(generated,None,remote).changed_artifacts
    transport,confirm=FakeTransport(remote),Mock(return_value=True)
    result=ConfigDeploymentTransaction(transport,generated,None,activation='none',confirm=confirm,
        verify_existing_ready=noop,snapshot_root=str(tmp_path/'snapshots')).run()
    assert result.state==ConfigTransactionState.PRECONDITION_FAILED and option in result.detail
    confirm.assert_not_called()
    assert transport.files==remote and all(c[0]=='read' for c in transport.calls)


def test_explicit_unresolved_limit_cannot_fall_back_to_default(tmp_path):
    user=_user(_value_provenance={'extruder_max_extrude_only_distance':'UNRESOLVED'})
    with pytest.raises(GenerationError,match='max_extrude_only_distance'):
        generate_config(_parsed(),user,output_path=str(tmp_path/'printer.cfg'),verbose=False)


@pytest.mark.parametrize('option,value', [('max_extrude_only_distance','0'),
    ('instantaneous_corner_velocity','0'),('min_extrude_temp','-10'),
    ('min_extrude_temp','0'),('min_extrude_temp','250'),('smooth_time','0.01')])
def test_official_inclusive_bounds_and_positive_smoothing(option,value):
    validate_primary_extruder_options({'extruder':{'min_temp':'-10','max_temp':'250',option:value}})
