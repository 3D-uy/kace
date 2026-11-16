"""Reviewed FORCE_MOVE policy; inherited profile enablement is not consent."""
from core.exceptions import GenerationError


DEFAULT_FORCE_MOVE = False


def reviewed_force_move(user_data) -> bool:
    value = user_data.get("force_move_enabled", DEFAULT_FORCE_MOVE)
    if type(value) is not bool:
        raise GenerationError("force_move_enabled must be an explicit boolean decision.")
    return value


def inherited_force_move(parsed_data) -> bool:
    for section, options in parsed_data.items():
        if str(section).strip().casefold() == "force_move" and isinstance(options, dict):
            for name, value in options.items():
                if str(name).strip().casefold() == "enable_force_move":
                    return str(value).strip().casefold() in {"true", "1", "yes", "on"}
    return False
