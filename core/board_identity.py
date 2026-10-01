"""Reviewed filename/MCU identity, separate from wiring and firmware support."""
from core.loader import load_boards_yaml


def canonical_mcu(value: str) -> str:
    """Normalize only explicit official Kconfig spellings, never a family prefix."""
    name = str(value or "").strip().casefold()
    return load_boards_yaml()["board_mcu_aliases"].get(name, name)


def board_mcu_candidates(filename: str) -> tuple[str, ...]:
    name = str(filename or "").strip().casefold()
    return tuple(load_boards_yaml()["board_mcu_models"].get(name, ()))


def resolve_board_mcu(filename: str, detected_mcu: str = "") -> str:
    candidates = board_mcu_candidates(filename)
    if detected_mcu:
        model = canonical_mcu(detected_mcu)
        return model if model in candidates else ""
    return candidates[0] if len(candidates) == 1 else ""


def suggested_board_configs(filenames: list[str], detected_mcu: str) -> list[str]:
    """Suggest reviewed model candidates; never select a board or flashing target."""
    model = canonical_mcu(detected_mcu)
    return list(dict.fromkeys(name for name in filenames
                              if model and model in board_mcu_candidates(name)))
