#!/usr/bin/env python3
"""KACE Hardware Display Compatibility Validation Suite."""
import sys
import os

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.display_checker import classify_hardware_combination

ok = True

def check(label, cond):
    global ok
    tag = " \033[92m[PASS]\033[0m" if cond else " \033[91m[FAIL]\033[0m"
    if not cond:
        ok = False
    print(f"{tag} {label}")

print("=" * 65)
print(" KACE — Hardware Display Compatibility Validation")
print("=" * 65)

# 1. RP2040 + 5V display (neopixel) -> unsafe
print("\n[1] Test Case: RP2040 (SKR Pico) + 5V display (neopixel)")
res1 = classify_hardware_combination("neopixel", "generic-bigtreetech-skr-pico-v1.0.cfg", {})
check("Classified as unsafe", res1["compatibility_class"] == "unsafe")
check("Includes overvoltage damage risk", any("RP2040" in r for r in res1["damage_risks"]))
check("Includes level shifter mod", any("level shifter" in m for m in res1["required_modifications"]))

# 2. ATmega + standard RepRap LCD (st7920) -> fully_compatible
print("\n[2] Test Case: ATmega (RAMPS) + standard RepRap LCD (st7920)")
res2 = classify_hardware_combination("st7920", "generic-ramps.cfg", {})
check("Classified as fully_compatible", res2["compatibility_class"] == "fully_compatible")

# 3. STM32 + mini12864 (uc1701) -> fully_compatible
print("\n[3] Test Case: STM32 (BTT Octopus) + mini12864 (uc1701)")
res3 = classify_hardware_combination("uc1701", "generic-bigtreetech-octopus.cfg", {})
check("Classified as fully_compatible", res3["compatibility_class"] == "fully_compatible")

# 4. CR6-SE + t5uid1 -> unsafe
print("\n[4] Test Case: CR-6 SE + t5uid1 display")
res4 = classify_hardware_combination("t5uid1", "printer-creality-cr6-se.cfg", {})
check("Classified as unsafe", res4["compatibility_class"] == "unsafe")
check("Recommendation is disconnect", res4["recommendation"] == "disconnect")

# 5. Artillery + tft_serial -> compatible_with_adapter
print("\n[5] Test Case: Artillery + tft_serial display")
res5 = classify_hardware_combination("tft_serial", "printer-artillery-sidewinder-x1.cfg", {})
check("Classified as compatible_with_adapter", res5["compatibility_class"] == "compatible_with_adapter")

# 6. Board without EXP1/EXP2 + EXP-required display -> compatible_with_adapter
print("\n[6] Test Case: Duet2 (no EXP1/EXP2) + ST7920 (requires EXP1_EXP2)")
res6 = classify_hardware_combination("st7920", "generic-duet2.cfg", {})
check("Classified as compatible_with_adapter", res6["compatibility_class"] == "compatible_with_adapter")
check("Includes adapter board mod", any("adapter board" in m.lower() or "breakout board" in m.lower() or "wiring harness" in m.lower() for m in res6["required_modifications"]))

print("\n" + "=" * 65)
print("RESULT:", "\033[92mALL TESTS PASSED\033[0m" if ok else "\033[91mSOME TESTS FAILED\033[0m")
print("=" * 65)

sys.exit(0 if ok else 1)
