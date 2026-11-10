import os
import posixpath
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
    from core.dashboard import _detect_webui, _PATH_MAINSAIL, _PATH_FLUIDD, get_printer_cfg_path
    from core.config_transaction import LocalConfigTransport, read_config_state, ConfigConflictError
    from core.managed_config import config_includes

    def explain(key, **values):
        width = max(20, shutil.get_terminal_size((80, 24)).columns - 4)
        print(textwrap.fill(t(key, **values), width=width, initial_indent="  ", subsequent_indent="  "))

    installed = [name for name, path in (("Mainsail", _PATH_MAINSAIL), ("Fluidd", _PATH_FLUIDD))
                 if _detect_webui(name.lower(), path)]
    existing = []
    reviewed = True
    try:
        # Reuse the deployment reader's path boundaries, explicit-include rules
        # and graph limits. This operation only reads files; no activation API.
        state = read_config_state(LocalConfigTransport(os.path.dirname(get_printer_cfg_path())))
        existing = sorted({posixpath.basename(name)[:-4].title() for name in state
                           if posixpath.basename(name).casefold() in ("mainsail.cfg", "fluidd.cfg")})
        for name, content in state.items():
            if content is not None:
                for _, included in config_includes(content, name):
                    if state.get(included) is None:
                        raise ValueError("an included configuration file is unavailable")
    except (OSError, UnicodeError, ValueError, ConfigConflictError):
        reviewed = False
    explain("software.macros_help")
    if len(installed) == 2:
        explain("software.both_detected")
    if existing:
        explain("software.includes_existing", includes=", ".join(existing))
    if not reviewed:
        explain("software.includes_unverified")

    choices = ["Mainsail", "Fluidd",
               {"name": t("software.keep_includes" if existing else "software.no_include"), "value": "None"},
               _back_choice(), _quit_choice()]
    if not reviewed:
        choices = [{"name": t("software.keep_includes"), "value": "None"}, _back_choice(), _quit_choice()]
    while True:
        ans = numbered_select(t("software.select_macros"), choices=choices,
                              default=2 if reviewed and existing else 0)
        if ans == _QUIT or ans is None:
            raise WizardExit()
        if ans == _BACK:
            return _BACK
        if existing and ans != "None" and any(name != ans for name in existing):
            explain("software.include_conflict", selected=ans, existing=", ".join(existing))
            resolution = numbered_select(t("software.resolve_include"), choices=[
                {"name": t("software.keep_includes"), "value": "keep"},
                {"name": t("software.choose_again"), "value": "again"},
                _back_choice(), _quit_choice(),
            ])
            if resolution == _QUIT or resolution is None:
                raise WizardExit()
            if resolution == _BACK:
                return _BACK
            if resolution != "keep":
                continue
            ans = "None"
        if existing and ans in existing:
            # The include may be nested: adding it at the root would execute it
            # twice even when the selected interface matches the existing one.
            ans = "None"
        user_data["web_interface"] = ans
        # Presentation only: generation retains its existing single-include contract.
        user_data["web_interface_preserved"] = existing if ans == "None" else []
        user_data["web_interface_review_required"] = not reviewed
        return ans
