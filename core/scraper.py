import urllib.request
import json
import re
import os
import time

# ── Modular BLTouch database ───────────────────────────────────────────────────
# Loaded from data/boards.yaml. Hardcoded dict is the fallback when YAML is
# missing (e.g., older installs or partial clones).

_BLTOUCH_FALLBACK = {
    "skr-v1.4":         {"sensor_pin": "^P0.10",  "control_pin": "P2.0"},
    "skr-v1.3":         {"sensor_pin": "^P1.27",  "control_pin": "P2.0"},
    "skr-mini-e3-v2.0": {"sensor_pin": "^PC14",   "control_pin": "PA1"},
    "skr-mini-e3-v3.0": {"sensor_pin": "^PC14",   "control_pin": "PA1"},
    "creality-v4.2.2":  {"sensor_pin": "^PB1",    "control_pin": "PB0"},
    "creality-v4.2.7":  {"sensor_pin": "^PB1",    "control_pin": "PB0"},
    "mks-gen-l":        {"sensor_pin": "^D18",    "control_pin": "D11"},
    "mks-sgen-l":       {"sensor_pin": "^P1.27",  "control_pin": "P2.0"},
    "mks-robin-nano":   {"sensor_pin": "^PA11",   "control_pin": "PA8"},
}

def _load_bltouch_db() -> dict:
    """Load BLTouch pin overrides from data/boards.yaml.

    Returns a flat dict mapping board-filename-fragment → {sensor_pin, control_pin}.
    Falls back to the hardcoded dict if the file is missing or unreadable.
    """
    try:
        import yaml
        _db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'boards.yaml')
        _db_path = os.path.normpath(_db_path)
        with open(_db_path, 'r', encoding='utf-8') as f:
            db = yaml.safe_load(f)
        result = {}
        for entry in db.get('boards', []):
            for board_key, pins in entry.get('bltouch', {}).items():
                if pins:
                    result[board_key] = pins
        return result if result else _BLTOUCH_FALLBACK
    except Exception:
        return _BLTOUCH_FALLBACK

# Module-level cache — loaded once per process
_BLTOUCH_DB = _load_bltouch_db()


def fetch_config_list():
    """Fetches the list of generic and printer configs from Klipper GitHub."""
    cache_file = os.path.expanduser("~/.kace_boards_cache.json")
    
    # 1. Check persistent cache first (valid for 3 days)
    try:
        if os.path.exists(cache_file):
            if time.time() - os.path.getmtime(cache_file) < 3 * 24 * 3600:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    configs = json.load(f)
                    if configs:
                        return configs
    except Exception:
        pass

    # 2. Try GitHub API
    url = "https://api.github.com/repos/Klipper3d/klipper/contents/config"
    req = urllib.request.Request(url, headers={'User-Agent': 'KACE-App'})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            configs = [item['name'] for item in data if item['name'].startswith('generic-') or item['name'].startswith('printer-')]
            
            try:
                with open(cache_file, 'w', encoding='utf-8') as f:
                    json.dump(configs, f)
            except Exception: pass
            
            return configs
    except Exception as api_err:
        # 3. API Limit hit, fallback to scraping GitHub HTML tree
        try:
            tree_url = "https://github.com/Klipper3d/klipper/tree/master/config"
            req_html = urllib.request.Request(tree_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) KACE-App'})
            with urllib.request.urlopen(req_html, timeout=10) as response:
                html = response.read().decode('utf-8', errors='ignore')
                
                # Extract from React JSON payload or standard hrefs
                matches = re.findall(r'"name":"((?:generic|printer)-[^"]+\.cfg)"', html)
                matches_url = re.findall(r'href="/Klipper3d/klipper/blob/[^/]+/config/((?:generic|printer)-.*?\.cfg)"', html)
                configs = list(set(matches + matches_url))
                
                if configs:
                    configs = sorted(configs)
                    try:
                        with open(cache_file, 'w', encoding='utf-8') as f:
                            json.dump(configs, f)
                    except Exception: pass
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
    cache_dir = os.path.expanduser("~/.kace_configs_cache")
    if not os.path.exists(cache_dir):
        try: os.makedirs(cache_dir)
        except Exception: pass
        
    cache_file = os.path.join(cache_dir, filename)
    
    # 1. Check cache first (valid for 3 days)
    try:
        if os.path.exists(cache_file):
            if time.time() - os.path.getmtime(cache_file) < 3 * 24 * 3600:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    return f.read()
    except Exception:
        pass

    url = f"https://raw.githubusercontent.com/Klipper3d/klipper/master/config/{filename}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 KACE-App'})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            content = response.read().decode('utf-8', errors='ignore')
            # Save to cache
            try:
                with open(cache_file, 'w', encoding='utf-8') as f:
                    f.write(content)
            except Exception: pass
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

