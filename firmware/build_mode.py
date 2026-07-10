"""
firmware/build_mode.py
======================
Centralized build-mode detection for KACE.

Defines a single source of truth for:
  - Whether the current environment is using the mock `make` or a real toolchain
  - The `KACE_REAL_BUILD` override mechanism (env var or --real-build CLI flag)
  - Shared constants (firmware size warning threshold)
  - User-facing banners and warnings printed before / after compilation
"""

import os

# ── Constants ─────────────────────────────────────────────────────────────────

# Minimum plausible size (bytes) for a real Klipper firmware binary.
# Any output artifact smaller than this is flagged as a likely mock or corrupt build.
# Real minimums observed:
#   AVR ATmega series  : ~30 KB
#   STM32 / LPC176x    : ~50 KB
#   RP2040 UF2         : ~200 KB
# 10 KB is a conservative sentinel that safely catches the 12-byte mock files
# while never triggering on any legitimate build.
FIRMWARE_MINIMUM_SIZE_BYTES: int = 10 * 1024   # 10 KB

# Path where the mock make script is installed inside the Docker container
_MOCK_MAKE_PATH = "/usr/local/bin/make"

# Marker string written inside the mock_make script (used for content detection)
_MOCK_MAKE_MARKER = "Mock make"

# ANSI helpers
_R  = "\033[0m"
_B  = "\033[1m"
_Y  = "\033[93m"   # yellow / warning
_C  = "\033[96m"   # cyan
_G  = "\033[92m"   # green
_RE = "\033[91m"   # red


# ── Detection ─────────────────────────────────────────────────────────────────

def is_mock_build(make_command: str = "make") -> bool:
    """Return True when the mock make script is active."""
    if make_command != "make":
        return False

    if os.path.exists(_MOCK_MAKE_PATH):
        try:
            with open(_MOCK_MAKE_PATH, "r", encoding="utf-8", errors="ignore") as fh:
                return _MOCK_MAKE_MARKER in fh.read()
        except OSError:
            pass
    return False


# ── User-facing output ────────────────────────────────────────────────────────

def _safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        # Fallback to pure ASCII for environments that don't support unicode
        ascii_text = text.encode("ascii", errors="replace").decode("ascii")
        # Map replaced ? characters back to nice clean dashes/equals
        ascii_text = ascii_text.replace("?", "-")
        print(ascii_text)


def print_build_mode_banner(make_command: str = "make") -> None:
    """
    Print a one-line build-mode status banner at the start of every compile run.
    Shows clearly whether KACE is using the mock toolchain or the real one.
    """
    if not is_mock_build(make_command):
        return

    SEP = "─" * 52
    mode_label = f"{_Y}{_B}⚠  MOCK BUILD MODE{_R}"
    note = f"{_Y}Firmware artifacts are placeholders — not flashable.{_R}"
    hint = (
        f"  {_C}To use the real toolchain:{_R}\n"
        f"    KACE_REAL_BUILD=1 python3 kace.py\n"
        f"    python3 kace.py --real-build"
    )
    _safe_print(f"\n  {SEP}")
    _safe_print(f"  {mode_label}")
    _safe_print(f"  {note}")
    _safe_print(f"{hint}")
    _safe_print(f"  {SEP}\n")


def print_mock_warning(make_command: str = "make") -> None:
    """
    Print a prominent warning block after a mock build completes,
    reminding the user the output files cannot be flashed.
    """
    if not is_mock_build(make_command):
        return
    _safe_print(
        f"\n  {_Y}{'═' * 52}{_R}\n"
        f"  {_Y}{_B}  Development Mode Detected{_R}\n"
        f"  {_Y}  Using mock compiler.{_R}\n"
        f"\n"
        f"  {_Y}  Generated firmware files are {_B}placeholders{_R}{_Y}\n"
        f"  and {_B}cannot be flashed{_R}{_Y} to real hardware.{_R}\n"
        f"  {_Y}{'═' * 52}{_R}\n"
    )


def print_size_warning(path: str, size_bytes: int) -> None:
    """
    Print a firmware size warning when the artifact is suspiciously small.
    Called by the builder when size < FIRMWARE_MINIMUM_SIZE_BYTES.
    """
    size_str = _human_size(size_bytes)
    threshold_str = _human_size(FIRMWARE_MINIMUM_SIZE_BYTES)
    _safe_print(
        f"\n  {_Y}{'─' * 52}{_R}\n"
        f"  {_Y}{_B}  WARNING: Suspicious firmware size{_R}\n"
        f"  {_Y}  File   : {path}{_R}\n"
        f"  {_Y}  Size   : {_B}{size_str}{_R}{_Y}  (threshold: {threshold_str}){_R}\n"
        f"\n"
        f"  {_Y}  This firmware appears to be a {_B}mock build{_R}{_Y} or an\n"
        f"  {_Y}  invalid compilation output. Do NOT flash this file.{_R}\n"
        f"  {_Y}{'─' * 52}{_R}\n"
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _human_size(n: int) -> str:
    """Format a byte count as a human-readable string (e.g. '12 bytes', '48.3 KB')."""
    if n < 1024:
        return f"{n} bytes"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"
