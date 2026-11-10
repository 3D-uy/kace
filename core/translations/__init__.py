# core/translations/__init__.py
#
# Public API for the translations package.
# All callers use: from core.translations import t, get_lang, set_lang, ...
# Nothing below this file needs to change.
#
# Translation tables and their public API:
#   _state.py   — language/mode state variables and their setters/getters
#   _strings.py — UI_STRINGS dict (the entire string table)
#   _wizard_review.py — focused wizard review and layout guidance
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
from core.translations._wizard_review import WIZARD_REVIEW_STRINGS
from core.translations._wizard_presentation import WIZARD_PRESENTATION_STRINGS
from core.translations._probe_review_actions import PROBE_REVIEW_ACTION_STRINGS
from core.translations._deployment_conflicts import DEPLOYMENT_CONFLICT_STRINGS
from core.translations._catalog_review import CATALOG_REVIEW_STRINGS
from core.translations._software_presentation import SOFTWARE_PRESENTATION_STRINGS
from core.translations._motor_directions import MOTOR_DIRECTION_STRINGS

UI_STRINGS.update(WIZARD_REVIEW_STRINGS)
UI_STRINGS.update(WIZARD_PRESENTATION_STRINGS)
UI_STRINGS.update(PROBE_REVIEW_ACTION_STRINGS)
UI_STRINGS.update(DEPLOYMENT_CONFLICT_STRINGS)
UI_STRINGS.update(CATALOG_REVIEW_STRINGS)
UI_STRINGS.update(SOFTWARE_PRESENTATION_STRINGS)
UI_STRINGS.update(MOTOR_DIRECTION_STRINGS)

from core.translations._t import t, translate_comment  # noqa: F401
