# core/translations/_state.py
# Language and mode state — set once at session start, read everywhere.

# core/translations.py

# ── i18n: UI String Layer ──────────────────────────────────────
# Language state — set once after the user's language choice, then
# read by all modules via get_lang() so callers never thread lang
# through every function signature.

_current_lang = "English"

_SUPPORTED_LANGS = ("English", "Español", "Português")


def set_lang(lang: str) -> None:
    """Set the active UI language for the current session."""
    global _current_lang
    if lang in _SUPPORTED_LANGS:
        _current_lang = lang


def get_lang() -> str:
    """Return the active UI language."""
    return _current_lang


_current_mode = "Beginner"


def set_mode(mode: str) -> None:
    """Set the configuration mode for the current session."""
    global _current_mode
    if mode in ("Beginner", "Advanced"):
        _current_mode = mode


def get_mode() -> str:
    """Return the active configuration mode."""
    return _current_mode


# All user-facing UI strings keyed by a short dot-separated ID.
# Each entry maps language name → display string.
# Strings may contain {placeholders} for str.format(**kwargs).
# Detection paths listed here use standard Klipper defaults and
# are kept in one place to make future configurability easy.