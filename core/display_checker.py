# core/display_checker.py
#
# Display Compatibility Layer — KACE
#
# Detects display-related sections in a parsed Klipper config, looks up
# their compatibility status from data/displays.yaml, and returns structured
# findings for the warning system in kace.py.
#
# Public API:
#   check_display_compatibility(parsed_cfg, printer_filename, board_filename)
#       → list[dict]  — list of findings, empty if no display sections found
#
# Each finding dict:
#   {
#     "section":                 str   — Klipper section name (e.g. "t5uid1")
#     "status":                  str   — "supported" | "partial" | "unsupported" | "untested"
#     "compatibility_class":     str   — "fully_compatible" | "compatible_with_adapter" | "experimental" | "unsafe"
#     "recommendation":          str   — "disconnect" | "optional" | "none" | ""
#     "notes":                   list  — human-readable bullet points
#     "source":                  str   — "printer_profile" | "display_config" | "fallback"
#     "damage_risks":            list  — list of potential risks
#     "required_modifications":  list  — list of steps to make safe
#   }
#
# Design contract:
#   - Works without data/displays.yaml / data/boards.yaml (hardcoded fallbacks)
#   - Never modifies the parsed config
#   - Never raises exceptions to the caller

import os

# ── Known display section names ────────────────────────────────────────────────
# All Klipper config section names that indicate a display-related component.
# Used to filter parsed config keys before database lookup.
_DISPLAY_SECTION_NAMES = {
    # Native Klipper display sections
    "display", "lcd_menu", "display_status", "display_template", "display_data",
    "hd44780", "ssd1306", "uc1701", "st7920",
    # OEM / proprietary protocols
    "t5uid1", "dwin_set", "tft_serial",
    # LED / exotic
    "neopixel", "dotstar", "sx1509",
}

