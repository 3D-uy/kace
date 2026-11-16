"""Bounded capture and cancellable subprocesses for firmware tools.

Commands remain argv vectors. POSIX tools own a process group so cancellation
also stops compiler children, including when the original make process exited.
Windows uses taskkill /T when available; POSIX tree cleanup is the qualified
contract for the Linux printer host, not an assertion about detached processes.
"""
from __future__ import annotations

import math
import os
import signal
import subprocess
import threading
import time


DEFAULT_OUTPUT_LIMIT = 8 * 1024 * 1024


class ProcessCancelled(subprocess.SubprocessError):
    """Cancellation is not a compiler failure and must not trigger LTO retry."""


class ProcessOutputLimitExceeded(subprocess.SubprocessError):
    def __init__(self, limit, stdout, stderr):
        super().__init__(f"command output exceeded {limit} bytes; result rejected")
        self.stdout = stdout
        self.stderr = stderr


def validated_timeout(value):
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("command timeout must be a finite positive number")
    timeout = float(value)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("command timeout must be a finite positive number")
    return timeout


def build_command_timeout(environment=None):
    """No guessed Pi build duration: explicit per-command policy until measured."""
    environment = os.environ if environment is None else environment
    value = environment.get("KACE_BUILD_TIMEOUT_SECONDS")
    return validated_timeout(value) if value not in (None, "") else None


def identity_command_timeout(environment=None):
    """Configurable query policy, not a measured maximum for Pi Git checkouts."""
    environment = os.environ if environment is None else environment
    value = environment.get("KACE_IDENTITY_TIMEOUT_SECONDS", "30")
    return validated_timeout(value)


def _terminate_tree(process):
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=.5)
        except subprocess.TimeoutExpired:
            pass
        # The leader may have exited while descendants still hold pipes.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif process.poll() is None:
        # Never interpolate a command line: this PID belongs to our Popen.
        try:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=3, check=False)
        except (OSError, subprocess.SubprocessError):
            process.kill()
    if process.poll() is None:
        process.kill()
    process.wait(timeout=3)


def run_process(argv, *, cwd=None, env=None, check=False, timeout=None,
                cancel_event=None, max_output_bytes=DEFAULT_OUTPUT_LIMIT):
    """Return complete bounded text, or fail; truncated output is never success.

    A timeout covers process execution and pipe draining. Captured bytes across
    stdout/stderr share one maximum; there are no unbounded temporary log files.
    KeyboardInterrupt also tears down the child group before propagating.
    """
    timeout = validated_timeout(timeout)
    if isinstance(max_output_bytes, bool) or not isinstance(max_output_bytes, int) or max_output_bytes < 1:
        raise ValueError("max_output_bytes must be a positive integer")
    if cancel_event is not None and cancel_event.is_set():
        raise ProcessCancelled("command cancelled before launch")
    start = time.monotonic()
    options = {"start_new_session": True} if os.name == "posix" else {
        "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP,
    }
    process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, **options)
    buffers = [bytearray(), bytearray()]
    captured = 0
    capture_lock = threading.Lock()
    exceeded = threading.Event()
    finished = [threading.Event(), threading.Event()]
    errors = []

    def read_output(stream, index):
        nonlocal captured
        try:
            while True:
                block = stream.read1(64 * 1024)
                if not block:
                    break
                with capture_lock:
                    remaining = max_output_bytes - captured
                    buffers[index].extend(block[:remaining])
                    captured += min(len(block), remaining)
                    if len(block) > remaining:
                        exceeded.set()
        except (OSError, ValueError) as exc:
            errors.append(exc)
        finally:
            finished[index].set()

    threads = [threading.Thread(target=read_output, args=(stream, index),
                                name=f"kace-command-output-{index}", daemon=True)
               for index, stream in enumerate((process.stdout, process.stderr))]
    failure = None
    try:
        for thread in threads:
            thread.start()
        while True:
            if exceeded.is_set():
                failure = "output"
                break
            if cancel_event is not None and cancel_event.is_set():
                failure = "cancelled"
                break
            if timeout is not None and time.monotonic() - start >= timeout:
                failure = "timeout"
                break
            if errors:
                raise OSError(f"cannot capture command output: {errors[0]}")
            if process.poll() is not None and all(done.is_set() for done in finished):
                break
            time.sleep(.025)
        if failure is not None:
            _terminate_tree(process)
    except BaseException:
        _terminate_tree(process)
        raise
    finally:
        for thread in threads:
            if thread.ident is not None:
                thread.join(timeout=1)
        for stream, done, thread in zip((process.stdout, process.stderr), finished, threads):
            if done.is_set() or thread.ident is None:
                stream.close()
    if not all(done.is_set() for done in finished):
        raise subprocess.SubprocessError("child output remains open after termination; cleanup unverified")
    if errors:
        raise OSError(f"cannot capture command output: {errors[0]}")
    stdout, stderr = (bytes(buffer).decode("utf-8", errors="replace").replace("\r\n", "\n") for buffer in buffers)
    # A late final read can cross the cap while the leader exits.
    if failure == "output" or exceeded.is_set():
        raise ProcessOutputLimitExceeded(max_output_bytes, stdout, stderr)
    if failure == "cancelled":
        raise ProcessCancelled("command cancelled; process termination completed")
    if failure == "timeout":
        raise subprocess.TimeoutExpired(argv, timeout, output=stdout, stderr=stderr)
    result = subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
    if check:
        result.check_returncode()
    return result
