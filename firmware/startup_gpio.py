"""Reviewed board startup requirements, distinct from runtime output_pin levels."""
from firmware.identity import FirmwareIdentityError

CR10_SMART_PRO = "printer-creality-cr10-smart-pro-2022.cfg"
MONOPRICE_MINI_V1 = "printer-monoprice-select-mini-v1-2016.cfg"
BIQU_BX = "printer-biqu-bx-2021.cfg"
ALFAWISE_U30 = "printer-alfawise-u30-2018.cfg"
_STM32F103_STARTUP_PINS = {
    ALFAWISE_U30: ("!PC4", "!PD12"),
    CR10_SMART_PRO: ("PA0",),
    MONOPRICE_MINI_V1: ("PA8", "PB1", "PB11", "PB9"),
    "generic-bigtreetech-skr-mini-e3-v1.0.cfg": ("!PC13",),
    "generic-bigtreetech-skr-mini-e3-v1.2.cfg": ("!PC13",),
    "generic-bigtreetech-skr-e3-dip.cfg": ("!PC13",),
    "generic-bigtreetech-skr-mini-e3-v2.0.cfg": ("!PA14",),
    "generic-bigtreetech-skr-mini-mz.cfg": ("!PA14",),
    "generic-bigtreetech-skr-cr6-v1.0.cfg": ("!PA14",),
}


def required_startup_pins(board, processor=None):
    """Exact selected-board requirements from reviewed official profile headers.

    No inference from MCU family, printer profile or arbitrary runtime outputs.
    Positive PA0 means high in Klipper INITIAL_PINS; !PA0 means low.
    """
    from firmware.board_serial import board_serial_ports
    if board_serial_ports(board):
        if processor is not None and str(processor).lower() not in {"stm32f103", "stm32f103rc", "stm32f103re", "stm32f103ret6"}:
            raise ValueError("Robin startup GPIO requires STM32F103")
        return ("!PC6", "!PD13")
    if board == BIQU_BX:
        if processor is not None and str(processor).lower() != "stm32h743":
            raise ValueError(f"{board} startup GPIO requires its STM32H743 processor")
        return ("PB5", "PE5")
    if board not in _STM32F103_STARTUP_PINS:
        return ()
    if processor is not None and str(processor).lower() not in {
        "stm32f103", "stm32f103rc", "stm32f103re", "stm32f103ret6",
    }:
        raise ValueError(f"{board} startup GPIO requires its STM32F103 processor")
    return _STM32F103_STARTUP_PINS[board]


def verify_startup_artifact(board, path, identity, *, serial_port=None):
    """Bind a selected board's startup requirement to the actual firmware bytes."""
    required = required_startup_pins(board)
    if not required:
        return
    from firmware.pin_reservations import read_identify_dictionary
    metadata = identity.to_dict() if hasattr(identity, "to_dict") else identity
    config = metadata.get("canonical_config", "") if isinstance(metadata, dict) else ""
    expected = ','.join(required)
    if not isinstance(config, str):
        raise FirmwareIdentityError("Selected-board startup GPIO has invalid build configuration evidence")
    values = [line.split('=', 1)[1] for line in config.splitlines()
              if line.startswith('CONFIG_INITIAL_PINS=')]
    if values != [f'"{expected}"']:
        raise FirmwareIdentityError(f"Selected-board startup GPIO requires CONFIG_INITIAL_PINS=\"{expected}\"; rebuild required")
    dictionary = read_identify_dictionary(path, identity)
    if dictionary["config"].get("INITIAL_PINS") != expected:
        raise FirmwareIdentityError(f"Compiled firmware lacks required startup GPIO {expected}; rebuild required")
    from firmware.board_serial import verify_board_serial
    verify_board_serial(board, config, dictionary, serial_port)
