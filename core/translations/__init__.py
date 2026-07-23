# core/translations/__init__.py
#
# Public API for the translations package.
# All callers use: from core.translations import t, get_lang, set_lang, ...
# Nothing below this file needs to change.
#
# Q-01: Replaced the 2,489-line monolith with a 4-file package:
#   _state.py   — language/mode state variables and their setters/getters
#   _strings.py — UI_STRINGS dict (the entire string table)
#   _t.py       — t() lookup function and translate_comment()
#   __init__.py — this file; re-exports every public symbol

from core.translations._state import (  # noqa: F401
    _SUPPORTED_LANGS,
    set_lang,
    get_lang,
    set_mode,
    get_mode,
)

from core.translations._strings import UI_STRINGS  # noqa: F401

from core.translations._t import t, translate_comment  # noqa: F401
