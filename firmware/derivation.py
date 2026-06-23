import os

# ── Firmware configuration database ───────────────────────────────────────────
# Loaded from data/boards.yaml (mcu_firmware section).
# The hardcoded list below is the fallback used when the YAML file is missing
# or cannot be parsed — guarantees zero regression risk on existing installs.
#
# Field reference:
#   pattern      : substring matched against the detected MCU string (lowercase)
#                  Order matters: most specific patterns MUST come before generic ones.
#   arch         : value for CONFIG_MCU (Klipper architecture string)
#   mach         : CONFIG_MACH_{mach} key suffix (None if not applicable)
#   flash_start  : CONFIG_FLASH_START hex string; None = ambiguous, prompt user
#   clock_freq   : CONFIG_CLOCK_FREQ value in Hz (optional)
#   set_mcu_flag : if True, also sets CONFIG_MCU_{detected_mcu.upper()} = "y"
#   extra_flag   : additional CONFIG_* key to set to "y" (optional)
#   early_return : if True, return immediately after arch (no interface config)

_FW_DB_FALLBACK = [
    # STM32 — most specific first
    {"pattern": "stm32f103",  "arch": "stm32",   "mach": "STM32",   "flash_start": "0x7000", "set_mcu_flag": True},
    {"pattern": "stm32f1",    "arch": "stm32",   "mach": "STM32",   "flash_start": "0x0",    "set_mcu_flag": True},
    {"pattern": "stm32f4",    "arch": "stm32",   "mach": "STM32",   "flash_start": "0x8000", "set_mcu_flag": True},
    {"pattern": "stm32h7",    "arch": "stm32",   "mach": "STM32",   "flash_start": "0x20000","set_mcu_flag": True},
    {"pattern": "stm32g0b",   "arch": "stm32",   "mach": "STM32",   "flash_start": "0x2000", "set_mcu_flag": True},
    {"pattern": "stm32",      "arch": "stm32",   "mach": "STM32",   "flash_start": None,     "set_mcu_flag": True},
    # LPC176x — most specific first
    {"pattern": "lpc1769",    "arch": "lpc176x", "mach": "LPC176X", "flash_start": "0x4000", "clock_freq": 120000000, "set_mcu_flag": True},
    {"pattern": "lpc1768",    "arch": "lpc176x", "mach": "LPC176X", "flash_start": "0x4000", "clock_freq": 100000000, "set_mcu_flag": True},
    {"pattern": "lpc176",     "arch": "lpc176x", "mach": "LPC176X", "flash_start": "0x4000", "set_mcu_flag": True},
    # RP2040
    {"pattern": "rp2040",     "arch": "rp2040",  "mach": "RPXXXX"},
    # ESP32
    {"pattern": "esp32",      "arch": "esp32",   "mach": "ESP32"},
    # AVR — most specific first
    {"pattern": "atmega2560", "arch": "avr",     "mach": "AVR",     "extra_flag": "CONFIG_MCU_ATMEGA2560"},
    {"pattern": "atmega",     "arch": "avr",     "mach": "AVR"},
    {"pattern": "avr",        "arch": "avr",     "mach": "AVR"},
    # Linux host MCU
    {"pattern": "linux",      "arch": "linux",   "early_return": True},
    {"pattern": "host",       "arch": "linux",   "early_return": True},
]


def _load_firmware_db() -> list:
    """Load MCU firmware config entries from data/boards.yaml.

    Falls back to _FW_DB_FALLBACK if the file is missing, unreadable,
    or fails the strict precedence validation.
    The order of entries in the YAML is preserved — most specific patterns
    must appear before generic ones (e.g. stm32f103 before stm32f1).
    """
    try:
        from core.loader import load_boards_yaml
        db = load_boards_yaml()
            
        entries = db.get('mcu_firmware', [])
        if not entries:
            return _FW_DB_FALLBACK
            
        # ── Precedence Validation ─────────────────────────────────────────────
        # Ensure that no pattern is shadowed by a more generic pattern that
        # appears earlier in the list.
        for i, entry in enumerate(entries):
            current_pattern = entry.get("pattern", "")
            for j in range(i + 1, len(entries)):
                subsequent_pattern = entries[j].get("pattern", "")
                if current_pattern in subsequent_pattern:
                    print(f"\n\033[93m[!] WARNING: Invalid pattern precedence in boards.yaml\033[0m")
                    print(f"    Generic pattern '{current_pattern}' at index {i} shadows more")
                    print(f"    specific pattern '{subsequent_pattern}' at index {j}.")
                    print(f"    \033[96mFalling back to built-in hardware defaults.\033[0m\n")
                    return _FW_DB_FALLBACK
                    
        return entries
        
    except Exception as e:
        print(f"\n\033[93m[!] WARNING: Failed to load modular hardware database.\033[0m")
        print(f"    Error: {e}")
        print(f"    \033[96mFalling back to built-in hardware defaults.\033[0m\n")
        return _FW_DB_FALLBACK