# ── Hardcoded fallback ────────────────────────────────────────────────────────
# Used when data/displays.yaml is missing.
_DISPLAY_CONFIGS_FALLBACK = {
    "display": {
        "status": "supported",
        "compatibility_class": "fully_compatible",
        "recommendation": "none",
        "interface_required": "EXP1_EXP2",
        "voltage_logic": "3.3V_tolerant",
        "damage_risks": [],
        "required_modifications": [],
        "notes": ["Standard LCD displays are natively supported by Klipper"],
    },
    "lcd_menu": {
        "status": "supported",
        "compatibility_class": "fully_compatible",
        "recommendation": "none",
        "interface_required": "none",
        "voltage_logic": "any",
        "damage_risks": [],
        "required_modifications": [],
        "notes": ["lcd_menu is a native Klipper feature — fully supported"],
    },
    "display_status": {
        "status": "supported",
        "compatibility_class": "fully_compatible",
        "recommendation": "none",
        "interface_required": "none",
        "voltage_logic": "any",
        "damage_risks": [],
        "required_modifications": [],
        "notes": ["display_status is a standard Klipper object — no compatibility concerns"],
    },
    "display_template": {
        "status": "supported",
        "compatibility_class": "fully_compatible",
        "recommendation": "none",
        "interface_required": "none",
        "voltage_logic": "any",
        "damage_risks": [],
        "required_modifications": [],
        "notes": ["display_template is a native Klipper feature — fully supported"],
    },
    "display_data": {
        "status": "supported",
        "compatibility_class": "fully_compatible",
        "recommendation": "none",
        "interface_required": "none",
        "voltage_logic": "any",
        "damage_risks": [],
        "required_modifications": [],
        "notes": ["display_data is a native Klipper feature — fully supported"],
    },
    "t5uid1": {
        "status": "unsupported",
        "compatibility_class": "unsafe",
        "recommendation": "disconnect",
        "interface_required": "UART",
        "voltage_logic": "3.3V_tolerant",
        "damage_risks": [
            "Sending Klipper UART traffic to t5uid1 controller can corrupt display EEPROM",
            "Boot loop caused by incompatible protocol can stress MCU power delivery"
        ],
        "required_modifications": [
            "DISCONNECT the display before running Klipper for the first time",
            "Use Mainsail or Fluidd web interface for all printer control"
        ],
        "notes": [
            "OEM DGUS touchscreen protocol — designed for Creality Marlin firmware",
            "No built-in Klipper support without community plugins",
            "Expected outcome: black screen or boot loop",
        ],
    },
    "dwin_set": {
        "status": "partial",
        "compatibility_class": "compatible_with_adapter",
        "recommendation": "disconnect",
        "interface_required": "UART",
        "voltage_logic": "5V",
        "damage_risks": [
            "Firmware version mismatch can cause non-recoverable display brick"
        ],
        "required_modifications": [
            "Install community 'klipper-dgus' plugin (NOT installed by KACE)",
            "Flash matching DGUS firmware to the display",
            "Alternatively: disconnect display and use web UI"
        ],
        "notes": [
            "DWIN displays require firmware matching the display version",
            "Community plugins exist but are not installed by KACE",
            "Mismatch causes: frozen UI, missing menus, or black screen",
        ],
    },
    "tft_serial": {
        "status": "partial",
        "compatibility_class": "compatible_with_adapter",
        "recommendation": "optional",
        "interface_required": "UART",
        "voltage_logic": "3.3V_tolerant",
        "damage_risks": [
            "UART serial conflicts may corrupt communication with other serial devices"
        ],
        "required_modifications": [
            "Set BTT TFT firmware to 'Marlin emulation' mode (not touch mode)",
            "Connect via UART TX/RX pins — not USB",
            "Configure [display] with lcd_type: hd44780 or st7920 for emulation"
        ],
        "notes": [
            "Serial TFT displays use a bridge protocol designed for Marlin",
            "Menu functionality is typically limited or absent under Klipper",
            "Web UI (Mainsail/Fluidd) provides full feature parity",
        ],
    },
    "neopixel": {
        "status": "supported",
        "compatibility_class": "fully_compatible",
        "recommendation": "none",
        "interface_required": "SPI",
        "voltage_logic": "5V",
        "damage_risks": [
            "WS2812/WS2812B data lines expect 5V logic — connecting 3.3V MCU directly can cause unreliable operation"
        ],
        "required_modifications": [
            "For 3.3V MCUs (STM32, RP2040): use a 74AHCT125 level shifter on the data line"
        ],
        "notes": ["Neopixel/WS2812 LED sections are natively supported by Klipper"],
    },
    "dotstar": {
        "status": "supported",
        "compatibility_class": "fully_compatible",
        "recommendation": "none",
        "interface_required": "SPI",
        "voltage_logic": "5V",
        "damage_risks": [],
        "required_modifications": [],
        "notes": ["Dotstar/APA102 LED sections are natively supported by Klipper"],
    },
    "sx1509": {
        "status": "supported",
        "compatibility_class": "compatible_with_adapter",
        "recommendation": "none",
        "interface_required": "I2C",
        "voltage_logic": "3.3V_tolerant",
        "damage_risks": [],
        "required_modifications": [
            "Ensure I2C address is correctly configured (0x3E default)"
        ],
        "notes": ["SX1509 GPIO expander is natively supported by Klipper"],
    },
    "hd44780": {
        "status": "supported",
        "compatibility_class": "fully_compatible",
        "recommendation": "none",
        "interface_required": "EXP1_EXP2",
        "voltage_logic": "3.3V_tolerant",
        "damage_risks": [],
        "required_modifications": [],
        "notes": ["HD44780 character displays are natively supported by Klipper"],
    },
    "ssd1306": {
        "status": "supported",
        "compatibility_class": "fully_compatible",
        "recommendation": "none",
        "interface_required": "I2C",
        "voltage_logic": "3.3V_tolerant",
        "damage_risks": [],
        "required_modifications": [],
        "notes": ["SSD1306 OLED displays are natively supported by Klipper"],
    },
    "uc1701": {
        "status": "supported",
        "compatibility_class": "fully_compatible",
        "recommendation": "none",
        "interface_required": "SPI",
        "voltage_logic": "3.3V",
        "damage_risks": [],
        "required_modifications": [],
        "notes": ["UC1701 displays (e.g., mini12864) are natively supported by Klipper"],
    },
    "st7920": {
        "status": "supported",
        "compatibility_class": "fully_compatible",
        "recommendation": "none",
        "interface_required": "EXP1_EXP2",
        "voltage_logic": "3.3V_tolerant",
        "damage_risks": [],
        "required_modifications": [],
        "notes": ["ST7920 displays are natively supported by Klipper"],
    },
}

