"""A USB MCU name cannot override Robin image and selected transport proof."""
from dataclasses import replace
from unittest.mock import Mock, patch

import pytest

from core.firmware_workflow import (artifact_evidence, create_checkpoint, transition_checkpoint,
    verify_reappeared_mcu, validate_checkpoint, _with_integrity,
    FirmwareWorkflowState, CheckpointIncompatible)
from firmware.detector import mcu_context_from_path
from tests.unit.test_robin_bridge_recovery import BRIDGE
from tests.unit.test_robin_transformation import DELIVERIES, prepared_case

NAMED_USB = '/dev/serial/by-id/usb-Klipper_stm32f103_ORIGINAL-if00'
IDENTITY = replace(BRIDGE, configured_path=NAMED_USB)
DIRECT_ROUTES = [route for route in DELIVERIES if route[1] == 'USART1']


def checkpoint(tmp_path, board, port, lcd, *, transformed=True):
    built, _, prepared, user = prepared_case(tmp_path, board, port, lcd)
    if not transformed:
        user.pop('prepared_firmware_deployment')
        user['firmware_path'] = built.path
    user['mcu_path'] = NAMED_USB
    cp = create_checkpoint(user, identity_reader=Mock(read=Mock(return_value=IDENTITY)))
    cp = transition_checkpoint(cp, FirmwareWorkflowState.ARTIFACT_READY, artifact=artifact_evidence(user))
    return transition_checkpoint(cp, FirmwareWorkflowState.AWAITING_FLASH)


def recover(cp):
    # This is intentionally an otherwise positively matched original USB
    # identity: failing only on a nameless/different adapter misses the bug.
    with patch('core.firmware_workflow.os.path.exists', return_value=True):
        return verify_reappeared_mcu(cp, flash_evidence=True,
            detector=lambda: mcu_context_from_path(NAMED_USB),
            identity_reader=Mock(read=Mock(return_value=IDENTITY)), ambiguity_resolver=lambda _: True)


@pytest.mark.parametrize('board,port,lcd', DIRECT_ROUTES)
def test_direct_uart_cannot_be_verified_by_a_matched_named_usb_mcu(tmp_path, board, port, lcd):
    cp = checkpoint(tmp_path, board, port, lcd)
    assert mcu_context_from_path(NAMED_USB)['derived_mcu'] == 'stm32f103'
    with pytest.raises(CheckpointIncompatible, match='USART1'):
        recover(cp)
    assert cp['state'] == 'AWAITING_FLASH'
    assert cp['hardware']['verified_serial_path'] == ''


@pytest.mark.parametrize('board,port,lcd', DELIVERIES)
def test_native_only_image_cannot_authorize_robin_recovery(tmp_path, board, port, lcd):
    cp = checkpoint(tmp_path, board, port, lcd, transformed=False)
    with pytest.raises(CheckpointIncompatible, match='transformed Robin'):
        recover(cp)
    assert cp['state'] == 'AWAITING_FLASH'


@pytest.mark.parametrize('board,port,lcd', [r for r in DELIVERIES if r[1] == 'USART3'])
def test_transformed_usart3_retains_matched_usb_recovery(tmp_path, board, port, lcd):
    cp = checkpoint(tmp_path, board, port, lcd)
    verified, _ = recover(cp)
    assert verified['state'] == 'MCU_VERIFIED'
    assert verified['hardware']['verified_serial_path'] == NAMED_USB
    assert validate_checkpoint(verified)['state'] == 'MCU_VERIFIED'


def test_rejected_transport_does_not_scan_or_ask_to_override(tmp_path):
    cp = checkpoint(tmp_path, *DIRECT_ROUTES[0])
    detector, reader, confirm = Mock(), Mock(), Mock(return_value=True)
    with pytest.raises(CheckpointIncompatible, match='USART1'):
        verify_reappeared_mcu(cp, flash_evidence=True, detector=detector,
            identity_reader=reader, ambiguity_resolver=confirm)
    detector.assert_not_called()
    reader.read.assert_not_called()
    confirm.assert_not_called()


@pytest.mark.parametrize('state', ['MCU_VERIFIED', 'CONFIG_GENERATED', 'READY_TO_DEPLOY', 'DEPLOYING', 'COMPLETE'])
@pytest.mark.parametrize('transformed', [True, False])
def test_previous_wrong_success_cannot_be_resumed_with_a_fresh_hash(tmp_path, state, transformed):
    cp = checkpoint(tmp_path, *DIRECT_ROUTES[0], transformed=transformed)
    # Represent an older erroneously advanced checkpoint, not a permitted new
    # transition. A valid checksum must not bless its absent transport proof.
    cp['state'] = state
    cp['hardware']['verified_serial_path'] = NAMED_USB
    cp['hardware']['flash_evidence_recorded_at'] = 1
    cp = _with_integrity(cp)
    for verify_artifact in (False, True):
        with pytest.raises(CheckpointIncompatible, match='USART1|transformed Robin'):
            validate_checkpoint(cp, verify_artifact=verify_artifact)
