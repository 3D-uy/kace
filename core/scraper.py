import urllib.request
import json
import re
import os
import time

from firmware.boards.upstream import load_klipper_source_contract
from core.config_sections import section_identity

KLIPPER_REF = load_klipper_source_contract().validated_commit

CACHE_EXPIRY_SECONDS = 3 * 24 * 3600  # 3 days cache duration

# ── Modular BLTouch database ───────────────────────────────────────────────────
# Loaded exclusively from the authoritative data/boards.yaml database.

    # ── LPC176x ────────────────────────────────────────────────
    # ── STM32F103 ──────────────────────────────────────────────
    # ── STM32F429 (Octopus Pro v1.0 / SKR-2) ─────────────────
    # ── STM32F446 (Octopus / Spider) — more-specific key first ─
    # ── STM32H723 (Octopus MAX EZ) ───────────────────────────
    # ── AVR / other ──────────────────────────────────────────

def _load_bltouch_db() -> dict:
    """Load BLTouch pin overrides from data/boards.yaml.

    Returns a flat dict mapping exact filename → {sensor_pin, control_pin}.
    Missing or invalid authoritative data is a hard error.
    """
    try:
        from core.loader import load_boards_yaml
        db = load_boards_yaml()
        result = {}
        for entry in db.get('boards', []):
            for board_key, pins in entry.get('bltouch', {}).items():
                if pins:
                    result[board_key] = pins
        if result:
            return result
        
        raise RuntimeError("[KACE] boards.yaml has no BLTouch pin entries")
    except Exception as e:
        raise RuntimeError(f"[KACE] failed to load authoritative boards.yaml: {e}") from e

# Lazy-loaded cache module-level database
_BLTOUCH_DB = None

def _get_bltouch_db() -> dict:
    global _BLTOUCH_DB
    if _BLTOUCH_DB is None:
        _BLTOUCH_DB = _load_bltouch_db()
    return _BLTOUCH_DB


def get_bltouch_pins_for_board(board_name: str) -> dict:
    """Return known BLTouch pin overrides for *board_name*, or an empty dict.

    Matches an exact config filename in ``data/boards.yaml`` (case-insensitive).
    A similar name or MCU family is not evidence for another board revision.
    Returns a dict with ``sensor_pin`` and ``control_pin`` keys, or ``{}``
    when no entry matches.

    Callers should treat an empty return value as "pins unknown" and prompt
    the user interactively rather than emitting placeholder TODO strings into
    the generated config.
    """
    if not board_name:
        return {}
    return dict(_get_bltouch_db().get(board_name.lower(), {}))


def _bltouch_fallback_is_available(sections, pins):
    """Check known allocations before suggesting a complete wiring example.

    Structured BLTouch generation replaces the primary Z endstop with the probe
    virtual endstop, so only the sensor may reuse that input. This is not proof
    of connector availability or firmware transport reservations.
    """
    from core.pin_validator import PinAliases, PinAliasError

    try:
        resolver = PinAliases(sections)
        identities = {role: resolver.resolve(pin) for role, pin in pins.items()}
        if len(set(identities.values())) != 2:
            return False
        for section, options in sections.items():
            if (section == "bltouch" or section == "board_pins"
                    or section.startswith("board_pins ") or section == "duplicate_pin_override"):
                continue
            for key, value in options.items():
                if not (key == "pin" or key.endswith("_pin")
                        or key in ("pins", "select_pins", "encoder_pins")):
                    continue
                for token in re.split(r"[,\s]+", value.strip()):
                    if not token:
                        continue
                    identity = resolver.resolve(token)
                    for role, candidate in identities.items():
                        if identity != candidate:
                            continue
                        if role == "sensor_pin" and section == "stepper_z" and key == "endstop_pin":
                            continue
                        return False
    except PinAliasError:
        return False
    return True


