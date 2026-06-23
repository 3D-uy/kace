"""
KACE — Advanced Module Passthrough Handler
==========================================

Loads data/advanced_modules.yaml and exposes two public functions:

  get_advanced_sections(parsed_data) -> list[str]
      Scans the parsed Klipper config for sections that match a
      passthrough entry. Returns a list of rendered commented-out
      string blocks, one per matched section, ready for template
      injection.

  is_unsupported_section(section_name) -> bool
      Returns True if the section matches an entry with
      passthrough=False (still UNSUPPORTED in the sweep gate).

Both functions have hardcoded fallback schemas so they work even
when advanced_modules.yaml is missing.
"""

import os
import textwrap

# ---------------------------------------------------------------------------
# Hardcoded fallback — mirrors advanced_modules.yaml exactly.
# Used when the YAML file is missing or unreadable.
# ---------------------------------------------------------------------------
_FALLBACK_SCHEMAS = [
    {
        "section_prefix": "neopixel",
        "passthrough": True,
        "banner": "Neopixel / WS2812 LED",
        "note": (
            "Neopixel LED section detected. Pin data preserved below. "
            "Review pin, chain_count, and color_order, then uncomment to enable."
        ),
        "fields": ["pin", "chain_count", "color_order",
                   "initial_red", "initial_green", "initial_blue", "initial_white", "*"],
    },
    {
        "section_prefix": "dotstar",
        "passthrough": True,
        "banner": "DotStar / APA102 LED",
        "note": (
            "DotStar LED section detected. Pin data preserved below. "
            "Review data_pin, clock_pin, and chain_count, then uncomment to enable."
        ),
        "fields": ["data_pin", "clock_pin", "chain_count",
                   "initial_red", "initial_green", "initial_blue", "*"],
    },
    {
        "section_prefix": "adxl345",
        "passthrough": True,
        "banner": "ADXL345 Accelerometer (Input Shaper)",
        "note": (
            "ADXL345 accelerometer detected. SPI pin data preserved below. "
            "After wiring, uncomment and run SHAPER_CALIBRATE."
        ),
        "fields": ["cs_pin", "spi_bus", "spi_software_sclk_pin",
                   "spi_software_mosi_pin", "spi_software_miso_pin", "axes_map", "*"],
    },
    {
        "section_prefix": "pca9685",
        "passthrough": True,
        "banner": "PCA9685 PWM Expander",
        "note": (
            "PCA9685 PWM expander detected. I2C data preserved below. "
            "Uncomment and verify i2c_address before enabling."
        ),
        "fields": ["i2c_bus", "i2c_address", "i2c_mcu", "cycle_time", "*"],
    },
    {
        "section_prefix": "sx1509",
        "passthrough": True,
        "banner": "SX1509 GPIO Expander",
        "note": (
            "SX1509 GPIO expander detected. I2C data preserved below. "
            "Uncomment and verify i2c_address before enabling."
        ),
        "fields": ["i2c_bus", "i2c_address", "i2c_mcu", "*"],
    },
    {"section_prefix": "resonance_tester", "passthrough": False, "banner": "", "note": "", "fields": ["*"]},
    {"section_prefix": "lis2dw",           "passthrough": False, "banner": "", "note": "", "fields": ["*"]},
    {"section_prefix": "mpu9250",          "passthrough": False, "banner": "", "note": "", "fields": ["*"]},
    {"section_prefix": "palette2",         "passthrough": False, "banner": "", "note": "", "fields": ["*"]},
]


# ---------------------------------------------------------------------------
# Schema loading (module-level cache)
# ---------------------------------------------------------------------------

def _load_schemas() -> list:
    """Load advanced_modules.yaml. Falls back to _FALLBACK_SCHEMAS."""
    try:
        from core.loader import load_advanced_modules_yaml
        db = load_advanced_modules_yaml()
        schemas = db.get('advanced_modules', [])
        if schemas:
            return schemas
    except Exception:
        pass
    return _FALLBACK_SCHEMAS


_SCHEMAS: list = None

def _get_schemas() -> list:
    global _SCHEMAS
    if _SCHEMAS is None:
        _SCHEMAS = _load_schemas()
    return _SCHEMAS


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _schema_for(section_name: str) -> dict | None:
    """Return the first schema whose section_prefix appears in section_name."""
    sl = section_name.lower()
    for schema in _get_schemas():
        if schema["section_prefix"] in sl:
            return schema
    return None


def _render_block(section_name: str, fields: dict, schema: dict) -> str:
    """Render one advanced section as a commented-out cfg block string."""
    lines = []
    banner      = schema.get("banner", section_name)
    note        = schema.get("note", "").strip()
    field_order = schema.get("fields", ["*"])

    # Header
    lines.append("# " + "-" * 50)
    lines.append(f"# {banner}")
    if note:
        for wrapped_line in textwrap.wrap(note, width=70):
            lines.append(f"# {wrapped_line}")
    lines.append("# " + "-" * 50)

    # Section header
    lines.append(f"# [{section_name}]")

    # Fields
    if "*" in field_order:
        listed_keys = [k for k in field_order if k != "*" and k in fields]
        extra_keys = [k for k in fields if k not in listed_keys]
        emit_keys = listed_keys + extra_keys
    else:
        emit_keys = [k for k in field_order if k in fields]

    for key in emit_keys:
        val = fields.get(key, "")
        if val is None or str(val).strip() == "":
            continue
        lines.append(f"# {key}: {val}")

    lines.append("")  # trailing blank line separator
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_advanced_sections(parsed_data: dict) -> list:
    """Return rendered passthrough blocks for all advanced sections found.

    Args:
        parsed_data: Dict returned by core.scraper.parse_config().

    Returns:
        List of commented-out cfg block strings (may be empty).
    """
    blocks = []
    for section_name, section_fields in parsed_data.items():
        if not isinstance(section_fields, dict):
            continue
        schema = _schema_for(section_name)
        if schema is None:
            continue
        if not schema.get("passthrough", False):
            continue
        blocks.append(_render_block(section_name, section_fields, schema))
    return blocks


def is_unsupported_section(section_name: str) -> bool:
    """Return True if section_name maps to a passthrough=False schema.

    Used by the sweep runner — sections with passthrough=True are no
    longer gated; they are handled by get_advanced_sections().

    Args:
        section_name: A parsed config section key (lowercased).

    Returns:
        True  → still UNSUPPORTED (gate the sweep result).
        False → passthrough-handled, or unknown (no gate).
    """
    schema = _schema_for(section_name)
    if schema is None:
        return False
    return not schema.get("passthrough", False)
