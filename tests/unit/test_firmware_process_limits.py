"""Synthetic subprocesses only: no firmware tools, block devices or network."""
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from firmware.process_runner import (
    ProcessCancelled, ProcessOutputLimitExceeded, run_process,
)


def test_normal_result_and_failed_exit_keep_subprocess_contract():
    result = run_process([sys.executable, '-c', 'print("ok")'], timeout=3)
    assert result.stdout == 'ok\n'
    assert result.stderr == ''
    assert result.returncode == 0
    with pytest.raises(subprocess.CalledProcessError) as error:
        run_process([sys.executable, '-c', 'import sys; print("bad", file=sys.stderr); sys.exit(7)'], timeout=3, check=True)
    assert error.value.returncode == 7
    assert error.value.stderr == 'bad\n'


def test_output_limit_rejects_instead_of_reporting_truncated_success():
    with pytest.raises(ProcessOutputLimitExceeded) as error:
        run_process([sys.executable, '-c', 'import sys; sys.stdout.write("x" * 1000000)'],
                    timeout=3, max_output_bytes=4096)
    assert len(error.value.stdout.encode()) + len(error.value.stderr.encode()) <= 4096


def test_timeout_does_not_return_success():
    start = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run_process([sys.executable, '-c', 'import time; time.sleep(30)'], timeout=.15)
    assert time.monotonic() - start < 4


def test_pre_cancelled_operation_never_starts(monkeypatch):
    event = threading.Event()
    event.set()
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **kw: pytest.fail('cancelled command started'))
    with pytest.raises(ProcessCancelled):
        run_process([sys.executable, '-c', 'raise SystemExit(0)'], cancel_event=event)


def test_cancel_during_operation_closes_process():
    event = threading.Event()
    timer = threading.Timer(.15, event.set)
    timer.start()
    try:
        with pytest.raises(ProcessCancelled):
            run_process([sys.executable, '-c', 'import time; time.sleep(30)'],
                        timeout=3, cancel_event=event)
    finally:
        timer.cancel()
        timer.join()


@pytest.mark.parametrize('value', [0, -1, float('nan'), float('inf'), True])
def test_invalid_timeout_rejected_before_launch(value, monkeypatch):
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **kw: pytest.fail('invalid command started'))
    with pytest.raises(ValueError):
        run_process(['unused'], timeout=value)


@pytest.mark.skipif(os.name != 'posix', reason='POSIX process-group cleanup, not Windows qualification')
def test_timeout_terminates_child_even_if_leader_exits(tmp_path):
    pid = tmp_path / 'child.pid'
    code = ('import subprocess, sys; '
            'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"]); '
            'open(sys.argv[1],"w").write(str(p.pid))')
    with pytest.raises(subprocess.TimeoutExpired):
        run_process([sys.executable, '-c', code, str(pid)], timeout=.3)
    child = int(pid.read_text())
    status = Path(f'/proc/{child}/stat')
    # A reaped or zombie child is no longer executing; container PID1 may defer reaping.
    assert not status.exists() or status.read_text().split()[2] == 'Z'


@pytest.mark.skipif(os.name != 'posix', reason='POSIX group cleanup, Windows qualification pending')
def test_cancel_without_budget_interrupts_child_pipe_drain(tmp_path):
    pid = tmp_path / 'child.pid'
    code = ('import subprocess, sys; '
            'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"]); '
            'open(sys.argv[1],"w").write(str(p.pid))')
    event = threading.Event()
    timer = threading.Timer(.3, event.set)
    timer.start()
    start = time.monotonic()
    try:
        with pytest.raises(ProcessCancelled):
            run_process([sys.executable, '-c', code, str(pid)], cancel_event=event)
    finally:
        timer.cancel()
        timer.join()
    assert time.monotonic() - start < 4
    child = int(pid.read_text())
    status = Path(f'/proc/{child}/stat')
    assert not status.exists() or status.read_text().split()[2] == 'Z'
    assert not any(t.name.startswith('kace-command-output-') for t in threading.enumerate())


def test_keyboard_interrupt_cleans_up_before_propagating(monkeypatch):
    from types import SimpleNamespace
    from firmware import process_runner
    real_sleep = time.sleep
    calls = 0
    def interrupt_once(seconds):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise KeyboardInterrupt()
        real_sleep(seconds)
    monkeypatch.setattr(process_runner, 'time', SimpleNamespace(monotonic=time.monotonic, sleep=interrupt_once))
    with pytest.raises(KeyboardInterrupt):
        run_process([sys.executable, '-c', 'import time; time.sleep(30)'])
    assert not any(t.name.startswith('kace-command-output-') for t in threading.enumerate())