# Module-level cache — loaded once per process
_FW_DB = None

def _get_fw_db() -> list:
    global _FW_DB
    if _FW_DB is None:
        _FW_DB = _load_firmware_db()
    return _FW_DB


def derive_config(mcu, hint=None, flash_start=None):
    """Intelligently build Kconfig parameters for the given MCU string.

    Uses the modular hardware database (data/boards.yaml) with a hardcoded
    fallback dict to ensure reliability on all installs.

    Pattern matching uses first-match-wins substring search, so the database
    must list more-specific patterns before generic ones.
    """
    from core.exceptions import DerivationAmbiguityError

    config = {
        "CONFIG_LOW_LEVEL_OPTIONS": "y"
    }

    if mcu:
        mcu = str(mcu).lower()

    # ── 1. Derive architecture, family and bootloader offset ──────────────────
    if mcu is None:
        # No MCU detected — raise error to let the caller handle prompt
        raise DerivationAmbiguityError("mcu_family", ["stm32", "lpc176x", "rp2040", "avr", "linux"])
    else:
        # Find the first matching entry in the database
        matched = None
        for entry in _get_fw_db():
            if entry["pattern"] in mcu:
                matched = entry
                break

        if matched is None:
            raise ValueError("Unknown MCU model")

        arch = matched["arch"]
        mach = matched.get("mach")

        config["CONFIG_MCU"] = f'"{arch}"'

        if mach:
            config[f"CONFIG_MACH_{mach}"] = "y"

        if matched.get("set_mcu_flag") and mach:
            # e.g. CONFIG_MCU_STM32F446XX = "y"
            config[f"CONFIG_MCU_{mcu.upper()}"] = "y"

        # Early return for Linux/host MCU — no interface or bootloader needed
        if matched.get("early_return"):
            return config

        # Bootloader offset:
        #   key absent          → no flash config needed (e.g. rp2040, avr, linux)
        #   flash_start = null  → ambiguous, raise error
        #   flash_start = "0x0" → explicitly no offset, skip CONFIG_FLASH_START
        #   flash_start = "0xN" → set CONFIG_FLASH_START
        if "flash_start" not in matched:
            pass  # no bootloader configuration needed for this architecture
        elif matched["flash_start"] is None:
            if flash_start is not None:
                if flash_start != "0x0":
                    config["CONFIG_FLASH_START"] = flash_start
            else:
                options = {
                    "No bootloader (0x0)":        "0x0",
                    "8KiB bootloader (0x2000)":   "0x2000",
                    "28KiB bootloader (0x7000)":  "0x7000",
                    "32KiB bootloader (0x8000)":  "0x8000",
                    "64KiB bootloader (0x10000)": "0x10000",
                    "128KiB bootloader (0x20000)":"0x20000",
                }
                raise DerivationAmbiguityError("bootloader_offset", options, mcu)
        elif matched["flash_start"] != "0x0":
            config["CONFIG_FLASH_START"] = matched["flash_start"]

        # Optional clock frequency
        clock = matched.get("clock_freq")
        if clock:
            config["CONFIG_CLOCK_FREQ"] = str(clock)

        # Optional extra Kconfig flag (e.g. CONFIG_MCU_ATMEGA2560)
        extra_flag = matched.get("extra_flag")
        if extra_flag:
            config[extra_flag] = "y"

    # ── 2. Derive communication interface ─────────────────────────────────────
    comm = hint
    if not hint or hint not in ["usb", "uart", "can", "spi", "tty"]:
        raise DerivationAmbiguityError("comm_interface", ["USB", "UART", "CAN", "SPI"], mcu or "Board")

    if comm == "usb":
        config["CONFIG_USB"]    = "y"
        config["CONFIG_SERIAL"] = "n"
        config["CONFIG_CANBUS"] = "n"
    elif comm == "can":
        config["CONFIG_CANBUS"] = "y"
        config["CONFIG_USB"]    = "n"
        config["CONFIG_SERIAL"] = "n"
    elif comm in ["uart", "tty"]:
        config["CONFIG_SERIAL"] = "y"
        config["CONFIG_USB"]    = "n"
        config["CONFIG_CANBUS"] = "n"
    elif comm == "spi":
        config["CONFIG_SPI"] = "y"

    return config
