<p align="center">
  <img src="docs/assets/kace_banner.png" width="1000"><br>
</p>

<h1 align="center">🚀 KACE — Klipper Automated Configuration Ecosystem</h1>

<p align="center">
  <a href="https://github.com/3D-uy/kace/actions/workflows/ci.yml">
    <img src="https://github.com/3D-uy/kace/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI">
  </a>
  <img src="https://img.shields.io/badge/version-v0.9.0-blue?style=flat-square" alt="Version">
  <img src="https://img.shields.io/badge/configs%20validated-192-brightgreen?style=flat-square" alt="Configs Validated">
  <img src="https://img.shields.io/badge/platform-Linux%20%7C%20Raspberry%20Pi-green?style=flat-square" alt="Platform">
  <img src="https://img.shields.io/github/license/3D-uy/KACE?style=flat-square" alt="License">
</p>

<p align="center">
🌐 <strong>Language</strong><br>
🇺🇸 English | 🇪🇸 <a href="docs/es/README.md">Español</a> | 🇧🇷 <a href="docs/pt/README.md">Português</a>
</p>

---

## ⚡ Install Klipper without the headaches

KACE automates the entire Klipper setup process — from hardware detection to firmware compilation and ready-to-use configuration generation.

👉 Fewer errors  
👉 Less time  
👉 More printing

---

## 🧠 What is KACE?

An **intelligent configuration and firmware engine** that:

- 🔍 Automatically detects your hardware (MCU)
- 📦 Fetches official Klipper configurations from GitHub
- ⚙️ Generates a clean, ready-to-use `printer.cfg`
- 🔥 Compiles firmware (`klipper.bin` / `.uf2` / `.hex`)
- 🧭 Guides you interactively only when strictly necessary
- 🌐 Works in English, Spanish, and Portuguese

---

## ⚡ One-Line Install

```bash
bash <(curl -s https://raw.githubusercontent.com/3D-uy/KACE/main/install.sh)
```

> Installs all dependencies, clones the repository (shallow + sparse), and sets up the global `kace` command automatically.

---

## 📋 Requirements

✔ Raspberry Pi running Mainsail OS / FluiddPI (Klipper + Moonraker pre-installed)  
✔ SSH access to your Pi

❌ You **no longer** need to:

- Manually compile firmware
- Hand-craft `printer.cfg` files

---

## 🎬 Documentation

| Guide | Link |
|-------|------|
| Testing Guide | [`docs/en/TESTING.md`](docs/en/TESTING.md) |
| Contributing | [`docs/en/CONTRIBUTING.md`](docs/en/CONTRIBUTING.md) |
| Release Engineering | [`docs/RELEASE.md`](docs/RELEASE.md) |
| Display Compatibility 🖥️ | [`docs/en/DISPLAYS.md`](docs/en/DISPLAYS.md) |
| Pi Imager Setup 🇺🇸 | [`docs/en/pi_imager.md`](docs/en/pi_imager.md) |
| Klipper Install 🇺🇸 | [`docs/en/Klipper_install.md`](docs/en/Klipper_install.md) |
| **Full Sweep Results 📊** | [`SWEEP_RESULTS.md`](SWEEP_RESULTS.md) |
| Español 🇪🇸 | [`docs/es/README.md`](docs/es/README.md) |
| Português 🇧🇷 | [`docs/pt/README.md`](docs/pt/README.md) |


---

## 🟢 Validation Status

KACE has been validated against the **complete official Klipper configuration library** using its automated regression framework.

