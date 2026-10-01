![KACE — Klipper Automated Configuration Ecosystem](docs/assets/kace_banner.png)

# KACE

### Klipper Automated Configuration Ecosystem

**Guided printer configuration, firmware preparation and deployment for Klipper.**

[![KACE version 0.9.4-rc.2](https://img.shields.io/badge/KACE-0.9.4--rc.2-e88c30?style=flat-square)](VERSION)
[![Status: pre-release](https://img.shields.io/badge/status-pre--release-d29b32?style=flat-square)](#project-status)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](docs/en/INSTALLATION.md)
[![License: GPLv3](https://img.shields.io/badge/license-GPLv3-2d718f?style=flat-square)](LICENSE)
[![GitHub Actions: KACE CI](https://img.shields.io/github/actions/workflow/status/3D-uy/kace/ci.yml?branch=main&style=flat-square&label=tests&logo=githubactions&logoColor=white)](https://github.com/3D-uy/kace/actions/workflows/ci.yml)<br>
[![Host: Linux](https://img.shields.io/badge/host-Linux-454545?style=flat-square&logo=linux&logoColor=white)](docs/en/INSTALLATION.md)
[![Host: Raspberry Pi](https://img.shields.io/badge/host-Raspberry_Pi-A22846?style=flat-square&logo=raspberrypi&logoColor=white)](https://www.raspberrypi.com/software/)
[![For Klipper](https://img.shields.io/badge/for-Klipper-e88c30?style=flat-square)](https://www.klipper3d.org/)
[![API: Moonraker](https://img.shields.io/badge/API-Moonraker-5965a8?style=flat-square)](https://moonraker.readthedocs.io/en/latest/)
[![GitHub stars](https://img.shields.io/github/stars/3D-uy/kace?style=flat-square&logo=github&label=stars&color=e3b341)](https://github.com/3D-uy/kace)

🌐 [English](README.md) · [Español](docs/es/README.md) · [Português](docs/pt/README.md)

KACE guides you through your printer's hardware choices to generate and review a Klipper configuration.
Its terminal wizard prepares MCU firmware where supported and takes you through applying and verifying the installation.

[Quick start](#quick-start) · [Hardware support](#hardware-and-platforms) · [KACE Studio](#kace-studio) · [Documentation](#documentation)

<a id="what-kace-does"></a>

## ✨ What KACE does

| Capability | What you get |
| --- | --- |
| 🔌 **Select hardware** | Board/MCU selection, motors, probes, thermistors and fans. |
| 📄 **Generate configuration** | `printer.cfg` and applicable macros in `~/kace/`, built from reviewed profiles and your answers. |
| ⚙️ **Prepare firmware** | Builds for declared MCU targets, with the available delivery method and any required manual steps. |
| 🔎 **Review changes** | Configuration differences before application, with supported calibration values and user-owned sections preserved. |
| ✅ **Apply and verify** | Host deployment, activation checks and required firmware identity checks. |

<a id="a-look-at-the-wizard"></a>
<a id="guided-setup"></a>

## 🧙 Guided setup

The terminal wizard offers **English, Spanish and Portuguese**, with **Beginner** and **Advanced** modes.

> **Hardware selection** → **Guided configuration** → **Generate Klipper config**<br>
> → **Build MCU firmware** → **Review** → **Apply** → **Verify**

Firmware steps depend on the selected supported target and workflow.

<!-- Insert a real wizard/configuration-review screenshot here: docs/assets/kace-wizard.png.
     Include descriptive alt text and the captured KACE version. Do not use a mockup as a product screenshot. -->

<a id="quick-start"></a>

## 🚀 Quick start

On an existing **Raspberry Pi or Linux printer host**, open a terminal or connect over SSH.
You need **Python 3.11+**, Git, Bash, Python's venv support and internet access.
The installer may request sudo for missing system dependencies and the `kace` command.

```bash
git clone https://github.com/3D-uy/KACE.git kace-source &&
cd kace-source &&
KACE_SOURCE_REF="$(git rev-parse HEAD)" bash install.sh
```

This installs the revision you just cloned into `~/kace/` and opens KACE.
Run `kace` to open it again. This path follows the repository's current default branch; use the verified option below for the fixed candidate.

After reviewing the changes, confirm application and activation, then follow the [hardware checks](docs/HARDWARE_TESTING.md) before printing.

Applying and verifying the configuration requires a working Klipper/Moonraker host.
For a fresh Pi, start with [KACE Studio](#kace-studio) or the [manual host preparation guide](docs/en/INSTALLATION.md).

<a id="verified-installation-pinned"></a>

### 🔒 Verified / pinned installation

For a fixed candidate with installer checksum verification, use the command below.
It keeps the existing pinned reference and may differ from the current source.

<details>
<summary>Show the pinned installer command</summary>

Requires `curl` and `sha256sum`. Review the script before running it.

```bash
KACE_COMMIT='b7988b57b5fc80fbc55c3d1326768289dbccb179'
KACE_INSTALL_SHA256='de7db74da6f6261bf28fa329067f9d3424bc3e5abde5db4dd91c3f66861f3500'
installer=$(mktemp)
trap 'rm -f "$installer"' EXIT
curl -fsSLo "$installer" "https://raw.githubusercontent.com/3D-uy/KACE/${KACE_COMMIT}/install.sh" &&
printf '%s  %s\n' "$KACE_INSTALL_SHA256" "$installer" | sha256sum -c - &&
KACE_SOURCE_REF="$KACE_COMMIT" KACE_EXPECTED_COMMIT="$KACE_COMMIT" bash "$installer"
```

</details>

<a id="kace-studio"></a>

## 🖥️ KACE Studio

[KACE Studio](https://github.com/3D-uy/KACE-studio) is the companion desktop app for preparing a Raspberry Pi from **Windows 10/11**.

- Write a Pi image to SD/USB and configure hostname, account, network and SSH for first boot.
- Discover the Pi and connect through an SSH workspace.
- Browse and download files over SFTP, then continue KACE setup on the Pi.

**Studio prepares the host; KACE configures the printer.** Studio requires Microsoft Edge WebView2 Runtime and is also a prerelease.
See its [setup instructions](https://github.com/3D-uy/KACE-studio#quick-start) for installation and current image/platform choices.

<a id="hardware-and-platforms"></a>

## 🔌 Hardware and platforms

| Area | Current scope |
| --- | --- |
| KACE host | Raspberry Pi / Linux with Python 3.11+; configuration activation uses Klipper and Moonraker. |
| Printer configuration | Cartesian and CoreXY, a primary extruder and heated bed, with supported motor, probe and fan paths. |
| Desktop provisioning | KACE Studio on Windows 10/11; Pi model and OS choices are validated by Studio. |

The current [board contracts](data/board_contracts/v1/) declare firmware runtime paths for these exact targets:

| Board | MCU variant | Host connection |
| --- | --- | --- |
| BTT SKR Mini E3 v3.0 | STM32G0B1 | Native USB |
| BTT SKR v1.4 / v1.4 Turbo | LPC1768 / LPC1769, respectively | Native USB |
| BTT SKR Pico v1.0 | RP2040 | Native USB |
| Creality v4.2.7 | STM32F103 | USB serial bridge, MCU USART1 |
| MKS Robin Nano V3 | STM32F407 | Native USB |

These are implemented software paths, **not a list of physically certified printers**.
Board revision, MCU, wiring, bootloader and delivery method must match the selected target.
Other entries may be provisional, configuration-only or preparation-only; a searchable Klipper profile does not establish full support.
Check the [support scope](docs/en/SUPPORT_SCOPE.md) and [firmware delivery profiles](data/firmware_deployments.yaml) for the boundaries.

<a id="project-status"></a>

## 🧪 Project status

KACE is **pre-1.0**. See [VERSION](VERSION) for the source version, [CHANGELOG](CHANGELOG.md) for changes and [ROADMAP](ROADMAP.md) for pending work.

- Physical hardware validation is still pending; sensors, endstops, motion and heating need commissioning on your printer.
- Multiple extruders, IDEX/toolchangers and general migration of arbitrary Klipper profiles are outside the current scope.
- Guided active display generation is not yet available for a qualified board/display pair; see [display support](docs/en/DISPLAYS.md).
- Some remote configuration changes require manual application. KACE covers initial setup and unfinished resumes; it does not monitor later edits.

<a id="documentation"></a>

## 📚 Documentation

| Looking for… | Read |
| --- | --- |
| Host preparation, installation and running from source | [Installation guide](docs/en/INSTALLATION.md) |
| Configuration review, deployment, concurrent edits and recovery | [Deployment guide](docs/en/DEPLOYMENT.md) |
| Detailed hardware and feature boundaries | [Support scope](docs/en/SUPPORT_SCOPE.md) · [Displays](docs/en/DISPLAYS.md) |
| Physical checks before using the printer | [Hardware testing](docs/HARDWARE_TESTING.md) |
| Architecture, contracts, tests and firmware build environments | [Development guide](docs/DEVELOPMENT.md) |
| Pinned versions, checksums and release validation | [Release guide](docs/RELEASE.md) |
| Planned work and recent changes | [Roadmap](ROADMAP.md) · [Changelog](CHANGELOG.md) |

<a id="development-and-contributing"></a>

## 🛠️ Development and contributing

Bug reports, documentation improvements and contributions to reviewed hardware support are welcome.
Start with the [development guide](docs/DEVELOPMENT.md) for the source map, environment and relevant tests.
For a bug report, include the KACE revision, host environment, exact board/MCU and reproduction steps, with credentials removed.

Follow the [code of conduct](CODE_OF_CONDUCT.md). Report vulnerabilities through the [security policy](SECURITY.md).

<a id="community--acknowledgements"></a>

## ❤️ Community & Acknowledgements

**Special thanks to the Klipper project and its community** for the firmware, configuration examples, documentation and shared knowledge that make KACE possible.

| Project | Its role in KACE |
| --- | --- |
| [<img src="https://www.klipper3d.org/img/klipper.svg" width="24" height="24" alt="">&nbsp;Klipper](https://www.klipper3d.org/) | The firmware and configuration system KACE targets; reviewed upstream profiles and source underpin configuration generation and MCU builds. |
| [<img src="https://moonraker.readthedocs.io/en/latest/assets/images/favicon.png" width="24" height="24" alt="">&nbsp;Moonraker](https://moonraker.readthedocs.io/en/latest/) | The host API used for configuration access, activation and printer/firmware state checks. |
| [<img src="https://docs.mainsail.xyz/assets/logo.svg" width="24" height="24" alt="">&nbsp;Mainsail](https://docs.mainsail.xyz/) &<br>[<img src="https://docs.mainsail.xyz/assets/logo.svg" width="24" height="24" alt="">&nbsp;MainsailOS](https://docs.mainsail.xyz/mainsailos/) | A dashboard offered by the bootstrap, plus a preconfigured image base used by Studio. |
| [<img src="https://raw.githubusercontent.com/fluidd-core/fluidd/7a75e4857282a24d733540ebf07cf6b1bc7717e9/public/img/icons/favicon-32x32.png" width="24" height="24" alt="">&nbsp;Fluidd](https://docs.fluidd.xyz/) | An alternative dashboard installed by the bootstrap when selected, including its client configuration. |
| [<img src="https://downloads.raspberrypi.com/raspios_armhf/Raspberry_Pi_OS_(32-bit).png" width="24" height="24" alt="">&nbsp;Raspberry&nbsp;Pi](https://www.raspberrypi.com/software/) | The host ecosystem, Raspberry Pi OS image options and Imager for manual host preparation. |
| [<picture><source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/mainsail-crew/crowsnest/436042452f564f3d737e3b980a213f849a8a0562/.github/crowsnest-logo-darkmode.png"><img src="https://raw.githubusercontent.com/mainsail-crew/crowsnest/436042452f564f3d737e3b980a213f849a8a0562/.github/crowsnest-logo-lightmode.png" width="24" height="24" alt=""></picture>&nbsp;Crowsnest](https://docs.mainsail.xyz/crowsnest/) | Optional webcam streaming installed through the bootstrap. |

Report bugs and suggest improvements through [KACE issues](https://github.com/3D-uy/kace/issues).

**KACE is an independent project and is not officially affiliated with or endorsed by Klipper or any other project mentioned here.**

<a id="license"></a>

## 📜 License

KACE is open source under the [GNU GPL v3](LICENSE).
