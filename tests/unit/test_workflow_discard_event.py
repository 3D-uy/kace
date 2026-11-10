"""Studio can retire an old progress view only after the approved archive succeeds."""
import json
from unittest.mock import patch

import pytest

from core.firmware_workflow import (
    CheckpointConflict, create_checkpoint, discard_checkpoint, load_checkpoint, write_checkpoint,
)


def saved_checkpoint(tmp_path):
    data = {'board': 'generic-bigtreetech-skr-v1.4.cfg', 'mcu_type': 'lpc1769',
            'language': 'Español'}
    checkpoint = create_checkpoint(data)
    path = tmp_path/'checkpoint.json'
    write_checkpoint(checkpoint, str(path))
    return checkpoint, path


def test_discard_emits_only_after_archival_and_keeps_saved_bytes(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv('KACE_MACHINE_OUTPUT', raising=False)
    checkpoint, path = saved_checkpoint(tmp_path)
    before = path.read_bytes()
    monkeypatch.setenv('KACE_MACHINE_OUTPUT', '1')
    events = []

    def observe(event):
        assert not path.exists()
        assert next(tmp_path.glob('checkpoint.json.discarded-*')).read_bytes() == before
        events.append(event)

    with patch('core.moonraker_deployer.JsonEventSink', return_value=observe):
        discard_checkpoint(checkpoint)
    assert events == [{'schema': 2, 'workflow_kind': 'firmware_deployment',
                       'workflow_id': checkpoint['workflow_id'], 'sequence': checkpoint['sequence'] + 1,
                       'state': 'DISCARDED', 'data': {'language': 'Español'}}]
    assert load_checkpoint(str(path)) is None
    assert checkpoint['state'] == 'HARDWARE_SELECTED'
    assert not capsys.readouterr().out


@pytest.mark.parametrize('failure', ['conflict', 'archive'])
def test_failed_discard_does_not_emit_or_remove_checkpoint(tmp_path, monkeypatch, failure, capsys):
    monkeypatch.delenv('KACE_MACHINE_OUTPUT', raising=False)
    checkpoint, path = saved_checkpoint(tmp_path)
    if failure == 'conflict':
        path.write_bytes(path.read_bytes() + b'\n')
    before = path.read_bytes()
    monkeypatch.setenv('KACE_MACHINE_OUTPUT', '1')
    with patch('core.moonraker_deployer.JsonEventSink') as sink:
        if failure == 'archive':
            with patch('core.firmware_workflow.os.replace', side_effect=OSError('archive unavailable')):
                with pytest.raises(OSError):
                    discard_checkpoint(checkpoint)
        else:
            with pytest.raises(CheckpointConflict):
                discard_checkpoint(checkpoint)
        sink.assert_not_called()
    assert path.read_bytes() == before
    assert not list(tmp_path.glob('*.discarded-*'))
    assert not capsys.readouterr().out


def test_closed_terminal_does_not_undo_archival(tmp_path, monkeypatch):
    monkeypatch.delenv('KACE_MACHINE_OUTPUT', raising=False)
    checkpoint, path = saved_checkpoint(tmp_path)
    before = path.read_bytes()
    monkeypatch.setenv('KACE_MACHINE_OUTPUT', '1')
    with patch('core.moonraker_deployer.JsonEventSink', side_effect=BrokenPipeError):
        discard_checkpoint(checkpoint)
    assert not path.exists()
    assert next(tmp_path.glob('*.discarded-*')).read_bytes() == before


def test_plain_cli_discard_has_no_machine_output(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv('KACE_MACHINE_OUTPUT', raising=False)
    checkpoint, path = saved_checkpoint(tmp_path)
    discard_checkpoint(checkpoint)
    assert not path.exists()
    assert not capsys.readouterr().out
