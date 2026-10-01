"""Board startup is part of firmware, not a PRINT_START convention."""
import json
import zlib
from unittest.mock import Mock, patch

import pytest

from firmware.configuration import klipper_config
from firmware.derivation import derive_config
from firmware.firmware_generator import generate_firmware_config
from firmware.validator import validate_config
from firmware.startup_gpio import CR10_SMART_PRO, required_startup_pins, verify_startup_artifact
from firmware.identity import FirmwareBuildInputs, FirmwareIdentityError, ToolchainIdentity
from firmware.artifacts import BuildArtifact
from firmware.deployment.service import FirmwareDeploymentService
from firmware.deployment.models import DeploymentTarget, DeploymentMethodId, DeploymentArtifactError
from core.firmware_workflow import (artifact_evidence, generation_pin_reservations, create_checkpoint,
    transition_checkpoint, validate_checkpoint, FirmwareWorkflowState, CheckpointIncompatible,
    FirmwareWorkflowError)
from tests.unit.test_firmware_workflow import identity_reader


def requested():
    config = derive_config('stm32f103', 'uart', flash_start='0x10000')
    config['CONFIG_CLOCK_REF_FREQ'] = '8000000'
    return config


def artifact(tmp_path, pins='PA0', config='"PA0"'):
    text = 'CONFIG_MCU="stm32"\n'
    if config is not None: text += f'CONFIG_INITIAL_PINS={config}\n'
    inputs = FirmwareBuildInputs.create(klipper_commit='b'*40, canonical_config=text,
        toolchain=ToolchainIdentity('make','test','gcc','test'),build_id='a'*32)
    constants = {'MCU':'stm32f103xe'}
    if pins is not None: constants['INITIAL_PINS'] = pins
    data = {'version':inputs.reported_version, 'config':constants}
    path = tmp_path/'klipper.bin'
    path.write_bytes(b'prefix'+zlib.compress(json.dumps(data).encode())+b'suffix')
    return BuildArtifact.create(path=str(path),native_filename=path.name,size_bytes=path.stat().st_size,
        mcu='stm32f103',firmware_fingerprint=inputs.reported_version,mock_build=False,
        size_warning=False,build_identity=inputs)


def test_only_selected_board_enables_pa0():
    assert klipper_config(requested(),'stm32f103',board=CR10_SMART_PRO)['CONFIG_INITIAL_PINS']=='"PA0"'
    assert 'CONFIG_INITIAL_PINS' not in klipper_config(requested(),'stm32f103',board='other.cfg')
    assert required_startup_pins('other.cfg')==()


def test_board_requirement_cannot_use_untyped_writer_or_validator(tmp_path):
    cfg=tmp_path/'.config'; cfg.write_text('existing')
    ok,detail=generate_firmware_config(requested(),str(tmp_path),board=CR10_SMART_PRO)
    assert not ok and 'processor' in detail and cfg.read_text()=='existing'
    ok,detail=validate_config(str(tmp_path),board=CR10_SMART_PRO)
    assert not ok and 'startup GPIO' in detail


@pytest.mark.parametrize('model',['stm32f103x6','stm32f446','rp2040','atmega2560'])
def test_wrong_processor_cannot_inherit_pa0(model):
    with pytest.raises(ValueError,match='STM32F103'):
        required_startup_pins(CR10_SMART_PRO,model)


def test_wizard_passes_board_authority_to_builder():
    from core.firmware_wizard import run_firmware_wizard
    from core.translations import t
    with patch('core.firmware_wizard.yes_no',return_value=True), \
         patch('core.firmware_wizard._resolve_firmware_configuration',return_value=(requested(),'stm32f103','uart')), \
         patch('core.firmware_wizard.numbered_select',return_value=t('builder.compile_now')), \
         patch('core.firmware_wizard.build_firmware_orchestrator',return_value={'status':'error','message':'stop'}) as build:
        run_firmware_wizard({'board':CR10_SMART_PRO,'printer_profile':'unrelated.cfg',
                             'mcu_type':'stm32f103','mcu_hint':'uart'})
    assert build.call_args.kwargs['board']==CR10_SMART_PRO


@pytest.mark.parametrize('line',['','CONFIG_INITIAL_PINS="!PA0"\n','CONFIG_INITIAL_PINS="PA1"\n'])
def test_resolved_kconfig_must_preserve_required_pin(tmp_path,line):
    ok,detail=generate_firmware_config(requested(),str(tmp_path),processor='stm32f103',board=CR10_SMART_PRO)
    assert ok, detail
    cfg=tmp_path/'.config'
    text=cfg.read_text().replace('CONFIG_INITIAL_PINS="PA0"\n',line)
    # Match the derived flash address; the new startup assertion must be the failure.
    cfg.write_text(text+'CONFIG_FLASH_APPLICATION_ADDRESS=0x08010000\n')
    ok,detail=validate_config(str(tmp_path),requested=requested(),processor='stm32f103',board=CR10_SMART_PRO)
    assert not ok and 'CONFIG_INITIAL_PINS' in detail


@pytest.mark.parametrize('pins',[None,'','!PA0','PA1','PA0,PA1'])
def test_matching_build_identity_does_not_bless_missing_or_changed_startup(tmp_path,pins):
    built=artifact(tmp_path,pins=pins)
    with pytest.raises(FirmwareIdentityError,match='startup GPIO'):
        verify_startup_artifact(CR10_SMART_PRO,built.path,built.firmware_identity)
    assert not FirmwareDeploymentService(output_dir=str(tmp_path)).available_methods(
        DeploymentTarget(board=CR10_SMART_PRO,mcu='stm32f103'),built)


