"""Motor inversion is explicit, staged, repeatable and independent of geometry."""
import copy
import json
import re

import pytest

from core.exceptions import GenerationError, WizardExit
from core.firmware_workflow import persistable_wizard_data, restore_wizard_data
from core.generator import generate_config
from core.motor_direction import (apply_motor_directions, available_motor_sections,
    direction_mode, effective_direction_pin, motor_sections, set_motor_direction)
from core.scraper import parse_config
from core.translations import get_lang, get_mode, set_lang, set_mode, t
from core.wizard.runner import _BACK, _QUIT
from core.wizard.steps import motion
from tests.unit.test_generator import _parsed, _user


def data(count=1, kinematics='cartesian'):
    parsed=_parsed()
    parsed['stepper_y']['dir_pin']='!PC2'
    for index,letter in enumerate(('F','G','H'),1):
        parsed[f'stepper_z{index}']={'step_pin':f'P{letter}1','dir_pin':f'!P{letter}2','enable_pin':f'!P{letter}3'}
    return _user(board_parsed=parsed,z_motors=str(count),kinematics=kinematics)


@pytest.fixture(autouse=True)
def interactive(monkeypatch):
    language,mode=get_lang(),get_mode()
    monkeypatch.setenv('KACE_AUTO','0')
    monkeypatch.setenv('KACE_QUIET','1')
    monkeypatch.setattr(motion,'_INTERACTIVE_MODE',False)
    yield
    set_lang(language)
    set_mode(mode)


@pytest.mark.parametrize('count',[1,2,3,4])
@pytest.mark.parametrize('kinematics',['cartesian','corexy'])
def test_all_configured_motors_change_only_dir_polarity_and_regenerate_identically(tmp_path,count,kinematics):
    user=data(count,kinematics)
    parsed=user['board_parsed']
    before=copy.deepcopy(user)
    original=generate_config(parsed,user,output_path=str(tmp_path/'original.cfg'),verbose=False)['content']
    for section in motor_sections(user): set_motor_direction(user,parsed,section,'invert')
    selected=copy.deepcopy(user)
    first=generate_config(parsed,user,output_path=str(tmp_path/'first.cfg'),verbose=False)['content']
    second=generate_config(parsed,user,output_path=str(tmp_path/'second.cfg'),verbose=False)['content']
    assert first==second
    # Compare the entire artifact, including geometry and every unrelated pin.
    expected=original
    for section in motor_sections(user):
        pin=parsed[section]['dir_pin']
        effective=pin[1:] if pin.startswith('!') else '!'+pin
        expected=re.sub(r'(?m)^dir_pin: '+re.escape(pin)+r'(\s+)(#.*)$',
            lambda match:'dir_pin: '+effective+' '*max(1,len(match[1])+len(pin)-len(effective))+match[2],expected)
    assert first==expected
    assert parsed==before['board_parsed']
    assert user==selected
    resumed=restore_wizard_data(json.loads(json.dumps(persistable_wizard_data(user))))
    assert generate_config(resumed['board_parsed'],resumed,output_path=str(tmp_path/'resumed.cfg'),verbose=False)['content']==first


@pytest.mark.parametrize('section',['stepper_x','stepper_y','stepper_z','extruder','stepper_z1','stepper_z2','stepper_z3'])
def test_keep_restores_original_direction_after_repeated_invert_selection(section):
    user=data(4)
    parsed=user['board_parsed']
    original=copy.deepcopy(parsed)
    set_motor_direction(user,parsed,section,'invert')
    first=effective_direction_pin(parsed,user,section)
    set_motor_direction(user,parsed,section,'invert')
    assert effective_direction_pin(parsed,user,section)==first
    set_motor_direction(user,parsed,section,'keep')
    assert effective_direction_pin(parsed,user,section)==original[section]['dir_pin']
    assert user['motor_directions']=={}
    assert parsed==original