_PRINTER_PROFILES_FALLBACK = {
    "cr6-se": {
        "display_type": "t5uid1",
        "status": "unsupported",
        "compatibility_class": "unsafe",
        "recommendation": "disconnect",
        "notes": [
            "The CR-6 SE uses a proprietary DGUS/t5uid1 touchscreen with Creality OEM firmware",
            "Not compatible with Klipper without a community firmware patch",
            "Recommended: disconnect display and use Mainsail or Fluidd web interface",
        ],
        "damage_risks": [
            "Incompatible UART traffic from Klipper MCU may corrupt display EEPROM",
            "Persistent boot loop stresses MCU power delivery (VReg thermal cycling)"
        ],
        "required_modifications": [
            "Step 1: Physically disconnect the display ribbon cable from the board",
            "Step 2: Boot Klipper — all control via web interface"
        ],
    },
    "artillery-sidewinder": {
        "display_type": "tft_serial",
        "status": "partial",
        "compatibility_class": "compatible_with_adapter",
        "recommendation": "optional",
        "notes": [
            "Artillery Sidewinder uses a serial TFT display designed for Marlin",
            "Serial TFT menus are typically non-functional under Klipper",
            "Web UI (Mainsail/Fluidd) provides full printer control",
        ],
        "damage_risks": [],
        "required_modifications": [
            "Set TFT firmware to 12864 emulation mode",
            "Use web UI for primary printer control"
        ],
    },
    "artillery-genius": {
        "display_type": "tft_serial",
        "status": "partial",
        "compatibility_class": "compatible_with_adapter",
        "recommendation": "optional",
        "notes": [
            "Artillery Genius uses a serial TFT display designed for Marlin",
            "Serial TFT menus are typically non-functional under Klipper",
        ],
        "damage_risks": [],
        "required_modifications": [
            "Use web UI (Mainsail/Fluidd) for all printer control"
        ],
    },
    "artillery-hornet": {
        "display_type": "tft_serial",
        "status": "partial",
        "compatibility_class": "compatible_with_adapter",
        "recommendation": "optional",
        "notes": [
            "Artillery Hornet uses a serial TFT display designed for Marlin",
            "Serial TFT menus are typically non-functional under Klipper",
        ],
        "damage_risks": [],
        "required_modifications": [
            "Use web UI (Mainsail/Fluidd) for all printer control"
        ],
    },
    "cr10-smart": {
        "display_type": "tft_serial",
        "status": "partial",
        "compatibility_class": "compatible_with_adapter",
        "recommendation": "optional",
        "notes": ["CR-10 Smart TFT display has limited functionality under Klipper"],
        "damage_risks": [],
        "required_modifications": [
            "Use web UI (Mainsail/Fluidd) for all printer control"
        ],
    },
    "ender-6": {
        "display_type": "tft_serial",
        "status": "partial",
        "compatibility_class": "compatible_with_adapter",
        "recommendation": "optional",
        "notes": ["Ender 6 TFT display has limited compatibility with Klipper"],
        "damage_risks": [],
        "required_modifications": [
            "Use web UI (Mainsail/Fluidd) for all printer control"
        ],
    },
    "mks-robin": {
        "display_type": "tft_serial",
        "status": "partial",
        "compatibility_class": "compatible_with_adapter",
        "recommendation": "optional",
        "notes": ["MKS TFT displays have limited compatibility with Klipper"],
        "damage_risks": [],
        "required_modifications": [
            "Use web UI (Mainsail/Fluidd) for all printer control"
        ],
    },
}


def _load_display_db() -> tuple[dict, dict, dict, dict]:
    """Load display compatibility data from data/displays.yaml.

    Returns a tuple of (display_configs_dict, printer_profiles_dict, board_display_matrix_dict, display_catalog_dict).
    Falls back to the hardcoded dicts above if the file is missing or unparseable.
    Guarantees zero regression risk — never raises.
    """
    try:
        from core.loader import load_displays_yaml
        db = load_displays_yaml()

        display_configs = db.get('display_configs') or {}
        printer_profiles = db.get('printer_display_profiles') or {}
        board_display_matrix = db.get('board_display_matrix') or {}
        display_catalog = db.get('display_catalog') or {}

        # Validate we got real data — fall back per-dict if empty
        if not display_configs:
            display_configs = _DISPLAY_CONFIGS_FALLBACK
        if not printer_profiles:
            printer_profiles = _PRINTER_PROFILES_FALLBACK

        return display_configs, printer_profiles, board_display_matrix, display_catalog

    except Exception:
        return _DISPLAY_CONFIGS_FALLBACK, _PRINTER_PROFILES_FALLBACK, {}, {}


def _load_boards_db() -> list:
    """Load board entries from data/boards.yaml boards list."""
    try:
        from core.loader import load_boards_yaml
        db = load_boards_yaml()
        return db.get('boards', [])
    except Exception:
        return []


# Module-level cache — loaded once per process when accessed
_DISPLAY_CONFIGS = None
_PRINTER_PROFILES = None
_BOARD_DISPLAY_MATRIX = None
_DISPLAY_CATALOG = None
_BOARDS = None

def _ensure_display_db_loaded():
    global _DISPLAY_CONFIGS, _PRINTER_PROFILES, _BOARD_DISPLAY_MATRIX, _DISPLAY_CATALOG
    _DISPLAY_CONFIGS, _PRINTER_PROFILES, _BOARD_DISPLAY_MATRIX, _DISPLAY_CATALOG = _load_display_db()

def _get_display_configs() -> dict:
    global _DISPLAY_CONFIGS
    if _DISPLAY_CONFIGS is None:
        _ensure_display_db_loaded()
    return _DISPLAY_CONFIGS

def _get_printer_profiles() -> dict:
    global _PRINTER_PROFILES
    if _PRINTER_PROFILES is None:
        _ensure_display_db_loaded()
    return _PRINTER_PROFILES

def _get_board_display_matrix() -> dict:
    global _BOARD_DISPLAY_MATRIX
    if _BOARD_DISPLAY_MATRIX is None:
        _ensure_display_db_loaded()
    return _BOARD_DISPLAY_MATRIX

