#!/usr/bin/env python3
"""KACE Advanced Module Passthrough — Full Validation (run from repo root)."""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.advanced_module_handler import get_advanced_sections, is_unsupported_section
from core.generator import generate_config

ok = True

def check(label, cond):
    global ok
    tag = "OK  " if cond else "FAIL"
    if not cond: ok = False
    print(f"  [{tag}] {label}")

print("=" * 60)
print("KACE Advanced Module Passthrough — Full Validation")
print("=" * 60)

# ── 1. Gate logic ──────────────────────────────────────────────
print("\n[1] Gate classification")
for s in ["resonance_tester", "lis2dw", "mpu9250", "palette2"]:
    check(repr(s) + " -> UNSUPPORTED", is_unsupported_section(s) is True)

for s in ["neopixel", "neopixel sb_leds", "adxl345", "sx1509", "dotstar", "pca9685"]:
    check(repr(s) + " -> passthrough (not gated)", is_unsupported_section(s) is False)

# ── 2. Block rendering ─────────────────────────────────────────
print("\n[2] Block rendering")
parsed = {
    "mcu":              {"serial": "/dev/test"},
    "stepper_x":        {"step_pin": "PA1", "dir_pin": "PA2",
                         "enable_pin": "!PA3", "endstop_pin": "PB0",
                         "position_max": "235"},
    "stepper_y":        {"step_pin": "PC1", "dir_pin": "PC2",
                         "enable_pin": "!PC3", "endstop_pin": "PB1",
                         "position_max": "235"},
    "stepper_z":        {"step_pin": "PD1", "dir_pin": "PD2",
                         "enable_pin": "!PD3", "endstop_pin": "PB2",
                         "position_max": "250"},
    "extruder":         {"step_pin": "PE1", "dir_pin": "PE2",
                         "enable_pin": "!PE3",
                         "heater_pin": "PA4", "sensor_pin": "PA5"},
    "heater_bed":       {"heater_pin": "PA6", "sensor_pin": "PA7"},
    "fan":              {"pin": "PC5"},
    "neopixel sb_leds": {"pin": "PB7", "chain_count": "3", "color_order": "GRBW"},
    "adxl345":          {"cs_pin": "PA4", "spi_software_sclk_pin": "PA5"},
    "sx1509":           {"i2c_address": "0x3e"},
}
blocks = get_advanced_sections(parsed)
check(f"{len(blocks)} blocks rendered (expect 3)", len(blocks) == 3)

if blocks:
    all_commented = all(
        all(line.lstrip().startswith("#") for line in b.strip().splitlines())
        for b in blocks
    )
    check("all block lines are comments", all_commented)
    check("neopixel pin PB7 in block 1",  len(blocks) > 0 and "PB7"  in blocks[0])
    check("adxl345 cs_pin PA4 in block 2", len(blocks) > 1 and "PA4"  in blocks[1])
    check("sx1509 0x3e in block 3",        len(blocks) > 2 and "0x3e" in blocks[2])

# ── 3. generate_config end-to-end ──────────────────────────────
print("\n[3] generate_config() end-to-end")
user = {
    "mcu_path": "/dev/serial/by-id/usb-test",
    "kinematics": "cartesian",
    "x_size": "235", "y_size": "235", "z_size": "250",
    "stepper_drivers": "None (Standard)",
    "driver_type": "None (Standard)", "driver_mode": "Standalone",
    "hotend_thermistor": "EPCOS 100K B57560G104F",
    "bed_thermistor":    "EPCOS 100K B57560G104F",
    "probe": "None", "motors": "4", "z_motors": "1", "extruder": "1",
    "runout": "No", "language": "en", "web_interface": "None",
    "board": "test.cfg", "printer_profile": "test.cfg",
    "gear_ratio_x": None, "gear_ratio_y": None,
    "gear_ratio_z": None, "gear_ratio_e": None,
    "rotation_distance_x": None, "rotation_distance_y": None,
    "rotation_distance_z": None, "rotation_distance_e": None,
}

out = os.path.join(tempfile.gettempdir(), "kace_adv_test.cfg")
try:
    generate_config(parsed, user, output_path=out)
    cfg = open(out, encoding="utf-8").read()

    check("ADVANCED HARDWARE SECTIONS banner present", "ADVANCED HARDWARE SECTIONS" in cfg)
    check("# [neopixel sb_leds] in output",            "# [neopixel sb_leds]" in cfg)
    check("# [adxl345] in output",                     "# [adxl345]" in cfg)
    check("# [sx1509] in output",                      "# [sx1509]" in cfg)
    check("# pin: PB7 in output",                      "# pin: PB7" in cfg)
    check("# cs_pin: PA4 in output",                   "# cs_pin: PA4" in cfg)
    check("no active [neopixel] line",
          not any(l.startswith("[neopixel") for l in cfg.splitlines()))
    check("no active [adxl345] line",
          not any(l.startswith("[adxl345")  for l in cfg.splitlines()))

    print(f"\n  Output: {out}")
except Exception as e:
    import traceback
    print(f"  [FAIL] generate_config raised: {e}")
    traceback.print_exc()
    ok = False

print("\n" + "=" * 60)
print("RESULT:", "ALL PASSED" if ok else "SOME CHECKS FAILED")
print("=" * 60)
sys.exit(0 if ok else 1)
