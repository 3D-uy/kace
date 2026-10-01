"""USB pullup and inactive stepper enables must all survive firmware creation."""
from unittest.mock import patch

import pytest

from firmware.startup_gpio import MONOPRICE_MINI_V1, required_startup_pins, verify_startup_artifact
from firmware.configuration import klipper_config
from firmware.derivation import derive_config
from firmware.firmware_generator import generate_firmware_config
from firmware.validator import validate_config
from firmware.identity import FirmwareIdentityError
from firmware.deployment.service import FirmwareDeploymentService
from firmware.deployment.models import DeploymentTarget
from core.firmware_workflow import (generation_pin_reservations, artifact_evidence,
    create_checkpoint, transition_checkpoint, validate_checkpoint, FirmwareWorkflowState,
    FirmwareWorkflowError, CheckpointIncompatible)
from tests.unit.test_startup_gpio import artifact
from tests.unit.test_firmware_workflow import identity_reader

PINS = ('PA8','PB1','PB11','PB9')
VALUE = ','.join(PINS)


def requested():
    config = derive_config('stm32f103','usb',flash_start='0x2000')
    config['CONFIG_CLOCK_REF_FREQ'] = '8000000'
    return config


def test_complete_selected_board_requirement_and_wrong_mcu():
    assert required_startup_pins(MONOPRICE_MINI_V1,'stm32f103') == PINS
    assert klipper_config(requested(),'stm32f103',board=MONOPRICE_MINI_V1)['CONFIG_INITIAL_PINS'] == f'"{VALUE}"'
    assert 'CONFIG_INITIAL_PINS' not in klipper_config(requested(),'stm32f103',board='unrelated.cfg')
    with pytest.raises(ValueError,match='STM32F103'):
        required_startup_pins(MONOPRICE_MINI_V1,'rp2040')


@pytest.mark.parametrize('pin',PINS)
@pytest.mark.parametrize('mutation',['omitted','inverted'])
def test_each_required_pin_is_checked_in_build_config_and_binary(tmp_path,pin,mutation):
    wrong = ','.join(('!'+p if p==pin and mutation=='inverted' else p)
                     for p in PINS if not (p==pin and mutation=='omitted'))
    built = artifact(tmp_path,pins=wrong,config=f'"{VALUE}"')
    with pytest.raises(FirmwareIdentityError,match='Compiled firmware lacks'):
        verify_startup_artifact(MONOPRICE_MINI_V1,built.path,built.firmware_identity)
    assert not FirmwareDeploymentService(output_dir=str(tmp_path/'out')).available_methods(
        DeploymentTarget(board=MONOPRICE_MINI_V1,mcu='stm32f103'),built)
    built = artifact(tmp_path,pins=VALUE,config=f'"{wrong}"')
    with pytest.raises(FirmwareIdentityError,match='CONFIG_INITIAL_PINS'):
        verify_startup_artifact(MONOPRICE_MINI_V1,built.path,built.firmware_identity)


def test_valid_firmware_and_old_checkpoint_refusal(tmp_path):
    built = artifact(tmp_path,pins=VALUE,config=f'"{VALUE}"')
    verify_startup_artifact(MONOPRICE_MINI_V1,built.path,built.firmware_identity)
    user = {'board':MONOPRICE_MINI_V1,'mcu_type':'stm32f103','firmware_artifact':built,
            'firmware_path':built.path,'mcu_path':'/dev/serial/by-id/test'}
    assert generation_pin_reservations(user) == {'mcu':{}}
    built = artifact(tmp_path,pins='PB9',config='"PB9"')
    user['firmware_artifact'] = built
    with pytest.raises(FirmwareWorkflowError,match='startup GPIO'):
        artifact_evidence(user)
    checkpoint = create_checkpoint(user,identity_reader=identity_reader())
    evidence = {'path':built.path,'sha256':built.sha256,'size_bytes':built.size_bytes,
                'build':built.to_dict(),'final_filename':'klipper.bin','method':'manual','strategy':'MANUAL'}
    checkpoint = transition_checkpoint(checkpoint,FirmwareWorkflowState.ARTIFACT_READY,artifact=evidence)
    with pytest.raises(CheckpointIncompatible,match='startup GPIO'):
        validate_checkpoint(checkpoint)


def test_kconfig_writer_and_resolved_validation_require_all_pins(tmp_path):
    ok,detail = generate_firmware_config(requested(),str(tmp_path),processor='stm32f103',board=MONOPRICE_MINI_V1)
    assert ok,detail
    cfg = tmp_path/'.config'
    text = cfg.read_text()
    assert f'CONFIG_INITIAL_PINS="{VALUE}"' in text
    cfg.write_text(text.replace(VALUE,'PB9')+'CONFIG_FLASH_APPLICATION_ADDRESS=0x08002000\n')
    ok,detail = validate_config(str(tmp_path),requested=requested(),processor='stm32f103',board=MONOPRICE_MINI_V1)
    assert not ok and 'CONFIG_INITIAL_PINS' in detail


def test_wizard_uses_board_not_printer_profile():
    from core.firmware_wizard import run_firmware_wizard
    from core.translations import t
    with patch('core.firmware_wizard.yes_no',return_value=True), \
         patch('core.firmware_wizard._resolve_firmware_configuration',return_value=(requested(),'stm32f103','usb')), \
         patch('core.firmware_wizard.numbered_select',return_value=t('builder.compile_now')), \
         patch('core.firmware_wizard.build_firmware_orchestrator',return_value={'status':'error','message':'stop'}) as build:
        run_firmware_wizard({'board':MONOPRICE_MINI_V1,'printer_profile':'other.cfg',
                             'mcu_type':'stm32f103','mcu_hint':'usb'})
    assert build.call_args.kwargs['board'] == MONOPRICE_MINI_V1
