<p align="center">
  <img src="docs/assets/kace_banner.png" width="1000" alt="KACE banner">
</p>

<h1 align="center">KACE</h1>

<p align="center">
  <strong>Klipper Automated Configuration Ecosystem</strong><br>
  The interactive companion for turning printer choices into reviewable Klipper artifacts.
</p>

<p align="center">
  <a href="https://github.com/3D-uy/KACE/actions/workflows/ci.yml"><img src="https://github.com/3D-uy/KACE/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
  <img src="https://img.shields.io/badge/status-pre--1.0-yellow" alt="Project status: pre-1.0">
  <img src="https://img.shields.io/badge/Python-3.11%2B-blue" alt="Python 3.11 or newer">
  <img src="https://img.shields.io/badge/platform-Linux%20%7C%20Raspberry%20Pi-green" alt="Linux and Raspberry Pi">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-GPL--3.0-blue" alt="GPL-3.0 license"></a>
</p>

<p align="center">
  <strong>English</strong> · <a href="docs/es/README.md">Español</a> · <a href="docs/pt/README.md">Português</a>
</p>

> [!WARNING]
> KACE is in active pre-1.0 development. The `main` branch can change without backward-compatibility guarantees until a stable release process exists.

## Contents

- [What is KACE?](#what-is-kace)
- [Quick start](#quick-start)
- [How the ecosystem flows](#how-the-ecosystem-flows)
- [Why KACE?](#why-kace)
- [Features](#features)
- [Current status](#current-status)
- [Requirements](#requirements)
- [Installation](#installation)
- [End-to-end workflow](#end-to-end-workflow)
- [Architecture](#architecture)
- [Technologies](#technologies)
- [Testing and validation](#testing-and-validation)
- [Docker](#docker)
- [CICD](#cicd)
- [Compatibility and limits](#compatibility-and-limits)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

---

## What is KACE?

KACE is the Raspberry Pi-side interactive CLI in the KACE ecosystem. It guides a user through printer hardware choices, derives a Klipper configuration, can build the matching MCU firmware, and deploys the generated artifacts through supported local or remote paths.

> [!WARNING]
> KACE does not replace Klipper and does not eliminate printer commissioning. The person responsible for the machine must still verify wiring, pin assignments, motion limits, heaters, sensors, homing, and the first controlled movement.

## Quick start

| Starting point | Recommended path |
| --- | --- |
| New Raspberry Pi printer host | Use [KACE Studio](https://github.com/3D-uy/KACE-studio) to image, configure first boot, discover the Pi, connect over SSH, and start the pinned bootstrap flow. |
| Existing Debian-family Linux host | Run the installation command below, then launch `kace`. |
| Source checkout or contributor setup | Clone the repository, install the locked dependencies, and run `python kace.py`. |

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/3D-uy/KACE/main/install.sh)
```

> [!WARNING]
> This convenience command streams remote content from the mutable `main` branch directly to Bash. For an auditable installation, download `install.sh` from an immutable commit or tag, verify its SHA-256 through a separately trusted value, inspect it, and then execute it.

## How the ecosystem flows

```text
KACE Studio (Windows)
        │ image, first-boot settings, discovery and SSH
        ▼
Raspberry Pi printer host
        │ pinned bootstrap.sh provisions the host
        ▼
KACE (interactive Linux CLI)
        │ configuration and optional firmware artifacts
        ▼
Klipper + printer commissioning
```

| Stage | Responsibility |
| --- | --- |
| 🪟 [KACE Studio](https://github.com/3D-uy/KACE-studio) | Writes a Raspberry Pi image, injects network, first-boot, and KACE bootstrap files; after boot it discovers the Pi, connects through SSH, and starts the injected `bootstrap.sh`. |
| 🍓 Bootstrap | Provisions Klipper, Moonraker, the selected web interface, optional Crowsnest support, and KACE. Studio pins the bootstrap by immutable Git commit and SHA-256 in CI. The bootstrap pins the KACE installer URL, revision, and SHA-256 as one contract. |
| 🧩 KACE | Guides printer choices, generates printer-specific configuration and firmware artifacts, and offers supported deployment paths. |
| 🔧 Klipper and the operator | Run Klipper and complete the official electrical, mechanical, thermal, homing, and motion verification sequence. |

Machine-readable stage and error markers in `scripts/bootstrap.sh` are consumed by the Studio UI and must remain synchronized.

## Why KACE?

| Manual path | KACE-assisted path |
| --- | --- |
| Collect board, motion, endstop, heater, sensor, probe, display, and software details across separate steps. | Gather those choices in one guided CLI flow. |
| Assemble configuration and firmware artifacts manually. | Resolve maintained board and MCU profiles, then generate configuration, macros, and optional firmware artifacts. |
| Choose transfer and recovery steps ad hoc. | Use supported local/removable-media, SSH/SFTP, Moonraker, or safety-gated firmware deployment paths with backup, validation, and rollback support where implemented. |
| Validate the physical printer after each change. | Validate the physical printer after each change; KACE makes artifacts and workflow more repeatable, but does not replace commissioning. |

## Features

| Area | What KACE provides |
| --- | --- |
| 🧭 Guided setup | Interactive CLI in English, Spanish, and Portuguese. |
| 🧠 Profiles | Board and MCU profile resolution from maintained YAML data. |
| 🖨️ Motion and probing | Configuration generation for implemented Cartesian and CoreXY flows; no probe, BLTouch, CR Touch, inductive, and custom probe flows. |
| 🖥️ Displays | Compatibility checks and generated display configuration where supported. |
| 📄 Generated artifacts | Klipper configuration and macro generation from project templates, stored under `~/kace/` on the printer host. |
| ⚙️ Firmware | Optional Klipper MCU firmware derivation and build; deployment-agnostic firmware artifacts plus MANUAL and safety-gated USB strategies. |
| 📦 Deployment | Local/removable-media, SSH/SFTP, and Moonraker configuration deployment paths; backup, validation, and rollback support around deployment. |

Unsupported or contradictory selections are expected to fail safely rather than produce a configuration that is known to be invalid.

## Current status

KACE is in active pre-1.0 development. Its configuration generators, snapshot tests, board coverage checks, pinned-Klipper matrices, and containerized firmware builds run in CI. Those automated checks do not substitute for physical validation on every supported controller, probe, display, or printer.

The authoritative project version is stored in `VERSION`.

> [!NOTE]
> Automated tests do not physically test every controller, printer, probe, display, wiring arrangement, or commissioning sequence.

## Requirements

| Audience | Requirements |
| --- | --- |
| End users | A Debian-family Linux printer host, normally a Raspberry Pi; Python 3.11 or newer; Git and standard system packages installed by `install.sh`; network access for installation and operations that fetch upstream Klipper data; appropriate access to the chosen deployment target. |
| Contributors | Python 3.11, Git, and Docker for the pinned-Klipper validation matrix and containerized firmware builds. |

## Installation

### Provision a new printer host with KACE Studio

For a new Raspberry Pi, use [KACE Studio](https://github.com/3D-uy/KACE-studio). Studio handles imaging, first-boot configuration, discovery, SSH access, and the pinned KACE bootstrap flow.

### Install directly on an existing Linux host

The convenience command installs from the mutable `main` branch:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/3D-uy/KACE/main/install.sh)
```

This streams network content directly to Bash. For an auditable installation, download `install.sh` from an immutable commit or tag, verify its SHA-256 through a separately trusted value, inspect it, and then execute it. `install.sh` honors `KACE_SOURCE_REF` so an integrator can install the repository content from the same immutable revision as the installer.

### Run from a source checkout

```bash
git clone https://github.com/3D-uy/KACE.git
cd KACE
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --require-hashes -r requirements.txt
python kace.py
```

Run `python kace.py --help` for the available CLI options.

<details>
<summary>Installation safety reminder</summary>

`main` is mutable. Pinning the installer and source revision, checking a separately trusted SHA-256, and inspecting the script are the auditable path when that level of control is required.

</details>

## End-to-end workflow

1. Provision or prepare the Linux printer host.
2. Launch KACE with `kace` after installation, or `python kace.py` from a checkout.
3. Select language and describe the printer, controller, motion system, endstops, bed, heaters, sensors, probe, display, and software choices.
4. Let KACE resolve the board profile and generate the Klipper configuration under `~/kace/`.
5. Build the MCU firmware when required by the selected board workflow.
6. Review the generated artifacts and deploy them using the chosen local or remote target.
7. Flash the MCU only according to the controller manufacturer's documented procedure.
8. Start Klipper and complete its official verification sequence before energizing heaters or commanding unrestricted motion.

For an integrated firmware path, KACE displays transactional installation progress directly in an interactive terminal and keeps `Ctrl+C` available for a safe cancellation. Redirected output, pipes, CI, and terminals without dynamic capabilities receive plain ASCII progress lines instead. The same canonical workflow events are emitted as `KACE_WORKFLOW_EVENT` JSON lines for KACE Studio; neither terminal view controls or reconstructs the installation state machine.

> [!TIP]
> Review generated artifacts before deployment, and treat the first power-on, homing, heater, sensor, and movement checks as operator-controlled safety steps.

## Architecture

| Area | Responsibility |
| --- | --- |
| `kace.py` | CLI entry point, argument parsing, and top-level orchestration. |
| `core/wizard/` | Interactive workflow and normalized user selections. |
| `core/scraper.py`, `core/hardware_detector.py` | Upstream configuration retrieval and hardware discovery. |
| `core/generator.py`, `core/templates.py` | Klipper configuration and macro generation. |
| `firmware/` | Firmware derivation/build plus typed artifacts and MANUAL/USB deployment strategies. |
| `data/firmware_deployments.yaml` | Final filenames, instructions, and allow-listed USB safety profiles. |
| `core/deployer.py`, `core/moonraker.py`, `core/moonraker_deployer.py` | Deployment, transactional installation, remote transfer, backup, and rollback paths. |
| `core/terminal_progress.py` | Native TTY and line-oriented views of canonical installation events. |
| `data/`, `templates/`, `config/` | Board contracts, translations, generated-content templates, and configuration data. |
| `scripts/bootstrap.sh` | Integration contract used by KACE Studio to provision a printer host. |
| `tests/` | Unit, regression, snapshot, schema, sweep, and pinned-Klipper matrix validation. |

Generated printer artifacts remain separate from the source tree at `~/kace/`.

## Technologies

- Python, Questionary, PyYAML, and Jinja2.
- Paramiko for the optional SSH/SFTP deployment path.
- Bash for installation and host provisioning.
- Docker for reproducible Klipper parsing and MCU build validation.
- GitHub Actions for CI.

## Testing and validation

Install the locked runtime dependencies, then run the narrow validation needed for the change:

```bash
python tests/run_tests.py --verbose
python tests/run_tests.py --yaml-check
python tests/matrix/run_matrix.py --profile quick
```

The full pairwise matrix is intended for manual or pre-release use:

```bash
python tests/matrix/run_matrix.py --profile full
```

The matrix generates configurations through the real KACE flow, validates accepted cases with a fixed Klipper commit inside Docker, distinguishes safe expected rejections from failures, and writes Markdown and JSON reports. The broader upstream configuration sweep is available with:

```bash
python tests/run_tests.py --full-klipper-sweep --verbose
```

Snapshot-update modes are maintainer operations and must not be used merely to make a failing test pass. See [Testing](docs/en/TESTING.md) for the test layout and expectations.

## Docker

KACE is installed directly on the printer host; it is not shipped as a runtime container. The repository Docker image exists for reproducible development and validation:

```bash
docker build -f docker/ci/Dockerfile -t kace-dev .
docker run --rm -it -v "$PWD:/workspace" kace-dev
```

The matrix runner also uses Docker to execute the real configuration loader from its pinned Klipper revision. No physical device is accessed by these validation jobs.

## CI/CD

GitHub Actions currently checks:

- Python syntax.
- Unit and snapshot regression tests.
- `boards.yaml` schema and precedence rules.
- A reduced KACE-to-Klipper matrix on pull requests and pushes.
- The full upstream configuration sweep on pushes to `main`.
- A full pairwise matrix when manually dispatched.
- Containerized firmware builds for representative LPC1769, STM32, RP2040, and AVR targets.

CI validates source and generated artifacts. It does not publish a release and it does not exercise real printers or flash physical controllers.

## Compatibility and limits

- Runtime target: Debian-family Linux hosts with Python 3.11 or newer.
- Automated generation coverage: implemented Cartesian and CoreXY workflows and all board contracts required by the matrix.
- Automated probe coverage: none, BLTouch, CR Touch, inductive, and custom; unsupported dockable combinations are classified as safe rejections.
- KACE Studio performs the Windows-side provisioning flow; KACE itself runs on the Linux printer host.
- Upstream Klipper, board definitions, and third-party web interfaces can change independently. The pinned matrix detects parser incompatibilities but cannot prove electrical or mechanical safety.

## Roadmap

Before 1.0, the project should prioritize reproducible releases, contract synchronization across both repositories, documented hardware qualification, end-to-end installation evidence, and closure of known safety and compatibility risks. After 1.0, work should focus on measured board coverage, migration stability, and contributor-facing diagnostics. Broader automation or additional hardware families belong in a later roadmap only after they have tests and maintainers.

See [CHANGELOG.md](CHANGELOG.md) for recorded changes. Roadmap items are intentions, not shipped features.

## Contributing

Read the [contributor guide](docs/en/CONTRIBUTING.md), [security policy](SECURITY.md), and [code of conduct](CODE_OF_CONDUCT.md) before opening a change. Keep changes scoped, add the narrowest relevant regression coverage, and do not update snapshots without reviewing the generated difference.

Issues and pull requests are managed in the [KACE repository](https://github.com/3D-uy/KACE).

## License

KACE is licensed under the [GNU General Public License v3.0](LICENSE).
