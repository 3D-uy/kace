"""Disk-backed disposable workspaces for KACE's heavy workflows."""

from __future__ import annotations

from contextlib import contextmanager
import errno
import os
from pathlib import Path
import shutil
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


class WorkspaceSpaceError(RuntimeError):
    """Raised before a heavy operation cannot fit in its workspace."""


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
def heavy_workspace(prefix: str, *, parent: Path | str | None = None) -> Iterator[Path]:
    """Create and safely remove an isolated disk-backed KACE workspace."""
    root = Path(parent).expanduser().resolve() if parent else kace_cache_directory() / "workspaces"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    workspace = root / f"{prefix}{uuid.uuid4().hex}"
    workspace.mkdir(mode=0o700)
    try:
        yield workspace
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
