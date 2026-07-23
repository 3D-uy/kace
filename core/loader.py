# core/loader.py
import os
import yaml

_BOARDS_CACHE = None
_DISPLAYS_CACHE = None
_ADVANCED_MODULES_CACHE = None
_VERSION_CACHE = None

_BYPASS_CACHE = False
_BOARDS_PATH_OVERRIDE = None

def set_bypass_cache(bypass: bool) -> None:
    """Toggle in-memory YAML and version caching (useful for dynamic testing configurations)."""
    global _BYPASS_CACHE
    _BYPASS_CACHE = bypass

def set_boards_path_override(path: str) -> None:
    """Override the default path to the boards database and invalidate any loaded cache."""
    global _BOARDS_PATH_OVERRIDE, _BOARDS_CACHE
    _BOARDS_PATH_OVERRIDE = path
    _BOARDS_CACHE = None

def _get_boards_path() -> str:
    if _BOARDS_PATH_OVERRIDE is not None:
        return _BOARDS_PATH_OVERRIDE
    return os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'data', 'boards.yaml'))

def _get_displays_path() -> str:
    return os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'data', 'displays.yaml'))

def _get_advanced_modules_path() -> str:
    return os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'data', 'advanced_modules.yaml'))

def load_boards_yaml() -> dict:
    """Load and parse data/boards.yaml, caching the result in memory."""
    global _BOARDS_CACHE
    if not _BYPASS_CACHE and _BOARDS_CACHE is not None:
        return _BOARDS_CACHE
    path = _get_boards_path()
    # R-01: Wrap file open in a friendly error handler so a missing or corrupt
    # YAML file produces a clear message instead of a raw traceback in main().
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        raise RuntimeError(
            f"[KACE] boards database not found at '{path}'. "
            "Re-run 'git clone' or reinstall KACE to restore the data/ directory."
        )
    except PermissionError:
        raise RuntimeError(f"[KACE] Permission denied reading boards database: '{path}'.")
    except yaml.YAMLError as e:
        raise RuntimeError(f"[KACE] boards.yaml is corrupt or invalid YAML: {e}")
    if not _BYPASS_CACHE:
        _BOARDS_CACHE = data
    return data

def load_displays_yaml() -> dict:
    """Load and parse data/displays.yaml, caching the result in memory."""
    global _DISPLAYS_CACHE
    if not _BYPASS_CACHE and _DISPLAYS_CACHE is not None:
        return _DISPLAYS_CACHE
    path = _get_displays_path()
    # R-01: Same friendly error handling as load_boards_yaml().
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        raise RuntimeError(
            f"[KACE] displays database not found at '{path}'. "
            "Re-run 'git clone' or reinstall KACE to restore the data/ directory."
        )
    except PermissionError:
        raise RuntimeError(f"[KACE] Permission denied reading displays database: '{path}'.")
    except yaml.YAMLError as e:
        raise RuntimeError(f"[KACE] displays.yaml is corrupt or invalid YAML: {e}")
    if not _BYPASS_CACHE:
        _DISPLAYS_CACHE = data
    return data

def load_advanced_modules_yaml() -> dict:
    """Load and parse data/advanced_modules.yaml, caching the result in memory."""
    global _ADVANCED_MODULES_CACHE
    if not _BYPASS_CACHE and _ADVANCED_MODULES_CACHE is not None:
        return _ADVANCED_MODULES_CACHE
    path = _get_advanced_modules_path()
    # R-01: Same friendly error handling as load_boards_yaml().
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        raise RuntimeError(
            f"[KACE] advanced_modules database not found at '{path}'. "
            "Re-run 'git clone' or reinstall KACE to restore the data/ directory."
        )
    except PermissionError:
        raise RuntimeError(f"[KACE] Permission denied reading advanced_modules database: '{path}'.")
    except yaml.YAMLError as e:
        raise RuntimeError(f"[KACE] advanced_modules.yaml is corrupt or invalid YAML: {e}")
    if not _BYPASS_CACHE:
        _ADVANCED_MODULES_CACHE = data
    return data

def read_version() -> str:
    """Read version from VERSION file (single source of truth).

    R-02: Returns a safe fallback string instead of raising FileNotFoundError
    at import time when the VERSION file is missing (e.g. partial git clone).
    """
    global _VERSION_CACHE
    if not _BYPASS_CACHE and _VERSION_CACHE is not None:
        return _VERSION_CACHE
    _vf = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'VERSION'))
    try:
        with open(_vf, 'r', encoding='utf-8') as _f:
            version = 'v' + _f.read().strip()
    except (FileNotFoundError, OSError):
        # Fallback so that a missing VERSION file never crashes at import time.
        version = 'v?.?.?'
    if not _BYPASS_CACHE:
        _VERSION_CACHE = version
    return version
