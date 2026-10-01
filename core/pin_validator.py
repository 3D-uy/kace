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
That is a Klipper configuration error. It does not establish a Linux restart
loop, memory exhaustion, host shutdown or the cause of an SSH disconnect.

This module parses a printer.cfg, resolves the target MCU family, and flags
any pin that does NOT belong to that family's namespace **before** the file
is pushed to the Pi.

It is intentionally self-contained (stdlib only) so it runs anywhere, and the
MCU -> arch table mirrors ``data/boards.yaml::mcu_firmware``. Because every
board in the Klipper config repo maps to one of these MCU families, validating
by family covers every board.
"""

import configparser
import re

# ── Required-section integrity check ──────────────────────────────
# A printer.cfg that is missing its hardware body — no [mcu], no [printer],
# no steppers — can fail Klipper configuration loading (for example, a missing
# MCU serial option). This catches structural defects before publication;
# it does not inspect systemd policy, host memory or SSH availability.
#
# A macro-only or truncated configuration motivates this structural check.
# The historical loss of access to the Pi has no established cause here.
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


class PinAliasError(ValueError):
    """A declared alias is malformed, ambiguous, reserved or cyclic."""


class PinAliases:
    """Resolve board aliases within their MCU, following Klipper pins.py.

    Keep definitions in configuration order: upstream flattens existing chains
    while adding each alias, and rejects conflicting redefinitions. This helper
    additionally rejects cycles before MCU identification. It never rewrites
    input tokens and does not model the sharing rules of individual consumers.
    """

    def __init__(self, sections):
        self.aliases = {}
        self.reserved = {}
        # adc_scaled constructs its sensor ADC on the reference MCU directly;
        # aliases are consequently resolved by that physical MCU's PinResolver.
        self.scaled_mcus = {}
        for section, options in sections.items():
            parts = section.split()
            if len(parts) == 2 and parts[0] == "adc_scaled":
                reference = options.get("vref_pin", "")
                if isinstance(reference, str) and reference.strip():
                    self.scaled_mcus[parts[1]] = self.split_pin(reference)[0]
        for section, options in sections.items():
            if section != "board_pins" and not section.startswith("board_pins "):
                continue
            if "aliases" not in options:
                raise PinAliasError(f"[{section}] requires aliases")
            mcus = [name.strip() for name in options.get("mcu", "mcu").split(",")]
            if not all(mcus):
                raise PinAliasError(f"[{section}] has an empty MCU name")
            keys = ["aliases"] + [key for key in options if key.startswith("aliases_")]
            for key in keys:
                # Strip comments also for mappings supplied by core.scraper.
                value = "\n".join(line.split("#", 1)[0].split(";", 1)[0]
                                  for line in options[key].splitlines())
                for assignment in value.split(","):
                    if not assignment.strip():
                        continue
                    parts = [part.strip() for part in assignment.split("=")]
                    if len(parts) != 2 or not all(parts):
                        raise PinAliasError(f"[{section}] invalid alias: {assignment.strip()}")
                    alias, target = parts
                    for mcu in mcus:
                        self._add(mcu, alias, target)

    def _add(self, mcu, alias, target):
        aliases = self.aliases.setdefault(mcu, {})
        reserved = self.reserved.setdefault(mcu, {})
        if target.startswith("<") and target.endswith(">"):
            if alias in reserved and reserved[alias] != target:
                raise PinAliasError(f"{mcu}:{alias} has conflicting reservations")
            reserved[alias] = target
            return
        if any(char in target for char in "^~!:") or "".join(target.split()) != target:
            raise PinAliasError(f"{mcu}:{alias} has invalid alias target {target!r}")
        if alias in aliases and aliases[alias] != target:
            raise PinAliasError(f"{mcu}:{alias} has conflicting alias definitions")
        physical = aliases.get(target, target)
        if physical == alias:
            raise PinAliasError(f"{mcu}:{alias} has a cyclic alias definition")
        aliases[alias] = physical
        for name, pin in aliases.items():
            if pin == alias:
                aliases[name] = physical

    @staticmethod
    def split_pin(token):
        # Modifiers belong before [mcu:]pin; their legality for a particular
        # consumer remains Klipper's responsibility.
        value = token.strip().lstrip("^~!")
        if ":" in value:
            return tuple(part.strip() for part in value.split(":", 1))
        return "mcu", value

    def resolve(self, token):
        mcu, name = self.split_pin(token)
        mcu = self.scaled_mcus.get(mcu, mcu)
        physical = self.aliases.get(mcu, {}).get(name, name)
        reservation = self.reserved.get(mcu, {}).get(physical)
        if reservation is not None:
            raise PinAliasError(f"{token} is reserved for {reservation}")
        return mcu, physical


def _read_pin_config(content):
    parser = configparser.RawConfigParser(
        strict=False, inline_comment_prefixes=("#", ";"))
    try:
        parser.read_string(content)
    except configparser.Error as exc:
        raise PinAliasError(f"Cannot parse pin configuration: {exc}") from exc
    sections = {name: dict(parser.items(name)) for name in parser.sections()}
    # Keep diagnostics attached to the original option, including '=' syntax.
    locations = {}
    section = ""
    for lineno, raw in enumerate(content.splitlines(), 1):
        line = raw.split("#", 1)[0].split(";", 1)[0].strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
        else:
            match = re.match(r"([a-zA-Z0-9_]+)\s*[:=]", line)
            if match:
                locations[section, match.group(1).lower()] = lineno
    return sections, locations


def validate_pins_for_mcu(cfg_path, mcu):
    """Return namespace violations without changing the original config.

    ``mcu`` is the primary MCU type, or a mapping of MCU name to type. Unknown
    secondary architectures are not guessed from the primary. Definite alias
    errors raise PinAliasError; architecture heuristics retain the existing
    (line_number, field, original_token, expected_arch) diagnostics. This reads
    the supplied file only; it does not expand external includes.
    """
    mcus = mcu if isinstance(mcu, dict) else {"mcu": mcu}
    arches = {name: arch_for_mcu(value) for name, value in mcus.items()}
    try:
        with open(cfg_path, "r", encoding="utf-8", errors="replace") as source:
            sections, locations = _read_pin_config(source.read())
    except OSError:
        return None
    resolver = PinAliases(sections)
    # Unused reserved header positions are legal. Check ordinary aliases even
    # if unused, so a typo does not become a silently accepted GPIO later.
    for chip, aliases in resolver.aliases.items():
        ns = _NAMESPACES.get(arches.get(chip))
        for alias, target in aliases.items():
            if target in resolver.reserved.get(chip, {}):
                continue
            if ns is not None and not any(pattern and pattern.fullmatch(target)
                                         for pattern in _NAMESPACES.values()):
                raise PinAliasError(f"{chip}:{alias} resolves to undefined pin or alias {target!r}")

    issues = []
    spellings = {}
    for section, options in sections.items():
        if section == "board_pins" or section.startswith("board_pins "):
            continue
        for field, value in options.items():
            if not (field == "pin" or field.endswith("_pin")
                    or field in ("pins", "select_pins", "encoder_pins")):
                continue
            for token in re.split(r"[,\s]+", value.strip()):
                if not token:
                    continue
                chip, physical = resolver.resolve(token)
                _, spelling = resolver.split_pin(token)
                if not _is_real_gpio(physical):
                    continue
                ns = _NAMESPACES.get(arches.get(chip))
                if ns is not None and not ns.fullmatch(physical):
                    issues.append((locations.get((section, field), 0), field,
                                   token, arches[chip]))
                if section == "duplicate_pin_override":
                    # This registers permission; it emits no MCU pin command.
                    continue
                # Klipper's PinResolver forbids using two names for the same
                # physical pin. Repeated use of the SAME name remains subject
                # to upstream consumer sharing rules (e.g. shared enables).
                identity = chip, physical
                previous = spellings.setdefault(identity, spelling)
                if previous != spelling:
                    raise PinAliasError(f"{token} is an alias of already used {chip}:{previous}")
    if not any(arches.values()) and not issues:
        return None
    return issues


def validate_bltouch_pin_usage(content, *, firmware_reservations=None):
    """Reject BLTouch conflicts in effective, rendered hardware text.

    This checks exclusive sensor/control allocations, not all consumers' sharing
    rules. Z reuse is legal only after the physical endstop was actually replaced.
    Includes must already be expanded by the caller. Firmware reservations are
    supplied per MCU by the caller from identity-bound firmware evidence.
    The supplied map may include reviewed hardware bus reservations; special
    host-dependent buses and unreviewed device classes remain outside its scope.
    """
    _validate_probe_section(content, "bltouch", ("sensor_pin", "control_pin"),
                            "BLTouch", firmware_reservations)


def validate_probe_pin_usage(content, *, firmware_reservations=None):
    """Validate supported physical probe pins in already expanded configuration.

    Standard [probe] covers guided/raw custom and inductive strategies. Other
    probe classes have different pin contracts and are not inferred here.
    """
    validate_bltouch_pin_usage(content, firmware_reservations=firmware_reservations)
    _validate_probe_section(content, "probe", ("pin",), "Probe", firmware_reservations)


def _validate_probe_section(content, section_name, fields, label, firmware_reservations):
    if not re.search(r"(?m)^\s*\[" + re.escape(section_name) + r"\]\s*(?:[#;].*)?$", content):
        return
    try:
        sections, _ = _read_pin_config(content)
        aliases = PinAliases(sections)
        identities = {}
        from core.validators import questionary_fan_pin_validator, validate_klipper_pin

        for field in fields:
            token = sections[section_name].get(field, "").strip()
            if field == "control_pin":
                valid = questionary_fan_pin_validator(token) is True
            else:
                bare = re.sub(r"^[\^~]?!?", "", token)
                valid = validate_klipper_pin(token) and not any(c in bare for c in "^~!")
            if not valid:
                raise PinAliasError(f"{label} {field} has an invalid pin: {token!r}")
            identity = aliases.resolve(token)
            reason = (firmware_reservations or {}).get(identity[0], {}).get(identity[1])
            if reason is not None:
                raise PinAliasError(f"{label} {field} {token} is reserved by firmware for {reason}")
            if identity in identities:
                raise PinAliasError(f"{label} {field} {token} shares the GPIO of {identities[identity]}")
            identities[identity] = field

        for section, options in sections.items():
            if (section in (section_name, "board_pins", "duplicate_pin_override")
                    or section.startswith(("board_pins ", "gcode_macro ", "delayed_gcode "))):
                continue
            for field, value in options.items():
                if not (field == "pin" or field.endswith("_pin")
                        or field in ("pins", "select_pins", "encoder_pins")):
                    continue
                for token in re.split(r"[,\s]+", value.strip()):
                    if not token:
                        continue
                    role = identities.get(aliases.resolve(token))
                    if role:
                        raise PinAliasError(
                            f"{label} {role} conflicts with [{section}] {field}: {token}")
    except PinAliasError as exc:
        raise PinAliasError(f"{label} pin validation failed: {exc}") from exc