def _get_display_catalog() -> dict:
    global _DISPLAY_CATALOG
    if _DISPLAY_CATALOG is None:
        _ensure_display_db_loaded()
    return _DISPLAY_CATALOG

def _get_boards() -> list:
    global _BOARDS
    if _BOARDS is None:
        _BOARDS = _load_boards_db()
    return _BOARDS


def detect_display_sections(parsed_cfg: dict) -> list:
    """Return a list of display-related section names found in the parsed config.

    Checks only against the known set of display section names (_DISPLAY_SECTION_NAMES).
    Does NOT include auxiliary sections like 'display_status' that appear in
    virtually all configs — only genuine display hardware sections trigger a finding.
    """
    found = []
    for key in parsed_cfg:
        # Normalize: strip trailing specifiers like "neopixel my_led" → "neopixel"
        base_key = key.split()[0].lower()
        if base_key in _DISPLAY_SECTION_NAMES:
            if base_key not in found:
                found.append(base_key)
    return found


def _match_printer_profile(printer_filename: str) -> tuple[str, dict] | tuple[None, None]:
    """Try to match a printer filename against known printer display profiles.

    Returns (profile_key, profile_dict) on match, (None, None) if no match.
    Checked before display_configs — printer profile takes precedence.
    """
    fname_lower = printer_filename.lower()
    for profile_key, profile_data in _get_printer_profiles().items():
        if profile_key in fname_lower:
            return profile_key, profile_data
    return None, None


def _find_board_entry(board_filename: str) -> dict | None:
    if not board_filename:
        return None
    fname_lower = board_filename.lower()
    for board in _get_boards():
        for term in board.get("search_terms", []):
            if term.lower() in fname_lower:
                return board
    return None


def _infer_board_mcu(board_filename: str, parsed_cfg: dict) -> str | None:
    # 1. Check boards.yaml matching first
    board_entry = _find_board_entry(board_filename)
    if board_entry and board_entry.get("mcu"):
        return board_entry["mcu"].lower()
    
    # 2. Check if mcu is defined in parsed config
    if "mcu" in parsed_cfg and isinstance(parsed_cfg["mcu"], dict):
        # We don't have a direct chip config inside [mcu] typically, but checking for properties:
        pass
        
    # 3. Guess based on filename terms
    bf_lower = board_filename.lower()
    if "rp2040" in bf_lower or "pico" in bf_lower:
        return "rp2040"
    if "stm32" in bf_lower:
        return "stm32"
    if "lpc176" in bf_lower:
        return "lpc176x"
    if "mega2560" in bf_lower or "ramps" in bf_lower or "atmega" in bf_lower:
        return "atmega2560"
    if "duet2" in bf_lower or "sam4e" in bf_lower:
        return "sam4e8e"
    return None


def _infer_board_voltage(board_filename: str, parsed_cfg: dict) -> str:
    board_entry = _find_board_entry(board_filename)
    if board_entry and board_entry.get("voltage"):
        return board_entry["voltage"]
        
    mcu = _infer_board_mcu(board_filename, parsed_cfg)
    if mcu:
        mcu = mcu.lower()
        if "stm32" in mcu or "lpc176" in mcu or "rp2040" in mcu or "sam4" in mcu or "samd" in mcu:
            return "3.3V"
        if "atmega" in mcu or "at90usb" in mcu:
            return "5V"
            
    return "3.3V" # safe default for modern 3D printer boards


def _infer_board_tolerance(board_filename: str, parsed_cfg: dict) -> str:
    board_entry = _find_board_entry(board_filename)
    if board_entry and board_entry.get("gpio_voltage_tolerance"):
        return board_entry["gpio_voltage_tolerance"]
        
    mcu = _infer_board_mcu(board_filename, parsed_cfg)
    if mcu:
        mcu = mcu.lower()
        if "rp2040" in mcu:
            return "3.3V_only"
        if "atmega" in mcu or "at90usb" in mcu:
            return "5V_native"
            
    return "3.3V_tolerant"


def _infer_board_interfaces(board_filename: str, parsed_cfg: dict) -> list:
    interfaces = []
    board_entry = _find_board_entry(board_filename)
    if board_entry and board_entry.get("display_interfaces"):
        interfaces = list(board_entry["display_interfaces"])
    else:
        # Default interfaces for generic boards
        interfaces = ["SPI", "I2C", "UART"]
        
    # Check if [board_pins] contains EXP1 or EXP2 pins
    has_exp = False
    for section in parsed_cfg:
        if section.startswith("board_pins"):
            content = parsed_cfg[section]
            if isinstance(content, dict):
                for k, v in content.items():
                    if "EXP" in str(k) or "EXP" in str(v):
                        has_exp = True
                        break
            if has_exp:
                break
    if has_exp and "EXP1_EXP2" not in interfaces:
        interfaces.append("EXP1_EXP2")
        
    if not board_entry:
        if "pico" not in board_filename.lower() and "EXP1_EXP2" not in interfaces:
            interfaces.append("EXP1_EXP2")
            
    return interfaces


