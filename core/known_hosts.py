"""Fail-closed, atomic storage for KACE SSH host trust."""

from contextlib import contextmanager
import os
import tempfile
import threading
import time


LOCK_TIMEOUT_SECONDS = 5.0
_thread_lock = threading.RLock()


def _restrict_permissions(path: str, *, directory: bool = False) -> None:
    """Restrict trust storage to the current user on KACE's POSIX runtime."""
    os.chmod(path, 0o700 if directory else 0o600)


def atomic_write_known_hosts(path: str, content: str) -> None:
    """Durably replace known_hosts without exposing partial file contents."""
    directory = os.path.dirname(os.path.abspath(path))
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=".known_hosts.", suffix=".part", dir=directory
    )
    descriptor_open = True
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            descriptor_open = False
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        _restrict_permissions(temporary_path)
        os.replace(temporary_path, path)
        _restrict_permissions(path)
        if os.name != "nt":
            directory_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except Exception:
        if descriptor_open:
            os.close(descriptor)
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass
        raise


@contextmanager
def known_hosts_lock(known_hosts_path: str):
    """Serialize trust read/connect/publish across threads and processes."""
    lock_path = os.path.join(os.path.dirname(known_hosts_path), "known_hosts.lock")
    if not _thread_lock.acquire(timeout=LOCK_TIMEOUT_SECONDS):
        raise TimeoutError("Timed out locking SSH known_hosts storage.")
    try:
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        lock_file = os.fdopen(descriptor, "r+b", closefd=True)
        acquired = False
        try:
            if os.path.getsize(lock_path) == 0:
                lock_file.write(b"\0")
                lock_file.flush()
                os.fsync(lock_file.fileno())
            _restrict_permissions(lock_path)
            deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
            while True:
                try:
                    lock_file.seek(0)
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Timed out locking SSH known_hosts storage.")
                    time.sleep(0.05)
            yield
        finally:
            if acquired:
                lock_file.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()
    finally:
        _thread_lock.release()


def get_known_hosts_path() -> str:
    """Create and return KACE's private trust file."""
    directory = os.path.join(os.path.expanduser("~"), ".config", "kace")
    os.makedirs(directory, mode=0o700, exist_ok=True)
    _restrict_permissions(directory, directory=True)
    path = os.path.join(directory, "known_hosts")
    with known_hosts_lock(path):
        if not os.path.exists(path):
            atomic_write_known_hosts(path, "")
        else:
            _restrict_permissions(path)
    return path


def persist_host_keys_atomically(
    paramiko_module, client, known_hosts_path: str, *, lock_held: bool = False
) -> None:
    """Merge accepted keys and publish them atomically under the trust lock."""
    def merge_and_publish() -> None:
        merged = paramiko_module.HostKeys()
        if os.path.getsize(known_hosts_path) > 0:
            merged.load(known_hosts_path)
        for hostname, keys in client.get_host_keys().items():
            for key_type, key in keys.items():
                merged.add(hostname, key_type, key)
        lines = []
        for hostname in sorted(merged.keys()):
            for key_type, key in sorted(merged[hostname].items()):
                lines.append(f"{hostname} {key_type} {key.get_base64()}\n")
        atomic_write_known_hosts(known_hosts_path, "".join(lines))

    if lock_held:
        merge_and_publish()
    else:
        with known_hosts_lock(known_hosts_path):
            merge_and_publish()
