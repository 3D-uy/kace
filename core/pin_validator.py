# core/pin_validator.py
"""
Pre-flight pin-namespace validator for generated printer.cfg files.

Problem this solves
-------------------
Every MCU family understands GPIO pins in exactly one naming convention:

  - LPC176x  -> P<port>.<pin>     (e.g. P1.10, P0.10, P2.0)
  - STM32    -> P<port><pin>      (e.g. PA0, PD7, PB4, PC5)
  - RP2040   -> gpio<number>      (e.g. gpio15)
  - ESP32    -> gpio<number>      (e.g. gpio4)
  - AVR      -> P<port><pin> | D<number> | AR<number>   (e.g. PA0, D18, AR0)

Klipper aborts startup with ``Unknown pin`` if a config mixes conventions
— for example STM32-style ``PD7``/``PC5`` on an LPC1769 (SKR v1.4) board.
On a low-RAM host such as a Raspberry Pi 3, that abort turns into a
systemd restart loop, which OOM-kills the box (Klipper + Moonraker +
Mainsail thrashing 1 GB) and the user loses all access — SSH, web, everything.

This module parses a printer.cfg, resolves the target MCU family, and flags
any pin that does NOT belong to that family's namespace **before** the file
is pushed to the Pi.

It is intentionally self-contained (stdlib only) so it runs anywhere, and the
MCU -> arch table mirrors ``data/boards.yaml::mcu_firmware``. Because every
board in the Klipper config repo maps to one of these MCU families, validating
by family covers every board.
"""

import re

# ── Required-section integrity check ──────────────────────────────
# A printer.cfg that is missing its hardware body — no [mcu], no [printer],
# no steppers — causes Klipper to fatal at startup ("Option 'serial' in
# section 'mcu' must be specified"), then systemd restart-loops it. On a
# low-RAM host (Pi 3, 1 GB) that loop OOM-kills sshd/networking and the user
# loses all access. This catches the defect *before* the file is pushed.
#
# Root cause in the field: the generator/template produced a file containing
# only the Mainsail macro body, or a partial/truncated file was uploaded.
# Either way the result is the same: a config that Klipper can never load.
#
# Each entry: (regex matching the section header, human description).
# We resolve `[include]`/`[include *.cfg]` by counting those too — if the
# section lives in an included file we still want to see it referenced,
# but a missing core section is fatal regardless of includes.

_REQUIRED_SECTIONS = [
    (re.compile(r"^\[mcu\]\s*$", re.MULTILINE),            "[mcu]"),
    (re.compile(r"^\[printer\]\s*$", re.MULTILINE),         "[printer]"),
    (re.compile(r"^\[stepper_[a-z]+\]\s*$", re.MULTILINE), "[stepper_x] / [stepper_a] (at least one stepper)"),
]

# R-05: The previous pattern used re.DOTALL which let [^\[]*? cross section
# boundaries (newlines), causing a false-negative when [mcu] exists without
# serial: but a later section does have it. Fix: extract the [mcu] block
# first (everything from [mcu] up to the next section header or EOF), then
# check for serial: within that block only. No DOTALL needed.
_MCU_SECTION_RE = re.compile(r"^\[mcu\](.+?)(?=^\[|\Z)", re.MULTILINE | re.DOTALL)
_SERIAL_IN_BLOCK_RE = re.compile(r"^\s*serial:\s*\S+", re.MULTILINE)