**Latest full sweep — 192 configs tested against [Klipper master](https://github.com/Klipper3d/klipper/tree/master/config):**

| Result | Count | Meaning |
|--------|-------|---------|
| ✅ **PASS** | **172** | Full parse + config generation succeeded |
| 🔵 **UNSUPPORTED** | **20** | Config uses sections outside KACE's current scope (neopixel, adxl345) |
| 🟠 **SAFE\_ABORT** | **0** | — |
| 🔴 **FAILURE** | **0** | **Zero hard crashes** |

- **Zero Python exceptions** across all 192 official configs
- **Zero template failures** — every parseable config generates cleanly
- **Zero parser regressions** — deterministic output on every run
- **10 generation warnings** — all delta-kinematics printers where Klipper itself ships `TODO` endstop pins by design

Unsupported configs contain features outside KACE's current scope:
RGB/neopixel controllers, SX1509 GPIO expanders, or ADXL345 accelerometers.
KACE **reports these gracefully** instead of crashing.

📄 **[View the complete sweep results → SWEEP_RESULTS.md](SWEEP_RESULTS.md)**  
Includes a full per-config breakdown of all 192 boards, printers, and displays.

> Run the sweep yourself: `python3 tests/run_tests.py --full-klipper-sweep`

---

## 🧪 Automated Testing

KACE ships with a production-grade test framework built entirely on the Python standard library — **zero test dependencies**.

| What | How |
|------|-----|
| Unit tests | Derivation logic, YAML loading, BLTouch injection, offline deployer |
| Snapshot regression | Golden `.cfg` files locked per board — fails on any character diff |
| YAML integrity | Schema validation + pattern precedence check on every run |
| Full config sweep | 192+ official Klipper configs parsed and classified on every `main` push |
| CI pipeline | GitHub Actions — 5 stages, concurrency cancellation, merge blocking |

```
Current status: 59/59 tests passing ✅
```

```bash
python3 tests/run_tests.py                   # full suite
python3 tests/run_tests.py --yaml-check      # YAML integrity only
python3 tests/run_tests.py --full-klipper-sweep  # 192-config sweep
```

See [`docs/en/TESTING.md`](docs/en/TESTING.md) for the full testing guide.

---

## 🏗️ Architecture Highlights

- **YAML-driven hardware database** — add a new board with a single YAML edit, no Python changes
- **Modular firmware derivation** — MCU → Kconfig parameters via ordered pattern matching
- **Automatic fallback recovery** — every data load has a hardcoded fallback; YAML failures never crash production
- **Sparse + shallow installer** — minimal download footprint on Raspberry Pi hardware
- **Lazy optional dependencies** — SSH support installs on first use, not at install time
- **Deterministic config generation** — Jinja2 rendering is snapshot-protected and reproducible
- **4-code sweep classification** — `PASS / SAFE_ABORT / UNSUPPORTED / FAILURE` for clear diagnostics

See [`docs/en/ARCHITECTURE.md`](docs/en/ARCHITECTURE.md) for the full reference.

---

## 🛠️ Key Features

| Feature | Description |
| --- | --- |
| 🔍 **MCU Auto-detection** | Identifies your connected board via USB/serial |
| 🧠 **Intelligent Engine** | Derives firmware config without manual `make menuconfig` |
| ⚙️ **Config Generator** | Generates a clean `printer.cfg` from official Klipper data |
| 🔥 **Firmware Builder** | Compiles `klipper.bin` / `.uf2` / `.hex` automatically |
| 🧪 **Pre-validation** | Catches TODO pins and config errors before they reach your printer |
| 🌐 **GitHub Scraper** | Always pulls from official, up-to-date Klipper configurations |
| 💻 **Interactive CLI** | Guided wizard in EN / ES / PT with ANSI colour UI |
| 📡 **System Dashboard** | Detects Klipper, Moonraker, Mainsail, Fluidd, Crowsnest on startup |

---

## 🧭 How it works

```
1. 🔍 Detect MCU via USB/serial
2. 📦 Fetch official Klipper config for your board
3. 🧠 Derive firmware parameters (MCU family → Kconfig)
4. 💬 Ask only what can't be safely assumed
5. ⚙️ Generate printer.cfg (Jinja2, validated, TODO-free)
6. 🔥 Compile firmware automatically
7. 📁 Deploy to ~/kace/ (or USB / SSH)
```

---

## 📦 Output

```
~/kace/
├── printer.cfg          # Ready-to-use Klipper configuration
└── klipper.bin          # Compiled firmware (or .uf2 / .hex)
```

---

## 🚀 Next Steps

1. Flash firmware to your board (SD card / USB)
2. Upload `printer.cfg` to Klipper / Moonraker
3. Restart:

```bash
sudo reboot
```

---

## 🙌 Contribute & Feedback

KACE evolves with the community:

* 🐛 [Report bugs](https://github.com/3D-uy/kace/issues)
* 💡 Suggest improvements
* 🤝 [Contribute — read the guide](docs/en/CONTRIBUTING.md)

---

## ⚠️ Disclaimer

KACE is an open-source tool designed to simplify Klipper configuration.

By using this software, you acknowledge that you do so **at your own risk**.  
The author assumes **no responsibility for hardware damage, misconfiguration, or unexpected behavior** resulting from the generated configuration.

👉 Always review the generated `printer.cfg` before printing.  
👉 Verify firmware before flashing.

---

## 🗑️ Uninstall

```bash
sudo rm -f /usr/local/bin/kace   # or: rm -f ~/.local/bin/kace
rm -rf ~/kace
```

---

## 📜 License

KACE is licensed under GPL-3.0 🛠️

For commercial use, distribution in paid products, or rebranding, please contact the author.  
The "KACE" name and branding may not be used in commercial products without permission.

---

<p align="center">

⭐ If you like this project, give it a star  
🚀 Built to simplify Klipper

</p>
