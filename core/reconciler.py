"""
core/reconciler.py — Single Source of Truth for KACE Native Configuration Reconciliation.

Guarantees that native features ([exclude_object], [force_move] with enable_force_move: True
in printer.cfg, and [file_manager] with enable_object_processing: True in moonraker.conf)
are atomically and idempotently applied across all installation, generation, and deployment flows.
"""

from __future__ import annotations

import os
import re
import stat
import tempfile
from pathlib import Path


def ensure_ini_section_and_option(
    content: str, section_name: str, option_name: str | None = None, default_value: str | None = None
) -> tuple[str, bool]:
    """
    Idempotent, comment-preserving INI section and option inserter.
    Does not duplicate existing sections or options.
    Preserves existing option values if present.
    """
    newline = "\r\n" if "\r\n" in content else "\n"
    lines = content.splitlines()
    section_re = re.compile(r"^\s*\[\s*([^\]]+?)\s*\]\s*(?:[#;].*)?$", re.IGNORECASE)

    section_indexes = []
    for index, line in enumerate(lines):
        match = section_re.match(line)
        if match and match.group(1).strip().casefold() == section_name.casefold():
            section_indexes.append(index)

    changed = False
    if not section_indexes:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"[{section_name}]")
        if option_name and default_value is not None:
            lines.append(f"{option_name}: {default_value}")
        changed = True
    elif option_name and default_value is not None:
        option_re = re.compile(rf"^\s*{re.escape(option_name)}\s*[:=]", re.IGNORECASE)
        option_found = False
        for section_start in section_indexes:
            section_end = len(lines)
            for index in range(section_start + 1, len(lines)):
                if section_re.match(lines[index]):
                    section_end = index
                    break
            if any(option_re.match(line) for line in lines[section_start + 1:section_end]):
                option_found = True
                break

        if not option_found:
            insert_at = len(lines)
            for index in range(section_indexes[0] + 1, len(lines)):
                if section_re.match(lines[index]):
                    insert_at = index
                    break
            while insert_at > section_indexes[0] + 1 and not lines[insert_at - 1].strip():
                insert_at -= 1
            lines.insert(insert_at, f"{option_name}: {default_value}")
            changed = True

    if not changed:
        return content, False

    res_content = newline.join(lines)
    if content.endswith("\n") or content.endswith("\r\n"):
        res_content += newline
    return res_content, True


def reconcile_printer_cfg_content(content: str, existing_target_content: str | None = None) -> tuple[str, bool]:
    """
    Reconcile printer.cfg content to guarantee [exclude_object] and [force_move].

    If existing_target_content contains enable_force_move: False (or false/0/no/off),
    preserves False. Otherwise defaults enable_force_move: True.
    """
    if not isinstance(content, str):
        return "", False

    preserve_false = False
    if existing_target_content and isinstance(existing_target_content, str):
        fm_match = re.search(
            r"^\s*\[\s*force_move\s*\]([\s\S]*?)(?:^\s*\[|\Z)",
            existing_target_content,
            re.IGNORECASE | re.MULTILINE,
        )
        if fm_match:
            fm_block = fm_match.group(1)
            efm_match = re.search(
                r"^\s*enable_force_move\s*[:=]\s*(false|0|no|off)",
                fm_block,
                re.IGNORECASE | re.MULTILINE,
            )
            if efm_match:
                preserve_false = True

    mod_false = False
    if preserve_false:
        fm_match_curr = re.search(
            r"^\s*\[\s*force_move\s*\]([\s\S]*?)(?:^\s*\[|\Z)",
            content,
            re.IGNORECASE | re.MULTILINE,
        )
        if fm_match_curr:
            fm_block_curr = fm_match_curr.group(1)
            efm_match_true = re.search(
                r"^\s*(enable_force_move\s*[:=]\s*)(true|1|yes|on)",
                fm_block_curr,
                re.IGNORECASE | re.MULTILINE,
            )
            if efm_match_true:
                old_line = efm_match_true.group(0)
                new_line = f"{efm_match_true.group(1)}False"
                content = content.replace(old_line, new_line, 1)
                mod_false = True

    default_efm = "False" if preserve_false else "True"

    content, mod1 = ensure_ini_section_and_option(content, "exclude_object", None, None)
    content, mod2 = ensure_ini_section_and_option(content, "force_move", "enable_force_move", default_efm)

    return content, (mod1 or mod2 or mod_false)


def reconcile_moonraker_conf_content(content: str) -> tuple[str, bool]:
    """
    Reconcile moonraker.conf content to guarantee [file_manager] enable_object_processing: True.
    """
    if not isinstance(content, str):
        return "", False
    return ensure_ini_section_and_option(content, "file_manager", "enable_object_processing", "True")


def write_text_atomically(file_path: Path | str, content: str) -> None:
    """Publish text to a file only after its complete temporary copy is durable."""
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".part", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_name, mode)
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def reconcile_file_atomically(file_path: Path | str, reconciler_fn) -> bool:
    """
    Atomically reconcile a file on disk using reconciler_fn.
    """
    path = Path(file_path)
    try:
        content = path.read_text(encoding="utf-8") if path.exists() else ""
    except Exception as exc:
        raise OSError(f"Could not read existing configuration: {path}") from exc

    try:
        new_content, modified = reconciler_fn(content)
    except Exception:
        return False

    if not modified and path.exists():
        return False

    try:
        newline = "\r\n" if "\r\n" in new_content else "\n"
        if not new_content.endswith(newline):
            new_content += newline
        write_text_atomically(path, new_content)
        return True
    except Exception:
        return False


def reconcile_config_directory(config_dir: Path | str, existing_printer_cfg_content: str | None = None) -> bool:
    """
    Reconcile both printer.cfg and moonraker.conf in config_dir.
    """
    cfg_dir = Path(config_dir)
    printer_cfg = cfg_dir / "printer.cfg"
    moonraker_conf = cfg_dir / "moonraker.conf"

    m1 = False
    if printer_cfg.exists():
        def _reconcile_printer(curr_content):
            return reconcile_printer_cfg_content(curr_content, existing_target_content=existing_printer_cfg_content)
        m1 = reconcile_file_atomically(printer_cfg, _reconcile_printer)

    m2 = reconcile_file_atomically(moonraker_conf, reconcile_moonraker_conf_content)
    return m1 or m2
