import shutil
import textwrap

from core.menu import numbered_select
from core.translations import t
from core.exceptions import WizardExit
from core.display_wizard import run_display_setup_step
from core.wizard.runner import _BACK, _QUIT
from core.wizard.ui import _back_choice, _quit_choice


def _step_display(user_data):
    """Display setup step — wraps run_display_setup_step inside the wizard."""
    parsed_cfg = user_data.get('board_parsed') or {}
    display_result = run_display_setup_step(
        user_data=user_data,
        parsed_cfg=parsed_cfg,
        board_filename=user_data.get("board") or "",
    )
    if display_result.get("display_choice") == "__back__":
        return _BACK
    user_data.update({
        "display_choice":        display_result.get("display_choice"),
        "display_section":       display_result.get("display_section"),
        "display_compat_class":  display_result.get("display_compat_class"),
        "display_risk_accepted": display_result.get("display_risk_accepted", False),
    })
    return display_result.get("display_choice") or "none"


def _step_starter_macros(user_data):
    """Record the optional starter bundle before firmware can pause the flow."""
    answer = numbered_select(t("kace.generate_macros_prompt"), choices=[
        {"name": t("software.starter_macros_yes"), "value": "generate"},
        {"name": t("software.starter_macros_no"), "value": "skip"},
        _back_choice(), _quit_choice(),
    ], default=1 if user_data.get("macros_generated") is False else 0)
    if answer == _QUIT or answer is None:
        raise WizardExit()
    if answer == _BACK:
        return _BACK
    user_data["macros_generated"] = answer == "generate"
    return "done"


def _step_web_ui(user_data):
    from core.dashboard import _detect_webui, _PATH_MAINSAIL, _PATH_FLUIDD

    def explain(key, **values):
        width = max(20, shutil.get_terminal_size((80, 24)).columns - 4)
        print(textwrap.fill(t(key, **values), width=width, initial_indent="  ", subsequent_indent="  "))

    installed = [name for name, path in (("Mainsail", _PATH_MAINSAIL), ("Fluidd", _PATH_FLUIDD))
                 if _detect_webui(name.lower(), path)]
    explain("software.macros_help")
    explain("software.fresh_configuration")
    if len(installed) == 2:
        explain("software.both_detected")
    choices = ["Mainsail", "Fluidd",
               {"name": t("software.no_include"), "value": "None"},
               _back_choice(), _quit_choice()]
    previous = user_data.get("web_interface")
    default = {"Mainsail": 0, "Fluidd": 1, "None": 2}.get(previous, 0)
    ans = numbered_select(t("software.select_macros"), choices=choices, default=default)
    if ans == _QUIT or ans is None:
        raise WizardExit()
    if ans == _BACK:
        return _BACK
    user_data["web_interface"] = ans
    # Clear stale presentation facts from pre-fresh saved decisions. Dependency
    # availability is checked against the new tree before publication.
    user_data["web_interface_preserved"] = []
    user_data["web_interface_review_required"] = False
    return ans
