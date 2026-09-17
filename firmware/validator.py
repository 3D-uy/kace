import os

def validate_config(klipper_path="~/klipper", *, requested=None, processor=None):
    """
    Validates the generated Kconfig (.config) file to ensure it's ready for compilation.
    Runs after `make olddefconfig` to check final state.
    Returns (True, "Success") or (False, "Error msg").
    """
    config_path = os.path.expanduser(os.path.join(klipper_path, ".config"))
    
    if not os.path.exists(config_path):
        return False, f"Configuration file not found at {config_path}"
        
    with open(config_path, "r", encoding="utf-8") as f:
        content = f.read()

    if requested is not None:
        from .configuration import klipper_config
        try:
            expected = klipper_config(requested, processor)
            resolved = dict(line.split("=", 1) for line in content.splitlines()
                            if line.startswith("CONFIG_") and "=" in line)
            for key, value in expected.items():
                if resolved.get(key) != value:
                    return False, f"Klipper rejected requested selector {key}={value}"
            arch = requested.get("CONFIG_MCU", "").strip('"')
            if "CONFIG_FLASH_START" in requested:
                address = int(requested["CONFIG_FLASH_START"], 16) + (0x08000000 if arch == "stm32" else 0)
                if int(resolved.get("CONFIG_FLASH_APPLICATION_ADDRESS", "-1"), 0) != address:
                    return False, "Klipper resolved a different application address"
            if "CONFIG_CLOCK_FREQ" in requested and resolved.get("CONFIG_CLOCK_FREQ") != requested["CONFIG_CLOCK_FREQ"]:
                return False, "Klipper resolved a different processor clock"
            return True, "Requested Klipper choices verified after resolution"
        except (ValueError, TypeError) as exc:
            return False, str(exc)

    # 1. Architecture defined
    if "CONFIG_MCU=" not in content:
        return False, "Configuration error: MCU architecture (CONFIG_MCU) is missing."
        
    # 2. Flash Start defined for MCUs that need it
    if 'CONFIG_MCU="stm32"' in content or 'CONFIG_MCU="lpc176x"' in content:
        if "CONFIG_FLASH_START=" not in content:
             return False, "Configuration error: Bootloader flash offset (CONFIG_FLASH_START) is missing."
             
    # 3. Check communication method enabled
    comm_flags = [
        "CONFIG_USB=y",
        "CONFIG_SERIAL=y",
        "CONFIG_CANBUS=y",
        "CONFIG_SPI=y"
    ]
    
    if 'CONFIG_MCU="linux"' not in content:
        active_comms = sum(1 for flag in comm_flags if flag in content)
        if active_comms == 0:
             return False, "Configuration error: No communication interface (USB/UART/CAN) was enabled."
             
    return True, "Configuration validated successfully."