@pytest.mark.parametrize('change',['board','dir','step','socket','alias'])
def test_changed_board_pin_or_socket_requires_review_and_never_writes(tmp_path,change):
    user=data(2)
    parsed=user['board_parsed']
    parsed['board_pins']={'aliases':'DIR=PA2'}
    parsed['stepper_x']['dir_pin']='DIR'
    set_motor_direction(user,parsed,'stepper_x','invert')
    if change=='board': user['board']='other-board.cfg'
    if change=='dir': parsed['stepper_x']['dir_pin']='PA9'
    if change=='step': parsed['stepper_x']['step_pin']='PA9'
    if change=='socket': user['z_socket_assignments']={'stepper_x':'different'}
    if change=='alias': parsed['board_pins']['aliases']='DIR=PA9'
    path=tmp_path/'printer.cfg'
    path.write_bytes(b'previous')
    with pytest.raises(GenerationError,match='source changed'):
        generate_config(parsed,user,output_path=str(path),verbose=False)
    assert path.read_bytes()==b'previous'
    set_motor_direction(user,parsed,'stepper_x','keep')
    assert direction_mode(parsed,user,'stepper_x')=='keep'


def test_multi_mcu_alias_only_loses_or_gains_leading_inversion():
    user=data()
    parsed=user['board_parsed']
    parsed['board_pins tool']={'mcu':'tool','aliases':'DIR=gpio7'}
    parsed['stepper_x']['dir_pin']='!tool:DIR'
    set_motor_direction(user,parsed,'stepper_x','invert')
    assert effective_direction_pin(parsed,user,'stepper_x')=='tool:DIR'


@pytest.mark.parametrize('invalid',[False,[],{'heater_bed':{}},{'stepper_z3':{}},{'stepper_x':'invert'},{'stepper_x':None}])
def test_invalid_or_inactive_choices_fail_without_mutating_source(invalid):
    user=data()
    user['motor_directions']=invalid
    parsed=copy.deepcopy(user['board_parsed'])
    before=copy.deepcopy(parsed)
    with pytest.raises(GenerationError): apply_motor_directions(parsed,user)
    assert parsed==before


@pytest.mark.parametrize('pin',['','TODO','!!PA2','^PA2','tool:!gpio7','PA2\nG28'])
def test_invalid_source_pin_cannot_become_a_manual_pin_entry(pin):
    user=data()
    user['board_parsed']['stepper_x']['dir_pin']=pin
    with pytest.raises(GenerationError): set_motor_direction(user,user['board_parsed'],'stepper_x','invert')
    assert 'motor_directions' not in user


@pytest.mark.parametrize('language',['English','Español','Português'])
@pytest.mark.parametrize('mode',['Beginner','Advanced'])
def test_profile_editor_offers_each_mapped_motor_and_stages_save(monkeypatch,language,mode):
    set_lang(language);set_mode(mode)
    user=data(4)
    defaults=copy.deepcopy(user)
    parsed={}
    original=copy.deepcopy(user)
    replies=iter(['motor_direction_stepper_x','invert','motor_direction_stepper_y','invert',
                  'motor_direction_stepper_z3','invert','motor_direction_extruder','invert','save'])
    def select(prompt,choices,**kw):
        if prompt==t('wizard.profile_editor_prompt'):
            fields=[getattr(c,'value',None) for c in choices]
            assert all('motor_direction_'+motor in fields for motor in motor_sections(user))
        assert user==original
        return next(replies)
    monkeypatch.setattr(motion,'numbered_select',select)
    assert motion._step_profile_editor_inner(defaults,parsed,user)=='save'
    assert set(user['motor_directions'])=={'stepper_x','stepper_y','stepper_z3','extruder'}
    assert user['board_parsed']==original['board_parsed']
    assert 'motor_directions' not in defaults
    assert not any('dir_pin' in options for options in parsed.values())


