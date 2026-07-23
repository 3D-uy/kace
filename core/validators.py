# core/validators.py
import re
from typing import Union

# Covers standard Klipper pin formats (PA0, ^PB7, !gpio4, P0.10, etc.)
# and multi-MCU/CAN bus pins (e.g. toolhead:gpio5, can0:gpio4).
_PIN_RE = re.compile(r'^[!^~]*(?:[A-Za-z0-9_-]+:)?[!^~]*[A-Za-z0-9_.]+$')


def validate_klipper_pin(s: str) -> bool:
    """Validate a Klipper pin name.

    Leading/trailing whitespace is stripped before validation — " PA0" is
    treated as "PA0" and considered valid. Internal whitespace is rejected.
    Accepts optional prefix chars: !, ^, ~ (combinable, e.g. !^PA0).
    """
    if not s:
        return False
    return bool(_PIN_RE.match(s.strip()))


def questionary_pin_validator(value: str) -> Union[bool, str]:
    """Validator for questionary.text pin inputs."""
    if validate_klipper_pin(value):
        return True
    return "Invalid Klipper pin format. Use alphanumeric characters, dots, underscores, and optional prefixes (!, ^, ~)"


def questionary_numeric_validator(value: str) -> Union[bool, str]:
    """Validator for questionary.text numeric/limits inputs."""
    val_strip = value.strip().lower()
    if val_strip in ("<", "back", "volver", ""):
        return True
    try:
        float(val_strip)
        return True
    except ValueError:
        # Q-02: Deferred import — validators.py is imported very early in kace.py
        # before translations is fully initialised. A module-level import here would
        # create a circular dependency chain. Do NOT move this to the top of the file.
        from core.translations import get_lang
        lang = get_lang()
        if lang == "Español":
            return "Por favor ingrese un número válido (ej. 0, -5.5, 235) o '<' para volver"
        elif lang == "Português":
            return "Por favor insira um número válido (ex. 0, -5.5, 235) ou '<' para voltar"
        else:
            return "Please enter a valid number (e.g. 0, -5.5, 235) or '<' to go back"


def questionary_pos_numeric_validator(value: str) -> Union[bool, str]:
    """Validator for questionary.text positive numeric/volume inputs."""
    val_strip = value.strip().lower()
    if val_strip in ("<", "back", "volver", ""):
        return True
    try:
        f = float(val_strip)
        if f <= 0:
            # Q-02: Same deferred import as above — see comment in questionary_numeric_validator.
            from core.translations import get_lang
            lang = get_lang()
            if lang == "Español":
                return "El valor debe ser mayor que 0"
            elif lang == "Português":
                return "O valor deve ser maior que 0"
            else:
                return "Value must be greater than 0"
        return True
    except ValueError:
        # Q-02: Same deferred import as above — see comment in questionary_numeric_validator.
        from core.translations import get_lang
        lang = get_lang()
        if lang == "Español":
            return "Por favor ingrese un número válido mayor que 0 (ej. 235) o '<' para volver"
        elif lang == "Português":
            return "Por favor insira um número válido maior que 0 (ex. 235) ou '<' para voltar"
        else:
            return "Please enter a valid number greater than 0 (e.g. 235) or '<' to go back"

