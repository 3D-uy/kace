"""Review native TMC virtual endstops without operating the driver or motor."""
import re

from core.exceptions import GenerationError
from core.pin_validator import PinAliases, PinAliasError


_MODELS = ("tmc2208", "tmc2209", "tmc2130", "tmc5160")
_DIAG = ("diag_pin", "diag0_pin", "diag1_pin")


def validate_tmc_virtual_endstops(sections):
    """Validate the reviewed native model/DIAG contract in effective sections.

    Unused DIAG strings are not allocated by Klipper. Active DIAG is an
    endstop GPIO and need not belong to the same MCU as the driver transport.
    Physical homing, driver tuning and arbitrary external models are not covered.
    """
    drivers = {}
    for name, options in sections.items():
        model, separator, target = name.partition(" ")
        if not separator or model not in _MODELS:
            continue
        if not target.strip():
            raise GenerationError(f"[{name}]: TMC driver requires a stepper name.")
        allowed = (() if model == "tmc2208" else ("diag_pin",) if model == "tmc2209"
                   else ("diag0_pin", "diag1_pin"))
        unused = set(_DIAG).intersection(options) - set(allowed)
        if model in ("tmc2130", "tmc5160") and all(field in options for field in allowed):
            unused.add("diag1_pin")
        if unused:
            raise GenerationError(f"[{name}]: unused DIAG options: {', '.join(sorted(unused))}.")
        if model != "tmc2208":
            field = next((field for field in allowed if field in options), None)
            drivers[f"{model}_{target.split()[-1]}"] = (name, options.get(field))

    try:
        aliases = PinAliases(sections)
        mcus = {"mcu"} | {name[4:] for name in sections if name.startswith("mcu ")}
        active, refs = {}, {}
        for name, options in sections.items():
            if name.startswith(("gcode_macro ", "delayed_gcode ", "board_pins")):
                continue
            for field, value in options.items():
                if field in _DIAG or not (field == "pin" or field.endswith("_pin")):
                    continue
                token = value.strip()
                bare = token.lstrip("^~!").strip()
                chip, sep, pin = bare.partition(":")
                chip, pin = chip.strip(), pin.strip()
                if not sep or not chip.startswith(tuple(model + "_" for model in _MODELS)):
                    continue
                if (field != "endstop_pin" or not (name.startswith("stepper_") or name.startswith("manual_stepper "))
                        or pin != "virtual_endstop" or token != bare):
                    raise GenerationError(f"[{name}] {field}: TMC virtual_endstop must be an unmodified endstop.")
                if chip not in drivers:
                    raise GenerationError(f"[{name}]: TMC virtual_endstop has no supported driver section for {chip}.")
                driver, diag = drivers[chip]
                if diag is None:
                    raise GenerationError(f"[{driver}]: TMC virtual_endstop requires DIAG.")
                # Klipper shares an endstop within one rail, not across rails.
                rail = re.sub(r"\d+$", "", name) if name.startswith("stepper_") else name
                if chip in refs and refs[chip] != rail:
                    raise GenerationError(f"[{name}]: TMC virtual_endstop is already used by another rail.")
                refs[chip] = rail
                value = diag.strip()
                if value.startswith(("^", "~")):
                    value = value[1:].strip()
                if value.startswith("!"):
                    value = value[1:].strip()
                parts = value.split(":", 1)
                mcu, spelling = (part.strip() for part in parts) if len(parts) == 2 else ("mcu", value)
                if mcu not in mcus or not spelling or any(c in spelling for c in "^~!:") or "".join(spelling.split()) != spelling:
                    raise GenerationError(f"[{driver}]: invalid active DIAG pin {diag!r}.")
                identity = aliases.resolve(f"{mcu}:{spelling}")
                if identity in active and active[identity] != driver:
                    raise GenerationError(f"[{driver}]: active DIAG conflicts with {active[identity]}.")
                active[identity] = driver
        if not active:
            return
        for name, options in sections.items():
            if (name in ("board_pins", "duplicate_pin_override")
                    or name.startswith(("board_pins ", "gcode_macro ", "delayed_gcode "))):
                continue
            for field, value in options.items():
                if field in _DIAG or not (field == "pin" or field.endswith("_pin") or field in ("pins", "select_pins", "encoder_pins")):
                    continue
                for token in re.split(r"[,\s]+", value.strip()):
                    if token and aliases.resolve(token) in active:
                        raise GenerationError(f"[{name}] {field}: pin conflicts with active DIAG of {active[aliases.resolve(token)]}.")
    except PinAliasError as exc:
        raise GenerationError(f"TMC DIAG: {exc}") from exc
