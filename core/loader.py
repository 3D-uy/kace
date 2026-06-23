# core/loader.py
import os
import yaml

_BOARDS_CACHE = None
_DISPLAYS_CACHE = None
_ADVANCED_MODULES_CACHE = None
_VERSION_CACHE = None

def _get_boards_path() -> str:
    if os.environ.get("KACE_TESTING") == "1":
        for override in ["data/broken_boards.yaml", "data/bad_boards_test.yaml"]:
            if os.path.exists(override):
                return os.path.normpath(override)
            rel_override = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', override))
            if os.path.exists(rel_override):
                return rel_override
    return os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'data', 'boards.yaml'))

def _get_displays_path() -> str:
    return os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'data', 'displays.yaml'))

def _get_advanced_modules_path() -> str:
    return os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'data', 'advanced_modules.yaml'))

def load_boards_yaml() -> dict:
    """Load and parse data/boards.yaml, caching the result in memory."""
    global _BOARDS_CACHE
    if os.environ.get("KACE_TESTING") != "1" and _BOARDS_CACHE is not None:
        return _BOARDS_CACHE
    path = _get_boards_path()
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
        if os.environ.get("KACE_TESTING") != "1":
            _BOARDS_CACHE = data
        return data

def load_displays_yaml() -> dict:
    """Load and parse data/displays.yaml, caching the result in memory."""
    global _DISPLAYS_CACHE
    if os.environ.get("KACE_TESTING") != "1" and _DISPLAYS_CACHE is not None:
        return _DISPLAYS_CACHE
    path = _get_displays_path()
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
        if os.environ.get("KACE_TESTING") != "1":
            _DISPLAYS_CACHE = data
        return data

def load_advanced_modules_yaml() -> dict:
    """Load and parse data/advanced_modules.yaml, caching the result in memory."""
    global _ADVANCED_MODULES_CACHE
    if os.environ.get("KACE_TESTING") != "1" and _ADVANCED_MODULES_CACHE is not None:
        return _ADVANCED_MODULES_CACHE
    path = _get_advanced_modules_path()
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
        if os.environ.get("KACE_TESTING") != "1":
            _ADVANCED_MODULES_CACHE = data
        return data

def read_version() -> str:
    """Read version from VERSION file (single source of truth)."""
    global _VERSION_CACHE
    if os.environ.get("KACE_TESTING") != "1" and _VERSION_CACHE is not None:
        return _VERSION_CACHE
    _vf = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'VERSION'))
    with open(_vf, 'r', encoding='utf-8') as _f:
        version = 'v' + _f.read().strip()
        if os.environ.get("KACE_TESTING") != "1":
            _VERSION_CACHE = version
        return version
