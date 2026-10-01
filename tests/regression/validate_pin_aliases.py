"""Compare KACE aliases with the official PinResolver in the matrix container.

The real loader stops before MCU identification; aliases are also expanded
later in PinResolver.update_command. Exercise that official phase explicitly.
No serial connection or firmware command is sent.
"""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(os.environ.get("KLIPPER_ROOT", "/opt/klipper")) / "klippy"))

from pins import PinResolver, error as KlipperPinError
from core.pin_validator import PinAliases, PinAliasError


def main():
    rows = []
    for definitions, token, expected in (
        ([("EXP1_1", "PA0")], "EXP1_1", "PA0"),
        ([("A", "B"), ("B", "PA0")], "A", "PA0"),
        ([("B", "PA0"), ("A", "B")], "A", "PA0"),
        ([("A", "B"), ("B", "C"), ("C", "PA0")], "A", "PA0"),
        ([("A", "PA0"), ("A", "PA0")], "A", "PA0"),
    ):
        official = PinResolver()
        for alias, target in definitions:
            official.alias_pin(alias, target)
        candidate = PinAliases({"board_pins": {"aliases": ",".join(a + "=" + p for a, p in definitions)}})
        assert official.update_command("config pin=" + token) == "config pin=" + expected
        assert candidate.resolve(token) == ("mcu", expected)
        rows.append({"definitions": definitions, "token": token, "physical": expected, "result": "PASS"})

    for definitions in (
        [("A", "PA0"), ("A", "PA1")], [("A", "!PA0")],
        [("A", "toolhead:PA0")], [("A", "PA 0")],
    ):
        official = PinResolver()
        try:
            for alias, target in definitions:
                official.alias_pin(alias, target)
        except KlipperPinError:
            pass
        else:
            raise AssertionError(("official unexpectedly accepted", definitions))
        try:
            PinAliases({"board_pins": {"aliases": ",".join(a + "=" + p for a, p in definitions)}})
        except PinAliasError:
            pass
        else:
            raise AssertionError(("KACE unexpectedly accepted", definitions))
        rows.append({"definitions": definitions, "result": "EXPECTED_REJECT"})

    official = PinResolver()
    official.alias_pin("A", "PA0")
    official.alias_pin("B", "PA0")
    assert official.update_command("config pin=A") == "config pin=PA0"
    try:
        official.update_command("config pin=B")
    except KlipperPinError:
        rows.append({"case": "two aliases used for one physical pin", "result": "EXPECTED_REJECT"})
    else:
        raise AssertionError("official accepted conflicting alias use")

    official = PinResolver()
    official.reserve_pin("GND", "<GND>")
    official.alias_pin("OTHER", "GND")
    try:
        official.update_command("config pin=OTHER")
    except KlipperPinError:
        rows.append({"case": "reserved pin through alias", "result": "EXPECTED_REJECT"})
    else:
        raise AssertionError("official accepted reserved GPIO")
    print(json.dumps({"official_module": str(Path(sys.modules['pins'].__file__)),
                      "klipper_ref": os.environ.get("KLIPPER_REF"), "cases": rows}, indent=2))


if __name__ == "__main__":
    main()
