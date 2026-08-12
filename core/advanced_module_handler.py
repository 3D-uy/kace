"""Data-driven passthrough handling for advanced Klipper modules.

``data/advanced_modules.yaml`` is authoritative. KACE fails closed when the
database is missing, malformed, or empty instead of selecting shadow defaults.
"""

import textwrap


def _load_schemas() -> list:
    """Load and validate the authoritative advanced-module schemas."""
    try:
        from core.loader import load_advanced_modules_yaml

        schemas = load_advanced_modules_yaml().get("advanced_modules", [])
    except Exception as exc:
        raise RuntimeError(
            f"[KACE] failed to load authoritative advanced_modules.yaml: {exc}"
        ) from exc
    if not isinstance(schemas, list) or not schemas:
        raise RuntimeError(
            "[KACE] advanced_modules.yaml has no advanced_modules entries"
        )
    return schemas


_SCHEMAS: list | None = None


def _get_schemas() -> list:
    global _SCHEMAS
    if _SCHEMAS is None:
        _SCHEMAS = _load_schemas()
    return _SCHEMAS


def _schema_for(section_name: str) -> dict | None:
    """Return the first schema whose section_prefix appears in section_name."""
    section_lower = section_name.lower()
    for schema in _get_schemas():
        if schema["section_prefix"] in section_lower:
            return schema
    return None


def _render_block(section_name: str, fields: dict, schema: dict) -> str:
    """Render one advanced section as a commented-out cfg block string."""
    lines = []
    banner = schema.get("banner", section_name)
    note = schema.get("note", "").strip()
    field_order = schema.get("fields", ["*"])

    lines.append("# " + "-" * 50)
    lines.append(f"# {banner}")
    if note:
        for wrapped_line in textwrap.wrap(note, width=70):
            lines.append(f"# {wrapped_line}")
    lines.append("# " + "-" * 50)
    lines.append(f"# [{section_name}]")

    if "*" in field_order:
        listed_keys = [key for key in field_order if key != "*" and key in fields]
        extra_keys = [key for key in fields if key not in listed_keys]
        emit_keys = listed_keys + extra_keys
    else:
        emit_keys = [key for key in field_order if key in fields]

    for key in emit_keys:
        value = fields.get(key, "")
        if value is None or str(value).strip() == "":
            continue
        lines.append(f"# {key}: {value}")

    lines.append("")
    return "\n".join(lines)


def get_advanced_sections(parsed_data: dict) -> list:
    """Return rendered passthrough blocks for all advanced sections found."""
    blocks = []
    for section_name, section_fields in parsed_data.items():
        if not isinstance(section_fields, dict):
            continue
        schema = _schema_for(section_name)
        if schema is None or not schema.get("passthrough", False):
            continue
        blocks.append(_render_block(section_name, section_fields, schema))
    return blocks


def is_unsupported_section(section_name: str) -> bool:
    """Return whether section_name maps to a passthrough-disabled schema."""
    schema = _schema_for(section_name)
    return schema is not None and not schema.get("passthrough", False)
