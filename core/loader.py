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
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
        if not _BYPASS_CACHE:
            _BOARDS_CACHE = data
        return data

def load_displays_yaml() -> dict:
    """Load and parse data/displays.yaml, caching the result in memory."""
    global _DISPLAYS_CACHE
    if not _BYPASS_CACHE and _DISPLAYS_CACHE is not None:
        return _DISPLAYS_CACHE
    path = _get_displays_path()
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
        if not _BYPASS_CACHE:
            _DISPLAYS_CACHE = data
        return data

def load_advanced_modules_yaml() -> dict:
    """Load and parse data/advanced_modules.yaml, caching the result in memory."""
    global _ADVANCED_MODULES_CACHE
    if not _BYPASS_CACHE and _ADVANCED_MODULES_CACHE is not None:
        return _ADVANCED_MODULES_CACHE
    path = _get_advanced_modules_path()
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
        if not _BYPASS_CACHE:
            _ADVANCED_MODULES_CACHE = data
        return data

def read_version() -> str:
    """Read version from VERSION file (single source of truth)."""
    global _VERSION_CACHE
    if not _BYPASS_CACHE and _VERSION_CACHE is not None:
        return _VERSION_CACHE
    _vf = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'VERSION'))
    with open(_vf, 'r', encoding='utf-8') as _f:
        version = 'v' + _f.read().strip()
        if not _BYPASS_CACHE:
            _VERSION_CACHE = version
        return version
