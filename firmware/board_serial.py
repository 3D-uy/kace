"""Finite serial connection contract for reviewed F103 Robin printer profiles."""
KINGROON = "printer-kingroon-kp3s-2020.cfg"
SAPPHIRE = (
    "printer-twotrees-sapphire-plus-sp-5-v1-2020.cfg",
    "printer-twotrees-sapphire-plus-sp-5-v1.1-2021.cfg",
    "printer-twotrees-sapphire-pro-sp-3-2020.cfg",
)
SERIAL_PINS = {"USART1": "PA10,PA9", "USART3": "PB11,PB10"}


def board_serial_ports(board):
    if board == KINGROON:
        return ("USART3",)
    if board in SAPPHIRE:
        return ("USART3", "USART1")
    return ()


def board_serial_selector(board, processor, config):
    ports = board_serial_ports(board)
    port = config.get("KACE_SERIAL_PORT")
    if not ports:
        if port is not None:
            raise ValueError("Explicit serial port requires a reviewed selected board")
        return None
    if str(processor).lower() not in {"stm32f103", "stm32f103rc", "stm32f103re", "stm32f103ret6"}:
        raise ValueError("Robin serial connection requires STM32F103")
    if port not in ports or config.get("CONFIG_SERIAL") != "y":
        raise ValueError("Select the board's explicit USART connection; native USB is not its USB-serial bridge")
    if int(config.get("CONFIG_FLASH_START", "-1"), 0) != 0x7000:
        raise ValueError("Selected Robin profile requires a 28KiB bootloader")
    return "STM32_SERIAL_" + port


def verify_board_serial(board, config, dictionary, expected_port=None):
    """Verify the resolved choice and its physical pins in the native identify."""
    from firmware.identity import FirmwareIdentityError
    ports = board_serial_ports(board)
    if not ports:
        return
    values = {}
    for line in config.splitlines():
        if line.startswith("CONFIG_") and "=" in line:
            key, value = line.split("=", 1)
            if key in values:
                raise FirmwareIdentityError("Board serial evidence has duplicate configuration keys")
            values[key] = value
    selected = [p for p in ports if values.get("CONFIG_STM32_SERIAL_" + p) == "y"]
    if len(selected) != 1 or (expected_port is not None and selected != [expected_port]):
        raise FirmwareIdentityError("Board serial selection differs from its required or recorded USART")
    port = selected[0]
    # USB capability flags (e.g. DOUBLE_BUFFER_TX) may remain y for serial builds.
    # Reject active alternative transports, not unrelated MCU capabilities.
    selectors = [k for k, v in values.items() if v == "y" and k.startswith("CONFIG_STM32_SERIAL_")]
    if (selectors != ["CONFIG_STM32_SERIAL_" + port] or values.get("CONFIG_MACH_STM32F103") != "y"
            or values.get("CONFIG_SERIAL") != "y"
            or any(values.get(k) == "y" for k in ("CONFIG_USBSERIAL", "CONFIG_CANBUS", "CONFIG_USBCANBUS"))):
        raise FirmwareIdentityError("Board serial evidence has conflicting MCU/interface selectors")
    try:
        address = int(values.get("CONFIG_FLASH_APPLICATION_ADDRESS", "-1"), 0)
    except ValueError as exc:
        raise FirmwareIdentityError("Board serial evidence has invalid application address") from exc
    if address != 0x08007000 or dictionary["config"].get("RESERVE_PINS_serial") != SERIAL_PINS[port]:
        raise FirmwareIdentityError("Compiled board serial pins or bootloader differ from selected connection")
