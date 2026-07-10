# Changelog

All notable changes to KACE are documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
KACE uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.9.3.4] — Unreleased

### Refactored
- Decoupled testing-specific environment variable checks (`KACE_TESTING`, `KACE_REAL_BUILD`) from the production codebase (`core/` and `firmware/`).
- Introduced generic dependency injection points (`make_command`, `env`, `concurrency`) in `build_firmware_orchestrator` to decouple build-tool resolution.
- Extracted and encapsulated compiler LTO bypass wrapping logic into a dedicated testing fixture module under `tests/fixtures/`.
- Reorganized the `docker/` folder structure, moving all CI-specific mocking files and scripts into `docker/ci/`.
- Simplified test configurations by initializing global test-runner mocks and prepends inside test harness setups (`conftest.py` and `run_tests.py`).

### Cleaned
- Removed orphaned standalone validation/smoke scripts (`tests/smoke_advanced.py`, `tests/validate_advanced.py`, `tests/validate_display_hw.py`) since their functionality is fully covered by the integrated unit/regression test suite.
- Updated `.gitignore` to explicitly ignore generated build files (`*.bin`, `*.uf2`, `*.elf.hex`), local `.config` files, and local KACE output files (`printer.cfg`, `macros.cfg`, `jobs.json`, `test_printer.cfg`).
- Added missing `questionary` package declaration in `requirements.txt` with PyPI sha256 hashes.

---

## [0.9.3.3] — 2026-07-08

### Added
- Pre-flight configuration validation (`core/pin_validator.py`) to prevent Klipper crash loops and OOM-induced network lockouts by rejecting malformed files (missing `[mcu]`, `serial`, `[printer]`, etc.) or cross-family pin namespaces before upload.
- Environment variable `KACE_SSH_USER` support to override the default SSH user (e.g. for `kace` user instead of `pi`).
- Added KACE CLI styling color escapes (cyan menu titles, orange suggested/default items, and orange select input prompts) in `core/menu.py`.

### Fixed
- Switched `install.sh` to use an isolated Python virtual environment (`venv`) and wrapper commands to prevent system package collisions and potential network lockouts.
- Omitted the `--break-system-packages` flag conditionally when installing Python packages inside a virtual environment.
- Made the deployment verification loop RAM-aware (looser polling on hosts <=1GB RAM) and added a prompt to skip/select restart method instead of forcing an unconditional full-service restart.
- Reduced Pi download size by implementing git non-cone sparse checkout in `install.sh` to fetch only runtime files.
- Preserved `requirements-ssh.txt` in sparse-checkout patterns to prevent missing dependency errors during automatic SSH package setup.
- Automated local hostname resolution in `/etc/hosts` during installation to suppress generic `sudo` warnings.
- Mocked interactive restart prompts in deployment tests to resolve CI timeouts.
- Changed default SSH user references from `pi` to `kace` throughout UI prompts, translation files, and fallback default values.
- Suppressed `REAL BUILD MODE` notification banner in mock-build compile sequences.
- Changed `[*]` compile warning color indicator prefix from red to green to prevent false warning flags.
- Suppressed Git detached HEAD warning advice blocks during tag checkouts in the installer.

---

## [0.9.3.2] — 2026-06-29

### Fixed
- Fixed pin mapping bug when generating configuration files for printers with replaced (non-stock) board upgrades. Bypassed printer-profile pins and board_pins sections during merge if a non-stock board is active.
- Added expected MCU stock mappings for Anet A8 Plus 2019 config model file names to boards.yaml.

---

## [0.9.3.1] — 2026-06-28

### Fixed
- Fixed screen clearing mid-installation by removing redundant banner.py call.
- Relocated the `[include macros.cfg]` line to reside inside the `# Includes` block instead of prepending it to the start of the file.
- Skipped Z endstop checks and enforced negative `position_min` (`-2.0`) for Z virtual endstops (probes like BLTouch / CR-Touch) to avoid Klipper startup errors.

---

## [0.9.3] — 2026-06-24

### Fixed
- False-negative Mainsail/Fluidd detection when installed via nginx or run under
  `sudo` — replaced the single `os.path.isdir(~/mainsail)` check with a full
  `_detect_webui()` probe covering: default home path, `SUDO_USER` home (via
  `pwd.getpwnam`), `/home/*` glob, nginx web roots (`/var/www/mainsail`, etc.),
  and nginx config files (`/etc/nginx/sites-{enabled,available}/mainsail`).

### Added
- Six new unit tests in `tests/unit/test_dashboard.py` covering all
  `_detect_webui()` detection paths.

---

## [0.9.1] — 2026-06-12

