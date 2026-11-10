"""Guided TMC source matching respects whitespace in section names."""
import copy
import pytest
from core.exceptions import GenerationError
from core.profile_values import resolve_tmc_sections, extract_profile_values
from tests.unit.test_generator import _parsed, _user

@pytest.mark.parametrize('sep',[' ','\t','  '])
def test_select_same_driver_and_extract_values(sep):
    board=_parsed(); board['tmc2209'+sep+'stepper_x']={'uart_pin':'PC11','run_current':'0.580','sense_resistor':'0.150'}
    before=copy.deepcopy(board); user=_user(driver_type='TMC2209',driver_mode='UART')
    result=resolve_tmc_sections(board,user)
    assert result['tmc2209 stepper_x']==board['tmc2209'+sep+'stepper_x']
    assert extract_profile_values(board,driver_type='TMC2209')['run_current_x']=='0.580'
    assert board==before

@pytest.mark.parametrize('sep',[' ','\t','  '])
def test_foreign_driver_rejected(sep):
    board=_parsed();board['tmc2130'+sep+'stepper_x']={'cs_pin':'PC11'}
    with pytest.raises(GenerationError,match='incompatible source driver'):
        resolve_tmc_sections(board,_user(driver_type='TMC2209',driver_mode='UART'))

def test_ambiguous_duplicate_section_does_not_pick_by_order():
    board=_parsed();board['tmc2209 stepper_x']={'uart_pin':'PC11'}
    board['tmc2209\tstepper_x']={'uart_pin':'PC12'}
    with pytest.raises(GenerationError,match='ambiguous'):
        resolve_tmc_sections(board,_user(driver_type='TMC2209',driver_mode='UART'))

def test_other_model_does_not_override_existing_selected_source():
    board=_parsed();board['tmc2209 stepper_x']={'uart_pin':'PC11'}
    board['tmc2130\tstepper_x']={'cs_pin':'PC12'}
    assert resolve_tmc_sections(board,_user(driver_type='TMC2209',driver_mode='UART'))['tmc2209 stepper_x']=={'uart_pin':'PC11'}

def test_missing_source_still_uses_existing_fallback():
    assert resolve_tmc_sections(_parsed(),_user(driver_type='TMC2209',driver_mode='UART'))=={}
