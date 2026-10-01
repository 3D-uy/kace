"""Reviewed Robin USART3 recovery requires its original physical USB bridge."""
from dataclasses import replace
from unittest.mock import Mock, patch

import pytest

from core.firmware_workflow import (artifact_evidence, create_checkpoint, transition_checkpoint,
    verify_reappeared_mcu, FirmwareWorkflowState, FirmwareWorkflowError, CheckpointIncompatible)
from core.mcu_monitor import McuIdentity
from core.translations import get_lang, set_lang, t
from firmware.detector import mcu_context_from_path
from tests.unit.test_robin_transformation import DELIVERIES, prepared_case

SERIAL = '/dev/serial/by-id/usb-1a86_USB_Serial_BRIDGE-if00-port0'
BRIDGE = McuIdentity(SERIAL, '/dev/ttyUSB0', serial='BRIDGE', physical_port='1-1.2',
                     vendor_id='1a86', model_id='7523')
BRIDGE_ROUTES = [(b, p, lcd) for b, p, lcd in DELIVERIES if p == 'USART3']


def awaiting(tmp_path, board, port='USART3', lcd=None, baseline=BRIDGE):
    built, service, prepared, user = prepared_case(tmp_path, board, port, lcd)
    user['mcu_path'] = SERIAL
    cp = create_checkpoint(user, identity_reader=Mock(read=Mock(return_value=baseline)))
    cp = transition_checkpoint(cp, FirmwareWorkflowState.ARTIFACT_READY, artifact=artifact_evidence(user))
    return transition_checkpoint(cp, FirmwareWorkflowState.AWAITING_FLASH), prepared


def observe(cp, candidate=BRIDGE, **kwargs):
    # Only the OS existence check and udev data are simulated. The detector
    # receives an actual bridge-style name, which contains no MCU model.
    with patch('core.firmware_workflow.os.path.exists', return_value=True):
        return verify_reappeared_mcu(cp, detector=lambda: mcu_context_from_path(SERIAL),
            identity_reader=Mock(read=Mock(return_value=candidate)), **kwargs)


@pytest.mark.parametrize('board,port,lcd', BRIDGE_ROUTES)
def test_original_bridge_without_mcu_in_name_can_recover(tmp_path, board, port, lcd):
    cp, prepared = awaiting(tmp_path, board, port, lcd)
    assert mcu_context_from_path(SERIAL)['derived_mcu'] is None
    verified, observed = observe(cp, flash_evidence=True)
    assert verified['state'] == 'MCU_VERIFIED'
    assert observed['derived_mcu'] == 'stm32f103'
    assert verified['hardware']['verified_serial_path'] == SERIAL
    assert verified['hardware']['identity_manually_confirmed'] is False
    assert verified['artifact']['transformation'] == prepared.transformation


@pytest.mark.parametrize('candidate', [
    replace(BRIDGE, physical_port='1-1.3'), replace(BRIDGE, serial='OTHER'),
    replace(BRIDGE, vendor_id='9999'), replace(BRIDGE, model_id='0001'),
    replace(BRIDGE, physical_port=''), replace(BRIDGE, serial='', physical_port=''),
    replace(BRIDGE, vendor_id='', model_id=''), None,
])
def test_conflicting_or_incomplete_bridge_is_not_confirmable(tmp_path, candidate):
    from firmware.board_serial import KINGROON
    cp, _ = awaiting(tmp_path, KINGROON)
    confirm = Mock(return_value=True)
    with pytest.raises(CheckpointIncompatible): observe(cp, candidate, flash_evidence=True, ambiguity_resolver=confirm)
    confirm.assert_not_called()


@pytest.mark.parametrize('baseline', [None, replace(BRIDGE, vendor_id='', model_id=''), replace(BRIDGE, physical_port='')])
def test_missing_original_bridge_evidence_cannot_be_inferred(tmp_path, baseline):
    from firmware.board_serial import KINGROON
    cp, _ = awaiting(tmp_path, KINGROON, baseline=baseline)
    with pytest.raises(CheckpointIncompatible): observe(cp, flash_evidence=True, ambiguity_resolver=lambda _: True)


def test_manual_installation_confirmation_is_still_required(tmp_path):
    from firmware.board_serial import KINGROON
    cp, _ = awaiting(tmp_path, KINGROON)
    with pytest.raises(FirmwareWorkflowError, match='explicit evidence'): observe(cp, flash_evidence=False)


def test_direct_uart_does_not_inherit_usb_bridge_qualification(tmp_path):
    from firmware.board_serial import SAPPHIRE
    cp, _ = awaiting(tmp_path, SAPPHIRE[0], 'USART1', False)
    with pytest.raises(CheckpointIncompatible): observe(cp, flash_evidence=True)


def test_native_only_checkpoint_cannot_inherit_transformed_robin_bridge_contract(tmp_path):
    from firmware.board_serial import KINGROON
    built, service, prepared, user = prepared_case(tmp_path, KINGROON)
    user.pop('prepared_firmware_deployment')
    user['firmware_path'] = built.path
    user['mcu_path'] = SERIAL
    cp = create_checkpoint(user, identity_reader=Mock(read=Mock(return_value=BRIDGE)))
    cp = transition_checkpoint(cp, FirmwareWorkflowState.ARTIFACT_READY, artifact=artifact_evidence(user))
    cp = transition_checkpoint(cp, FirmwareWorkflowState.AWAITING_FLASH)
    with pytest.raises(CheckpointIncompatible): observe(cp, flash_evidence=True)


def test_changed_final_file_blocks_before_observing_devices(tmp_path):
    from pathlib import Path
    from firmware.board_serial import KINGROON
    cp, prepared = awaiting(tmp_path, KINGROON)
    Path(prepared.staged_path).write_bytes(b'changed')
    detector = Mock()
    with pytest.raises(CheckpointIncompatible): verify_reappeared_mcu(cp, detector=detector, flash_evidence=True)
    detector.assert_not_called()


@pytest.mark.parametrize('language', ['English', 'Español', 'Português'])
def test_manual_steps_are_persisted_without_running_commands(tmp_path, language):
    from firmware.board_serial import KINGROON
    previous = get_lang()
    try:
        set_lang(language)
        cp, prepared = awaiting(tmp_path, KINGROON)
        instructions = cp['artifact']['instructions']
        assert [i['id'] for i in instructions] == ['deployment.robin.transformed',
            'deployment.robin.manual_sd', 'deployment.robin.manual_verify']
        assert instructions[1]['text'] == t('deployment.robin.manual_sd', filename='Robin_nano.bin')
        assert 'update_mks_robin.py' in instructions[1]['text']
        assert cp['state'] == 'AWAITING_FLASH'
        assert prepared.plan.automation_eligible is False
    finally:
        set_lang(previous)
