# core/validators.py
import math
import re
from typing import Union

# Covers standard Klipper pin formats (PA0, ^PB7, !gpio4, P0.10, etc.)
# and multi-MCU/CAN bus pins (e.g. toolhead:gpio5, can0:gpio4).
_PIN_RE = re.compile(
    r'^[!^~]*(?:[A-Za-z0-9_-]+:)?[!^~]*(?=[A-Za-z0-9_.]*[A-Za-z0-9])[A-Za-z0-9_.]+$'
)


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
        number = float(val_strip)
        if not math.isfinite(number):
            raise ValueError
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
        if not math.isfinite(f) or f <= 0:
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


def questionary_thermistor_validator(value: str) -> Union[bool, str]:
    """Validator for custom thermistor name inputs."""
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        from core.translations import get_lang
        lang = get_lang()
        if lang == "Español":
            return "El nombre del termistor no puede contener saltos de línea ni caracteres de control"
        elif lang == "Português":
            return "O nome do termistor não pode conter quebras de linha ou caracteres de controle"
        else:
            return "Thermistor name cannot contain newlines or control characters"
    val_strip = value.strip()
    if val_strip.lower() in ("<", "back", "volver"):
        return True
    if not val_strip:
        return "Thermistor name must not be empty"
    return True


def questionary_arch_validator(value: str) -> Union[bool, str]:
    """Validator for Klipper MCU architecture inputs."""
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        from core.translations import get_lang
        lang = get_lang()
        if lang == "Español":
            return "La arquitectura no puede contener saltos de línea ni caracteres de control"
        elif lang == "Português":
            return "A arquitetura não pode conter quebras de linha ou caracteres de controle"
        else:
            return "Architecture cannot contain newlines or control characters"
    val_strip = value.strip()
    if val_strip.lower() in ("<", "back", "volver", ""):
        return True
    if re.match(r'^[a-zA-Z0-9_]+$', val_strip):
        try:
            from core.capabilities import validate_firmware_architecture
            validate_firmware_architecture(val_strip)
            return True
        except ValueError as exc:
            return str(exc)
    from core.translations import get_lang
    lang = get_lang()
    if lang == "Español":
        return "Arquitectura inválida. Use solo letras, números y guiones bajos (ej. stm32, rp2040)"
    elif lang == "Português":
        return "Arquitetura inválida. Use apenas letras, números e sublinhados (ex. stm32, rp2040)"
    else:
        return "Invalid architecture. Use only letters, numbers, and underscores (e.g. stm32, rp2040)"


def questionary_processor_validator(value: str) -> Union[bool, str]:
    """Validate a processor/model against the firmware derivation database."""
    val_strip = str(value or "").strip()
    if val_strip.lower() in ("<", "back", "volver"):
        return True
    try:
        from core.capabilities import validate_firmware_processor
        validate_firmware_processor(val_strip)
        return True
    except ValueError as exc:
        return str(exc)


def questionary_hex_offset_validator(value: str) -> Union[bool, str]:
    """Validator for HEX offset inputs."""
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        from core.translations import get_lang
        lang = get_lang()
        if lang == "Español":
            return "El offset HEX no puede contener saltos de línea ni caracteres de control"
        elif lang == "Português":
            return "O offset HEX não pode conter quebras de linha ou caracteres de controle"
        else:
            return "HEX offset cannot contain newlines or control characters"
    val_strip = value.strip()
    if val_strip.lower() in ("<", "back", "volver", ""):
        return True
    if re.match(r'^0[xX][0-9a-fA-F]+$', val_strip):
        return True
    from core.translations import get_lang
    lang = get_lang()
    if lang == "Español":
        return "Offset HEX inválido. Debe ser un formato hexadecimal comenzando con 0x (ej. 0x8000, 0x0)"
    elif lang == "Português":
        return "Offset HEX inválido. Deve ser um formato hexadecimal começando com 0x (ex. 0x8000, 0x0)"
    else:
        return "Invalid HEX offset. Must be a hexadecimal format starting with 0x (e.g. 0x8000, 0x0)"
