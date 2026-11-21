"""Directory publication barriers for KACE's POSIX persistent state.

Windows retains the existing file-fsync/atomic-replace behavior. Python does
not provide the POSIX directory-fsync contract there; this module does not
claim equivalent power-loss durability on that platform.
"""
from __future__ import annotations

import os
from pathlib import Path


def fsync_directory(directory: Path | str) -> None:
    """Persist directory metadata on POSIX, propagating unsupported/error cases."""
    if os.name != "posix":
        return
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def ensure_durable_directory(directory: Path | str, *, exist_ok: bool = True, mode: int = 0o777) -> None:
    """Create parents in order, committing each name before creating its child.

    Sync the existing ancestor's parent as well: a previous attempt may have
    created that ancestor and then failed its publication barrier.
    """
    path = Path(directory).absolute()
    missing = []
    ancestor = path
    while not ancestor.exists():
        missing.append(ancestor)
        ancestor = ancestor.parent
    if not ancestor.is_dir():
        raise NotADirectoryError(str(ancestor))
    if not missing and not exist_ok:
        raise FileExistsError(str(path))
    fsync_directory(ancestor.parent)
    for child in reversed(missing):
        child.mkdir(mode=mode, exist_ok=exist_ok if child == path else True)
        fsync_directory(child)
        fsync_directory(child.parent)
