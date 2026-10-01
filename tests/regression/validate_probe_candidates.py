"""Check candidate provenance against exact upstream CFGs and PinResolver.

Set KLIPPER_ROOT to an official checkout. This checks declared mappings only;
it cannot establish electrical suitability or firmware transport reservations.
"""
import configparser
import copy
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

from pins import PinResolver
from core.scraper import parse_config
from core.wizard.steps.sensors import _get_unused_pins


def main():
    rows = []
    for source in sorted((ROOT / "tests/fixtures/bltouch-catalog").glob("*.cfg")):
        raw = source.read_bytes()
        assert raw == (UPSTREAM / "config" / source.name).read_bytes(), source.name
        text = raw.decode("utf-8")
        config = configparser.RawConfigParser(inline_comment_prefixes=("#", ";"))
        config.read_string(text)
        resolvers, declared = {}, set()
        for section in config.sections():
            if section != "board_pins" and not section.startswith("board_pins "):
                continue
            options = dict(config.items(section))
            for chip in options.get("mcu", "mcu").split(","):
                chip = chip.strip()
                resolver = resolvers.setdefault(chip, PinResolver())
                for key in ["aliases"] + [k for k in options if k.startswith("aliases_")]:
                    for assignment in options[key].split(","):
                        if not assignment.strip():
                            continue
                        alias, pin = (part.strip() for part in assignment.split("="))
                        if pin.startswith("<") and pin.endswith(">"):
                            resolver.reserve_pin(alias, pin)
                        else:
                            resolver.alias_pin(alias, pin)
                            declared.add((chip, alias))
        parsed = parse_config(text, source.name, keep_comments=True)
        with patch("core.wizard.steps.sensors._get_parsed", return_value=parsed):
            candidates = _get_unused_pins({"board": source.name})
        for friendly, physical in candidates:
            chip, alias = friendly.split(":", 1) if ":" in friendly else ("mcu", friendly)
            assert (chip, alias) in declared, (source.name, friendly)
            resolved = copy.deepcopy(resolvers[chip]).update_command("config pin=" + alias)
            expected = resolved.removeprefix("config pin=")
            if chip != "mcu":
                expected = chip + ":" + expected
            assert physical == expected, (source.name, friendly, physical, expected)
        rows.append({"board": source.name, "sha256": hashlib.sha256(raw).hexdigest(),
                     "declared_aliases": len(declared), "candidates": candidates, "result": "PASS"})
    assert rows and any(row["candidates"] for row in rows)
    print(json.dumps({
        "klipper_commit": subprocess.check_output(
            ["git", "-C", str(UPSTREAM), "rev-parse", "HEAD"], text=True).strip(),
        "pins_sha256": hashlib.sha256((UPSTREAM / "klippy/pins.py").read_bytes()).hexdigest(),
        "boards": rows,
        "scope": "Declared mapping and alias expansion; no MCU identify or electrical qualification",
    }, indent=2))


if __name__ == "__main__":
    main()
