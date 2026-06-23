#!/usr/bin/env python3
"""
KACE — Advanced Module Passthrough Smoke Test
Tests is_unsupported_section(), get_advanced_sections(), and generate_config()
end-to-end. No network, no git, no temp-dir permissions needed.
"""
import sys, os, pathlib, tempfile

# Resolve project root robustly regardless of CWD or drive letter.
_ROOT = str(pathlib.Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
# Also add via os.path in case pathlib.resolve() strips the drive letter
_ROOT2 = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if _ROOT2 not in sys.path:
    sys.path.insert(0, _ROOT2)

from core.advanced_module_handler import get_advanced_sections, is_unsupported_section
from core.generator import generate_config

PASS_MARK = "\033[92mOK\033[0m"
FAIL_MARK = "\033[91mFAIL\033[0m"
failures  = []

def check(label, cond):
    tag = PASS_MARK if cond else FAIL_MARK
    print(f"  [{tag}] {label}")
    if not cond:
        failures.append(label)

# ── 1. Gate classification ────────────────────────────────────────────────────
print("\n── Test 1: is_unsupported_section() ─────────────────────────────")

for s in ["resonance_tester", "lis2dw", "mpu9250", "palette2"]:
    check(f"{s!r} still UNSUPPORTED (passthrough=False)", is_unsupported_section(s) is True)

for s in ["neopixel", "neopixel sb_leds", "adxl345", "sx1509", "dotstar", "pca9685"]:
    check(f"{s!r} no longer gated (passthrough=True)", is_unsupported_section(s) is False)

# ── 2. Block rendering ────────────────────────────────────────────────────────
print("\n── Test 2: get_advanced_sections() rendering ─────────────────────")

fake_parsed = {
    "mcu":            {"serial": "/dev/serial/by-id/usb-test"},
    "stepper_x":      {"step_pin": "PA1", "dir_pin": "PA2", "enable_pin": "!PA3",
                       "endstop_pin": "PB0", "position_max": "235"},
    "neopixel sb_leds": {
        "pin": "PB7", "chain_count": "3", "color_order": "GRBW",
        "initial_red": "0.0", "initial_green": "0.0",
        "initial_blue": "0.0", "initial_white": "0.0",
    },
    "adxl345": {
        "cs_pin": "PA4",
        "spi_software_sclk_pin": "PA5",
        "spi_software_mosi_pin": "PA7",
        "spi_software_miso_pin": "PA6",
    },
    "sx1509": {
        "i2c_address": "0x3e",
        "i2c_mcu": "mcu",
    },
}

blocks = get_advanced_sections(fake_parsed)
check("3 passthrough blocks rendered (neopixel + adxl345 + sx1509)", len(blocks) == 3)

neo  = next((b for b in blocks if "neopixel" in b.lower()), None)
adxl = next((b for b in blocks if "adxl345"  in b.lower()), None)
sx   = next((b for b in blocks if "sx1509"   in b.lower()), None)

check("neopixel block exists",          neo  is not None)
check("adxl345 block exists",           adxl is not None)
check("sx1509 block exists",            sx   is not None)
check("neopixel pin PB7 in block",      neo  is not None and "PB7"  in neo)
check("adxl345 cs_pin PA4 in block",    adxl is not None and "PA4"  in adxl)
check("sx1509 i2c_address in block",    sx   is not None and "0x3e" in sx)
check("all blocks start with '#'",      all(b.lstrip().startswith("#") for b in blocks))

# ── 3. End-to-end generate_config() ──────────────────────────────────────────
print("\n── Test 3: generate_config() end-to-end ─────────────────────────")

user_data = {
    "mcu_path": "/dev/serial/by-id/usb-test",
    "kinematics": "cartesian",
    "x_size": "235", "y_size": "235", "z_size": "250",
    "stepper_drivers": "None (Standard)",
    "driver_type": "None (Standard)", "driver_mode": "Standalone",
    "hotend_thermistor": "EPCOS 100K B57560G104F",
    "bed_thermistor":    "EPCOS 100K B57560G104F",
    "probe": "None", "motors": "4", "z_motors": "1", "extruder": "1",
    "runout": "No", "language": "en", "web_interface": "None",
    "board": "test-board.cfg", "printer_profile": "test-board.cfg",
    "gear_ratio_x": None, "gear_ratio_y": None,
    "gear_ratio_z": None, "gear_ratio_e": None,
    "rotation_distance_x": None, "rotation_distance_y": None,
    "rotation_distance_z": None, "rotation_distance_e": None,
}

out_path = os.path.join(_ROOT, "outputs", "_smoke_test_output.cfg")
os.makedirs(os.path.dirname(out_path), exist_ok=True)

try:
    generate_config(fake_parsed, user_data, output_path=out_path, include_macros=False)
    cfg = pathlib.Path(out_path).read_text(encoding="utf-8")

    check("ADVANCED HARDWARE SECTIONS banner in output",     "ADVANCED HARDWARE SECTIONS" in cfg)
    check("# [neopixel sb_leds] commented in output",        "# [neopixel sb_leds]" in cfg)
    check("# [adxl345] commented in output",                 "# [adxl345]" in cfg)
    check("# [sx1509] commented in output",                  "# [sx1509]" in cfg)
    check("# pin: PB7 in output",                            "# pin: PB7" in cfg)
    check("# cs_pin: PA4 in output",                         "# cs_pin: PA4" in cfg)
    check("no ACTIVE [neopixel] section (must stay comment)",
          not any(l.startswith("[neopixel") for l in cfg.splitlines()))
    check("no ACTIVE [adxl345] section",
          not any(l.startswith("[adxl345") for l in cfg.splitlines()))

    print(f"\n  Output saved → {out_path}")

except Exception as e:
    import traceback
    print(f"  \033[91mEXCEPTION:\033[0m {e}")
    traceback.print_exc()
    failures.append(f"generate_config raised: {e}")

# ── Result ────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
if failures:
    print(f"  \033[91mFAILED — {len(failures)} check(s) failed:\033[0m")
    for f in failures:
        print(f"    • {f}")
    sys.exit(1)
else:
    print("  \033[92mALL CHECKS PASSED\033[0m")
    sys.exit(0)
