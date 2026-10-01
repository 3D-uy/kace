"""Compare effective UART configuration with official registration/pin logic."""
import hashlib
import json
import subprocess

from validate_tmc_uart_identity import official_accepts, UPSTREAM
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.pin_validator import _read_pin_config
from core.tmc_uart import validate_uart_config
from core.exceptions import GenerationError
from tests.unit.test_tmc_uart_review import CASES, UART, remote_files


def main():
    rows = []
    # Explicit external pin requests, independent of KACE's consumer scan.
    consumers = {"fan-conflict": ["!PC11"], "stepper-conflict": ["PC11"],
                 "diag-conflict": ["^PC11"], "independent-mcu": ["tool:PC11"],
                 "multiline-alias": ["NEXT"], "override-does-not-bypass": ["PC11"]}
    for name, extra, expected in CASES:
        plan = build_managed_config_plan(UART, None, remote_files(extra))
        effective = effective_hardware_text(plan)
        sections, _ = _read_pin_config(effective)
        official, error = official_accepts(sections, external_pins=consumers.get(name, ()))
        try:
            validate_uart_config(effective)
            local = True
        except GenerationError:
            local = False
        assert official == local == expected, (name, official, local, error)
        rows.append({"case": name, "accepted": official, "official_error": error,
                     "scope": "Declared exclusive pin claims; override bypass intentionally not enabled" if name in consumers
                              else "UART registration", "result": "PASS"})
    print(json.dumps({"revision": subprocess.check_output(["git", "-C", str(UPSTREAM), "rev-parse", "HEAD"], text=True).strip(),
        "source_hashes": {name: hashlib.sha256((UPSTREAM / name).read_bytes()).hexdigest() for name in
            ("klippy/pins.py", "klippy/extras/tmc_uart.py", "klippy/extras/board_pins.py", "klippy/configfile.py")},
        "cases": rows, "limits": "Fake MCU transport. External pin claims model exclusivity, not complete peripheral loaders."
    }, indent=2))


if __name__ == "__main__":
    main()
