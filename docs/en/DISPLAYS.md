# 🖥️ Display Compatibility Guide

> **KACE philosophy:** detect → classify → inform → recommend.
> KACE never automatically modifies or disables your display configuration.

---

## Why does this matter?

Klipper is a **web-first** firmware. Its primary interfaces are [Mainsail](https://docs.mainsail.xyz/) and [Fluidd](https://docs.fluidd.xyz/) — browser-based dashboards that provide full printer control from any phone, tablet, or PC.

Many OEM printers ship with touchscreen displays that were designed **specifically for Marlin firmware**. These screens use proprietary protocols, vendor-specific serial bridges, or custom display firmware that assumes Marlin's command set. When Klipper replaces Marlin, these displays often stop working — not because Klipper is broken, but because the screen was never designed for it.

> **This is not a KACE bug.** It is an OEM display compatibility limitation.

---

## Compatibility Status Definitions

| Status | Meaning |
|--------|---------|
| 🟢 **SUPPORTED** | Known working natively under Klipper — no concerns |
| 🟡 **PARTIAL** | Works with limitations; reduced or missing menu functionality |
| 🔴 **UNSUPPORTED** | Not compatible; may cause black screen, boot loop, or serial conflicts |
| ⬜ **UNTESTED** | No compatibility data available; outcome unknown |

---

## Display Type Reference

### 🟢 Supported Displays

These are natively supported by Klipper with no additional configuration:

| Display Type | Examples | Notes |
|---|---|---|
| **Standard 12864 LCD** | Ender 3 stock LCD, RepRapDiscount Smart LCD | Fully supported |
| **mini12864** | BTT mini12864, SKR 1.4 kit display | Fully supported |
| **ST7920** | RepRapDiscount Smart LCD controller | Fully supported |
| **UC1701** | mini12864 variants | Fully supported |
| **HD44780** | 20×4 character LCD | Fully supported |
| **SSD1306 OLED** | Various small OLED modules | Fully supported |

---

### 🟡 Partial Support

These displays may work at a basic level but will likely have missing menus, reduced functionality, or minor issues:

| Display Type | Common Printers | Known Limitation |
|---|---|---|
| **Serial TFT (tft_serial)** | Artillery Sidewinder, Artillery Genius, Artillery Hornet, Ender 6, CR-10 Smart | Serial menus typically non-functional under Klipper |
| **DWIN / DGUS (dwin_set)** | Various | Requires matching community display firmware — version-sensitive |

**Recommended approach for partial support:** use the web UI (Mainsail/Fluidd) as your primary interface. The display may show basic status but is not reliable for menu navigation.

---

### 🔴 Unsupported Displays

These displays are not compatible with Klipper without significant community modifications:

| Display Type / Section | Common Printers | Issue |
|---|---|---|
| **t5uid1 (DGUS protocol)** | Creality CR-6 SE | Proprietary Creality OEM firmware — Klipper has no built-in support |
| **Neopixel / WS2812** | Various | Outside KACE's current configuration scope |
| **Dotstar / APA102** | Various | Outside KACE's current configuration scope |
| **SX1509 GPIO expander** | Some MKS boards | Not supported by KACE's config engine |

---

## OEM Printer Compatibility

### Creality CR-6 SE

**Status:** 🔴 UNSUPPORTED

The CR-6 SE uses a proprietary Creality DGUS touchscreen running OEM firmware designed exclusively for Marlin. Klipper has no built-in support for the `t5uid1` / DGUS protocol.

**Common symptoms when display remains connected:**
- Black screen on boot
- Boot loop / Klipper fails to start
- Serial communication conflicts

**Recommended action:** Physically disconnect the display ribbon cable from the mainboard.

**Community resource:** The open-source community has developed custom DGUS display firmware for the CR-6 SE. Search: *"CR-6 SE Klipper DGUS community firmware"*.

---

### Artillery Sidewinder X1 / X2

**Status:** 🟡 PARTIAL

Uses a serial TFT display designed for Marlin's TFT protocol. Under Klipper:
- The display may show basic printer status
- Navigation menus will typically not function
- Some users report no issues; others report serial conflicts

**Recommended action:** Use Mainsail or Fluidd as your primary interface. Keep the display connected if desired but do not rely on it for control.

---

### Artillery Genius

**Status:** 🟡 PARTIAL

Same serial TFT situation as the Sidewinder. Web UI is recommended for full control.

---

### Artillery Hornet

**Status:** 🟡 PARTIAL

Same serial TFT situation. Web UI recommended.

---

## Common Symptoms and Causes

| Symptom | Likely Cause |
|---------|-------------|
| Black screen after Klipper starts | Display firmware is incompatible (e.g., t5uid1 on CR-6 SE) |
| Display shows "No Printer Attached" | Serial TFT is not receiving Marlin-formatted responses |
| Klipper fails to connect to MCU | Display is occupying or conflicting with the serial port |
| Menu is frozen or unresponsive | TFT serial bridge is not receiving expected Marlin G-code responses |
| Boot loop / Klipper restart cycle | Display firmware is resetting the MCU via DTR/reset line |
| Partial menus but some entries missing | TFT firmware only partially handles Klipper's output format |

---

## Recommended Approach for Beginners

1. **Disconnect the OEM touchscreen** (especially for CR-6 SE, Artillery printers)
2. **Install Mainsail or Fluidd** on your Raspberry Pi
3. **Access your printer from any device** on your local network
4. Enjoy a better interface than the OEM screen provided

Mainsail and Fluidd offer:
- Real-time printer status and temperature graphs
- Gcode file management and upload
- Print history and statistics
- Webcam integration
- Full macro and configuration editing
- Mobile-friendly responsive UI

---

## For Advanced Users

If you want to experiment with OEM display compatibility:

- **DGUS/DWIN displays:** Look for community Klipper display firmware for your specific display model. The firmware version must match your display hardware exactly.
- **Serial TFT displays:** Some community members have had partial success by configuring Klipper's `[respond]` and using custom G-code forwarding. This is experimental.
- **Neopixel/RGB:** Klipper natively supports neopixel via the `[neopixel]` section — KACE simply does not configure it automatically. You can add it manually after generation.

KACE will never remove or disable your display configuration sections. You are free to experiment.

---

## Future: Known-Good Display Profiles

KACE's display database (`data/displays.yaml`) is designed for future expansion toward validated display profiles for known-good setups. Planned additions as hardware testing is completed:

- mini12864 (BTT) — standard support
- RepRapDiscount Full Graphic Smart Controller
- Fysetc Mini 12864 Panel
- Selected community DGUS mods

---

## See Also

- [Klipper Display Configuration](https://www.klipper3d.org/Config_Reference.html#display) — official reference
- [Mainsail Documentation](https://docs.mainsail.xyz/)
- [Fluidd Documentation](https://docs.fluidd.xyz/)
- [KACE Testing Guide](TESTING.md)
- [KACE architecture summary](../../README.md#architecture)
