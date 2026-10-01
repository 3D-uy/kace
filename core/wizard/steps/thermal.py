"""Review source thermal settings after MCU verification, before file generation."""
import copy
import os

from core.exceptions import GenerationError
from core.menu import yes_no
from core.terminal import SECTION, WARNING, RESET
from core.translations import t
from core.thermal_review import RECEIPT, required_policy, confirmation_matches


def review_thermal_policy(board, user, *, include_macros=False):
    if not required_policy(board, user):
        return
    from core.generator import generate_config

    def preview():
        return generate_config(board, user, include_macros=include_macros, verbose=False,
                               thermal_review_only=True)["thermal_review"]

    payload = preview()
    if confirmation_matches(user.get(RECEIPT), payload):
        return
    if os.environ.get("KACE_AUTO") == "1":
        raise GenerationError("Thermal policy requires explicit review; automatic mode cannot confirm it.")
    print(f"\n{SECTION}{t('wizard.thermal.title')}{RESET}")
    print(f"{WARNING}{t('wizard.thermal.help')}{RESET}")
    for name, fields in {**payload["hardware"], **payload["policy"]}.items():
        print(f"\n  [{name}]")
        for key, value in sorted(fields.items()):
            print(f"    {key}: {value}")
    if not yes_no(t("wizard.thermal.confirm"), default=False):
        raise GenerationError(t("wizard.thermal.declined"))
    if preview() != payload:
        raise GenerationError("Thermal review inputs changed during confirmation; review them again.")
    user[RECEIPT] = copy.deepcopy(payload)
