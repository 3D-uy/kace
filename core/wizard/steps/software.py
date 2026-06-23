import questionary
from core.style import custom_style
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


def _step_web_ui(user_data):
    ans = questionary.select(
        t("wizard.select_web_ui"),
        choices=["Mainsail", "Fluidd", "None", _back_choice(), _quit_choice()],
        style=custom_style
    ).ask()
    if ans == _QUIT or ans is None:
        raise WizardExit()
    if ans == _BACK:
        return _BACK
    user_data["web_interface"] = ans
    return ans
