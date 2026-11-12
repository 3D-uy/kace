"""Generated TMC section preserves reviewed source and rejects ambiguity."""
import pytest
from core.exceptions import GenerationError
from core.generator import generate_config
from core.scraper import parse_config
from tests.unit.test_generator import _parsed,_user

@pytest.mark.parametrize('sep',[' ','\t','  '])
def test_generation_preserves_selected_driver(tmp_path,sep):
    board=_parsed();board['tmc2209'+sep+'stepper_x']={'uart_pin':'PC11','run_current':'0.580','sense_resistor':'0.150'}
    out=tmp_path/'printer.cfg'; result=generate_config(board,_user(driver_type='TMC2209',driver_mode='UART'),output_path=str(out),verbose=False)
    assert parse_config(result['content'])['tmc2209 stepper_x']['uart_pin']=='PC11'
    assert parse_config(result['content'])['tmc2209 stepper_x']['sense_resistor']=='0.150'

@pytest.mark.parametrize('kind',['foreign','duplicate'])
def test_ambiguous_or_foreign_driver_fails_before_output(tmp_path,kind):
    board=_parsed();board['tmc2130\tstepper_x' if kind=='foreign' else 'tmc2209\tstepper_x']={'uart_pin':'PC11','run_current':'0.580'}
    if kind=='duplicate':board['tmc2209 stepper_x']={'uart_pin':'PC12','run_current':'0.580'}
    out=tmp_path/'printer.cfg';out.write_bytes(b'previous configuration'); sidecar=tmp_path/'printer.cfg.provenance.json';sidecar.write_bytes(b'previous provenance')
    with pytest.raises(GenerationError,match='ambiguous|incompatible'):
        generate_config(board,_user(driver_type='TMC2209',driver_mode='UART'),output_path=str(out),verbose=False)
    assert out.read_bytes()==b'previous configuration' and sidecar.read_bytes()==b'previous provenance'
