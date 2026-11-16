"""An advanced, explicit choice for diagnostic movement commands."""
import os

from core.exceptions import WizardExit
from core.force_move_policy import inherited_force_move, reviewed_force_move
from core.menu import numbered_select
from core.translations import get_mode, t
from core.wizard.runner import _BACK, _QUIT
from core.wizard.ui import _back_choice, _quit_choice


def _step_force_move(user_data):
    previous = reviewed_force_move(user_data)
    # Runner visibility controls presentation only; the prompt still executes.
    if get_mode() != "Advanced" or os.environ.get("KACE_AUTO") == "1":
        user_data["force_move_enabled"] = previous
        return "done"
    print(t("force_move.warning"))
    if "force_move_enabled" not in user_data and inherited_force_move(user_data.get("board_parsed") or {}):
        print(t("force_move.inherited"))
    choice = numbered_select(t("force_move.prompt"), choices=[
        {"name": t("force_move.disabled"), "value": "disabled"},
        {"name": t("force_move.enabled"), "value": "enabled"},
        _back_choice(), _quit_choice(),
    ], default=1 if previous else 0)
    if choice == _QUIT or choice is None:
        raise WizardExit()
    if choice == _BACK:
        return _BACK
    user_data["force_move_enabled"] = choice == "enabled"
    return "done"
