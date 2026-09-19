<p align="center">
  <img src="docs/assets/kace_banner.png" width="1000" alt="KACE — Klipper Automated Configuration Ecosystem">
</p>

<h1 align="center">KACE</h1>

<p align="center">
  <strong>Klipper Automated Configuration Ecosystem</strong><br>
  A guided Linux CLI that helps turn printer hardware choices into reviewable Klipper configuration and firmware artifacts.
</p>

<p align="center">
  <a href="https://github.com/3D-uy/KACE/actions/workflows/ci.yml"><img src="https://github.com/3D-uy/KACE/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI status"></a>
  <a href="CHANGELOG.md"><img src="https://img.shields.io/badge/version-0.9.4--rc.2-f59e0b?style=flat-square" alt="Version 0.9.4-rc.2"></a>
  <img src="https://img.shields.io/badge/status-hardware_qualification-f59e0b?style=flat-square" alt="Hardware qualification pending">
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&amp;logo=python&amp;logoColor=white" alt="Python 3.11 or newer">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-GPL--3.0-2ea44f?style=flat-square" alt="GPL-3.0 license"></a>
</p>

<p align="center">
  <strong>English</strong> · <a href="docs/es/README.md">Español</a> · <a href="docs/pt/README.md">Português</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Linux-host-FCC624?style=for-the-badge&amp;logo=linux&amp;logoColor=black" alt="Linux host">
  <img src="https://img.shields.io/badge/Raspberry_Pi-ready-A22846?style=for-the-badge&amp;logo=raspberrypi&amp;logoColor=white" alt="Raspberry Pi ready">
  <img src="https://img.shields.io/badge/Klipper-configuration_%26_firmware-F2A900?style=for-the-badge" alt="Klipper configuration and firmware">
  <img src="https://img.shields.io/badge/Moonraker-deployment-2471A3?style=for-the-badge" alt="Moonraker deployment">
</p>

> [!IMPORTANT]
> **0.9.4-rc.2 is a controlled test candidate.** Automated configuration and firmware checks pass, but physical qualification is still in progress. Read the [hardware testing guide](docs/HARDWARE_TESTING.md) before connecting a controller or powering a printer.

## Start here