def test_nonzero_exit_cannot_trigger_output_limit_lto_retry():
    with pytest.raises(ProcessOutputLimitExceeded) as error:
        run_process([sys.executable, '-c', 'import sys; sys.stderr.write("ltrans "*2000); sys.exit(2)'],
                    timeout=3, max_output_bytes=128, check=True)
    assert not isinstance(error.value, subprocess.CalledProcessError)


@pytest.mark.parametrize('failure, code', [
    (ProcessCancelled('cancelled'), 'BUILD_CANCELLED'),
    (subprocess.TimeoutExpired(['make'], 1, stderr='ltrans'), 'BUILD_TIMEOUT'),
    (ProcessOutputLimitExceeded(16, '', 'ltrans'), 'BUILD_OUTPUT_LIMIT'),
])
def test_builder_limits_never_retry_or_publish(failure, code, tmp_path):
    from unittest.mock import patch
    from firmware.builder import BuildContext, build_firmware_orchestrator
    from firmware.identity import FirmwareIdentityError
    completed = subprocess.CompletedProcess(['make'], 0, '', '')
    with patch('firmware.builder.generate_firmware_config', return_value=(True, '')), \
         patch('firmware.builder.validate_config', return_value=(True, '')), \
         patch('firmware.builder.create_build_inputs', side_effect=FirmwareIdentityError('synthetic build')), \
         patch('firmware.builder.run_process', side_effect=[completed, completed, failure]) as runner:
        result = build_firmware_orchestrator(
            klipper_path=str(tmp_path), output_dir=str(tmp_path / 'published'),
            config_dict={}, build_context=BuildContext(concurrency=1),
        )
    assert result['status'] == 'error'
    assert result['error_code'] == code
    assert runner.call_count == 3
    assert not (tmp_path / 'published').exists()


def test_eject_timeout_returns_failure_without_retry(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from firmware.boards import executor
    calls = []
    def fail(argv):
        calls.append(argv)
        raise subprocess.TimeoutExpired(argv, 120)
    monkeypatch.setattr(executor, 'os', SimpleNamespace(name='posix', path=SimpleNamespace(ismount=lambda path: False)))
    monkeypatch.setattr(executor.shutil, 'which', lambda name: '/fixture/udisksctl')
    selected = SimpleNamespace(device_path='/dev/synthetic-only', mount_path=str(tmp_path))
    result = executor.LinuxSafeEjector(command_runner=fail).eject(selected)
    assert result.status == executor.SafeEjectStatus.FAILED
    assert 'verify the selected media' in result.detail
    assert len(calls) == 1


def test_discovery_timeout_does_not_return_empty_success(monkeypatch):
    from types import SimpleNamespace
    from firmware.boards import executor
    monkeypatch.setattr(executor, 'os', SimpleNamespace(name='posix'))
    def fail(argv):
        raise subprocess.TimeoutExpired(argv, 3)
    with pytest.raises(executor.MediaSelectionError, match='did not complete'):
        executor.LinuxRemovableMediaProvider(command_runner=fail).list_candidates()


def test_slow_identity_query_respects_explicit_budget(tmp_path):
    from firmware.identity import FirmwareIdentityError, _first_version_line
    command = [sys.executable, '-c', 'import time; time.sleep(.15); print("synthetic compiler 1")']
    env = dict(os.environ, KACE_IDENTITY_TIMEOUT_SECONDS='.05')
    with pytest.raises(FirmwareIdentityError, match='could not identify build tool') as error:
        _first_version_line(command, cwd=str(tmp_path), env=env)
    assert isinstance(error.value.__cause__, subprocess.TimeoutExpired)
    env['KACE_IDENTITY_TIMEOUT_SECONDS'] = '3'
    assert _first_version_line(command, cwd=str(tmp_path), env=env) == 'synthetic compiler 1'


def test_output_limit_is_combined_across_streams():
    with pytest.raises(ProcessOutputLimitExceeded) as error:
        run_process([sys.executable, '-c', 'import sys; sys.stdout.write("x"*3000); sys.stderr.write("y"*3000)'],
                    timeout=3, max_output_bytes=4096)
    assert len(error.value.stdout) + len(error.value.stderr) <= 4096


def test_empty_processor_probe_never_enables_unlimited_make_jobs(tmp_path):
    from unittest.mock import patch
    from firmware.builder import build_firmware_orchestrator
    from firmware.identity import FirmwareIdentityError
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, '', '')
    with patch('firmware.builder.generate_firmware_config', return_value=(True, '')), \
         patch('firmware.builder.validate_config', return_value=(True, '')), \
         patch('firmware.builder.create_build_inputs', side_effect=FirmwareIdentityError('synthetic build')), \
         patch('firmware.builder.run_process', side_effect=run):
        build_firmware_orchestrator(klipper_path=str(tmp_path), output_dir=str(tmp_path / 'output'), config_dict={})
    assert ['nproc'] in commands
    assert commands[-1] == ['make']
