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
#     "source":                  str   — "printer_profile" | "display_config"
#     "damage_risks":            list  — list of potential risks
#     "required_modifications":  list  — list of steps to make safe
#   }
#
# Design contract:
#   - data/displays.yaml and data/boards.yaml are authoritative
#   - Missing or invalid hardware data fails closed
#   - Never modifies the parsed config

# ── Authoritative data loaders ────────────────────────────────────────────────
def _load_display_db() -> tuple[dict, dict, dict, dict]:
    """Load display compatibility data from data/displays.yaml.

    Returns a tuple of (display_configs_dict, printer_profiles_dict, board_display_matrix_dict, display_catalog_dict).
    Missing, empty, or malformed authoritative data is a hard error.
    """
    try:
        from core.loader import load_displays_yaml
        db = load_displays_yaml()

        display_configs = db.get('display_configs') or {}
        printer_profiles = db.get('printer_display_profiles') or {}
        board_display_matrix = db.get('board_display_matrix') or {}
        display_catalog = db.get('display_catalog') or {}

        if not display_configs:
            raise RuntimeError("[KACE] displays.yaml has no display_configs entries")
        if not printer_profiles:
            raise RuntimeError(
                "[KACE] displays.yaml has no printer_display_profiles entries"
            )

        return display_configs, printer_profiles, board_display_matrix, display_catalog

    except Exception as exc:
        raise RuntimeError(
            f"[KACE] failed to load authoritative displays.yaml: {exc}"
        ) from exc


