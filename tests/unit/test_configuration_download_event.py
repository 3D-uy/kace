"""Studio may offer export only after KACE has published generated state."""
import pytest

from core.firmware_workflow import FirmwareWorkflowState, transition_checkpoint, write_checkpoint
from tests.unit.test_firmware_workflow import awaiting_flash


@pytest.mark.parametrize('state', ['AWAITING_FLASH','MCU_VERIFIED','CONFIG_GENERATED','READY_TO_DEPLOY','DEPLOYING','COMPLETE'])
def test_published_checkpoint_announces_configuration_download_without_claiming_completion(tmp_path, monkeypatch, state):
    checkpoint=awaiting_flash(tmp_path)
    if state!='AWAITING_FLASH':
        checkpoint=transition_checkpoint(checkpoint,FirmwareWorkflowState.VERIFYING_MCU)
        checkpoint=transition_checkpoint(checkpoint,FirmwareWorkflowState.MCU_VERIFIED,
            verified_serial_path='/dev/serial/by-id/test',flash_evidence_recorded_at=1)
        for name in ['CONFIG_GENERATED','READY_TO_DEPLOY','DEPLOYING','COMPLETE']:
            if checkpoint['state']==state: break
            checkpoint=transition_checkpoint(checkpoint,FirmwareWorkflowState(name))
    events=[]
    monkeypatch.setenv('KACE_MACHINE_OUTPUT','1')
    monkeypatch.setattr('core.moonraker_deployer.JsonEventSink',lambda:events.append)
    write_checkpoint(checkpoint,str(tmp_path/'workflow.json'))
    assert len(events)==1
    assert events[0]['state']==state
    assert events[0]['data']['configuration_download_available']==(state in {'CONFIG_GENERATED','READY_TO_DEPLOY','DEPLOYING','COMPLETE'})