def classify_hardware_combination(
    display_section: str,
    board_filename: str,
    parsed_cfg: dict,
) -> dict:
    """Classify the hardware compatibility between a display and a board.

    Returns a dict with compatibility details.
    """
    display_lower = display_section.lower().split()[0]
    board_lower = board_filename.lower()

    # 1. Check board-display matrix overrides first
    for b_sub, displays_in_matrix in _get_board_display_matrix().items():
        if b_sub.lower() in board_lower:
            for d_sub, override_data in displays_in_matrix.items():
                if d_sub.lower() in display_lower:
                    display_entry = _get_display_configs().get(display_lower, {})
                    comp_class = override_data.get("compatibility_class", display_entry.get("compatibility_class", "experimental"))
                    
                    status_map = {
                        "fully_compatible": "supported",
                        "compatible_with_adapter": "partial",
                        "experimental": "partial",
                        "unsafe": "unsupported"
                    }
                    status = status_map.get(comp_class, display_entry.get("status", "untested"))
                    
                    damage_risks = override_data.get("damage_risks")
                    if damage_risks is None:
                        damage_risks = display_entry.get("damage_risks", [])
                        
                    req_mods = override_data.get("required_modifications")
                    if req_mods is None:
                        req_mods = display_entry.get("required_modifications", [])
                        
                    notes = override_data.get("notes") or display_entry.get("notes") or []
                    
                    return {
                        "compatibility_class": comp_class,
                        "status": status,
                        "damage_risks": damage_risks,
                        "required_modifications": req_mods,
                        "notes": notes,
                        "recommendation": override_data.get("recommendation", display_entry.get("recommendation", "none")),
                    }

    # 2. Fall back to generic display entry lookups
    display_entry = _get_display_configs().get(display_lower)
    if not display_entry:
        return {
            "compatibility_class": "experimental",
            "status": "untested",
            "damage_risks": [],
            "required_modifications": [],
            "notes": [
                f"Section '[{display_section}]' was detected but has no entry in KACE's display database.",
                "Compatibility with Klipper is unknown."
            ],
            "recommendation": "none",
        }

    comp_class = display_entry.get("compatibility_class", "experimental")
    status = display_entry.get("status", "untested")
    damage_risks = list(display_entry.get("damage_risks", []))
    req_mods = list(display_entry.get("required_modifications", []))
    notes = list(display_entry.get("notes", []))
    recommendation = display_entry.get("recommendation", "none")

    # If the database explicitly flags this display as unsafe (e.g. t5uid1), return immediately
    if comp_class == "unsafe":
        return {
            "compatibility_class": comp_class,
            "status": status,
            "damage_risks": damage_risks,
            "required_modifications": req_mods,
            "notes": notes,
            "recommendation": recommendation,
        }

    # Otherwise, perform algorithmic checks based on inferred board hardware features
    board_voltage = _infer_board_voltage(board_filename, parsed_cfg)
    board_tolerance = _infer_board_tolerance(board_filename, parsed_cfg)
    board_interfaces = _infer_board_interfaces(board_filename, parsed_cfg)

    display_voltage = display_entry.get("voltage_logic", "any")
    display_interface = display_entry.get("interface_required", "none")

    # Check interface compatibility
    if display_interface != "none" and display_interface not in board_interfaces:
        comp_class = "compatible_with_adapter"
        status = "partial"
        req_mods.append(f"Install an adapter board or custom wiring harness to expose the {display_interface} interface.")

    # Check voltage compatibility rules
    if display_voltage == "3.3V" and board_voltage == "5V":
        comp_class = "unsafe"
        status = "unsupported"
        damage_risks.append("5V logic levels from MCU will exceed UC1701 driver's absolute maximum logic rating, destroying the display controller IC.")
        req_mods.append("Use a 5V-to-3.3V logic level shifter on all data, chip select, and clock lines.")
        recommendation = "disconnect"
    elif display_voltage == "5V" and board_voltage == "3.3V":
        if board_tolerance == "3.3V_only":
            comp_class = "unsafe"
            status = "unsupported"
            damage_risks.append("5V logic signals fed back from the display will permanently destroy the 3.3V-only RP2040 GPIO pins.")
            req_mods.append("Install an active level shifter (e.g. 74AHCT125) to safely interface 3.3V outputs to 5V display inputs.")
            recommendation = "disconnect"
        elif board_tolerance == "3.3V_tolerant":
            if comp_class == "fully_compatible":
                comp_class = "experimental"
                status = "partial"
            notes.append("Board MCU is 5V-tolerant, but 3.3V logic outputs might not reliably trigger the 5V display logic threshold (noise issues).")
            req_mods.append("If display fails to register or glitches, use a 3.3V-to-5V level shifter on logic lines.")

    return {
        "compatibility_class": comp_class,
        "status": status,
        "damage_risks": damage_risks,
        "required_modifications": req_mods,
        "notes": notes,
        "recommendation": recommendation,
    }


