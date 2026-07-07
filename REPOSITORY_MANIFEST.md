# REPOSITORY MANIFEST — `3D-uy/kace`

**Last updated:** 2026-07-07 · **Version:** main

> This is a living document. Update the version number and `Last updated` date at the top on every release cycle.

---

## 1. Project Overview

KACE (Klipper Automated Configuration Ecosystem) is an intelligent CLI wizard for Raspberry Pi that automates the entire Klipper 3D-printer setup pipeline — from hardware detection to configuration generation and firmware compilation. It identifies the connected MCU over USB/serial, fetches the official Klipper board configuration directly from GitHub (with a 3-day local cache), derives the correct Kconfig firmware parameters through a YAML-driven pattern database, generates a clean and validated `printer.cfg` via Jinja2 templating, compiles the firmware binary (`klipper.bin` / `.uf2` / `.hex`), and deploys via SSH, Moonraker REST API, USB, or SD card — all in a single guided interactive session. KACE is validated against 192 official Klipper board configurations with zero hard crashes, supports English, Spanish, and Portuguese, and enforces hash-pinned Python dependencies for tamper-resistant installations.

---

## 2. Repository Structure

```
3D-uy/kace/
│
├── kace.py                     # Main entry point — CLI argument parsing + top-level flow orchestration
├── install.sh                  # Linux installer — clones, pins to release tag, installs deps, creates symlink
├── VERSION                     # Single source of truth for the release version string (e.g. "main")
├── requirements.txt            # Hash-pinned core Python dependencies (pip --require-hashes)
├── requirements.in             # Source file for requirements.txt (managed via pip-compile)
├── requirements-ssh.txt        # Hash-pinned optional SSH/SFTP dependencies (lazy-installed on first use)
├── requirements-ssh.in         # Source file for requirements-ssh.txt
│
├── core/                       # Business logic modules
│   ├── wizard.py               # 19-step interactive configuration wizard (main flow controller)
│   │                           #   • z_socket_assignment: conditionally skipped (single-Z builds bypass it via next())
│   │                           #   • bltouch_pins: mid-flow injection — inserted between probe and probe_offsets
│   │                           #     only when the probe answer is BLTouch/CR-Touch AND pins aren't pre-populated
│   │                           #     from boards.yaml; unlike z_socket_assignment this is not a graph skip but
│   │                           #     a branch in the probe step's next() function — different maintenance surface
│   ├── display_wizard.py       # Display compatibility sub-wizard (TFT, HDMI, Klipperscreen)
│   ├── firmware_wizard.py      # Firmware compilation sub-wizard
│   ├── generator.py            # Jinja2-based printer.cfg generator with comment alignment
│   ├── scraper.py              # GitHub config scraper (3-day cache, HTML fallback, path-sanitised)
│   ├── deployer.py             # Deployment orchestrator — SSH, Moonraker API, USB, SD card
│   ├── moonraker.py            # Moonraker REST API client (upload + restart, API key support)
│   ├── translations.py         # All user-facing strings in EN/ES/PT via t() lookup
│   ├── dashboard.py            # System status dashboard — detects Klipper, Moonraker, Mainsail, etc.
│   ├── display_checker.py      # Display hardware compatibility database and validation
│   ├── validators.py           # Klipper pin string validation (regex-based)
│   ├── pin_validator.py        # Pre-flight structural and pin namespace validation
│   ├── advanced_module_handler.py  # Advanced Klipper module configuration (BLTouch, sensors)
│   ├── banner.py               # ANSI decorative installer banner (called by install.sh post-clone)
│   ├── bed_mesh.py             # Bed mesh configuration logic
│   ├── leveling.py             # Bed leveling strategy selection
│   ├── loader.py               # YAML data loader with hardcoded fallback dict
│   ├── macro_generator.py      # Klipper macro snippet generation
│   ├── motion_model.py         # Motion system configuration (CoreXY, delta, cartesian)
│   ├── probe_offset_visualizer.py  # ASCII probe offset visualizer
│   ├── style.py                # ANSI colour constants shared across modules
│   ├── summary.py              # Configuration summary display before generation
│   ├── display_warning.py      # Display compatibility warning prompts
│   └── exceptions.py           # Custom exception hierarchy
│
├── firmware/                   # MCU detection and firmware derivation
│   ├── detector.py             # USB/serial MCU identification (maps device strings to board families)
│   └── derivation.py          # YAML-pattern-driven Kconfig parameter derivation engine
│
├── data/                       # Hardware and profile databases
│   └── boards.yaml             # Board database: MCU families, search terms, BLTouch pin overrides,
│                               #   firmware flash patterns, and mcu_firmware[] Kconfig derivation rules
│
├── templates/                  # Jinja2 config templates
│   └── printer.cfg.j2          # Master printer.cfg template — rendered per-board, snapshot-protected
│
├── tests/                      # Full automated test suite (zero external test dependencies)
│   ├── run_tests.py            # Test runner — supports --verbose, --yaml-check, --full-klipper-sweep,
│   │                           #   --update-snapshots, --auto flags
│   ├── kace_test_case.py       # Shared test case base class
│   ├── unit/                   # Unit tests for all core modules
│   │   ├── test_validators.py
│   │   ├── test_deployer.py
│   │   ├── test_moonraker.py
│   │   ├── test_firmware_wizard.py
│   │   ├── test_summary.py
│   │   └── ...
│   ├── regression/             # Snapshot regression tests
│   │   └── test_snapshot_expansion.py  # Golden .cfg output locked per board
│   ├── fixtures/               # Golden .txt snapshot fixtures (one per board)
│   └── sweep/                  # Full Klipper config sweep engine
│       ├── klipper_sweep.py    # Offline-safe sweep runner (192+ configs)
│       ├── result_codes.py     # PASS / SAFE_ABORT / UNSUPPORTED / FAILURE classification
│       └── full_sweep_runner.py
│
├── scripts/                    # Maintainer utilities
│   └── pre-commit              # Git pre-commit hook — blocks hardcoded UI strings and Windows paths
│
├── docs/                       # User and contributor documentation (multilingual)
│   ├── RELEASE.md              # Release engineering guide (versioning, tagging, rollback)
│   ├── en/
│   │   ├── ARCHITECTURE.md     # YAML schema reference, derivation pipeline, fallback logic
│   │   ├── TESTING.md          # Test suite usage and CI workflow
│   │   ├── CONTRIBUTING.md     # Board addition guide, PR checklist, dep management
│   │   ├── DISPLAYS.md         # Display hardware compatibility reference
│   │   ├── pi_imager.md        # Raspberry Pi Imager setup guide
│   │   ├── Klipper_install.md  # Klipper installation walkthrough
│   │   └── docker_guide.md     # Docker simulation testbed guide for Windows developers
│   ├── es/                     # Spanish translations of all guides above
│   └── pt/                     # Portuguese translations of all guides above
│
├── docker/                     # Docker simulation testbed (dev-only, .gitignore'd compose files)
│   ├── Dockerfile              # Multi-arch Linux image with cross-compilation toolchains
│   └── entrypoint.sh           # Simulation scenario builder (mocks services, serial ports, hardware)
│
├── .github/
│   └── workflows/
│       └── ci.yml              # GitHub Actions CI — 5-stage pipeline, concurrency cancellation
│
├── README.md                   # Project landing page with badges, install commands, validation results
├── CHANGELOG.md                # Keep-a-Changelog format release notes
├── SWEEP_RESULTS.md            # Full per-config breakdown of the 192-board validation sweep
├── SECURITY.md                 # Vulnerability reporting policy
├── CODE_OF_CONDUCT.md          # Contributor Covenant
├── LICENSE                     # GPL-3.0
├── .gitignore                  # Excludes out/, scratch/, *.log, .coverage, docker-compose files
└── .gitattributes              # Line-ending normalization (LF for .sh, .py, .yaml)
```