@pytest.mark.parametrize('exit_at',['back',_QUIT,None])
def test_profile_discard_or_quit_does_not_change_any_motor(monkeypatch,exit_at):
    user=data();defaults=copy.deepcopy(user);parsed={}
    original=copy.deepcopy((user,defaults,parsed))
    answers=iter(['motor_direction_stepper_x','invert',exit_at])
    monkeypatch.setattr(motion,'numbered_select',lambda *a,**k:next(answers))
    if exit_at=='back': assert motion._step_profile_editor_inner(defaults,parsed,user)=='back'
    else:
        with pytest.raises(WizardExit): motion._step_profile_editor_inner(defaults,parsed,user)
    assert (user,defaults,parsed)==original


def test_nested_back_keeps_other_staged_motor_changes(monkeypatch):
    user=data();defaults=copy.deepcopy(user);parsed={}
    answers=iter(['motor_direction_stepper_x','invert','motor_direction_stepper_y',_BACK,'save'])
    monkeypatch.setattr(motion,'numbered_select',lambda *a,**k:next(answers))
    assert motion._step_profile_editor_inner(defaults,parsed,user)=='save'
    assert set(user['motor_directions'])=={'stepper_x'}


def test_no_profile_route_stages_choices_and_back_discards_them(monkeypatch):
    user=data(2);before=copy.deepcopy(user)
    answers=iter(['stepper_z1','invert',_BACK])
    monkeypatch.setattr(motion,'numbered_select',lambda *a,**k:next(answers))
    assert motion._step_motor_directions(user)==_BACK
    assert user==before
    answers=iter(['stepper_z1','invert','extruder','invert','done'])
    assert motion._step_motor_directions(user)=='done'
    assert set(user['motor_directions'])=={'stepper_z1','extruder'}


def test_individual_keep_and_corexy_labels_do_not_modify_other_motors_or_homing(monkeypatch):
    user=data(kinematics='corexy')
    set_motor_direction(user,user['board_parsed'],'stepper_x','invert')
    set_motor_direction(user,user['board_parsed'],'stepper_y','invert')
    user['homing_positive_dir_x']='True'
    assert 'A / stepper_x' in motion._motor_label(user,'stepper_x')
    assert 'B / stepper_y' in motion._motor_label(user,'stepper_y')
    responses=iter(['stepper_x','keep','done'])
    def select(prompt, choices, **kwargs):
        assert all(choice.get('value') != 'keep_all' for choice in choices)
        return next(responses)
    monkeypatch.setattr(motion,'numbered_select',select)
    assert motion._step_motor_directions(user)=='done'
    assert set(user['motor_directions'])=={'stepper_y'}
    assert user['homing_positive_dir_x']=='True'


def test_profile_branch_and_auto_mode_do_not_repeat_motor_questions(monkeypatch):
    user=data()
    user['profile_loaded']=True
    monkeypatch.setattr(motion,'numbered_select',lambda *a,**k:pytest.fail('No repeated question'))
    assert motion._step_motor_directions(user)=='done'
    user.pop('profile_loaded');monkeypatch.setenv('KACE_AUTO','1')
    assert motion._step_motor_directions(user)=='done'


def test_managed_plan_keeps_selected_motor_direction_on_install_and_retry(tmp_path):
    from core.managed_config import build_managed_config_plan, effective_hardware_text
    user=data()
    board=user['board_parsed']
    old=generate_config(board,user,output_path=str(tmp_path/'old.cfg'),verbose=False)['content'].encode()
    set_motor_direction(user,board,'stepper_x','invert')
    generated=generate_config(board,user,output_path=str(tmp_path/'new.cfg'),verbose=False)['content'].encode()
    remote={'printer.cfg':old}
    plan=build_managed_config_plan(generated,None,remote)
    final=parse_config(effective_hardware_text(plan))
    assert final['stepper_x']['dir_pin']=='!PA2'
    assert final['stepper_y']['dir_pin']=='!PC2'
    remote.update({artifact.remote_name:artifact.content for artifact in plan.artifacts})
    assert not build_managed_config_plan(generated,None,remote).changed_artifacts