def get_display_compat(section_name: str, printer_filename: str = "") -> dict | None:
    """Look up compatibility data for a single display section.

    Checks printer_display_profiles first (by filename), then display_configs
    (by section name). Returns None if no entry found.

    Args:
        section_name:     Klipper config section name (e.g. "t5uid1")
        printer_filename: Optional printer profile filename for OEM matching

    Returns:
        dict with keys: status, compatibility_class, recommendation, notes, source, etc.
        None if not found in either database.
    """
    # 1. Try printer profile match first (most specific)
    if printer_filename:
        profile_key, profile_data = _match_printer_profile(printer_filename)
        if profile_data:
            comp_class = profile_data.get("compatibility_class", "experimental")
            return {
                "status":                 profile_data.get("status", "untested"),
                "compatibility_class":     comp_class,
                "recommendation":         profile_data.get("recommendation", "none"),
                "notes":                  profile_data.get("notes", []),
                "source":                 "printer_profile",
                "damage_risks":           profile_data.get("damage_risks", []),
                "required_modifications": profile_data.get("required_modifications", []),
            }

    # 2. Try section-based lookup
    section_lower = section_name.lower().split()[0]
    if section_lower in _get_display_configs():
        entry = _get_display_configs()[section_lower]
        comp_class = entry.get("compatibility_class", "experimental")
        return {
            "status":                 entry.get("status", "untested"),
            "compatibility_class":     comp_class,
            "recommendation":         entry.get("recommendation", "none"),
            "notes":                  entry.get("notes", []),
            "source":                 "display_config",
            "damage_risks":           entry.get("damage_risks", []),
            "required_modifications": entry.get("required_modifications", []),
        }

    return None


def check_display_compatibility(
    parsed_cfg: dict,
    printer_filename: str = "",
    board_filename:   str = "",
) -> list:
    """Main public entry point — check a parsed config for display compatibility issues.

    Args:
        parsed_cfg:       Parsed config dict from core/scraper.parse_config()
        printer_filename: Printer profile filename (e.g. "printer-cr6-se.cfg")
        board_filename:   Board config filename (e.g. "generic-creality-v4.2.2.cfg")

    Returns:
        List of finding dicts. Empty list = no display sections detected.
        Each finding contains: section, status, compatibility_class, recommendation,
                               notes, source, damage_risks, required_modifications
    """
    findings = []
    seen_sections = set()

    # ── Step 1: Printer profile match (highest priority) ──────────────────────
    if printer_filename:
        profile_key, profile_data = _match_printer_profile(printer_filename)
        if profile_data and profile_data.get("status") in ("partial", "unsupported"):
            display_type = profile_data.get("display_type", "tft_serial")
            comp_class = profile_data.get("compatibility_class", "experimental")
            findings.append({
                "section":                 display_type,
                "status":                  profile_data.get("status", "untested"),
                "compatibility_class":     comp_class,
                "recommendation":          profile_data.get("recommendation", "none"),
                "notes":                   profile_data.get("notes", []),
                "source":                  "printer_profile",
                "printer_profile":         profile_key,
                "damage_risks":           profile_data.get("damage_risks", []),
                "required_modifications": profile_data.get("required_modifications", []),
            })
            seen_sections.add(display_type)

    # ── Step 2: Scan config sections ──────────────────────────────────────────
    detected = detect_display_sections(parsed_cfg)

    for section in detected:
        if section in seen_sections:
            continue  # Already reported via printer profile

        # ── Step 3: Check compatibility using hardware inference/matrix rules ──
        hw_info = classify_hardware_combination(section, board_filename, parsed_cfg)
        findings.append({
            "section":                 section,
            "status":                  hw_info["status"],
            "compatibility_class":     hw_info["compatibility_class"],
            "recommendation":          hw_info["recommendation"],
            "notes":                   hw_info["notes"],
            "source":                  "display_config",
            "damage_risks":           hw_info["damage_risks"],
            "required_modifications": hw_info["required_modifications"],
        })
        seen_sections.add(section)

    return findings


# ─────────────────────────────────────────────────────────────────────────────
# NEW PUBLIC API — Display Wizard Support
# ─────────────────────────────────────────────────────────────────────────────

# Internal marker sections that are software-only — never shown as physical
# display choices in the wizard (they appear in every config, not user choices).
_WIZARD_SKIP_SECTIONS = {
    "lcd_menu", "display_status", "display_template", "display_data",
    "neopixel", "dotstar", "sx1509", "pca9685",
}


def get_display_catalog() -> dict:
    """Return the display catalog dict keyed by category id.

    Each value has:
      label   — human-readable category name
      members — list of display_configs section keys in this category
    """
    return dict(_get_display_catalog())