---

## 3. Entry Points

### `kace.py`
The primary CLI entry point. Responsibilities:
- Parses command-line flags: `--auto`, `--version`, `--yaml-check`, `--full-klipper-sweep`
- Reads version from `VERSION` file (single source of truth)
- Launches the system status dashboard (`core/dashboard.py`)
- Hands off to the interactive wizard (`core/wizard.py`)
- Contains the only permitted `sys.exit()` calls in the codebase

### `install.sh`
The Linux installer script. Responsibilities:
1. Installs `git` and `python3-pip` via `apt` if missing
2. Clones `https://github.com/3D-uy/kace.git` targeting `INSTALL_TAG` (`main`) using sparse + shallow checkout (`core firmware data templates` only — docs excluded)
3. Falls back to a full clone if Git < 2.25
4. Updates existing installations via `git fetch` + `git checkout tags/`
5. Installs `requirements.txt` with `--require-hashes` (tamper-resistant)
6. Creates the `kace` global symlink at `/usr/local/bin/kace` (or `~/.local/bin/kace` without sudo)
7. Launches `kace.py` immediately post-install with stdin reconnected to the terminal

---

## 4. Key Configuration Files

| File | Purpose |
|------|---------|
| `VERSION` | Single-line version string (`main`). Read by `kace.py` at runtime and by `install.sh` post-clone for the decorative banner. **Must match `INSTALL_TAG` in `install.sh` and the latest tagged entry in `CHANGELOG.md`.** |
| `requirements.txt` | Hash-pinned core dependencies compiled from `requirements.in` via `pip-compile --generate-hashes`. Enforced at install time with `--require-hashes`. Do not edit manually. |
| `requirements-ssh.txt` | Hash-pinned optional SSH dependencies. Lazily installed by `core/deployer.py` on first SSH deployment attempt. |
| `data/boards.yaml` | The central hardware database. Contains `boards[]` (MCU families + search terms + BLTouch overrides) and `mcu_firmware[]` (Kconfig derivation patterns). Adding a new board requires only a YAML edit here — no Python changes. |
| `templates/printer.cfg.j2` | The Jinja2 master template for `printer.cfg` generation. Any change here must be validated with `python3 tests/run_tests.py --verbose` to prevent silent snapshot regressions. |
| `.gitattributes` | Enforces LF line endings for all `.sh`, `.py`, `.yaml`, `.j2` files — critical for cross-platform development and hash reproducibility. |