@pytest.mark.parametrize('config',[None,'""','"!PA0"','"PA1"'])
def test_embedded_pin_does_not_bless_inconsistent_build_input(tmp_path,config):
    built=artifact(tmp_path,config=config)
    with pytest.raises(FirmwareIdentityError,match='CONFIG_INITIAL_PINS'):
        verify_startup_artifact(CR10_SMART_PRO,built.path,built.firmware_identity)


def test_valid_firmware_and_changed_bytes(tmp_path):
    built=artifact(tmp_path)
    verify_startup_artifact(CR10_SMART_PRO,built.path,built.firmware_identity)
    with open(built.path,'ab') as dest: dest.write(b'changed')
    with pytest.raises(FirmwareIdentityError,match='bytes changed'):
        verify_startup_artifact(CR10_SMART_PRO,built.path,built.firmware_identity)


def test_old_artifact_cannot_resume_or_publish_config(tmp_path):
    built=artifact(tmp_path,pins=None)
    user={'board':CR10_SMART_PRO,'mcu_type':'stm32f103','firmware_artifact':built,
          'firmware_path':built.path,'mcu_path':'/dev/serial/by-id/test'}
    with pytest.raises(FirmwareWorkflowError,match='startup GPIO'):
        artifact_evidence(user)
    with pytest.raises(FirmwareIdentityError,match='startup GPIO'):
        generation_pin_reservations(user)
    checkpoint=create_checkpoint(user,identity_reader=identity_reader())
    evidence={'path':built.path,'sha256':built.sha256,'size_bytes':built.size_bytes,
              'build':built.to_dict(),'final_filename':'klipper.bin','method':'manual','strategy':'MANUAL'}
    checkpoint=transition_checkpoint(checkpoint,FirmwareWorkflowState.ARTIFACT_READY,artifact=evidence)
    with pytest.raises(CheckpointIncompatible,match='startup GPIO'):
        validate_checkpoint(checkpoint)


def test_valid_manual_prepare_rechecks_startup_before_staging(tmp_path):
    from dataclasses import replace
    built=artifact(tmp_path)
    service=FirmwareDeploymentService(output_dir=str(tmp_path/'output'),event_sink=lambda _:None)
    target=DeploymentTarget(board=CR10_SMART_PRO,mcu='stm32f103')
    plan=service.plan(built,target,DeploymentMethodId.MANUAL)
    prepared=service.prepare(plan)
    assert prepared.sha256==built.sha256
    other=tmp_path/'old'; other.mkdir()
    old=artifact(other,pins=None)
    with patch('firmware.deployment.service.shutil.copy2') as copy:
        with pytest.raises(DeploymentArtifactError,match='startup GPIO'):
            service.prepare(replace(plan,artifact=old))
    copy.assert_not_called()
    old_prepared=replace(prepared,plan=replace(plan,artifact=old),staged_path=old.path,sha256=old.sha256)
    with patch.object(service.registry,'get') as executor:
        result=service.execute(old_prepared)
    assert result.error_code=='ARTIFACT_UNSAFE' and 'startup GPIO' in result.detail
    executor.assert_not_called()


def test_malformed_checkpoint_identity_has_a_controlled_failure(tmp_path):
    built=artifact(tmp_path)
    metadata=built.firmware_identity.to_dict(); metadata['canonical_config']=None
    with pytest.raises(FirmwareIdentityError,match='configuration evidence'):
        verify_startup_artifact(CR10_SMART_PRO,built.path,metadata)


@pytest.mark.parametrize('pins',[None,'!PA0'])
def test_builder_rejects_wrong_embedded_startup_before_copy(tmp_path,pins):
    from firmware.builder import build_firmware_orchestrator, BuildContext
    checkout=tmp_path/'source'; checkout.mkdir()
    (checkout/'Makefile').write_text('$(PYTHON) ./scripts/buildcommands.py -d $(OUT)klipper.dict')
    inputs=FirmwareBuildInputs.create(klipper_commit='b'*40,
        canonical_config='CONFIG_MCU="stm32"\nCONFIG_INITIAL_PINS="PA0"\n',
        toolchain=ToolchainIdentity('make','test','gcc','test'),build_id='a'*32)
    def run(argv,**kwargs):
        if 'olddefconfig' in argv:
            with (checkout/'.config').open('a') as cfg:
                cfg.write('CONFIG_MCU="stm32"\nCONFIG_FLASH_APPLICATION_ADDRESS=0x08010000\n')
        elif 'clean' not in argv:
            out=checkout/'out'; out.mkdir(exist_ok=True)
            constants={'MCU':'stm32f103xe'}
            if pins is not None: constants['INITIAL_PINS']=pins
            data={'version':inputs.reported_version,'config':constants}
            (out/'klipper.bin').write_bytes(zlib.compress(json.dumps(data).encode()))
    with patch('firmware.builder.subprocess.run',side_effect=run), \
         patch('firmware.builder.create_build_inputs',return_value=inputs), \
         patch('firmware.builder.shutil.copy2') as copy:
        result=build_firmware_orchestrator(derived_mcu='stm32f103',board=CR10_SMART_PRO,
            config_dict=requested(),klipper_path=str(checkout),output_dir=str(tmp_path/'output'),
            build_context=BuildContext(concurrency=1))
    assert result['status']=='error' and 'startup GPIO' in result['message']
    assert 'CONFIG_INITIAL_PINS="PA0"' in (checkout/'.config').read_text()
    copy.assert_not_called()