### Added
- Moonraker REST API deployment (`core/moonraker.py`) — upload `printer.cfg` and trigger `FIRMWARE_RESTART` or service restart without SSH
- `deploy_moonraker()` in `core/deployer.py` — interactive deploy flow with reachability probe, SSH fallback, and restart selection
- `🌐 Moonraker API (push + restart)` deploy option in the config deployment menu (`kace.py`)
- Optional Moonraker API key support in the deployment prompt
- 15 new unit tests for `core/moonraker.py` (`tests/unit/test_moonraker.py`)
- Full EN/ES/PT translations for all Moonraker deploy UI strings
- Secure hash pinning for dependencies (`requirements.txt` and `requirements-ssh.txt`) with `--require-hashes` enforcement
- Comprehensive unit tests for compiler ambiguity prompts and summary printing (`tests/unit/test_firmware_wizard.py` and `tests/unit/test_summary.py`)

### Changed
- Modularized `kace.py` by extracting summary and compilation wizard logic into `core/summary.py` and `core/firmware_wizard.py`
- Pinned installer `install.sh` to tag `v0.9.1` and removed unsafe remote Python execution fallback
- Gated scraper debug logging behind `KACE_DEBUG` environment variable
- Optimized startup performance on slow hosts by lazy-loading the BLTouch database override dictionary

### Fixed
- Path traversal vulnerability in `core/scraper.py` by sanitizing cache filenames with `os.path.basename()`
- Memory credential vulnerability in `core/deployer.py` by immediately purging `password` from memory post-extraction

---

## [0.9.0] — 2026-05-24

### Added
- `--full-klipper-sweep` flag: clones Klipper shallowly and validates all 192+ official configs
- `--yaml-check` flag: validates `data/boards.yaml` schema, required keys, and pattern precedence
- `tests/sweep/result_codes.py`: four-code classification system (`PASS`, `SAFE_ABORT`, `UNSUPPORTED`, `FAILURE`)
- `tests/sweep/klipper_sweep.py`: offline-safe sweep engine with sparse git checkout
- Six new regression snapshot fixtures: Creality v4.2.2, Creality v4.2.7, Octopus v1.1, SKR Pico (RP2040), SKR v1.3 (LPC176x), SKR Mini E3 sensorless
- `VERSION` file: single source of truth for the project version
- `docs/RELEASE.md`: release engineering guide (versioning, tagging, rollback)
- `docs/en/ARCHITECTURE.md`: YAML schema reference, derivation pipeline, fallback logic
- `docs/en/TESTING.md`: test suite usage, snapshot system, CI workflow
- `docs/en/CONTRIBUTING.md`: board addition guide, PR checklist
- `.github/workflows/ci.yml`: full GitHub Actions CI pipeline with concurrency cancellation
- Full sweep runner and results summary (`SWEEP_RESULTS.md`)
- `tests/sweep/full_sweep_runner.py` and `tests/sweep/last_sweep_report.txt`

### Changed
- `tests/run_tests.py`: added `--yaml-check` and `--full-klipper-sweep` flags; improved help text
- `kace.py`: `--version` flag now reads from `VERSION` file; `__version__` kept in sync
- Added timeouts to network requests in scraper

### Fixed
- Pathing issues in generator, deployer, and test_derivation
- Wizard navigation step 0 bug
- Dashboard banner version display

---

## [0.1.0] — 2026-05-07

### Added
- MCU auto-detection via USB/serial (`firmware/detector.py`)
- GitHub configuration scraper with 3-day cache and HTML fallback (`core/scraper.py`)
- Intelligent configuration engine — parses Klipper configs, extracts profile defaults
- Jinja2-based `printer.cfg` generator with comment alignment and translation support
- Firmware derivation engine (`firmware/derivation.py`) with YAML-backed pattern database
- Interactive CLI wizard — 14-step guided flow (`core/wizard.py`)
- Multi-language support: English, Spanish, Portuguese (`core/translations.py`)
- System status dashboard — detects Klipper, Moonraker, Mainsail, Fluidd, Crowsnest, MCU
- Modular hardware database (`data/boards.yaml`) — boards, BLTouch overrides, firmware patterns
- Fallback system — every YAML load has a hardcoded fallback dict preventing regressions
- Automated test runner framework (`tests/run_tests.py`) — zero external dependencies
- Snapshot regression testing against golden `.txt` fixtures (`tests/fixtures/`)
- SSH deployment via on-demand `paramiko` install (`core/deployer.py`)
- USB/SD card deployment support
- BLTouch pin injection from modular YAML database
- `--auto` flag for CI/headless operation
- Sparse + shallow git clone installer (`install.sh`)
- ANSI colour-coded terminal UI with emoji icon menus
- Validated against 192 official Klipper board configurations

[Unreleased]: https://github.com/3D-uy/kace/compare/v0.9.3.3...HEAD
[0.9.3.3]: https://github.com/3D-uy/kace/compare/v0.9.3.2...v0.9.3.3
[0.9.3.2]: https://github.com/3D-uy/kace/compare/v0.9.3.1...v0.9.3.2
[0.9.3.1]: https://github.com/3D-uy/kace/compare/v0.9.3...v0.9.3.1
[0.9.3]: https://github.com/3D-uy/kace/compare/v0.9.2...v0.9.3
[0.9.2]: https://github.com/3D-uy/kace/compare/v0.1.0...v0.9.2
[0.1.0]: https://github.com/3D-uy/kace/releases/tag/v0.1.0
