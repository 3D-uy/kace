"""BX panel initialization belongs to firmware, independently of print strategy."""
import json
import zlib
from unittest.mock import patch

import pytest

from firmware.startup_gpio import BIQU_BX, required_startup_pins, verify_startup_artifact
from firmware.configuration import klipper_config
from firmware.derivation import derive_config
from firmware.validator import validate_config
from firmware.firmware_generator import generate_firmware_config
from firmware.identity import FirmwareBuildInputs, ToolchainIdentity, FirmwareIdentityError
from firmware.artifacts import BuildArtifact
from firmware.deployment.service import FirmwareDeploymentService
from firmware.deployment.models import DeploymentTarget
from core.firmware_workflow import (generation_pin_reservations, artifact_evidence, create_checkpoint,
    transition_checkpoint, validate_checkpoint, FirmwareWorkflowState, FirmwareWorkflowError, CheckpointIncompatible)
from tests.unit.test_firmware_workflow import identity_reader


def requested():
    config = derive_config('stm32h743', 'usb', flash_start='0x20000')
    config['CONFIG_CLOCK_REF_FREQ'] = '25000000'  # Explicit test input, not autodetected crystal.
    return config


def artifact(tmp_path, pins='PB5,PE5', config='"PB5,PE5"'):
    text = 'CONFIG_MCU="stm32h743"\n'
    if config is not None:
        text += f'CONFIG_INITIAL_PINS={config}\n'
    inputs = FirmwareBuildInputs.create(klipper_commit='b'*40, canonical_config=text,
        toolchain=ToolchainIdentity('make', 'test', 'gcc', 'test'), build_id='a'*32)
    constants = {'MCU': 'stm32h743xx'}
    if pins is not None:
        constants['INITIAL_PINS'] = pins
    path = tmp_path/'klipper.bin'
    path.write_bytes(b'prefix'+zlib.compress(json.dumps({'version': inputs.reported_version,
        'config': constants}).encode())+b'suffix')
    return BuildArtifact.create(path=str(path), native_filename=path.name, size_bytes=path.stat().st_size,
        mcu='stm32h743', firmware_fingerprint=inputs.reported_version, mock_build=False,
        size_warning=False, build_identity=inputs)


def test_selected_bx_uses_h743_and_both_pins():
    assert required_startup_pins(BIQU_BX, 'stm32h743') == ('PB5', 'PE5')
    assert klipper_config(requested(), 'stm32h743', board=BIQU_BX)['CONFIG_INITIAL_PINS'] == '"PB5,PE5"'
    assert 'CONFIG_INITIAL_PINS' not in klipper_config(requested(), 'stm32h743', board='other.cfg')


@pytest.mark.parametrize('mcu', ['stm32h723', 'stm32h750', 'stm32h7', 'stm32f103', 'rp2040'])
def test_wrong_mcu_cannot_inherit_bx_pins(mcu):
    with pytest.raises(ValueError, match='STM32H743'):
        required_startup_pins(BIQU_BX, mcu)


@pytest.mark.parametrize('wrong', [None, '', 'PB5', 'PE5', '!PB5,PE5', 'PB5,!PE5', 'PB5,PE5,PA0'])
def test_native_and_config_checked_independently(tmp_path, wrong):
    built = artifact(tmp_path, pins=wrong)
    with pytest.raises(FirmwareIdentityError, match='Compiled firmware lacks'):
        verify_startup_artifact(BIQU_BX, built.path, built.firmware_identity)
    assert not FirmwareDeploymentService(output_dir=str(tmp_path/'out')).available_methods(
        DeploymentTarget(board=BIQU_BX, mcu='stm32h743'), built)
    built = artifact(tmp_path, config=None if wrong is None else f'"{wrong}"')
    with pytest.raises(FirmwareIdentityError, match='CONFIG_INITIAL_PINS'):
        verify_startup_artifact(BIQU_BX, built.path, built.firmware_identity)


def test_writer_validation_and_untyped_bypass(tmp_path):
    ok, detail = generate_firmware_config(requested(), str(tmp_path), processor='stm32h743', board=BIQU_BX)
    assert ok, detail
    cfg = tmp_path/'.config'
    text = cfg.read_text()
    assert 'CONFIG_INITIAL_PINS="PB5,PE5"' in text
    assert not generate_firmware_config(requested(), str(tmp_path), board=BIQU_BX)[0]
    assert cfg.read_text() == text
    assert not validate_config(str(tmp_path), board=BIQU_BX)[0]
    cfg.write_text(text.replace('PB5,PE5', 'PB5')+'CONFIG_FLASH_APPLICATION_ADDRESS=0x08020000\n')
    ok, detail = validate_config(str(tmp_path), requested=requested(), processor='stm32h743', board=BIQU_BX)
    assert not ok and 'CONFIG_INITIAL_PINS' in detail


def test_old_bx_checkpoint_cannot_resume_with_runtime_screen_pin_only(tmp_path):
    built = artifact(tmp_path, pins='PB5', config='"PB5"')
    user = {'board': BIQU_BX, 'mcu_type': 'stm32h743', 'firmware_artifact': built,
            'firmware_path': built.path, 'mcu_path': '/dev/serial/by-id/test'}
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


@pytest.mark.parametrize('macros', [False, True])
def test_complete_startup_and_runtime_panel_without_profile_print_start(tmp_path, macros):
    from core.generator import generate_config
    from core.pin_validator import _read_pin_config
    from tests.unit.test_fixed_pwm_beepers import board_case
    from core.board_bx_panel import reviewed_panel
    raw, board, choices = board_case(BIQU_BX)
    built = artifact(tmp_path)
    choices.update(mcu_type='stm32h743', firmware_artifact=built, firmware_path=built.path, display_choice=None)
    assert generation_pin_reservations(choices) == {'mcu': {}}
    text = generate_config(board, choices, output_path=str(tmp_path/'printer.cfg'), include_macros=macros,
                           verbose=False)['content']
    actual, official = _read_pin_config(text)[0], _read_pin_config(raw)[0]
    assert actual['output_pin screen'] == official['output_pin screen']
    for section in reviewed_panel()['sections']:
        assert actual[section] == official[section]
    assert not any(n.casefold() == 'gcode_macro print_start' for n in actual)
    if macros:
        assert 'gcode_macro PRINT_START' not in (tmp_path/'macros.cfg').read_text()


def test_wizard_keeps_selected_bx_authority():
    from core.firmware_wizard import run_firmware_wizard
    from core.translations import t
    with patch('core.firmware_wizard.yes_no', return_value=True), \
         patch('core.firmware_wizard._resolve_firmware_configuration', return_value=(requested(), 'stm32h743', 'usb')), \
         patch('core.firmware_wizard.numbered_select', return_value=t('builder.compile_now')), \
         patch('core.firmware_wizard.build_firmware_orchestrator', return_value={'status': 'error', 'message': 'stop'}) as build:
        run_firmware_wizard({'board': BIQU_BX, 'printer_profile': 'other.cfg', 'mcu_type': 'stm32h743', 'mcu_hint': 'usb'})
    assert build.call_args.kwargs['board'] == BIQU_BX
