# Changelog

All notable changes to KACE are documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
KACE uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [main] — 2026-06-12

### Added
- Standardized Klipper pin validation (`core/validators.py`) using regex pattern `^[!^~]*[A-Za-z0-9_.]+$`.
- Automated pre-commit hook to safeguard against hardcoded UI strings and local Windows paths (`scripts/pre-commit`).
- Full unit tests for pin validation (`tests/unit/test_validators.py`), including explicit verification of prefix-only (`!^`, `~`), internal spaces (`PA 0`), and combined prefixes (`!^PA0`).
- Moonraker plain HTTP API key transmission warning prompt requiring user confirmation (`core/deployer.py`).
- API key propagation header (`X-Api-Key`) for all Moonraker REST request calls (`core/moonraker.py`).
- Security/functional unit tests in `tests/unit/test_deployer.py` covering Moonraker HTTP warning triggers and parameter propagation.

### Changed
- Refactored eager-loading database databases to load lazily at runtime across `core/wizard.py`, `core/display_checker.py`, `firmware/derivation.py`, and `core/advanced_module_handler.py`.
- Consolidated Z-motor configuration logic under `_step_z_socket_assignment` and removed duplicated code.
- Cleaned up display warnings and interactive steps to utilize the central `t()` translation mechanism.
- Upgraded GitHub Actions `actions/checkout@v5` and `docker/setup-buildx-action@v4` in `ci.yml` and configured runner to execute under Node.js 24 natively.

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

[Unreleased]: https://github.com/3D-uy/kace/compare/main...HEAD
[main]: https://github.com/3D-uy/kace/compare/v0.9.1...main
[0.9.1]: https://github.com/3D-uy/kace/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/3D-uy/kace/compare/v0.1.0...v0.9.0
[0.1.0]: https://github.com/3D-uy/kace/releases/tag/v0.1.0