def fetch_config_list():
    """Fetches the list of generic and printer configs from Klipper GitHub."""
    cache_file = os.path.expanduser(f"~/.kace_boards_cache.{KLIPPER_REF}.json")
    
    # 1. Check persistent cache first (valid for CACHE_EXPIRY_SECONDS)
    try:
        if os.path.exists(cache_file):
            if time.time() - os.path.getmtime(cache_file) < CACHE_EXPIRY_SECONDS:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    configs = json.load(f)
                    if configs:
                        return configs
    except Exception:
        pass

    # 2. Try GitHub API
    url = f"https://api.github.com/repos/Klipper3d/klipper/contents/config?ref={KLIPPER_REF}"
    req = urllib.request.Request(url, headers={'User-Agent': 'KACE-App'})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            configs = [item['name'] for item in data if item['name'].startswith('generic-') or item['name'].startswith('printer-')]
            
            try:
                # S-05: Write with owner-only permissions (0o600) — the cache
                # contains board-selection history that should not be
                # world-readable on a multi-user system.
                _fd = os.open(cache_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(_fd, 'w', encoding='utf-8') as f:
                    json.dump(configs, f)
            except Exception as _cw_err:
                if os.environ.get("KACE_DEBUG") == "1":
                    print(f"[DEBUG] Cache write failed: {_cw_err}")
            
            return configs
    except Exception as api_err:
        # 3. API Limit hit, fallback to scraping GitHub HTML tree
        try:
            tree_url = f"https://github.com/Klipper3d/klipper/tree/{KLIPPER_REF}/config"
            req_html = urllib.request.Request(tree_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) KACE-App'})
            with urllib.request.urlopen(req_html, timeout=10) as response:
                html = response.read().decode('utf-8', errors='ignore')
                
                # Extract from React JSON payload or standard hrefs
                matches = re.findall(r'"name":"((?:generic|printer)-[^"]+\.cfg)"', html)
                matches_url = re.findall(r'href="/Klipper3d/klipper/blob/[^/]+/config/((?:generic|printer)-.*?\.cfg)"', html)
                configs = list(set(matches + matches_url))
                
                if not configs:
                    if os.environ.get("KACE_DEBUG") == "1":
                        print("\n\033[93m[DEBUG] HTML scraping regex returned zero matches.\033[0m")
                
                if configs:
                    configs = sorted(configs)
                    try:
                        # S-05: Same 0o600 permission enforcement as the API path above.
                        _fd = os.open(cache_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                        with os.fdopen(_fd, 'w', encoding='utf-8') as f:
                            json.dump(configs, f)
                    except Exception as _cw_err:
                        if os.environ.get("KACE_DEBUG") == "1":
                            print(f"[DEBUG] Cache write failed: {_cw_err}")
                    return configs
        except Exception:
            pass
            
        # 4. Try expired cache as last resort
        try:
            if os.path.exists(cache_file):
                with open(cache_file, 'r', encoding='utf-8') as f:
                    configs = json.load(f)
                    if configs:
                        return configs
        except Exception:
            pass

        print(f"\n\033[93mWarning: Error fetching config list from GitHub ({api_err}). Falling back to manual entry.\033[0m")
        return ["generic-bigtreetech-skr-v1.4.cfg", "generic-creality-v4.2.2.cfg"]

def fetch_raw_config(filename):
    """Fetches the raw content of a specific config file."""
    cache_dir = os.path.expanduser(f"~/.kace_configs_cache/{KLIPPER_REF}")
    # R-08: Use exist_ok=True to eliminate the TOCTOU race between the
    # os.path.exists() check and os.makedirs() call.
    try:
        os.makedirs(cache_dir, exist_ok=True)
    except OSError:
        pass
        
    cache_file = os.path.join(cache_dir, os.path.basename(filename))
    
    # 1. Check cache first (valid for CACHE_EXPIRY_SECONDS)
    try:
        if os.path.exists(cache_file):
            if time.time() - os.path.getmtime(cache_file) < CACHE_EXPIRY_SECONDS:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    return f.read()
    except Exception:
        pass

    url = f"https://raw.githubusercontent.com/Klipper3d/klipper/{KLIPPER_REF}/config/{filename}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 KACE-App'})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            content = response.read().decode('utf-8', errors='ignore')
            # Save to cache
            # S2-02: Enforce 0o600 (owner-only) so raw board configs are not
            # world-readable on shared/multi-user systems.
            try:
                _fd = os.open(cache_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(_fd, 'w', encoding='utf-8') as f:
                    f.write(content)
            except Exception as _cw_err:
                if os.environ.get("KACE_DEBUG") == "1":
                    print(f"[DEBUG] Raw config cache write failed: {_cw_err}")
            return content
    except Exception as e:
        # Fallback to expired cache
        try:
            if os.path.exists(cache_file):
                with open(cache_file, 'r', encoding='utf-8') as f:
                    return f.read()
        except Exception:
            pass
        print(f"\n\033[93mWarning: Failed to fetch {filename} ({e}).\033[0m")
        return ""

def parse_config(raw_cfg, filename="", keep_comments=False):
    """
    Parses the raw Klipper config. 
    Extracts pins from active configuration. If keep_comments is True,
    it also extracts from commented-out sections (like #[tmc2208 stepper_x]).
    """
    data = {}
    active_keys = {}
    active_sections = set()
    current_section = None
    section_commented = False
    last_key = None
    last_key_indent = 0
    for raw_line in raw_cfg.split('\n'):
        line = raw_line.strip()
        if not line: continue
        
        # Match section headers like [stepper_x] or #[tmc2208 stepper_x]
        section_match = re.match(r'^#?\s*\[(.*?)\]', line)
        if section_match:
            is_header_commented = line.startswith('#')

            # BUG-004 fix: only switch the active section on a commented header
            # when keep_comments=True.  In normal parse mode, a `#[section]`
            # inline annotation does NOT terminate the current section — keys
            # that follow still belong to the section that was active before
            # the comment.  Failing to enforce this caused keys after a
            # `#[tmc2209 stepper_x]` annotation to be attributed to
            # `tmc2209 stepper_x` instead of the enclosing active section.
            if is_header_commented and not keep_comments:
                # Ignore the commented-out section header; do not switch section.
                last_key = None
                continue

            current_section = section_identity(section_match.group(1))
            section_commented = is_header_commented
            if not section_commented:
                active_sections.add(current_section)
            if current_section not in data:
                data[current_section] = {}
            active_keys.setdefault(current_section, set())
            last_key = None
            continue
        elif re.match(r'^#?\s*\[', line):
            # Malformed section header (missing closing bracket).
            # Clear active section context to prevent leakage of subsequent keys.
            current_section = None
            last_key = None
            continue
        
        if current_section:
            # A namespaced pin on a continuation line contains ':' but is not
            # a new option. Match ConfigParser's indentation rule for this list.
            indent = len(raw_line) - len(raw_line.lstrip())
            if (((last_key == 'pins' and current_section.startswith('static_digital_output '))
                    or (last_key == 'heater' and current_section.startswith('heater_fan ')))
                    and indent > last_key_indent and not line.startswith('#')
                    and not section_commented):
                data[current_section][last_key] += '\n    ' + line.split('#', 1)[0].strip()
                continue
            # Match key-value pairs like step_pin: P2.2 or #uart_pin: P1.10
            kv_match = re.match(r'^#?\s*([a-zA-Z0-9_]+)\s*:\s*(.*)', line)
            if kv_match:
                is_key_commented = line.startswith('#')
                if not keep_comments and is_key_commented and not section_commented:
                    # Ignore commented-out keys in an active section
                    continue
                
                key = kv_match.group(1).strip().lower()
                val = kv_match.group(2).strip()
                
                # Keep named board_pins sections and their MCU ownership.
                # An option must never silently move into another section.
                # Clean up inline comments
                if '#' in val and key != 'aliases':
                    val = val.split('#')[0].strip()
                    
                is_active_key = not (section_commented or is_key_commented)
                if is_active_key:
                    data[current_section][key] = val
                    active_keys.setdefault(current_section, set()).add(key)
                else:
                    if key not in active_keys.get(current_section, set()):
                        data[current_section][key] = val
                last_key = key
                if is_active_key:
                    last_key_indent = indent
            elif last_key and (last_key == 'aliases' or last_key.startswith('aliases_')):
                clean_val = line
                if clean_val.startswith('#'):
                    if not keep_comments:
                        continue
                    stripped = clean_val.lstrip('#').strip()
                    if '=' in stripped:
                        clean_val = stripped
                    else:
                        clean_val = '# ' + stripped
                        
                if clean_val and "TODO" in clean_val:
                    # Filter out individual EXP1/EXP2 mappings containing TODO
                    parts = []
                    for p in clean_val.split(','):
                        p_strip = p.strip()
                        if "TODO" in p_strip and ("EXP" in p_strip):
                            continue
                        if p_strip:
                            parts.append(p_strip)
                    if parts:
                        clean_val = ', '.join(parts) + (',' if clean_val.rstrip().endswith(',') else '')
                    else:
                        clean_val = ""
                        
                if clean_val:
                    data[current_section][last_key] += '\n    ' + clean_val
                
    # Suggest a complete reviewed pair only when the source specifies neither
    # pin. Never mix a partial custom wiring choice with another wiring example.
    if "bltouch" not in data:
        data["bltouch"] = {}

    pins = get_bltouch_pins_for_board(filename)
    if (pins and not any(key in data["bltouch"] for key in ("sensor_pin", "control_pin"))
            and _bltouch_fallback_is_available(data, pins)):
        data["bltouch"].update(pins)

    from core.probe_configuration import BLTOUCH_HARDWARE_SOURCE, BLTOUCH_HARDWARE_OPTIONS
    if any(key in data["bltouch"] for key in BLTOUCH_HARDWARE_OPTIONS):
        data[BLTOUCH_HARDWARE_SOURCE] = {
            key: data["bltouch"][key] for key in active_keys.get("bltouch", set())
        } if "bltouch" in active_sections else {}

    from core.probe_sampling import SOURCE as PROBE_SAMPLING_SOURCE, OPTIONS as PROBE_SAMPLING_OPTIONS
    if any(key in data["bltouch"] for key in PROBE_SAMPLING_OPTIONS):
        data[PROBE_SAMPLING_SOURCE] = {
            key: data["bltouch"][key] for key in active_keys.get("bltouch", set())
            if key in PROBE_SAMPLING_OPTIONS
        } if "bltouch" in active_sections else {}

    from core.homing_source import ADDITIONAL_Z_ENDSTOPS
    extra_z = [f"stepper_z{i}" for i in range(1, 4) if f"stepper_z{i}" in data]
    if extra_z:
        data[ADDITIONAL_Z_ENDSTOPS] = {
            name: data[name].get("endstop_pin")
            if name in active_sections and "endstop_pin" in active_keys.get(name, set()) else None
            for name in extra_z
        }

    # Fan discovery may include commented examples; generation must only retain
    # active options from the source fan unless the user explicitly selects a pin.
    if "fan" in data:
        from core.part_fan import SOURCE_OPTIONS as FAN_SOURCE_OPTIONS
        data[FAN_SOURCE_OPTIONS] = (
            {key: data["fan"][key] for key in active_keys.get("fan", set())}
            if "fan" in active_sections else None
        )

    if "mcu" in data:
        from core.primary_mcu import SOURCE as MCU_SOURCE
        data[MCU_SOURCE] = {
            key: data['mcu'][key] for key in active_keys.get('mcu', set())
        } if 'mcu' in active_sections else {}

    from core.hotend_fan import SOURCE_OPTIONS as FAN_SECTIONS, is_fan_section
    if any(is_fan_section(name) for name in data):
        data[FAN_SECTIONS] = {
            name: {key: data[name][key] for key in active_keys.get(name, set())}
            for name in active_sections if is_fan_section(name)
        }

    if "homing_override" in data:
        from core.homing_source import SOURCE as HOMING_SOURCE
        data[HOMING_SOURCE] = "homing_override" in active_sections

    from core.heater_verification import SOURCE as VERIFICATION_SOURCE, is_verifier
    verification_sections = [name for name in data if is_verifier(name)]
    if verification_sections:
        data[VERIFICATION_SOURCE] = {
            name: ({key: data[name][key] for key in active_keys.get(name, set())}
                   if name in active_sections else None)
            for name in verification_sections
        }

    from core.board_auxiliary import SOURCE_ACTIVITY, SOURCE_OPTIONS, is_electrical_dependency
    electrical_sections = [name for name in data if is_electrical_dependency(name)]
    if electrical_sections:
        data[SOURCE_ACTIVITY] = {name: name in active_sections for name in electrical_sections}
        data[SOURCE_OPTIONS] = {name: sorted(active_keys.get(name, set())) for name in electrical_sections}
        from core.board_pwm import fixed_pwm_source, SOURCE_FIXED_PWM
        reviewed = fixed_pwm_source(raw_cfg, filename)
        if reviewed is not None:
            data[SOURCE_FIXED_PWM] = reviewed
        from core.board_probe_reset import RESET_OUTPUT, SOURCE_RESET, capture_probe_reset_source
        if RESET_OUTPUT in data:
            reset = capture_probe_reset_source(raw_cfg)
            if reset is not None:
                data[SOURCE_RESET] = reset
    from core.board_bx_panel import capture_panel_source, SOURCE_PANEL
    panel = capture_panel_source(raw_cfg, filename)
    if panel is not None:
        data[SOURCE_PANEL] = panel
    from core.board_cooling import capture_required_cooling, SOURCE as COOLING_SOURCE
    cooling = capture_required_cooling(raw_cfg, filename)
    if cooling is not None:
        data[COOLING_SOURCE] = cooling
    return data

def sanitize_geometry_value(key, val):
    if val is None:
        return val
    val_str = str(val).strip()
    match = re.match(r'^([-+]?\d+(?:\.\d+)?)\s*([a-zA-Z_]+.*)?$', val_str)
    if match:
        num_part = match.group(1)
        unit_part = match.group(2)
        if unit_part:
            print(f"\n\033[93mWarning: Unexpected unit '{unit_part}' in geometry field '{key}' (value: '{val_str}'). Restricting to numeric value '{num_part}'.\033[0m")
            return num_part
        return num_part
    return val_str

def extract_profile_defaults(parsed_data):
    """Extracts default values from a parsed printer profile, with graceful fallbacks."""
    defaults = {
        'kinematics': 'cartesian',
        'x_size': '235',
        'y_size': '235',
        'z_size': '250',
        'x_position_endstop': '0',
        'x_position_min': '0',
        'x_position_max': '235',
        'y_position_endstop': '0',
        'y_position_min': '0',
        'y_position_max': '235',
        'z_position_endstop': '0',
        'z_position_min': '0',
        'z_position_max': '250',
        'hotend_thermistor': 'EPCOS 100K B57560G104F',
        'bed_thermistor': 'EPCOS 100K B57560G104F',
        'probe': 'None'
    }
    
    try:
        def parse_rd(val):
            try:
                v = float(val)
                if v <= 0:
                    print(f"\n\033[93mWarning: Invalid rotation_distance ({val}) <= 0. Ignoring.\033[0m")
                    return None
                return f"{round(v, 4):g}"
            except Exception:
                return None
                
        def parse_gear(val):
            if val and ':' in str(val): return str(val)
            print(f"\n\033[93mWarning: Invalid gear_ratio ({val}). Ignoring.\033[0m")
            return None

        if 'printer' in parsed_data:
            defaults['kinematics'] = parsed_data['printer'].get('kinematics', 'cartesian')
            
        for axis in ['x', 'y', 'z']:
            sec = f'stepper_{axis}'
            if sec in parsed_data:
                pos_max = parsed_data[sec].get('position_max', defaults.get(f'{axis}_size', '250'))
                pos_max_clean = sanitize_geometry_value(f'{axis}_position_max', pos_max)
                defaults[f'{axis}_size'] = pos_max_clean
                defaults[f'{axis}_position_max'] = pos_max_clean
                
                if 'position_endstop' in parsed_data[sec]:
                    defaults[f'{axis}_position_endstop'] = sanitize_geometry_value(f'{axis}_position_endstop', parsed_data[sec]['position_endstop'])
                if 'position_min' in parsed_data[sec]:
                    defaults[f'{axis}_position_min'] = sanitize_geometry_value(f'{axis}_position_min', parsed_data[sec]['position_min'])
                
                rd = None
                if 'rotation_distance' in parsed_data[sec]:
                    rd = parse_rd(parsed_data[sec]['rotation_distance'])
                elif 'step_distance' in parsed_data[sec]:
                    # BUG-002 fix: per-field guards so an expression string like
                    # "1/16" or a value with a trailing comment doesn't silently
                    # discard the entire defaults dict via the outer except.
                    try:
                        sd = float(parsed_data[sec]['step_distance'])
                    except (ValueError, TypeError) as e:
                        print(f"\n\033[93mWarning: Could not parse step_distance for [{sec}] ({e}). Skipping rotation_distance derivation.\033[0m")
                        sd = None
                    if sd is not None:
                        try:
                            microsteps = float(parsed_data[sec].get('microsteps', 16))
                        except (ValueError, TypeError):
                            microsteps = 16.0
                        try:
                            full_steps = float(parsed_data[sec].get('full_steps_per_rotation', 200))
                        except (ValueError, TypeError):
                            full_steps = 200.0
                        rd = parse_rd(sd * microsteps * full_steps)
                
                if rd: defaults[f'rotation_distance_{axis}'] = rd
                
                if 'gear_ratio' in parsed_data[sec]:
                    gr = parse_gear(parsed_data[sec]['gear_ratio'])
                    if gr: defaults[f'gear_ratio_{axis}'] = gr
            
        if 'extruder' in parsed_data:
            defaults['hotend_thermistor'] = parsed_data['extruder'].get('sensor_type', 'EPCOS 100K B57560G104F')
            
            rd = None
            if 'rotation_distance' in parsed_data['extruder']:
                rd = parse_rd(parsed_data['extruder']['rotation_distance'])
            elif 'step_distance' in parsed_data['extruder']:
                try:
                    sd = float(parsed_data['extruder']['step_distance'])
                except (ValueError, TypeError) as e:
                    print(f"\n\033[93mWarning: Could not parse step_distance for [extruder] ({e}). Skipping rotation_distance derivation.\033[0m")
                    sd = None
                if sd is not None:
                    try:
                        microsteps = float(parsed_data['extruder'].get('microsteps', 16))
                    except (ValueError, TypeError):
                        microsteps = 16.0
                    try:
                        full_steps = float(parsed_data['extruder'].get('full_steps_per_rotation', 200))
                    except (ValueError, TypeError):
                        full_steps = 200.0
                    rd = parse_rd(sd * microsteps * full_steps)
                
            if rd: defaults['rotation_distance_e'] = rd
                
            if 'gear_ratio' in parsed_data['extruder']:
                gr = parse_gear(parsed_data['extruder']['gear_ratio'])
                if gr: defaults['gear_ratio_e'] = gr
                
        if 'heater_bed' in parsed_data:
            defaults['bed_thermistor'] = parsed_data['heater_bed'].get('sensor_type', 'EPCOS 100K B57560G104F')
            
        # Preserve the broader set of profile-derived Klipper behavior used by
        # the generator (motion, PID, currents, homing direction and material
        # dimensions).  The compatibility keys above remain for the wizard UI.
        from core.profile_values import extract_profile_values
        geometry_keys = {
            f"{axis}_{suffix}"
            for axis in ("x", "y", "z")
            for suffix in ("size", "position_min", "position_max", "position_endstop")
        }
        defaults.update(
            (key, value)
            for key, value in extract_profile_values(parsed_data).items()
            if key not in geometry_keys
        )

        if parsed_data.get('bltouch'):
            defaults['probe'] = 'BLTouch'
        elif parsed_data.get('probe') or parsed_data.get('smart_effector'):
            defaults['probe'] = 'Inductive'
    except (KeyError, TypeError, ValueError) as e:
        print(f"\n\033[93mWarning: Failed to parse some printer profile defaults ({e}). Using standard defaults.\033[0m")
        
    return defaults


def get_reusable_driver_sockets(raw_cfg: str, board_name: str = "") -> list:
    """Derive logical extra-driver socket aliases available for Z-motor re-use.

    Scans the *raw* Klipper board config string rather than the already-parsed
    dict so that commented-out section headers (``#[extruder1]``) are also
    discovered.  This is the correct approach for Octopus / Spider / SKR Pro
    class boards where spare E-sockets live behind commented-out headers.

    Returns a list of ``(section_key, friendly_label)`` tuples, e.g.::

        [("extruder1", "E1"), ("extruder2", "E2"), ("extruder3", "E3")]

    No board name is hard-coded in this function; the derivation is driven
    entirely by the board profile's own section naming conventions so that any
    board following Klipper conventions benefits automatically.

    Args:
        raw_cfg:    Raw text of the board's Klipper ``.cfg`` file.
        board_name: Board filename (unused currently; reserved for future
                    ``boards.yaml`` metadata overrides).

    Returns:
        Sorted list of ``(key, label)`` tuples ready for wizard consumption.
    """
    sockets: list = []
    seen: set = set()

    # Pattern 1 — active or commented [extruderN] headers (N >= 1)
    # Matches: [extruder1], #[extruder1], # [extruder1], etc.
    for m in re.finditer(r'^#?\s*\[extruder(\d+)\]', raw_cfg, re.MULTILINE):
        n = int(m.group(1))
        key = f"extruder{n}"
        label = f"E{n}"
        if key not in seen:
            sockets.append((key, label))
            seen.add(key)

    # Pattern 2 — [extruder_stepper <name>] (Klipper 0.11+ multi-extruder boards)
    for m in re.finditer(r'^#?\s*\[extruder_stepper\s+(\S+)\]', raw_cfg, re.MULTILINE):
        name = m.group(1)
        key = f"extruder_stepper {name}"
        label = name.upper()
        if key not in seen:
            sockets.append((key, label))
            seen.add(key)

    # Stable, natural sort: extruder1 < extruder2 < extruder_stepper …
    sockets.sort(key=lambda t: t[0])
    return sockets


def is_socketed_board(board_name: str) -> bool:
    if not board_name:
        return False
    name = board_name.lower()
    # List of known socketed board name patterns
    socketed_patterns = [
        "skr-v1.3", "skr-v1.4", "skr-2", "skr-pro", "octopus", "spider", 
        "mks-gen-l", "mks-sgen-l", "mks-sgenl", "sgen-l", "ramps", 
        "mega2560", "sbase", "duet2", "duet3"
    ]
    return any(p in name for p in socketed_patterns)


def detect_driver_info(parsed_data: dict, board_name: str = "") -> dict:
    """Scrapes/detects the driver type and mode from parsed config data.

    Returns a dict with keys:
      driver_type: str (e.g. "TMC2209") or None
      driver_mode: str ("UART", "SPI", "Standalone") or None
      integrated: bool (True if the board/profile has integrated drivers defined and is not socketed)
      is_socketed: bool (True if the board has socketed drivers)
    """
    types_map = {
        "tmc2208": "TMC2208",
        "tmc2209": "TMC2209",
        "tmc2225": "TMC2225",
        "tmc2130": "TMC2130",
        "tmc5160": "TMC5160",
        "a4988": "A4988",
        "drv8825": "DRV8825"
    }
    
    detected_type = None
    detected_mode = None
    integrated = False
    
    for section_key, section_data in parsed_data.items():
        clean_key = section_key.lstrip("#").strip().lower()
        words = clean_key.split()
        if not words:
            continue
        prefix = words[0]
        if prefix in types_map:
            detected_type = types_map[prefix]
            integrated = True
            
            # Detect mode
            if prefix in ("tmc2208", "tmc2209", "tmc2225"):
                if "uart_pin" in section_data:
                    detected_mode = "UART"
                else:
                    detected_mode = "Standalone"
            elif prefix in ("tmc2130", "tmc5160"):
                if "cs_pin" in section_data or "spi_bus" in section_data:
                    detected_mode = "SPI"
                else:
                    detected_mode = "Standalone"
            else:
                detected_mode = "Standalone"
            break  # Use the first detected driver info
            
    is_socketed = is_socketed_board(board_name)
    return {
        "driver_type": detected_type,
        "driver_mode": detected_mode,
        "integrated": integrated and not is_socketed,
        "is_socketed": is_socketed
    }


def detect_fan_pins(raw_cfg: str) -> list:
    """Scans the raw Klipper board config string for all fan-related sections
    (active or commented out) and extracts their pin names and labels.

    Returns a list of dicts:
        [{"pin": "PA8", "label": "Part Cooling Fan (PA8)", "section": "fan"}, ...]
    """
    # Find all section headers (active or commented out)
    # E.g. [fan], #[heater_fan fan1], # [fan]
    from core.validators import questionary_fan_pin_validator

    matches = list(re.finditer(r'^[ \t]*#?[ \t]*\[([a-zA-Z0-9_]+(?:\s+[^\]]+)?)\]', raw_cfg, re.MULTILINE))
    
    fan_pins = []
    seen_pins = set()
    
    for i, match in enumerate(matches):
        header = match.group(1).strip()
        lower_header = header.lower()
        
        is_fan = (
            lower_header == "fan" or
            lower_header.startswith("heater_fan ") or
            lower_header.startswith("controller_fan ") or
            lower_header.startswith("fan_generic ")
        )
        if not is_fan:
            continue
            
        # Get the body of this section (up to the next section start or end of file)
        start_pos = match.end()
        end_pos = matches[i+1].start() if i + 1 < len(matches) else len(raw_cfg)
        section_body = raw_cfg[start_pos:end_pos]
        
        # Search for pin: or # pin: inside the section body
        pin_matches = list(re.finditer(
            r'^[ \t]*(#?)[ \t]*pin[ \t]*[:=][ \t]*([^#;\r\n]*)',
            section_body, re.MULTILINE | re.IGNORECASE))
        active = [item for item in pin_matches if not item.group(1)]
        if pin_matches:
            pin_match = active[-1] if active else pin_matches[0]
            pin = pin_match.group(2).strip()
            if questionary_fan_pin_validator(pin) is not True:
                continue  # Never offer a truncated or silently repaired token.
            
            # Format friendly label
            if lower_header == "fan":
                label = f"Part Cooling Fan ({pin})"
            else:
                parts = header.split(maxsplit=1)
                fan_name = parts[1] if len(parts) > 1 else header
                label = f"{fan_name.replace('_', ' ').title()} ({pin})"
                
            if pin not in seen_pins:
                fan_pins.append({
                    "pin": pin,
                    "label": label,
                    "section": header
                })
                seen_pins.add(pin)
                
    return fan_pins
