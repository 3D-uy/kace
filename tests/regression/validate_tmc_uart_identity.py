"""Compare selected UART topology with unmodified official Klipper modules.

KLIPPER_ROOT selects an exact checkout. Fake MCU transport records config
commands only; real PrinterPins, mux and UART registration run unchanged.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = Path(os.environ["KLIPPER_ROOT"])
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(UPSTREAM / "klippy"))

from configfile import ConfigFileReader, ConfigWrapper, error as ConfigError
from pins import PrinterPins, error as PinError
from extras.tmc_uart import lookup_tmc_uart_bitbang
from extras.board_pins import PrinterBoardAliases
from core.profile_values import resolve_tmc_sections
from core.exceptions import GenerationError
from tests.unit.test_tmc_uart_identity import CASES, case_sections
from tests.unit.test_generator import _user


def official_accepts(sections, *, external_pins=()):
    ppins = PrinterPins()
    objects = {"pins": ppins}
    printer = SimpleNamespace(
        lookup_object=lambda name, default=None: objects.get(name, default),
        add_object=lambda name, obj: objects.update({name: obj}),
        get_reactor=lambda: SimpleNamespace(mutex=lambda: object()),
        config_error=RuntimeError)
    commands, callbacks = [], []
    ids = iter(range(100))
    for chip in sorted({"mcu"} | {name[4:] for name in sections if name.startswith("mcu ")}):
        mcu = SimpleNamespace(
            get_printer=lambda: printer, create_oid=lambda: next(ids),
            alloc_command_queue=lambda: object(),
            add_config_cmd=lambda command, chip=chip: commands.append((chip, command)),
            register_config_callback=callbacks.append,
            get_constants=lambda: {"MCU": "stm32f446xx"},
            seconds_to_clock=lambda value: int(value * 1000000),
            lookup_command=lambda *args, **kwargs: object(),
            lookup_query_command=lambda *args, **kwargs: object())
        # SimpleNamespace is unhashable; upstream keys the mutex by MCU object.
        class MCU:
            pass
        wrapper = MCU()
        wrapper.__dict__.update(mcu.__dict__)
        ppins.register_chip(chip, wrapper)
    text = "\n".join(f"[{name}]\n" + "\n".join(f"{key}: " + value.replace("\n", "\n  ") for key, value in values.items())
                     for name, values in sections.items())
    config = ConfigFileReader().build_fileconfig(text, "uart.cfg")
    try:
        for name in sections:
            if name == "board_pins" or name.startswith("board_pins "):
                PrinterBoardAliases(ConfigWrapper(printer, config, {}, name))
        for name in sections:
            if name.startswith(("tmc2208 ", "tmc2209 ")):
                lookup_tmc_uart_bitbang(ConfigWrapper(printer, config, {}, name),
                                       3 if name.startswith("tmc2209 ") else 0)
        for token in external_pins:
            params = ppins.lookup_pin(token, can_invert=True, can_pullup=True)
            commands.append((params["chip_name"], "config pin=" + params["pin"]))
        for callback in callbacks:
            callback()
        for chip, command in commands:
            ppins.get_pin_resolver(chip).update_command(command)
    except (RuntimeError, PinError, ConfigError) as exc:
        return False, str(exc)
    return True, None


def main():
    rows = []
    for name, changes, expected in CASES:
        sections = case_sections(changes)
        official, error = official_accepts(sections)
        try:
            resolve_tmc_sections(sections, _user(driver_type="TMC2209", driver_mode="UART"))
            local = True
        except GenerationError:
            local = False
        assert official == local == expected, (name, expected, official, local, error)
        rows.append({"case": name, "accepted": official, "official_error": error, "result": "PASS"})
    print(json.dumps({
        "revision": subprocess.check_output(["git", "-C", str(UPSTREAM), "rev-parse", "HEAD"], text=True).strip(),
        "source_hashes": {name: hashlib.sha256((UPSTREAM / name).read_bytes()).hexdigest()
                          for name in ("klippy/extras/tmc_uart.py", "klippy/pins.py", "klippy/configfile.py")},
        "cases": rows, "scope": "Unmodified upstream registration and config commands; fake transport, no MCU IO."
    }, indent=2))


if __name__ == "__main__":
    main()