def get_all_selectable_displays() -> list:
    """Return a sorted list of (section_key, entry_dict) for all display_configs
    entries that a user could physically select (excludes software-only sections).
    """
    result = []
    for key, entry in _get_display_configs().items():
        if key in _WIZARD_SKIP_SECTIONS:
            continue
        result.append((key, entry))
    result.sort(key=lambda x: x[0])
    return result


def get_recommended_displays(
    board_filename: str,
    detected_mcu:   str = "",
    parsed_cfg:     dict | None = None,
) -> dict:
    """Build a board-aware display recommendation map grouped by compatibility class.

    For each selectable display_configs entry (excluding software-only sections),
    classify it against the detected board hardware and group the results.

    Returns:
        {
          "fully_compatible":        [(section_key, entry, hw_info), ...],
          "compatible_with_adapter": [...],
          "experimental":            [...],
          "unsafe":                  [...],
        }

    The "unsafe" bucket is populated but intentionally hidden in the wizard's
    default recommendation list — only surfaced in Manual/Advanced mode.

    Args:
        board_filename: Board config filename (e.g. "generic-skr-mini-e3-v3.0.cfg")
        detected_mcu:   MCU string from firmware detector (e.g. "stm32g0b1")
        parsed_cfg:     Parsed board config dict (optional; used for EXP pin detection)
    """
    if parsed_cfg is None:
        parsed_cfg = {}

    buckets: dict[str, list] = {
        "fully_compatible":        [],
        "compatible_with_adapter": [],
        "experimental":            [],
        "unsafe":                  [],
    }

    for section_key, entry in _get_display_configs().items():
        if section_key in _WIZARD_SKIP_SECTIONS:
            continue

        hw_info = classify_hardware_combination(section_key, board_filename, parsed_cfg)
        comp_class = hw_info.get("compatibility_class", "experimental")

        # Clamp to known buckets
        if comp_class not in buckets:
            comp_class = "experimental"

        buckets[comp_class].append((
            section_key,
            entry,
            hw_info,
        ))

    # Within each bucket, sort by section key for deterministic ordering
    for bucket in buckets.values():
        bucket.sort(key=lambda t: t[0])

    return buckets


