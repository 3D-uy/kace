"""Physical LCD selection connects the wizard to verified Robin preparation."""
from pathlib import Path
from unittest.mock import patch

import pytest

from core.exceptions import WizardExit
from core.firmware_wizard import run_firmware_wizard, _select_robin_lcd
from core.firmware_workflow import (artifact_evidence, create_checkpoint, transition_checkpoint,
    validate_checkpoint, FirmwareWorkflowState, CheckpointIncompatible)
from core.translations import t, get_lang, set_lang, get_mode, set_mode
from firmware.board_serial import KINGROON, SAPPHIRE
from firmware.deployment.service import FirmwareDeploymentService
from tests.unit.test_robin_transformation import native, DELIVERIES
from tests.unit.test_firmware_workflow import identity_reader


def run_wizard(tmp_path, board, port, selection, *, auto=False, saved=None, skip=False):
    built = native(tmp_path, port)
    user = {'board': board, 'mcu_type': 'stm32f103', 'firmware_serial_port': port,
            'display': 'none', 'prepared_firmware_deployment': 'obsolete', 'pending_firmware_deployment': True}
    if saved is not None:
        user['robin_lcd_removed'] = saved
    events = []
    service = FirmwareDeploymentService(output_dir=str(tmp_path/'out'), event_sink=events.append)
    answers = [t('builder.compile_now'), 'none' if skip else 'MANUAL']
    if board != KINGROON and not auto and not skip:
        answers.append(selection)
    with patch('core.firmware_wizard.yes_no', return_value=True), \
         patch('core.firmware_wizard.board_reference_clock', return_value='8000000'), \
         patch('core.firmware_wizard._read_deployment_usb_identity', return_value={}), \
         patch('core.firmware_wizard.FirmwareDeploymentService', return_value=service), \
         patch.dict('os.environ', {'KACE_AUTO': '1' if auto else '0'}), \
         patch('core.firmware_wizard.numbered_select', side_effect=answers), \
         patch('core.firmware_wizard.build_firmware_orchestrator', return_value={
             'status': 'success', 'mcu': 'stm32f103', 'path': built.path, 'artifact': built}):
        result = run_firmware_wizard(user)
    return result, user, events


@pytest.mark.parametrize('board,port,lcd', DELIVERIES)
def test_wizard_persists_actual_final_plan_and_recovery_download(tmp_path, board, port, lcd, capsys):
    result, user, events = run_wizard(tmp_path, board, port, 'removed' if lcd else 'present')
    assert result.ok
    prepared = user['prepared_firmware_deployment']
    assert user['firmware_deployment_plan'] is prepared.plan
    assert user['robin_lcd_removed'] is lcd
    assert user['firmware_path'] == prepared.staged_path
    assert prepared.plan.final_filename in capsys.readouterr().out
    cp = transition_checkpoint(create_checkpoint(user, identity_reader=identity_reader()),
                              FirmwareWorkflowState.ARTIFACT_READY, artifact=artifact_evidence(user))
    assert validate_checkpoint(cp)['wizard_data']['robin_lcd_removed'] is lcd
    ready = [e for e in events if e['state'] == 'ARTIFACT_READY'][-1]
    assert ready['data']['staged_path'] == prepared.staged_path
    assert ready['data']['final_filename'] == prepared.plan.final_filename
    import kace
    previous = get_mode()
    try:
        set_mode('Beginner')
        with patch('core.firmware_workflow.checkpoint_path', return_value=str(tmp_path/'recovery/firmware-workflow.json')):
            kace._show_prepared_firmware(cp, view_only=True)
    finally:
        set_mode(previous)
    copy = tmp_path/'recovery/firmware-downloads'/prepared.plan.final_filename
    assert copy.read_bytes() == Path(prepared.staged_path).read_bytes()
    assert t('deployment.robin.transformed', filename=prepared.plan.final_filename) in capsys.readouterr().out


@pytest.mark.parametrize('lcd', [False, True])
def test_explicit_saved_choice_is_used_in_noninteractive_run(tmp_path, lcd):
    result, user, _ = run_wizard(tmp_path, SAPPHIRE[0], 'USART3', None, auto=True, saved=lcd)
    assert result.ok and user['robin_lcd_removed'] is lcd


@pytest.mark.parametrize('saved', [None, 'false', 0, 1])
def test_noninteractive_missing_or_invalid_lcd_never_guesses(tmp_path, saved):
    result, user, events = run_wizard(tmp_path, SAPPHIRE[0], 'USART3', None, auto=True, saved=saved)
    assert not result.ok
    assert 'prepared_firmware_deployment' not in user
    assert 'pending_firmware_deployment' not in user
    assert not any(e['state'] == 'ARTIFACT_READY' for e in events)
    assert not list(tmp_path.rglob('Robin*.bin'))


@pytest.mark.parametrize('answer', [None, 'cancel', 'unexpected'])
def test_lcd_cancellation_does_not_prepare_or_publish(tmp_path, answer):
    with pytest.raises(WizardExit): run_wizard(tmp_path, SAPPHIRE[0], 'USART3', answer)
    assert not list(tmp_path.rglob('Robin*.bin'))
    assert not (tmp_path/'out/deployment-manifest.json').exists()


def test_skip_clears_obsolete_runtime_preparation(tmp_path):
    result, user, events = run_wizard(tmp_path, SAPPHIRE[0], 'USART3', None, skip=True)
    assert result.ok
    assert 'prepared_firmware_deployment' not in user
    assert 'pending_firmware_deployment' not in user
    assert user['firmware_path'].endswith('klipper.bin')
    assert not any(e['state'] == 'ARTIFACT_READY' for e in events)


def test_interactive_choice_replaces_saved_lcd_without_using_display_config(tmp_path):
    result, user, _ = run_wizard(tmp_path, SAPPHIRE[0], 'USART1', 'present', saved=True)
    assert result.ok and user['robin_lcd_removed'] is False
    assert user['firmware_path'].endswith('Robin_nano35.bin')


@pytest.mark.parametrize('language', ['English', 'Español', 'Português'])
def test_lcd_question_is_localized_and_explicit(language):
    previous = get_lang()
    try:
        set_lang(language)
        with patch.dict('os.environ', {'KACE_AUTO': '0'}), patch('core.firmware_wizard.numbered_select', return_value='present') as select:
            assert _select_robin_lcd({'board': SAPPHIRE[0], 'display': 'none'}) is False
        assert select.call_args.args == (t('deployment.robin.lcd_prompt'),)
        assert select.call_args.kwargs['require_explicit'] is True
        assert [c['value'] for c in select.call_args.kwargs['choices']] == ['present', 'removed', 'cancel']
    finally:
        set_lang(previous)


@pytest.mark.parametrize('which', ['native', 'final'])
def test_recovery_view_revalidates_both_files_before_convenience_copy(tmp_path, which):
    result, user, _ = run_wizard(tmp_path, KINGROON, 'USART3', None)
    cp = transition_checkpoint(create_checkpoint(user, identity_reader=identity_reader()),
                              FirmwareWorkflowState.ARTIFACT_READY, artifact=artifact_evidence(user))
    changed = Path(user['firmware_artifact'].path if which == 'native' else user['firmware_path'])
    changed.write_bytes(changed.read_bytes() + b'corrupt')
    import kace
    with patch('core.firmware_workflow.checkpoint_path', return_value=str(tmp_path/'recovery/checkpoint.json')):
        with pytest.raises(CheckpointIncompatible): kace._show_prepared_firmware(cp, view_only=True)
    assert not (tmp_path/'recovery/firmware-downloads').exists()
