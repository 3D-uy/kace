"""Selected SKR F103 boards require low startup levels, not just a pin name."""
from unittest.mock import patch

import pytest

from firmware.startup_gpio import required_startup_pins, verify_startup_artifact
from firmware.configuration import klipper_config
from firmware.derivation import derive_config
from firmware.firmware_generator import generate_firmware_config
from firmware.validator import validate_config
from firmware.identity import FirmwareIdentityError
from firmware.boards.runtime import resolve_firmware_authority
from firmware.deployment.service import FirmwareDeploymentService
from firmware.deployment.models import DeploymentTarget
from core.firmware_workflow import (artifact_evidence, generation_pin_reservations,
    create_checkpoint, transition_checkpoint, validate_checkpoint, FirmwareWorkflowState,
    FirmwareWorkflowError, CheckpointIncompatible)
from tests.unit.test_startup_gpio import artifact
from tests.unit.test_firmware_workflow import identity_reader

BOARDS = [
    ('generic-bigtreetech-skr-mini-e3-v1.0.cfg', '!PC13'),
    ('generic-bigtreetech-skr-mini-e3-v1.2.cfg', '!PC13'),
    ('generic-bigtreetech-skr-e3-dip.cfg', '!PC13'),
    ('generic-bigtreetech-skr-mini-e3-v2.0.cfg', '!PA14'),
    ('generic-bigtreetech-skr-mini-mz.cfg', '!PA14'),
    ('generic-bigtreetech-skr-cr6-v1.0.cfg', '!PA14'),
]


def requested():
    config = derive_config('stm32f103', 'usb', flash_start='0x7000')
    config['CONFIG_CLOCK_REF_FREQ'] = '8000000'  # Explicit test input, not board autodetection.
    return config


@pytest.mark.parametrize('board,pin', BOARDS)
def test_each_selected_alias_has_legacy_authority_and_low_startup(board, pin):
    assert resolve_firmware_authority(board).to_dict()['authority'] == 'legacy'
    assert required_startup_pins(board, 'stm32f103') == (pin,)
    assert klipper_config(requested(), 'stm32f103', board=board)['CONFIG_INITIAL_PINS'] == f'"{pin}"'
    with pytest.raises(ValueError, match='STM32F103'):
        required_startup_pins(board, 'stm32g0b1')
    with pytest.raises(ValueError, match='STM32F103'):
        required_startup_pins(board, 'stm32f103x6')


@pytest.mark.parametrize('board,pin', BOARDS)
@pytest.mark.parametrize('mutation', ['missing', 'high', 'wrong_bank', 'extra'])
def test_config_and_native_bytes_independently_require_exact_low_pin(tmp_path, board, pin, mutation):
    wrong = {'missing': None, 'high': pin[1:],
             'wrong_bank': '!PA14' if pin == '!PC13' else '!PC13', 'extra': pin + ',PA0'}[mutation]
    built = artifact(tmp_path, pins=wrong, config=f'"{pin}"')
    with pytest.raises(FirmwareIdentityError, match='Compiled firmware lacks'):
        verify_startup_artifact(board, built.path, built.firmware_identity)
    assert not FirmwareDeploymentService(output_dir=str(tmp_path/'out')).available_methods(
        DeploymentTarget(board=board, mcu='stm32f103'), built)
    built = artifact(tmp_path, pins=pin, config=None if wrong is None else f'"{wrong}"')
    with pytest.raises(FirmwareIdentityError, match='CONFIG_INITIAL_PINS'):
        verify_startup_artifact(board, built.path, built.firmware_identity)


@pytest.mark.parametrize('board,pin', BOARDS)
def test_resolved_writer_and_untyped_bypass_rejection(tmp_path, board, pin):
    ok, detail = generate_firmware_config(requested(), str(tmp_path), processor='stm32f103', board=board)
    assert ok, detail
    cfg = tmp_path/'.config'
    text = cfg.read_text()
    assert f'CONFIG_INITIAL_PINS="{pin}"' in text
    ok, detail = generate_firmware_config(requested(), str(tmp_path), board=board)
    assert not ok and cfg.read_text() == text
    assert not validate_config(str(tmp_path), board=board)[0]
    cfg.write_text(text.replace(pin, pin[1:]) + 'CONFIG_FLASH_APPLICATION_ADDRESS=0x08007000\n')
    ok, detail = validate_config(str(tmp_path), requested=requested(), processor='stm32f103', board=board)
    assert not ok and 'CONFIG_INITIAL_PINS' in detail


@pytest.mark.parametrize('board,pin', BOARDS)
def test_valid_artifact_and_old_checkpoint_cannot_bypass_requirement(tmp_path, board, pin):
    built = artifact(tmp_path, pins=pin, config=f'"{pin}"')
    verify_startup_artifact(board, built.path, built.firmware_identity)
    user = {'board': board, 'mcu_type': 'stm32f103', 'firmware_artifact': built,
            'firmware_path': built.path, 'mcu_path': '/dev/serial/by-id/test'}
    assert generation_pin_reservations(user) == {'mcu': {}}
    built = artifact(tmp_path, pins=None, config=None)
    user['firmware_artifact'] = built
    with pytest.raises(FirmwareWorkflowError, match='startup GPIO'):
        artifact_evidence(user)
    with pytest.raises(FirmwareIdentityError, match='startup GPIO'):
        generation_pin_reservations(user)
    checkpoint = create_checkpoint(user, identity_reader=identity_reader())
    evidence = {'path': built.path, 'sha256': built.sha256, 'size_bytes': built.size_bytes,
                'build': built.to_dict(), 'final_filename': 'klipper.bin', 'method': 'manual', 'strategy': 'MANUAL'}
    checkpoint = transition_checkpoint(checkpoint, FirmwareWorkflowState.ARTIFACT_READY, artifact=evidence)
    with pytest.raises(CheckpointIncompatible, match='startup GPIO'):
        validate_checkpoint(checkpoint)


@pytest.mark.parametrize('board,pin', BOARDS)
def test_wizard_passes_selected_skr_not_printer_profile(board, pin):
    from core.firmware_wizard import run_firmware_wizard
    from core.translations import t
    with patch('core.firmware_wizard.yes_no', return_value=True), \
         patch('core.firmware_wizard._resolve_firmware_configuration', return_value=(requested(), 'stm32f103', 'usb')), \
         patch('core.firmware_wizard.numbered_select', return_value=t('builder.compile_now')), \
         patch('core.firmware_wizard.build_firmware_orchestrator', return_value={'status': 'error', 'message': 'stop'}) as build:
        run_firmware_wizard({'board': board, 'printer_profile': 'unrelated.cfg', 'mcu_type': 'stm32f103', 'mcu_hint': 'usb'})
    assert build.call_args.kwargs['board'] == board


@pytest.mark.parametrize('board', ['generic-bigtreetech-skr-mini-e3-v3.0.cfg',
                                  'generic-bigtreetech-skr-mini-e3-v2.1.cfg', 'unrelated.cfg'])
def test_no_fuzzy_inheritance_to_other_boards(board):
    assert required_startup_pins(board) == ()
    assert 'CONFIG_INITIAL_PINS' not in klipper_config(requested(), 'stm32f103', board=board)