| I want to… | Go to… |
| --- | --- |
| Set up a new Raspberry Pi from Windows | [KACE Studio](https://github.com/3D-uy/KACE-studio) |
| Install KACE on an existing Linux printer host | [Quick start](#quick-start) |
| Check whether my controller has an exact contract | [Supported controller contracts](#supported-controller-contracts) |
| Understand deployment and recovery behavior | [Deployment guide](docs/en/DEPLOYMENT.md) |
| Prepare a controlled hardware test | [Hardware testing guide](docs/HARDWARE_TESTING.md) |
| Report a problem or contribute | [Issues](https://github.com/3D-uy/KACE/issues) · [Contributing](docs/en/CONTRIBUTING.md) |

## One ecosystem, two tools

```text
KACE Studio on Windows  →  Raspberry Pi bootstrap  →  KACE on Linux  →  Klipper commissioning
 image · first boot · SSH      pinned contract        config · MCU       physical validation
```

| Component | Owns |
| --- | --- |
| 🪟 **[KACE Studio](https://github.com/3D-uy/KACE-studio)** | Raspberry Pi imaging, first-boot settings, host discovery, SSH/SFTP and bootstrap progress. |
| 🍓 **Bootstrap** | Installs the selected Klipper host stack from an immutable KACE/Studio contract. |
| 🧩 **KACE** | Collects printer choices, resolves exact board contracts and creates or deploys Klipper artifacts. |
| 🔧 **Klipper + operator** | Runs the printer and completes electrical, thermal, homing and motion commissioning. |

Studio and KACE are separate repositories joined by the versioned `scripts/bootstrap.sh` contract. Studio provisions the host; KACE performs printer-specific configuration on that host.

## What KACE does

| | Capability | What you get |
| --- | --- | --- |
| 🧭 | Guided setup | An interactive workflow in English, Spanish or Portuguese for boards, motion, endstops, heaters, sensors, probes, displays and host software. |
| 🧠 | Exact profiles | Maintained board contracts select the MCU, bootloader, connection and permitted deployment route. |
| 📄 | Reviewable output | Klipper configuration, includes and macros are generated under `~/kace/` for review before activation. |
| ⚙️ | Reproducible firmware | Optional firmware builds record their exact Klipper source, configuration, build identity and artifact checksum. |
| 📦 | Guarded deployment | Local, removable-media, SSH/SFTP and Moonraker paths validate changes and preserve recovery information. |
| 🖥️ | Display checks | Supported display combinations receive compatibility, voltage and pin-conflict checks before configuration is emitted. |

KACE currently supports **Cartesian** and **CoreXY** generation, with no probe, BLTouch, CR Touch, inductive and custom probe flows. Unsupported or contradictory choices stop with an explanation instead of producing a guessed configuration.

## Quick start

**New printer host**

Use [KACE Studio](https://github.com/3D-uy/KACE-studio) on Windows to prepare the Raspberry Pi, inject first-boot settings, discover it and launch the pinned provisioning flow.

**Existing Debian-family host**

The public installer is pinned to one reviewed commit and verified before execution:

```bash
KACE_COMMIT='a0cc0f542d6c61e38de5bb5a414e48dadba07df3'; KACE_INSTALL_SHA256='de7db74da6f6261bf28fa329067f9d3424bc3e5abde5db4dd91c3f66861f3500'; installer=$(mktemp); trap 'rm -f "$installer"' EXIT; curl -fsSLo "$installer" "https://raw.githubusercontent.com/3D-uy/KACE/${KACE_COMMIT}/install.sh" && printf '%s  %s\n' "$KACE_INSTALL_SHA256" "$installer" | sha256sum -c - && KACE_SOURCE_REF="$KACE_COMMIT" KACE_EXPECTED_COMMIT="$KACE_COMMIT" bash "$installer"
```

Then run:

```bash
kace
```

> [!WARNING]
> Keep the commit and SHA-256 together. Only update them from a reviewed release source. The installer verifies the download, checked-out commit and installed runtime identity.

<details>
<summary><strong>Run from a source checkout</strong></summary>

```bash
git clone https://github.com/3D-uy/KACE.git
cd KACE
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --require-hashes -r requirements.txt
python kace.py
```

Use `python kace.py --help` to see the available CLI options.

</details>

## Supported platforms

| Layer | Current support | Boundary |
| --- | --- | --- |
| Host | Debian-family Linux, normally Raspberry Pi; Python 3.11+ | The actual OS image and host still require qualification. |
| Firmware | Klipper configuration and pinned-source MCU builds | KACE does not generate Marlin firmware. |
| Motion | Cartesian and CoreXY | Other kinematics are outside current generation coverage. |
| Deployment | Local/removable media, SSH/SFTP and Moonraker paths where the selected contract permits them | Unsafe replacement and ambiguous targets stop for review. |
| Web UI | Mainsail or Fluidd selection through the bootstrap | These projects evolve independently from KACE. |

### Supported controller contracts

The table lists exact repository contracts, not generic support inferred from an MCU family.

<p align="center">
  <img src="https://img.shields.io/badge/STM32-exact_profiles-03234B?style=flat-square&amp;logo=stmicroelectronics&amp;logoColor=white" alt="Exact STM32 profiles">
  <img src="https://img.shields.io/badge/LPC176x-exact_profiles-0091BD?style=flat-square&amp;logo=arm&amp;logoColor=white" alt="Exact LPC176x profiles">
  <img src="https://img.shields.io/badge/RP2040-exact_profile-A22846?style=flat-square&amp;logo=raspberrypi&amp;logoColor=white" alt="Exact RP2040 profile">
  <img src="https://img.shields.io/badge/AVR-exact_profile-00979D?style=flat-square&amp;logo=arduino&amp;logoColor=white" alt="Exact AVR profile">
</p>

| Controller | MCU variant(s) in contract | Firmware route | Contract status |
| --- | --- | --- | --- |
| BIGTREETECH SKR Mini E3 v3.0 | STM32G0B1 | SD card | Runtime-supported |
| BIGTREETECH SKR V1.4 / V1.4 Turbo | LPC1768 / LPC1769 | SD card | Runtime-supported |
| BIGTREETECH SKR Pico v1.0 | RP2040 | BOOTSEL mass storage | Runtime-supported |
| MKS Robin Nano V3 | STM32F407 | SD card | Runtime-supported |
| Creality v4.2.7 | STM32F103 | SD card | Runtime-supported default target; provisional alternate UART target |
| Printrboard rev B–D | AT90USB1286 | AVRDUDE | Provisional |
| BIGTREETECH Octopus Pro v1.0 | STM32F446 / STM32F429 / STM32H723 | Prepare only | Configuration-only |

The status labels are deliberate:

- **Runtime-supported:** executable contract with automated coverage.
- **Provisional:** narrower path that still needs qualification.
- **Configuration-only / prepare only:** KACE can prepare reviewed settings or an artifact, but does not claim to flash the controller.

Every status still requires physical validation of the exact board revision, wiring and bootloader.

## Safety and recovery model

- Generated configuration is reviewed before activation and kept separate from the source tree in `~/kace/`.
- Local activation uses cooperative locking, a final content comparison and atomic replacement per file. Do not save configuration through Mainsail, SSH or another tool during deployment: external editors that ignore the lock can still race with replacement. See the [publication contract](docs/en/DEPLOYMENT.md#conditional-publication-and-final-readiness-gates).
- Remote Moonraker uploads and existing-file SFTP/offline-export replacement remain blocked; unsupported plans preserve current files and save a proposal for manual application.
- Firmware success requires the expected build identity and physical MCU evidence. A different controller of the same model does not satisfy that check.
- Removable-media and powered flashing flows separate preparation, operator action, re-enumeration and verification; pending work is never reported as success.
- Automatic recovery preserves live files and snapshots when restoration cannot be proven safe; explicit snapshot restoration remains operator-owned.
- Recovery may require manual action. Follow the recorded state instead of repeating a flash or deployment blindly.

> [!CAUTION]
> KACE cannot verify wiring or mechanical safety. Disconnect heaters and motors when appropriate, confirm pin assignments against the exact board revision, and complete Klipper's controlled first-start checks before normal operation.

## Current status

| Item | State |
| --- | --- |
| Project version | `0.9.4-rc.2` from `VERSION` |
| Release stage | Pre-1.0 controlled test candidate |
| Automated validation | Unit/regression tests, schema checks, snapshots, pinned-Klipper matrices and representative containerized MCU builds |
| Physical qualification | Pending across the supported controller matrix |
| Backward compatibility | `main` may still change before 1.0 |

Klipper, controller definitions and dashboards can change independently. Pinned tests catch software incompatibilities; electrical, thermal and mechanical safety still require physical checks.

## Documentation and support

| Topic | Resource |
| --- | --- |
| Deployment, activation and recovery | [Deployment guide](docs/en/DEPLOYMENT.md) |
| Displays and electrical compatibility | [Display guide](docs/en/DISPLAYS.md) |
| Controlled hardware qualification | [Hardware testing guide](docs/HARDWARE_TESTING.md) |
| Test suites and matrices | [Testing guide](docs/en/TESTING.md) |
| Architecture | [Architecture guide](docs/en/ARCHITECTURE.md) |
| Build modes | [Build modes](docs/build_modes.md) |
| Releases and history | [Release guide](docs/RELEASE.md) · [Changelog](CHANGELOG.md) |
| Security | [Security policy](SECURITY.md) |
| Community | [Issues](https://github.com/3D-uy/KACE/issues) · [Code of conduct](CODE_OF_CONDUCT.md) |

### Troubleshooting

| Symptom | First check |
| --- | --- |
| Installer checksum or commit verification fails | Stop. Obtain the commit/SHA pair again from the reviewed release source; do not bypass verification. |
| KACE saves a proposal instead of replacing a config | The selected transport cannot safely guard an existing file. Review the proposal and follow the [deployment guide](docs/en/DEPLOYMENT.md). |
| Firmware remains pending or enters recovery | Follow the stored instructions and keep the artifact and manifest together. Preparing media does not complete a flash. |
| A board or MCU is missing or ambiguous | Confirm the exact board revision and processor marking. Do not choose a profile solely because the MCU family matches. |

## Development

Run the narrow validation relevant to a change:

```bash
python tests/run_tests.py --verbose
python tests/run_tests.py --yaml-check
python tests/matrix/run_matrix.py --profile quick
```

Full matrices, upstream sweeps and containerized firmware builds are maintainer checks. KACE itself runs directly on the printer host. See the [testing guide](docs/en/TESTING.md) for the complete validation workflow.

## Contributing

Read the [contributor guide](docs/en/CONTRIBUTING.md), [security policy](SECURITY.md) and [code of conduct](CODE_OF_CONDUCT.md) before opening a change. Keep changes scoped and add the narrowest regression coverage that demonstrates the behavior.

## License

KACE is licensed under the [GNU General Public License v3.0](LICENSE).