---

## 5. Release Checklist

Use this checklist before every `git tag` + push to `3D-uy/kace`:

- [ ] **No `kace-dev` repo references remain** — `scripts/pre-commit` enforces this automatically on every commit; confirm the hook is installed (`ls .git/hooks/pre-commit`) and run `grep -ri "kace-dev" --include="*.md" --include="*.sh" --include="*.py" --include="*.yaml"` to verify clean state
- [ ] **`INSTALL_TAG` in `install.sh` matches `VERSION` file** — `grep INSTALL_TAG install.sh` must equal `v$(cat VERSION)`
- [ ] **`CHANGELOG.md` latest tagged entry matches `VERSION`** — the top non-`[Unreleased]` section heading must read `## [main]` (or current version)
- [ ] **`CHANGELOG.md` footer links all point to `3D-uy/kace`** — no `kace-dev` compare/release URLs in the link definitions at the bottom
- [ ] **`requirements.txt` hashes are current** — regenerate via `pip-compile --generate-hashes requirements.in` if any dependency was updated
- [ ] **`requirements-ssh.txt` hashes are current** — regenerate via `pip-compile --generate-hashes requirements-ssh.in` if any SSH dep was updated
- [ ] **Sparse checkout dirs in `install.sh` match actual directory structure** — `_SPARSE_DIRS="core firmware data templates"` must list every directory required at runtime (check against the repo root)
- [ ] **Full test suite passes** — `python3 tests/run_tests.py --verbose` → 0 failures, 0 errors.
- [ ] **YAML integrity passes** — `python3 tests/run_tests.py --yaml-check` → no schema or precedence errors
- [ ] **README install commands point to the main branch** — the installation commands must point to `raw.githubusercontent.com/3D-uy/KACE/main/install.sh`
- [ ] **All three README language variants updated** — `README.md`, `docs/es/README.md`, `docs/pt/README.md` must be in sync on badge URLs and install commands
- [ ] **`SWEEP_RESULTS.md` reflects the latest sweep run** — if boards.yaml or derivation logic changed, re-run `python3 tests/run_tests.py --full-klipper-sweep` and commit the updated results

---

## 6. What's Excluded from Release

The following are **never shipped** in the public `3D-uy/kace` repository:

| Excluded item | Reason | Enforced by |
|---------------|---------|-------------|
| `out/` | Generated `printer.cfg` + firmware output — changes every run | `.gitignore` |
| `scratch/` | Agent test runs, ad-hoc scripts, manual check files | `.gitignore` |
| `.coverage` | Python coverage binary output | `.gitignore` |
| `*.log` (`test_out.log`, `test_out_new.log`) | Test execution logs | `.gitignore` |
| `docker-compose.yml` / `docker-compose.dev.yml` / `docker-compose.prod.yml` | Developer-only Docker orchestration files | `.gitignore` |
| `run-dev.ps1` / `run-prod.ps1` | Windows dev-run scripts | `.gitignore` |
| `docs/PRD.md` | Internal product requirements document | `.gitignore` |
| `docs/en/ARCHITECTURE.md` | Internal architecture reference — **does not ship**; maintained in `.gitignore` permanently | `.gitignore` |
| `tests/results/` / `tests/results_profiles/` | Test run output artifacts | `.gitignore` |
| `KACE_old/` | Legacy code archive | `.gitignore` |
| `.git/` | Git metadata — never committed | inherent |
| `__pycache__/` / `*.pyc` | Python bytecode | `.gitignore` |
| `.env` / `venv/` / `*.egg-info/` | Local environment files | `.gitignore` |

> **Note on `docker/`:** The `docker/` directory itself **is** committed (Dockerfile + entrypoint.sh are useful to contributors). Only the `docker-compose*.yml` files are excluded because they may contain local path mounts or environment secrets.

> **Note on `REPOSITORY_MANIFEST.md`:** This file **intentionally ships** to `3D-uy/kace`. It is a contributor-facing document that maps the repository structure and surfaces the release checklist. It is not listed in the exclusions table above.

---

*Update this document every release cycle. Change the `Last updated` date and `Version` at the top to match the new release tag.*
