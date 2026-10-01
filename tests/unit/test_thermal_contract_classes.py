"""Thermal policy composition with MCU policy and multiple primary heaters."""
import json

import pytest

from core.board_auxiliary import selected_board_electrical_source, validate_board_electrical_artifact
from core.exceptions import GenerationError
from core.firmware_workflow import persistable_wizard_data
from core.generator import generate_config
from core.managed_config import _section_options
from core.scraper import parse_config
from core.thermal_review import RECEIPT
from tests.unit.test_thermal_policy_confirmation import selection, approve


@pytest.mark.parametrize('origin', ['board', 'profile'])
@pytest.mark.parametrize('method', ['command', 'arduino', 'cheetah', 'rpi_usb'])
def test_restart_change_requires_new_thermal_review_and_survives_recovery(origin, method, tmp_path):
    board, user = selection('check_gain_time: 120', origin)
    approve(board, user)
    old = json.loads(json.dumps(user[RECEIPT]))
    board['mcu'] = {'restart_method': method}
    path = tmp_path/'printer.cfg'
    path.write_bytes(b'previous')
    with pytest.raises(GenerationError, match='requires explicit review'):
        generate_config(board, user, output_path=str(path), verbose=False)
    assert path.read_bytes() == b'previous'
    assert user[RECEIPT] == old
    approve(board, user)
    assert user[RECEIPT] != old
    text = generate_config(board, user, output_path=str(path), verbose=False)['content']
    saved = json.loads(json.dumps(persistable_wizard_data(user)))
    context = selected_board_electrical_source({'workflow_checkpoint': {'wizard_data': saved}})
    validate_board_electrical_artifact(context, text)
    assert _section_options(text)['mcu']['restart_method'] == method
    assert _section_options(text)['verify_heater heater_bed']['check_gain_time'] == '120'


@pytest.mark.parametrize('swap', [False, True])
def test_two_primary_heater_policies_remain_bound_to_their_consumers(swap, tmp_path):
    board, user = selection('check_gain_time: 120')
    extra = parse_config('[verify_heater extruder]\ncheck_gain_time: 35\nheating_gain: 3\n')
    from core.heater_verification import SOURCE
    board[SOURCE].update(extra.pop(SOURCE))
    board.update(extra)
    approve(board, user)
    text = generate_config(board, user, output_path=str(tmp_path/'printer.cfg'), verbose=False)['content']
    context = selected_board_electrical_source(user)
    if swap:
        text = text.replace('[verify_heater heater_bed]', '[verify_heater placeholder]')
        text = text.replace('[verify_heater extruder]', '[verify_heater heater_bed]')
        text = text.replace('[verify_heater placeholder]', '[verify_heater extruder]')
        with pytest.raises(GenerationError, match='protection'):
            validate_board_electrical_artifact(context, text)
    else:
        validate_board_electrical_artifact(context, text)
        sections = _section_options(text)
        assert sections['verify_heater extruder'] == {'check_gain_time': '35', 'heating_gain': '3'}
        assert sections['verify_heater heater_bed'] == {'check_gain_time': '120'}
