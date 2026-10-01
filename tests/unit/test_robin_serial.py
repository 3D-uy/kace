"""Reviewed Robin connection choices survive Kconfig, native bytes and recovery."""
import json
import zlib
from unittest.mock import patch

import pytest

from firmware.board_serial import KINGROON, SAPPHIRE, SERIAL_PINS, board_serial_ports
from firmware.configuration import klipper_config, validate_firmware_configuration
from firmware.derivation import derive_config
from firmware.startup_gpio import verify_startup_artifact
from firmware.identity import FirmwareBuildInputs, ToolchainIdentity, FirmwareIdentityError
from firmware.artifacts import BuildArtifact
from firmware.deployment.service import FirmwareDeploymentService
from firmware.deployment.models import DeploymentTarget
from core.firmware_workflow import (generation_pin_reservations, create_checkpoint, transition_checkpoint,
    validate_checkpoint, FirmwareWorkflowState, CheckpointIncompatible)
from tests.unit.test_firmware_workflow import identity_reader

ROUTES = [(board, port) for board in (KINGROON, *SAPPHIRE) for port in board_serial_ports(board)]


def requested(port):
    result = derive_config('stm32f103', 'uart', flash_start='0x7000')
    result.update(KACE_SERIAL_PORT=port, CONFIG_CLOCK_REF_FREQ='8000000')
    return result


def artifact(tmp_path, port, *, pins=None, startup='!PC6,!PD13'):
    config = (f'CONFIG_MACH_STM32F103=y\nCONFIG_SERIAL=y\nCONFIG_STM32_USB_DOUBLE_BUFFER_TX=y\nCONFIG_FLASH_APPLICATION_ADDRESS=0x08007000\n'
              f'CONFIG_STM32_SERIAL_{port}=y\nCONFIG_INITIAL_PINS="!PC6,!PD13"\n')
    inputs = FirmwareBuildInputs.create(klipper_commit='b'*40, canonical_config=config,
        toolchain=ToolchainIdentity('make', 'test', 'gcc', 'test'), build_id='a'*32)
    data = {'version': inputs.reported_version, 'config': {'MCU': 'stm32f103xe',
            'RESERVE_PINS_serial': pins if pins is not None else SERIAL_PINS[port], 'INITIAL_PINS': startup}}
    path = tmp_path/'klipper.bin'
    path.write_bytes(zlib.compress(json.dumps(data).encode()))
    return BuildArtifact.create(path=str(path), native_filename='klipper.bin', size_bytes=path.stat().st_size,
        mcu='stm32f103', firmware_fingerprint=inputs.reported_version, mock_build=False, size_warning=False,
        build_identity=inputs)


@pytest.mark.parametrize('board,port', ROUTES)
def test_choices_emit_actual_usart_and_both_startup_pins(board, port):
    result = klipper_config(requested(port), 'stm32f103', board=board)
    assert result[f'CONFIG_STM32_SERIAL_{port}'] == 'y'
    assert result['CONFIG_INITIAL_PINS'] == '"!PC6,!PD13"'
    assert 'KACE_SERIAL_PORT' not in result
    assert result['CONFIG_STM32_FLASH_START_7000'] == 'y'


@pytest.mark.parametrize('board', [KINGROON, *SAPPHIRE])
@pytest.mark.parametrize('change', ['missing', 'native_usb', 'bad_port', 'wrong_offset', 'wrong_mcu'])
def test_no_silent_port_or_native_usb_fallback(board, change):
    config = requested('USART3')
    mcu = 'stm32f103'
    if change == 'missing': config.pop('KACE_SERIAL_PORT')
    elif change == 'native_usb': config.pop('CONFIG_SERIAL'); config['CONFIG_USB'] = 'y'
    elif change == 'bad_port': config['KACE_SERIAL_PORT'] = 'USART2'
    elif change == 'wrong_offset': config['CONFIG_FLASH_START'] = '0x0'
    else: mcu = 'stm32f103x6'
    with pytest.raises(ValueError):
        klipper_config(config, mcu, board=board)


def test_kingroon_cannot_select_direct_usart1_or_foreign_board_inherit_explicit_port():
    for board in (KINGROON, 'other.cfg', None):
        with pytest.raises(ValueError): klipper_config(requested('USART1'), 'stm32f103', board=board)
    config = requested('USART3'); config['unexpected'] = 'y'
    with pytest.raises(ValueError): validate_firmware_configuration(config, processor='stm32f103')


@pytest.mark.parametrize('board,port', ROUTES)
@pytest.mark.parametrize('change', ['serial_pins', 'startup'])
def test_native_mismatch_refuses_deployment(tmp_path, board, port, change):
    built = artifact(tmp_path, port, pins='PA0,PA1' if change == 'serial_pins' else None,
                     startup='!PC6' if change == 'startup' else '!PC6,!PD13')
    with pytest.raises(FirmwareIdentityError): verify_startup_artifact(board, built.path, built.firmware_identity)
    assert not FirmwareDeploymentService(output_dir=str(tmp_path/'out')).available_methods(
        DeploymentTarget(board=board, mcu='stm32f103'), built)