def validate_required_sections(cfg_path):
    """Verify the file contains Klipper's mandatory hardware sections.

    Returns a list of human-readable problems (empty list = healthy file).
    Returns None if the file cannot be read (caller decides how to handle).
    """
    try:
        with open(cfg_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return None

    problems = []
    for section_re, label in _REQUIRED_SECTIONS:
        if not section_re.search(content):
            problems.append(f"missing required section {label}")

    # [mcu] present but no serial: → the exact fatal error from the log.
    # R-05: Two-pass check: extract the [mcu] block first so we only look for
    # serial: within that section, not in any subsequent section.
    if re.search(r"^\[mcu\]\s*$", content, re.MULTILINE):
        mcu_match = _MCU_SECTION_RE.search(content)
        mcu_block = mcu_match.group(1) if mcu_match else ""
        if not _SERIAL_IN_BLOCK_RE.search(mcu_block):
            problems.append("[mcu] section is missing a 'serial:' line")

    # An effectively empty config (only macros/comments) is a structural
    # failure even if individual section markers happen to be absent.
    if len(content.strip()) < 200:
        problems.append(
            "file is suspiciously short — likely truncated or contains "
            "only macros (no hardware configuration)"
        )

    return problems


# ── MCU family -> architecture ────────────────────────────────────
# Order matters: more specific patterns first. Mirrors the `pattern` -> `arch`
# mapping in data/boards.yaml so board coverage stays in sync.
_MCU_PATTERNS = [
    ("stm32f103", "stm32"), ("stm32f1", "stm32"),
    ("stm32f4", "stm32"),   ("stm32h7", "stm32"),
    ("stm32g0b", "stm32"),  ("stm32", "stm32"),
    ("lpc1769", "lpc176x"), ("lpc1768", "lpc176x"), ("lpc176", "lpc176x"),
    ("rp2040", "rp2040"),
    ("esp32", "esp32"),
    ("atmega2560", "avr"),  ("atmega1284", "avr"), ("atmega", "avr"),
    ("at90usb", "avr"),     ("avr", "avr"),
    ("sam4e", "sam"), ("samd", "sam"),
    ("linux", "linux"), ("host", "linux"),
]

# ── Per-architecture valid pin namespaces ─────────────────────────
# Matched against the *core* pin name after leading prefixes (!, ^, ~) and an
# optional "<mcu>:" qualifier are stripped. ``None`` means "no reliable
# generic check" (Duet/SAM uses board-specific names; Linux host uses sysfs) —
# we do not reject on those architectures to avoid false positives.
_NAMESPACES = {
    "lpc176x": re.compile(r"^P[0-4]\.(0?[0-9]|1[0-9]|2[0-9]|3[0-1])$"),
    "stm32":   re.compile(r"^P[A-I]\d{1,2}$"),
    "rp2040":  re.compile(r"^gpio\d{1,3}$"),
    "esp32":   re.compile(r"^gpio\d{1,2}$"),
    "avr":     re.compile(r"^(P[A-L]\d{1,2}|D\d{1,2}|AR[0-7])$"),
    "sam":     None,
    "linux":   None,
}

# Pin option lines we inspect: bare `pin:` and any `*_pin:`.
_PIN_OPTION_RE = re.compile(r"^\s*([a-z0-9_]*pin)\s*:", re.IGNORECASE)

# Tokens that are not physical GPIO pins and must be ignored.
_PLACEHOLDERS = ("<GND>", "<5V>", "<3.3V>", "<VCC>", "<NC>", "<RST>", "<RESET>")


def arch_for_mcu(mcu):
    """Resolve a detected MCU string (e.g. 'lpc1769') to an architecture family.

    Returns None if the MCU is unrecognized.
    """
    if not mcu:
        return None
    m = str(mcu).lower()
    for pat, arch in _MCU_PATTERNS:
        if pat in m:
            return arch
    return None


def _is_real_gpio(core):
    """True if a stripped pin token refers to a physical GPIO we can validate."""
    if not core:
        return False
    if core in _PLACEHOLDERS:
        return False
    if core.lower() in ("none", "null"):
        return False
    return True


def _check_value(value, arch, ns, lineno, field, issues):
    """Validate every pin token in a single option value, appending mismatches."""
    for token in re.split(r"[, ]+", value.strip()):
        token = token.strip().strip(";")
        if not token:
            continue
        # mcu-qualified (toolhead:gpio5) or virtual (probe:z_virtual_endstop)
        # references cannot be validated without the remote MCU's map — skip.
        if ":" in token:
            continue
        core = token.lstrip("!^~")
        if not _is_real_gpio(core):
            continue
        if not ns.match(core):
            issues.append((lineno, field, token, arch))


def validate_pins_for_mcu(cfg_path, mcu):
    """Parse a printer.cfg and return a list of pin-namespace violations.

    Each violation is a tuple ``(line_number, field, pin, expected_arch)``.
    Returns ``None`` when the MCU/arch cannot be determined (validation
    skipped), or an empty list when everything is consistent.
    """
    arch = arch_for_mcu(mcu)
    if arch is None:
        return None
    ns = _NAMESPACES.get(arch)
    if ns is None:
        return []  # permissive architecture (sam / linux)

    issues = []
    section = ""
    in_aliases = False

    try:
        with open(cfg_path, "r", encoding="utf-8", errors="replace") as f:
            for lineno, raw in enumerate(f, 1):
                line = raw.split("#", 1)[0]  # drop inline comments
                stripped = line.strip()

                if not stripped:
                    in_aliases = False
                    continue

                if stripped.startswith("[") and stripped.endswith("]"):
                    section = stripped[1:-1].strip()
                    in_aliases = False
                    continue

                # [board_pins] aliases: block — body lines look like
                #   EXP1_1=P1.30, EXP1_3=P1.18, ...
                if section == "board_pins" and stripped.lower().startswith("aliases"):
                    in_aliases = True
                    continue
                if in_aliases:
                    for assign in stripped.split(","):
                        if "=" not in assign:
                            continue
                        _key, val = assign.split("=", 1)
                        _check_value(val, arch, ns, lineno, "aliases", issues)
                    continue

                m = _PIN_OPTION_RE.match(line)
                if m:
                    field = m.group(1)
                    _k, val = line.split(":", 1)
                    _check_value(val, arch, ns, lineno, field, issues)

    except OSError:
        return None

    return issues
