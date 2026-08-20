"""Disk-backed disposable workspaces for KACE's heavy workflows."""

from __future__ import annotations

from contextlib import contextmanager
import errno
import os
from pathlib import Path
import re
import shutil
import threading
import time
import uuid
from typing import Iterator


GIB = 1024 ** 3
CLONE_MINIMUM_FREE_BYTES = GIB
CHECKOUT_MINIMUM_FREE_BYTES = 2 * GIB
BUILD_MINIMUM_FREE_BYTES = 2 * GIB
_NO_SPACE_MARKERS = (
    "no space left on device",
    "enospc",
    "out of diskspace",
    "disk full",
)
_MEMORY_FILESYSTEMS = frozenset({"tmpfs", "ramfs", "devtmpfs"})
_workspace_thread_lock = threading.RLock()


class WorkspaceSpaceError(RuntimeError):
    """Raised before a heavy operation cannot fit in its workspace."""


class WorkspaceStorageError(RuntimeError):
    """Raised when a heavy workspace is placed on volatile storage."""


def _unescape_mount_path(value: str) -> str:
    return re.sub(
        r"\\([0-7]{3})",
        lambda match: chr(int(match.group(1), 8)),
        value,
    )


def _filesystem_type(path: Path) -> str | None:
    """Return the Linux filesystem type for the most-specific mount of path."""
    mounts = Path("/proc/mounts")
    if not mounts.is_file():
        return None
    try:
        resolved = str(path.resolve())
        matches: list[tuple[int, str]] = []
        for line in mounts.read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if len(fields) < 3:
                continue
            mount_point = _unescape_mount_path(fields[1])
            if resolved == mount_point or resolved.startswith(mount_point.rstrip("/") + "/"):
                matches.append((len(mount_point), fields[2]))
        return max(matches)[1] if matches else None
    except OSError:
        return None


def ensure_disk_backed_workspace(directory: Path | str) -> None:
    """Reject workspaces mounted on volatile memory filesystems such as `/tmp`."""
    path = Path(directory).expanduser().resolve()
    filesystem = _filesystem_type(path)
    if filesystem in _MEMORY_FILESYSTEMS:
        raise WorkspaceStorageError(
            f"Heavy KACE workspace {path} is on volatile {filesystem} storage. "
            "Use ~/.cache/kace on disk or set KACE_CACHE_HOME to a disk-backed path."
        )


def is_no_space_error(detail: object) -> bool:
    """Return whether an OS or tool error represents an exhausted filesystem."""
    if isinstance(detail, OSError) and detail.errno == errno.ENOSPC:
        return True
    text = str(detail).lower()
    return any(marker in text for marker in _NO_SPACE_MARKERS)


def kace_cache_directory() -> Path:
    """Resolve KACE's persistent cache without falling back to system temp."""
    configured = os.environ.get("KACE_CACHE_HOME") or os.environ.get("XDG_CACHE_HOME")
    root = Path(configured).expanduser() if configured else Path.home() / ".cache"
    path = (root / "kace").resolve()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def ensure_free_space(directory: Path | str, required_bytes: int, phase: str) -> None:
    """Fail clearly before a clone, checkout, or build exhausts its filesystem."""
    path = Path(directory).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    available = shutil.disk_usage(path).free
    if available < required_bytes:
        raise WorkspaceSpaceError(
            f"Insufficient disk space for {phase} in {path}: "
            f"need at least {required_bytes / GIB:.1f} GiB free, "
            f"only {available / GIB:.1f} GiB available. "
            "Free space on this filesystem or set KACE_CACHE_HOME to a larger disk."
        )


@contextmanager
def exclusive_file_lock(
    lock_path: Path | str,
    *,
    timeout_seconds: float = 600.0,
) -> Iterator[None]:
    """Serialize a persistent workspace mutation across threads and processes."""
    path = Path(lock_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not _workspace_thread_lock.acquire(timeout=timeout_seconds):
        raise TimeoutError(f"Timed out locking KACE workspace: {path}")
    try:
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        lock_file = os.fdopen(descriptor, "r+b", closefd=True)
        acquired = False
        try:
            if path.stat().st_size == 0:
                lock_file.write(b"\0")
                lock_file.flush()
                os.fsync(lock_file.fileno())
            try:
                path.chmod(0o600)
            except OSError:
                pass
            deadline = time.monotonic() + timeout_seconds
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
                        raise TimeoutError(f"Timed out locking KACE workspace: {path}")
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
        _workspace_thread_lock.release()


@contextmanager
def heavy_workspace(prefix: str, *, parent: Path | str | None = None) -> Iterator[Path]:
    """Create and safely remove an isolated disk-backed KACE workspace."""
    root = Path(parent).expanduser().resolve() if parent else kace_cache_directory() / "workspaces"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    ensure_disk_backed_workspace(root)
    workspace = root / f"{prefix}{uuid.uuid4().hex}"
    workspace.mkdir(mode=0o700)
    try:
        yield workspace
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