def _load_boards_db() -> list:
    """Load board entries from data/boards.yaml boards list."""
    try:
        from core.loader import load_boards_yaml
        db = load_boards_yaml()
        boards = db.get('boards', [])
        if not boards:
            raise RuntimeError("[KACE] boards.yaml has no boards entries")
        return boards
    except Exception as exc:
        raise RuntimeError(
            f"[KACE] failed to load authoritative boards.yaml: {exc}"
        ) from exc


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

    Checks only against section names from authoritative displays.yaml.
    Does NOT include auxiliary sections like 'display_status' that appear in
    virtually all configs — only genuine display hardware sections trigger a finding.
    """
    found = []
    known_sections = _get_display_configs()
    for key in parsed_cfg:
        # Normalize: strip trailing specifiers like "neopixel my_led" → "neopixel"
        base_key = key.split()[0].lower()
        if base_key in known_sections:
            if base_key not in found:
                found.append(base_key)
    return found


def _match_printer_profile(printer_filename: str) -> tuple[str, dict] | tuple[None, None]:
    """Resolve an exact declared OEM filename or explicit legacy alias.

    Identity is not hardware qualification. Family substrings and dictionary
    order must never select a different variant. Ambiguous database identities
    are errors, rather than permission to fall back to a generic display.
    """
    identities = {}
    for profile_key, profile_data in _get_printer_profiles().items():
        for field in ("config_filenames", "filename_aliases"):
            names = profile_data.get(field, [])
            if not isinstance(names, list):
                raise RuntimeError(f"[KACE] invalid OEM {field}: {profile_key}")
            for name in names:
                if (not isinstance(name, str) or not name.endswith(".cfg")
                        or name != name.strip().casefold() or "/" in name or "\\" in name):
                    raise RuntimeError(f"[KACE] invalid OEM filename: {profile_key}")
                if name in identities:
                    raise RuntimeError(f"[KACE] ambiguous OEM filename: {name}")
                identities[name] = (profile_key, profile_data)
    return identities.get(printer_filename.strip().casefold(), (None, None))


def _find_board_entry(board_filename: str, detected_mcu: str = "") -> dict | None:
    """Resolve display metadata only for an exact reviewed filename/MCU pair.

    A selected MCU narrows known variants; it never legitimizes another filename.
    This resolves declared identity, not physical wiring or processor detection.
    """
    if not board_filename:
        return None
    filename = board_filename.strip().casefold()
    mcu = str(detected_mcu or "").strip().casefold()
    candidates = [board for board in _get_boards()
                  if filename in board.get("display_config_filenames", [])]
    if mcu:
        candidates = [board for board in candidates if board.get("mcu", "").casefold() == mcu]
    elif any(filename in board.get("display_requires_mcu", []) for board in candidates):
        return None
    # Conflicting/duplicate bindings cannot be resolved by database order.
    return candidates[0] if len(candidates) == 1 else None


def _infer_board_mcu(board_filename: str, parsed_cfg: dict, detected_mcu: str = "") -> str | None:
    board_entry = _find_board_entry(board_filename, detected_mcu)
    if board_entry and board_entry.get("mcu"):
        return board_entry["mcu"].lower()
    
    return None


def _infer_board_voltage(board_filename: str, parsed_cfg: dict, detected_mcu: str = "") -> str | None:
    board_entry = _find_board_entry(board_filename, detected_mcu)
    if board_entry and board_entry.get("voltage"):
        return board_entry["voltage"]
        
    return None


def _infer_board_tolerance(board_filename: str, parsed_cfg: dict, detected_mcu: str = "") -> str | None:
    board_entry = _find_board_entry(board_filename, detected_mcu)
    if board_entry and board_entry.get("gpio_voltage_tolerance"):
        return board_entry["gpio_voltage_tolerance"]
        
    return None


def _infer_board_interfaces(board_filename: str, parsed_cfg: dict, detected_mcu: str = "") -> list:
    board_entry = _find_board_entry(board_filename, detected_mcu)
    if not board_entry:
        return []
    # Legacy MCU bus flags establish neither exposed pins nor display wiring.
    # Only the separately reviewed connector mapping is evidence here.
    interfaces = []
    from core.loader import load_boards_yaml
    mappings = load_boards_yaml().get("display_exp_mappings", {})
    mapped = mappings.get(board_filename.strip().casefold()) if isinstance(mappings, dict) else None
    if mapped == ["EXP1", "EXP2"]:
        interfaces.extend(["EXP1", "EXP2", "EXP1_EXP2"])
    elif mapped == ["EXP1"]:
        interfaces.append("EXP1")
    # Missing/malformed mapping stays unknown. Runtime aliases are not evidence.
    return interfaces


def _display_hardware_entry(display_section: str, parsed_cfg: dict) -> dict:
    """Use the selected controller, not generic EXP metadata, for real LCDs."""
    key = display_section.lower().strip()
    if key.split()[0] == "display":
        sections = [fields for name, fields in parsed_cfg.items()
                    if name.lower() == key or (key == "display" and name.lower().startswith("display "))]
        if sections:
            drivers = {str(fields.get("lcd_type", "")).strip().lower()
                       for fields in sections if isinstance(fields, dict)}
            # A base-section diagnostic may aggregate several displays. Do not
            # let one known controller certify missing or different controllers.
            if len(drivers) != 1 or not all(isinstance(fields, dict) for fields in sections):
                return {}
            key = drivers.pop()
            # LCD_chips at the reviewed Klipper refs. A software section or
            # catalog-only OEM entry is not a valid lcd_type.
            from core.display_configuration import DISPLAY_REQUIRED_OPTIONS
            if key not in DISPLAY_REQUIRED_OPTIONS:
                return {}
    return _get_display_configs().get(key.split()[0] if key else "", {})


def _display_voltage_conflict(entry: dict, board_filename: str, detected_mcu: str = "") -> bool:
    board = _find_board_entry(board_filename, detected_mcu) or {}
    return ((entry.get("voltage_logic") == "3.3V" and board.get("voltage") == "5V")
            or (entry.get("voltage_logic") == "5V" and board.get("voltage") == "3.3V"
                and board.get("gpio_voltage_tolerance") == "3.3V_only"))


def _missing_display_board_evidence(display_entry: dict, board_filename: str, detected_mcu: str = "") -> list:
    if display_entry.get("interface_required") == "none":
        return []
    board = _find_board_entry(board_filename, detected_mcu)
    if not board:
        return ["board identity", "interface", "electrical data"]
    missing = [field for field in ("mcu", "voltage", "gpio_voltage_tolerance", "display_interfaces")
               if not board.get(field)]
    display_voltage = display_entry.get("voltage_logic")
    if display_voltage not in ("3.3V", "5V", "3.3V_tolerant"):
        # Only software-only entries may treat voltage as unrestricted.
        missing.append("display logic voltage")
    elif display_voltage == "3.3V_tolerant" and board.get("voltage") == "5V":
        # A nominal 3.3 V label is not evidence that a module accepts 5 V
        # signals. Its supply voltage and Klipper driver do not prove this.
        missing.append("5V input tolerance of the display module")
    interface = display_entry.get("interface_required")
    if interface in ("EXP1", "EXP2", "EXP1_EXP2"):
        # Current EXP entries identify controller families, not exact modules
        # with reviewed signal thresholds, wiring and supply requirements.
        # Board aliases and accepted risk cannot supply that evidence.
        missing.append("display module identity and reviewed electrical/wiring specification")
    if (interface != "none"
            and interface not in _infer_board_interfaces(board_filename, {}, detected_mcu)):
        missing.append("reviewed connector/bus mapping for " + str(interface))
    if (display_entry.get("voltage_logic") == "5V" and board.get("voltage") == "3.3V"
            and board.get("gpio_voltage_tolerance") not in ("3.3V_only", "5V_tolerant")):
        # 3.3 V tolerance says nothing about whether a selected GPIO accepts 5 V.
        # A known 3.3 V-only incompatibility remains unsafe, rather than unknown.
        missing.append("5V input tolerance of the selected GPIOs")
    return missing


def classify_hardware_combination(
    display_section: str,
    board_filename: str,
    parsed_cfg: dict,
    detected_mcu: str = "",
) -> dict:
    """Classify the hardware compatibility between a display and a board.

    Returns a dict with compatibility details.
    """
    display_lower = display_section.lower().split()[0]
    board_lower = board_filename.lower()

    entry = _display_hardware_entry(display_section, parsed_cfg)
    voltage_conflict = _display_voltage_conflict(entry, board_filename, detected_mcu)
    missing = _missing_display_board_evidence(entry, board_filename, detected_mcu)
    if missing and entry.get("compatibility_class") != "unsafe" and not voltage_conflict:
        return {
            "compatibility_class": "experimental", "status": "untested",
            "hardware_evidence": "unknown", "missing_evidence": missing,
            "damage_risks": list(entry.get("damage_risks", [])),
            "required_modifications": [], "recommendation": "none",
            "notes": ["Hardware compatibility is unknown: missing " + ", ".join(missing) + ".",
                      "Klipper LCD driver support and EXP aliases do not establish electrical compatibility.",
                      "KACE cannot generate an active display configuration without board and display hardware evidence."],
        }

    # 1. Check board-display matrix overrides first
    for b_sub, displays_in_matrix in _get_board_display_matrix().items():
        if entry.get("compatibility_class") == "unsafe" or voltage_conflict:
            break  # Positive matrix metadata cannot erase a known hazard.
        if b_sub.lower() in board_lower:
            for d_sub, override_data in displays_in_matrix.items():
                if d_sub.lower() in display_lower:
                    display_entry = entry
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
    display_entry = entry
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
    board_voltage = _infer_board_voltage(board_filename, parsed_cfg, detected_mcu)
    board_tolerance = _infer_board_tolerance(board_filename, parsed_cfg, detected_mcu)

    display_voltage = display_entry.get("voltage_logic", "any")

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
            req_mods.append("Do not connect 5V feedback to 3.3V-only GPIOs. Voltage translation must be reviewed for each signal direction and device.")
            recommendation = "disconnect"
        elif board_tolerance == "5V_tolerant":
            if comp_class == "fully_compatible":
                comp_class = "experimental"
                status = "partial"
            notes.append("Declared 5V input tolerance does not establish that 3.3V outputs meet the display's input thresholds.")
            req_mods.append("Verify the selected GPIOs, display input thresholds and signal directions before connecting.")

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
            if comp_class != "unsafe":
                result = classify_hardware_combination(profile_data.get("display_type", section_name), "", {})
                return {**result, "source": "printer_profile"}
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
        return {**classify_hardware_combination(section_lower, "", {}), "source": "display_config"}

    return None


def check_display_compatibility(
    parsed_cfg: dict,
    printer_filename: str = "",
    board_filename:   str = "",
    detected_mcu:     str = "",
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
            if comp_class != "unsafe":
                findings[-1].update(classify_hardware_combination(
                    display_type, board_filename, parsed_cfg, detected_mcu,
                ))
            seen_sections.add(display_type)

    # ── Step 2: Scan config sections ──────────────────────────────────────────
    detected = detect_display_sections(parsed_cfg)

    for section in detected:
        if section in seen_sections:
            continue  # Already reported via printer profile

        # ── Step 3: Check compatibility using hardware inference/matrix rules ──
        hw_info = classify_hardware_combination(section, board_filename, parsed_cfg, detected_mcu)
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
        if hw_info.get("hardware_evidence") == "unknown":
            findings[-1]["hardware_evidence"] = "unknown"
            findings[-1]["missing_evidence"] = list(hw_info["missing_evidence"])
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
        parsed_cfg:     Parsed board config dict (optional; aliases do not establish hardware compatibility)
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

        hw_info = classify_hardware_combination(section_key, board_filename, parsed_cfg, detected_mcu)
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
    hw_info = classify_hardware_combination(display_key_lower, board_filename, parsed_cfg, detected_mcu)
    display_entry = _display_hardware_entry(display_key_lower, parsed_cfg)
    missing = _missing_display_board_evidence(display_entry, board_filename, detected_mcu)
    if hw_info.get("hardware_evidence") == "unknown" or missing:
        voltage_conflict = _display_voltage_conflict(display_entry, board_filename, detected_mcu)
        interface = display_entry.get("interface_required")
        interface_mapped = interface in _infer_board_interfaces(board_filename, parsed_cfg, detected_mcu)
        return {**hw_info,
            "voltage_validation": {
                "result": "danger" if voltage_conflict else "unknown",
                "detail": ("Declared board/display logic levels conflict; do not treat the connection as safe."
                           if voltage_conflict else "Board/display electrical compatibility is not established.")},
            "interface_validation": {
                "result": "ok" if interface_mapped else "unknown",
                "detail": (f"{interface} is mapped in the reviewed board reference; display wiring and electrical compatibility remain unverified."
                           if interface_mapped else "Required connector and pinout are not established.")},
            "cable_orientation_risks": [], "firmware_mode_requirements": [],
            "adapter_requirements": [], "confidence_level": "Unknown"}
    comp_class = hw_info.get("compatibility_class", "experimental")

    # ── Voltage validation ────────────────────────────────────────────────────
    board_voltage    = _infer_board_voltage(board_filename, parsed_cfg, detected_mcu)
    board_tolerance  = _infer_board_tolerance(board_filename, parsed_cfg, detected_mcu)
    display_voltage  = display_entry.get("voltage_logic", "any")

    if display_voltage == "any":
        voltage_result = "ok"
        voltage_detail = f"No specific voltage requirement — compatible with {board_voltage} board."
    elif display_voltage == "3.3V_tolerant":
        voltage_result = "ok"
        voltage_detail = (
            "The catalog declares 3.3V logic compatibility; this does not establish 5V input tolerance. "
            "Verify the exact module's supply, signal directions and input thresholds."
        )
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
                f"Do not connect until voltage translation for each signal direction has been reviewed."
            )
        else:
            voltage_result = "warn"
            voltage_detail = (
                f"Declared 5V input tolerance does not establish that 3.3V outputs meet the display's input thresholds. "
                f"Verify the selected GPIOs and the specific display's electrical specifications."
            )
    elif display_voltage == "5V" and board_voltage == "5V":
        voltage_result = "ok"
        voltage_detail = "Display and board both operate at 5V — direct compatible."
    else:
        voltage_result = "warn"
        voltage_detail = f"Voltage relationship between '{display_voltage}' display and '{board_voltage}' board is uncharted. Verify before connecting."

    # ── Interface validation ──────────────────────────────────────────────────
    board_interfaces   = _infer_board_interfaces(board_filename, parsed_cfg, detected_mcu)
    display_interface  = display_entry.get("interface_required", "none")

    if display_interface == "none":
        interface_result = "ok"
        interface_detail = "No external interface required — software-only section."
    elif display_interface in board_interfaces:
        interface_result = "ok"
        if display_interface in ("EXP1", "EXP2", "EXP1_EXP2"):
            interface_detail = f"{display_interface} is mapped in the reviewed board reference; verify the exact display wiring and electrical limits separately."
        else:
            interface_detail = f"{display_interface} has a reviewed mapping; verify the selected device and wiring separately."
    else:
        interface_result = "warn"
        interface_detail = (
            f"{display_interface} interface is NOT listed for this board. "
            f"Wiring and transport must be reviewed before connecting. "
            f"Reviewed mappings: {', '.join(board_interfaces) if board_interfaces else 'none'}."
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
    if voltage_result in ("warn", "danger") and display_voltage in ("3.3V", "5V"):
        adapter_reqs.append(
            "Voltage translation is not specified by KACE: review each signal's direction, voltage limits, "
            "input thresholds, pull-ups and timing for the exact board and display."
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