def parse_config(raw_cfg, filename=""):
    """
    Parses the raw Klipper config. 
    Extracts pins even from commented-out sections (like #[tmc2208 stepper_x]).
    """
    data = {}
    current_section = None
    last_key = None
    for raw_line in raw_cfg.split('\n'):
        line = raw_line.strip()
        if not line: continue
        
        # Match section headers like [stepper_x] or #[tmc2208 stepper_x]
        section_match = re.match(r'^#?\s*\[(.*?)\]', line)
        if section_match:
            current_section = section_match.group(1).strip().lower()
            if current_section not in data:
                data[current_section] = {}
            last_key = None
            continue
        
        if current_section:
            # Match key-value pairs like step_pin: P2.2 or #uart_pin: P1.10
            kv_match = re.match(r'^#?\s*([a-zA-Z0-9_]+)\s*:\s*(.*)', line)
            if kv_match:
                key = kv_match.group(1).strip().lower()
                val = kv_match.group(2).strip()
                
                # Prevent [board_pins] parser leakage: 'aliases' uniquely belongs to board_pins
                if key == 'aliases' and current_section != 'board_pins':
                    current_section = 'board_pins'
                    if current_section not in data:
                        data[current_section] = {}
                        
                # Clean up inline comments
                if '#' in val and key != 'aliases':
                    val = val.split('#')[0].strip()
                    
                data[current_section][key] = val
                last_key = key
            elif last_key == 'aliases':
                clean_val = line
                if clean_val.startswith('#'):
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
                
    # Inject known BLTouch pins for boards that don't define them in their cfg.
    # Pin data is loaded from data/boards.yaml (_BLTOUCH_DB) with a hardcoded
    # fallback — so this works even without the YAML file present.
    if "bltouch" not in data:
        data["bltouch"] = {}

    fname = filename.lower()
    for board_key, pins in _BLTOUCH_DB.items():
        if board_key in fname:
            if "sensor_pin" not in data["bltouch"]:
                data["bltouch"]["sensor_pin"] = pins["sensor_pin"]
            if "control_pin" not in data["bltouch"]:
                data["bltouch"]["control_pin"] = pins["control_pin"]
            break  # first match wins — most specific keys should come first in YAML

    return data

def extract_profile_defaults(parsed_data):
    """Extracts default values from a parsed printer profile, with graceful fallbacks."""
    defaults = {
        'kinematics': 'cartesian',
        'x_size': '235',
        'y_size': '235',
        'z_size': '250',
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
                defaults[f'{axis}_size'] = parsed_data[sec].get('position_max', defaults.get(f'{axis}_size', '250'))
                
                rd = None
                if 'rotation_distance' in parsed_data[sec]:
                    rd = parse_rd(parsed_data[sec]['rotation_distance'])
                elif 'step_distance' in parsed_data[sec]:
                    sd = float(parsed_data[sec]['step_distance'])
                    microsteps = float(parsed_data[sec].get('microsteps', 16))
                    full_steps = float(parsed_data[sec].get('full_steps_per_rotation', 200))
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
                sd = float(parsed_data['extruder']['step_distance'])
                microsteps = float(parsed_data['extruder'].get('microsteps', 16))
                full_steps = float(parsed_data['extruder'].get('full_steps_per_rotation', 200))
                rd = parse_rd(sd * microsteps * full_steps)
                
            if rd: defaults['rotation_distance_e'] = rd
                
            if 'gear_ratio' in parsed_data['extruder']:
                gr = parse_gear(parsed_data['extruder']['gear_ratio'])
                if gr: defaults['gear_ratio_e'] = gr
                
        if 'heater_bed' in parsed_data:
            defaults['bed_thermistor'] = parsed_data['heater_bed'].get('sensor_type', 'EPCOS 100K B57560G104F')
            
        if parsed_data.get('bltouch'):
            defaults['probe'] = 'BLTouch'
        elif parsed_data.get('probe') or parsed_data.get('smart_effector'):
            defaults['probe'] = 'Inductive'
    except Exception as e:
        print(f"\n\033[93mWarning: Failed to parse some printer profile defaults ({e}). Using standard defaults.\033[0m")
        
    return defaults
