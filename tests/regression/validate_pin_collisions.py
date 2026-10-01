"""Exercise official PrinterPins and PinResolver alongside the wizard.

Set KLIPPER_ROOT to an exact official checkout. This imports pure Python pin
logic only: no MCU is connected, no firmware command is sent. Real consumer
sharing is tested independently of the wizard's exclusive probe allocation.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = Path(os.environ["KLIPPER_ROOT"])
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(UPSTREAM / "klippy"))

from pins import PrinterPins, error as KlipperPinError
from core.wizard.steps.sensors import make_pin_validator_with_collision_check


def registry():
    pins = PrinterPins()
    for chip in ("mcu", "toolhead", "other", "Toolhead"):
        pins.register_chip(chip, object())
        resolver = pins.get_pin_resolver(chip)
        resolver.alias_pin("HEADER", "gpio5")
        resolver.alias_pin("CHAIN", "HEADER")
        resolver.reserve_pin("GND", "<GND>")
    return pins


def main():
    rows = []
    cases = [
        ("gpio5", "toolhead:gpio5", True),
        ("toolhead:gpio5", "gpio5", True),
        ("toolhead:gpio5", "other:gpio5", True),
        ("toolhead:gpio5", "Toolhead:gpio5", True),
        ("gpio5", "mcu:gpio5", False),
        ("mcu:gpio5", "gpio5", False),
        ("!toolhead:gpio5", "^toolhead:gpio5", False),
        ("HEADER", "gpio5", False),
        ("gpio5", "HEADER", False),
        ("HEADER", "CHAIN", False),
        ("toolhead:HEADER", "HEADER", True),
        ("toolhead:HEADER", "toolhead:gpio5", False),
        ("gpio6", "GND", False),
        ("gpio6", "toolhead:GND", False),
        ("gpio6", "^!toolhead:gpio5", True),
        ("gpio6", "toolhead:!gpio5", False),
        ("gpio6", "!!gpio5", False),
        ("gpio6", "!^gpio5", False),
        ("gpio6", "^~gpio5", False),
    ]
    for used, candidate, expected in cases:
        official = registry()
        accepted, error = True, None
        try:
            allocated = official.lookup_pin(used, can_invert=True)
            requested = official.lookup_pin(candidate, can_invert=True, can_pullup=True)
            # Alias expansion happens later than lookup_pin in Klipper.
            for params in (allocated, requested):
                official.get_pin_resolver(params["chip_name"]).update_command(
                    "config pin=" + params["pin"])
        except KlipperPinError as exc:
            accepted, error = False, str(exc)
        sections = {"fan": {"pin": used}, "board_pins headers": {
            "mcu": "mcu,toolhead,other,Toolhead",
            "aliases": "HEADER=gpio5,CHAIN=HEADER,GND=<GND>"}}
        with patch("core.wizard.steps.sensors._get_parsed", return_value=sections):
            check = make_pin_validator_with_collision_check({"mcu_type": "rp2040"})
        result = check(candidate)
        assert accepted == expected, (used, candidate, error)
        assert (result is True) == expected, (used, candidate, result)
        rows.append({"used": used, "candidate": candidate, "accepted": accepted,
                     "official_error": error, "result": "PASS"})

    # Shared enables are permitted, but a new exclusive probe cannot reuse one.
    official = registry()
    first = official.lookup_pin("!gpio5", can_invert=True, share_type="stepper_enable")
    second = official.lookup_pin("!mcu:gpio5", can_invert=True, share_type="stepper_enable")
    assert first is second
    for token, share_type, expected_error in (
        ("gpio5", "stepper_enable", "same polarity"),
        ("gpio5", None, "used multiple times"),
    ):
        try:
            official.lookup_pin(token, can_invert=True, share_type=share_type)
        except KlipperPinError as exc:
            assert expected_error in str(exc)
        else:
            raise AssertionError("Expected sharing conflict")
    rows.append({"case": "shared enable / polarity / exclusive probe", "result": "PASS"})
    print(json.dumps({
        "revision": subprocess.check_output(
            ["git", "-C", str(UPSTREAM), "rev-parse", "HEAD"], text=True).strip(),
        "pins_sha256": hashlib.sha256((UPSTREAM / "klippy/pins.py").read_bytes()).hexdigest(),
        "cases": rows,
    }, indent=2))


if __name__ == "__main__":
    main()