@pytest.mark.parametrize('board,port', ROUTES)
def test_recorded_port_is_enforced_during_generation_and_recovery(tmp_path, board, port):
    built = artifact(tmp_path, port)
    user = {'board': board, 'mcu_type': 'stm32f103', 'firmware_serial_port': port,
            'firmware_artifact': built, 'firmware_path': built.path, 'mcu_path': '/dev/serial/by-id/test'}
    assert set(generation_pin_reservations(user)['mcu']) == set(SERIAL_PINS[port].split(','))
    cp = create_checkpoint(user, identity_reader=identity_reader())
    cp = transition_checkpoint(cp, FirmwareWorkflowState.ARTIFACT_READY, artifact={
        'path': built.path, 'sha256': built.sha256, 'size_bytes': built.size_bytes, 'build': built.to_dict(),
        'final_filename': 'klipper.bin', 'method': 'manual', 'strategy': 'MANUAL'})
    assert validate_checkpoint(cp)['wizard_data']['firmware_serial_port'] == port
    user['firmware_serial_port'] = 'USART1' if port == 'USART3' else 'USART3'
    with pytest.raises(FirmwareIdentityError): generation_pin_reservations(user)
    with pytest.raises(CheckpointIncompatible): validate_checkpoint(cp, current_hardware=user)


@pytest.mark.parametrize('board,port', ROUTES)
def test_wizard_persists_connection_and_passes_explicit_choice_to_builder(board, port):
    from core.firmware_wizard import run_firmware_wizard
    from core.translations import t
    user = {'board': board, 'mcu_type': 'stm32f103', 'mcu_hint': 'usb', 'firmware_serial_port': port}
    with patch('core.firmware_wizard.yes_no', return_value=True), \
         patch('core.firmware_wizard.board_reference_clock', return_value='8000000'), \
         patch('core.firmware_wizard.numbered_select', return_value=t('builder.compile_now')), \
         patch('core.firmware_wizard.build_firmware_orchestrator', return_value={'status': 'error', 'message': 'stop'}) as build:
        run_firmware_wizard(user)
    assert build.call_args.kwargs['config_dict']['KACE_SERIAL_PORT'] == port
    assert build.call_args.kwargs['hint'] == 'uart'
    assert user['firmware_serial_port'] == port


def test_sapphire_requires_explicit_choice_and_supports_both_connections():
    from core.firmware_wizard import _select_board_serial
    for port in ('USART1', 'USART3'):
        with patch.dict('os.environ', {'KACE_AUTO': '0'}), patch('core.firmware_wizard.numbered_select', return_value=port):
            assert _select_board_serial(SAPPHIRE[0]) == port
    with patch.dict('os.environ', {'KACE_AUTO': '1'}):
        with pytest.raises(ValueError): _select_board_serial(SAPPHIRE[0])
    assert _select_board_serial(KINGROON) == 'USART3'


@pytest.mark.parametrize('flag', ['CONFIG_USBSERIAL', 'CONFIG_CANBUS', 'CONFIG_USBCANBUS'])
def test_active_alternative_transport_is_not_a_harmless_usb_capability(tmp_path, flag):
    from firmware.board_serial import verify_board_serial
    built = artifact(tmp_path, 'USART3')
    config = built.firmware_identity.canonical_config + f'{flag}=y\n'
    with pytest.raises(FirmwareIdentityError, match='conflicting'):
        verify_board_serial(KINGROON, config, {'config': {'RESERVE_PINS_serial': 'PB11,PB10'}})


def test_editing_sapphire_connection_reaches_builder_without_native_usb_fallback():
    from core.firmware_wizard import run_firmware_wizard
    from core.translations import t
    user = {'board': SAPPHIRE[0], 'mcu_type': 'stm32f103', 'firmware_serial_port': 'USART3'}
    with patch('core.firmware_wizard.yes_no', return_value=True), \
         patch('core.firmware_wizard.board_reference_clock', return_value='8000000'), \
         patch.dict('os.environ', {'KACE_AUTO': '0'}), \
         patch('core.firmware_wizard.numbered_select', side_effect=[t('builder.edit_comm'), 'USART1', t('builder.compile_now')]), \
         patch('core.firmware_wizard.build_firmware_orchestrator', return_value={'status': 'error', 'message': 'stop'}) as build:
        run_firmware_wizard(user)
    assert user['firmware_serial_port'] == 'USART1'
    choices = build.call_args.kwargs['config_dict']
    assert choices['KACE_SERIAL_PORT'] == 'USART1' and choices['CONFIG_SERIAL'] == 'y'
    assert choices['CONFIG_USB'] == 'n'
    resolved_choices = klipper_config(choices, 'stm32f103', board=SAPPHIRE[0])
    assert resolved_choices['CONFIG_STM32_SERIAL_USART1'] == 'y'
    assert 'CONFIG_STM32_USB_PA11_PA12' not in resolved_choices
