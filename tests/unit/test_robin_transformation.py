"""Separate native/final firmware evidence through preparation and recovery."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock, patch
import zlib

import pytest

from core.firmware_workflow import (artifact_evidence, create_checkpoint, transition_checkpoint,
    validate_checkpoint, generation_pin_reservations, FirmwareWorkflowState,
    FirmwareWorkflowError, CheckpointIncompatible)
from firmware.artifacts import BuildArtifact
from firmware.board_serial import KINGROON, SERIAL_PINS
from firmware.identity import FirmwareBuildInputs, FirmwareIdentityError, ToolchainIdentity
from firmware.robin import REVISION, prepare_robin, verify_robin
from firmware.deployment.models import (DeploymentTarget, DeploymentMethodId, DeploymentExecutionContext,
    DeploymentStatus, verify_prepared_artifact, DeploymentArtifactError)
from firmware.deployment.service import FirmwareDeploymentService
from tests.unit.test_robin_serial import ROUTES
from tests.unit.test_firmware_workflow import identity_reader

DELIVERIES = [(b, p, lcd) for b, p in ROUTES for lcd in ([None] if b == KINGROON else [False, True])]


def native(tmp_path, port='USART3', revision=REVISION):
    config = (f'CONFIG_MACH_STM32F103=y\nCONFIG_SERIAL=y\nCONFIG_FLASH_APPLICATION_ADDRESS=0x08007000\n'
              f'CONFIG_STM32_SERIAL_{port}=y\nCONFIG_INITIAL_PINS="!PC6,!PD13"\n')
    inputs = FirmwareBuildInputs.create(klipper_commit=revision, canonical_config=config,
        toolchain=ToolchainIdentity('make', 'test', 'gcc', 'test'), build_id='a'*32)
    dictionary = {'version': inputs.reported_version, 'config': {'MCU': 'stm32f103xe',
                  'RESERVE_PINS_serial': SERIAL_PINS[port], 'INITIAL_PINS': '!PC6,!PD13'}}
    path = tmp_path/'klipper.bin'
    path.write_bytes(b'\0'*32000 + zlib.compress(json.dumps(dictionary).encode()))
    return BuildArtifact.create(path=str(path), native_filename='klipper.bin', size_bytes=path.stat().st_size,
        mcu='stm32f103', firmware_fingerprint=inputs.reported_version, mock_build=False, size_warning=False, build_identity=inputs)


def prepared_case(tmp_path, board=KINGROON, port='USART3', lcd=None):
    built = native(tmp_path, port)
    service = FirmwareDeploymentService(output_dir=str(tmp_path/'out'), event_sink=lambda _: None)
    plan = service.plan(built, DeploymentTarget(board, 'stm32f103'), DeploymentMethodId.MANUAL)
    prepared = service.prepare_robin(plan, serial_port=port, lcd_removed=lcd)
    user = {'board': board, 'mcu_type': 'stm32f103', 'firmware_serial_port': port, 'robin_lcd_removed': lcd,
            'firmware_artifact': built, 'prepared_firmware_deployment': prepared, 'firmware_path': prepared.staged_path}
    return built, service, prepared, user


@pytest.mark.parametrize('board,port,lcd', DELIVERIES)
def test_two_artifacts_survive_preparation_checkpoint_and_pin_lookup(tmp_path, board, port, lcd):
    built, service, prepared, user = prepared_case(tmp_path, board, port, lcd)
    expected = 'Robin_nano.bin' if lcd is None else ('Robin_nano43.bin' if lcd else 'Robin_nano35.bin')
    assert Path(prepared.staged_path).name == expected
    assert prepared.sha256 != built.sha256
    assert verify_prepared_artifact(prepared) == built.path
    evidence = artifact_evidence(user)
    assert evidence['sha256'] == prepared.sha256
    assert evidence['build']['sha256'] == built.sha256
    checkpoint = transition_checkpoint(create_checkpoint(user, identity_reader=identity_reader()),
        FirmwareWorkflowState.ARTIFACT_READY, artifact=evidence)
    assert validate_checkpoint(checkpoint)['artifact']['path'] == prepared.staged_path
    assert set(generation_pin_reservations(user)['mcu']) == set(SERIAL_PINS[port].split(','))
    restored = dict(checkpoint['wizard_data'], workflow_checkpoint=checkpoint)
    assert set(generation_pin_reservations(restored)['mcu']) == set(SERIAL_PINS[port].split(','))
    provider, runner = Mock(), Mock()
    result = service.execute(prepared, DeploymentExecutionContext(media_path_provider=provider, command_runner=runner))
    assert result.status is DeploymentStatus.ACTION_REQUIRED and not result.ok
    provider.assert_not_called(); runner.assert_not_called()
    manifest = json.loads((tmp_path/'out/deployment-manifest.json').read_text())
    assert manifest['deployment']['transformation'] == prepared.transformation


@pytest.mark.parametrize('change', ['native', 'final', 'rehash_final', 'double', 'missing_native', 'missing_final',
                                   'filename', 'script', 'port', 'native_hash', 'schema', 'lcd_type'])
def test_corruption_rejects_execution_and_recovery(tmp_path, change):
    built, service, prepared, user = prepared_case(tmp_path)
    evidence = artifact_evidence(user)
    source, final = Path(built.path), Path(prepared.staged_path)
    proof = deepcopy(prepared.transformation)
    if change == 'native': source.write_bytes(source.read_bytes() + b'x')
    elif change in ('final', 'rehash_final'):
        data = bytearray(final.read_bytes()); data[350] ^= 1; final.write_bytes(data)
        if change == 'rehash_final':
            proof['final_sha256'] = hashlib.sha256(data).hexdigest()
            evidence['sha256'] = proof['final_sha256']
            prepared = replace(prepared, sha256=proof['final_sha256'])
    elif change == 'double': final.write_bytes(source.read_bytes())
    elif change == 'missing_native': source.unlink()
    elif change == 'missing_final': final.unlink()
    else:
        key, value = {'filename': ('final_filename', 'Robin_nano43.bin'), 'script': ('script_sha256', '0'*64),
            'port': ('serial_port', 'USART1'), 'native_hash': ('native_sha256', '0'*64),
            'schema': ('schema', 'other'), 'lcd_type': ('lcd_removed', 0)}[change]
        proof[key] = value
    prepared = replace(prepared, transformation=proof)
    user['prepared_firmware_deployment'] = prepared
    assert service.execute(prepared).status is DeploymentStatus.FAILED
    with pytest.raises(FirmwareWorkflowError): artifact_evidence(user)
    evidence['transformation'] = proof
    cp = transition_checkpoint(create_checkpoint(user, identity_reader=identity_reader()),
        FirmwareWorkflowState.ARTIFACT_READY, artifact=evidence)
    with pytest.raises(CheckpointIncompatible): validate_checkpoint(cp)


@pytest.mark.parametrize('lcd', [None, 0, 1, 'removed', 'false'])
def test_sapphire_needs_a_physical_boolean_choice(tmp_path, lcd):
    from firmware.board_serial import SAPPHIRE
    built = native(tmp_path)
    with pytest.raises(FirmwareIdentityError):
        prepare_robin(built.path, built.firmware_identity, board=SAPPHIRE[0], serial_port='USART3', lcd_removed=lcd, output_dir=tmp_path/'out')
    assert not (tmp_path/'out').exists()


def test_native_identity_cannot_be_replaced_or_processed_twice(tmp_path):
    built, service, prepared, user = prepared_case(tmp_path)
    with pytest.raises(FirmwareIdentityError):
        prepare_robin(prepared.staged_path, built.firmware_identity, board=KINGROON, serial_port='USART3', lcd_removed=None, output_dir=tmp_path/'twice')
    with pytest.raises(FirmwareIdentityError):
        service.prepare_robin(prepared.plan, serial_port='USART3', lcd_removed=None)
    assert verify_prepared_artifact(prepared) == built.path
    with pytest.raises(DeploymentArtifactError): verify_prepared_artifact(replace(prepared, transformation=None))


def test_wrong_revision_and_unknown_alias_fail_before_writing(tmp_path):
    built = native(tmp_path, revision='b'*40)
    for board in (KINGROON, 'other.cfg'):
        with pytest.raises(FirmwareIdentityError):
            prepare_robin(built.path, built.firmware_identity, board=board, serial_port='USART3', lcd_removed=None, output_dir=tmp_path/'out')
    assert not (tmp_path/'out').exists()


def test_failed_publication_preserves_native_and_has_no_ready_manifest(tmp_path):
    built = native(tmp_path)
    service = FirmwareDeploymentService(output_dir=str(tmp_path/'out'), event_sink=lambda _: None)
    plan = service.plan(built, DeploymentTarget(KINGROON, 'stm32f103'), DeploymentMethodId.MANUAL)
    with patch('firmware.robin.os.link', side_effect=OSError('publication interrupted')):
        with pytest.raises(FirmwareIdentityError): service.prepare_robin(plan, serial_port='USART3', lcd_removed=None)
    assert hashlib.sha256(Path(built.path).read_bytes()).hexdigest() == built.sha256
    assert not list((tmp_path/'out').rglob('Robin_nano.bin'))
    assert not (tmp_path/'out/deployment-manifest.json').exists()


def test_changed_lcd_choice_and_removed_proof_are_not_valid_recovery(tmp_path):
    from firmware.board_serial import SAPPHIRE
    built, service, prepared, user = prepared_case(tmp_path, SAPPHIRE[0], 'USART3', False)
    evidence = artifact_evidence(user)
    cp = transition_checkpoint(create_checkpoint(user, identity_reader=identity_reader()),
        FirmwareWorkflowState.ARTIFACT_READY, artifact=evidence)
    with pytest.raises(CheckpointIncompatible): validate_checkpoint(cp, current_hardware=dict(user, robin_lcd_removed=True))
    evidence.pop('transformation')
    cp = transition_checkpoint(create_checkpoint(user, identity_reader=identity_reader()),
        FirmwareWorkflowState.ARTIFACT_READY, artifact=evidence)
    with pytest.raises(CheckpointIncompatible): validate_checkpoint(cp)