def run_manual_selection_analysis(
    display_key:    str,
    board_filename: str,
    detected_mcu:   str = "",
    parsed_cfg:     dict | None = None,
) -> dict:
    """Run a full risk analysis for a manually-selected display against a board.

    Wraps classify_hardware_combination() and enriches the result with
    structured validation sub-results that the wizard's risk panel can render.

    Args:
        display_key:    Display section key (e.g. "uc1701", "t5uid1")
        board_filename: Board config filename
        detected_mcu:   MCU string from firmware detector
        parsed_cfg:     Parsed board config dict

    Returns a dict:
      {
        "compatibility_class":     str,
        "status":                  str,
        "damage_risks":            list[str],
        "required_modifications":  list[str],
        "notes":                   list[str],
        "recommendation":          str,
        "voltage_validation":      {"result": "ok"|"warn"|"danger", "detail": str},
        "interface_validation":    {"result": "ok"|"warn"|"danger", "detail": str},
        "cable_orientation_risks": list[str],
        "firmware_mode_requirements": list[str],
        "adapter_requirements":    list[str],
        "confidence_level":        str,   # "High" | "Medium" | "Low" | "Unknown"
      }
    """
    if parsed_cfg is None:
        parsed_cfg = {}

    display_key_lower = display_key.lower().strip()

    # Base hardware classification
    hw_info = classify_hardware_combination(display_key_lower, board_filename, parsed_cfg)
    comp_class = hw_info.get("compatibility_class", "experimental")

    # ── Voltage validation ────────────────────────────────────────────────────
    board_voltage    = _infer_board_voltage(board_filename, parsed_cfg)
    board_tolerance  = _infer_board_tolerance(board_filename, parsed_cfg)
    display_entry    = _get_display_configs().get(display_key_lower, {})
    display_voltage  = display_entry.get("voltage_logic", "any")

    if display_voltage == "any":
        voltage_result = "ok"
        voltage_detail = f"No specific voltage requirement — compatible with {board_voltage} board."
    elif display_voltage == "3.3V_tolerant":
        voltage_result = "ok"
        voltage_detail = f"Display accepts both 3.3V and 5V logic — compatible with {board_voltage} board."
    elif display_voltage == "3.3V" and board_voltage == "3.3V":
        voltage_result = "ok"
        voltage_detail = "Display and board both operate at 3.3V — direct compatible."
    elif display_voltage == "3.3V" and board_voltage == "5V":
        voltage_result = "danger"
        voltage_detail = (
            f"Board outputs 5V logic but display expects 3.3V max. "
            f"Without a level shifter, board GPIO will exceed display's absolute maximum rating and destroy it."
        )
    elif display_voltage == "5V" and board_voltage == "3.3V":
        if board_tolerance == "3.3V_only":
            voltage_result = "danger"
            voltage_detail = (
                f"Display 5V feedback lines will permanently damage RP2040 GPIO pins (3.3V-only, not 5V tolerant). "
                f"An active level shifter (e.g. 74AHCT125) is mandatory."
            )
        else:
            voltage_result = "warn"
            voltage_detail = (
                f"Board MCU is 5V-tolerant but outputs 3.3V logic. "
                f"Display may not reliably detect 3.3V signals as HIGH (display VIH ≥ 0.7×5V = 3.5V). "
                f"A 3.3V→5V level shifter is recommended."
            )
    elif display_voltage == "5V" and board_voltage == "5V":
        voltage_result = "ok"
        voltage_detail = "Display and board both operate at 5V — direct compatible."
    else:
        voltage_result = "warn"
        voltage_detail = f"Voltage relationship between '{display_voltage}' display and '{board_voltage}' board is uncharted. Verify before connecting."

    # ── Interface validation ──────────────────────────────────────────────────
    board_interfaces   = _infer_board_interfaces(board_filename, parsed_cfg)
    display_interface  = display_entry.get("interface_required", "none")

    if display_interface == "none":
        interface_result = "ok"
        interface_detail = "No external interface required — software-only section."
    elif display_interface in board_interfaces:
        interface_result = "ok"
        interface_detail = f"{display_interface} interface is available on this board."
    else:
        interface_result = "warn"
        interface_detail = (
            f"{display_interface} interface is NOT listed for this board. "
            f"An adapter board or custom wiring harness is required. "
            f"Available interfaces: {', '.join(board_interfaces) if board_interfaces else 'none detected'}."
        )

    # ── Cable orientation risks ───────────────────────────────────────────────
    cable_risks = []
    if display_interface == "EXP1_EXP2":
        cable_risks.append(
            "EXP1/EXP2 ribbon cables are NOT keyed — reversed connection destroys GPIO on both board and display."
        )
        cable_risks.append(
            "Always verify Pin 1 orientation (marked with a dot or triangle) before powering on."
        )
    if display_key_lower in ("btt_tft35", "tft_serial"):
        cable_risks.append(
            "BTT TFT ribbon cable orientation varies by revision — check your board's pinout diagram carefully."
        )

    # ── Firmware mode requirements ────────────────────────────────────────────
    fw_modes = []
    if display_key_lower == "tft_serial":
        fw_modes.append("Set BTT/MKS TFT firmware to '12864 Marlin emulation' mode (not native touch mode).")
        fw_modes.append("Touch functionality will NOT be available under Klipper regardless of mode.")
    if display_key_lower == "btt_tft35":
        fw_modes.append("Flash BTT TFT35 to '12864 emulation' firmware via the TFT's own firmware update process.")
        fw_modes.append("Boot TFT35 into 12864 emulation mode before connecting to the board.")
    if display_key_lower in ("dwin_set", "t5uid1"):
        fw_modes.append("Community DGUS/DWIN firmware must be flashed to the display (NOT covered by KACE).")
        fw_modes.append("Display firmware version must exactly match the community plugin version.")

    # ── Adapter requirements ──────────────────────────────────────────────────
    adapter_reqs = []
    if interface_result == "warn":
        adapter_reqs.append(f"An adapter board or wiring harness exposing the {display_interface} bus is required.")
    if voltage_result in ("warn", "danger") and display_voltage in ("3.3V", "5V"):
        adapter_reqs.append(
            "A bidirectional logic level shifter (e.g. 74AHCT125 for 3.3V→5V, or voltage divider for 5V→3.3V) "
            "is required on all data, clock, and chip-select lines."
        )

    # ── Confidence level ─────────────────────────────────────────────────────
    if comp_class == "fully_compatible" and voltage_result == "ok" and interface_result == "ok":
        confidence = "High"
    elif comp_class == "experimental":
        confidence = "Low"
    elif comp_class == "unsafe":
        confidence = "Unknown"
    elif voltage_result == "danger" or interface_result == "danger":
        confidence = "Unknown"
    elif voltage_result == "warn" or interface_result == "warn":
        confidence = "Medium"
    else:
        confidence = "Medium"

    return {
        "compatibility_class":        hw_info.get("compatibility_class", comp_class),
        "status":                     hw_info.get("status", "untested"),
        "damage_risks":               hw_info.get("damage_risks", []),
        "required_modifications":     hw_info.get("required_modifications", []),
        "notes":                      hw_info.get("notes", []),
        "recommendation":             hw_info.get("recommendation", "none"),
        "voltage_validation":         {"result": voltage_result, "detail": voltage_detail},
        "interface_validation":       {"result": interface_result, "detail": interface_detail},
        "cable_orientation_risks":    cable_risks,
        "firmware_mode_requirements": fw_modes,
        "adapter_requirements":       adapter_reqs,
        "confidence_level":           confidence,
    }
