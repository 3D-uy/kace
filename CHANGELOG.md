# Changelog

All notable changes to KACE are documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
KACE uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.9.3.5] — Unreleased

### Added
- **Versioned Board Contracts**: Added schema-validated, board-specific firmware build and deployment contracts with reproducible Kconfig generation, shadow builds, artifact promotion, and runtime verification.
- **Structured Configuration Review**: Added a semantic validation model for homing, probes, Z endstops, heater control modes, generated macros, and calibration guidance before configuration apply.
- **Reusable Moonraker Power Controller**: Added one configured-device controller for real power status, readiness, verified ON/OFF operations, Studio's Power button, and firmware deployment power cycles without direct GPIO access.
- **Pre-KACE Relay Power Gate**: When Studio requests GPIO relay control, the bootstrap now waits for Moonraker, validates the configured power device, explicitly confirms it on, and requires an MCU device node before launching KACE.
- **Interactive Terminal Simulation**: Expanded the Docker development testbed with selectable mocked Pi environments, Klipper/Moonraker service state, simulated MCU serial paths, and a Moonraker API mock for exercising the wizard without physical hardware.
- **Semantic Terminal Color System**: Added a shared ANSI palette for questions, active input, success, warnings, errors, informational/progress messages, section headers, and hints; covered core menu styling with regression tests.
- **Locale Continuity Regression Coverage**: Added catalog-completeness and runtime tests that ensure the selected EN/ES/PT locale persists through dashboard, wizard, MCU detection, menus, and probe-offset visualization.
- **Guided Custom Probe Setup**: Replaced the raw Klipper configuration paste workflow with a guided custom `[probe]` setup. It collects a validated probe pin, optional pull-up/inversion modifiers, offsets, sampling settings, speed, and retract distance, then presents the generated section for review.
- **Typed Custom Probe Configuration**: Added `CustomProbeConfig` and the `ProbeConfiguration` strategy integration so generated custom probe sections remain typed, preserve resolved offsets for motion and bed-mesh calculations, and do not duplicate standard probe output.
- **Board-Aware Probe Pin Selection**: The custom-probe pin step recommends a board-declared probe connector when available, filters unavailable power/control labels and duplicate pins, supports searchable GPIO selection, and retains validated manual entry as a fallback.
- **SD Firmware Flash Follow-up**: Added firmware-artifact preparation and a Moonraker-backed post-flash workflow that expects the temporary MCU disconnect, waits for Klipper to return, and verifies the compiled firmware fingerprint with recovery guidance on timeout.

### Changed
- **User-Focused Dry Run**: Replaced the default unified diff wall with a concise configuration summary, affected files, important changes, actionable warnings, validation status, and an optional advanced technical diff.
- **Authoritative Version Display**: Banner, CLI, installer, bootstrap, and packaged output now read the repository `VERSION` file (`0.9.3.5`) instead of maintaining hardcoded display versions.
- **Consistent Interactive Presentation**: Standardized questionnaire colors across the wizard, display selection, firmware summaries, and probe guidance. Step frames and headings now use cyan, while selection, success, warning, error, and hint colors retain their semantic roles.
- **Probe Offset Visualizer Localization**: Localized the full preview diagram, orientation guidance, reachability warnings, and confirmation text for English, Spanish, and Portuguese; removed ambiguous vertical LEFT/RIGHT labels from the diagram.
- **Guided Probe Review and Defaults**: Centralized conservative defaults for custom probes (`speed=10`, `samples=2`, `samples_tolerance=0.5`, `samples_tolerance_retries=3`, `samples_result=median`, and `sample_retract_dist=5`) and added EN/ES/PT guidance for every question.
- **Installation Documentation**: Kept the one-line installer as the quick-start path while documenting its trust tradeoff and a download, SHA-256 verification, then execution alternative in the README and installation guides.

### Fixed
- **Safe Cancellation Outcome**: A user declining the final apply is now rendered as `CANCELLED` with a short neutral message; machine-readable outcome events remain available to Studio without being presented as installation failures.
- **Sequential Fan Prompts**: Part-cooling and hotend-fan menus now require and consume one explicit answer each, and long prompt text wraps cleanly on narrow terminals.
- **Single Interactive Banner**: Removed the duplicate initialization path so an interactive KACE execution renders its banner exactly once.
- **Homing and Calibration Coherence**: Inferable homing directions no longer reach the dry run as `UNRESOLVED`; ambiguous directions require wizard input, physical Z endstops no longer show `PROBE_CALIBRATE`, and configured probes receive the appropriate calibration guidance.
- **Heater Control Coherence**: Watermark-controlled beds no longer emit PID constants or a `PID_BED` macro; PID calibration content now follows the selected heater control mode.
- **Locale Fallback and Recovery Flows**: Removed silent fallback to English after language selection, kept the selected locale authoritative in wizard state, and translated the dashboard selector plus the no-MCU diagnostics, retry, and manual serial-path flow.
- **Display Selection Noise**: Removed the redundant detected-board/MCU block from the display-selection screen.
- **Custom Probe Wizard Transition**: Fixed linear wizard transitions declared as static step identifiers; the runner now accepts both static transitions and answer-dependent callbacks, preventing `TypeError: 'str' object is not callable`.
- **Probe Pin Menu Quality**: Prevented the custom probe selector from presenting `<GND>`, `<5V>`, `<RST>`, `<NC>`, or duplicate GPIO entries.

### Security Hardening (Second-Pass Code Audit)
- **Menu Exit Signal Hardening (S2-01)**: Replaced `sys.exit(0)` on Ctrl-C/EOF across `simple_input()`, `yes_no()`, `autocomplete_select()`, and `password_input()` in `core/menu.py` with `raise WizardExit`, ensuring top-level cleanup and connection closure.
- **Raw Board Config Cache Permissions (S2-02)**: Enforced `0o600` (owner-only) file permissions on raw board config caches in `fetch_raw_config()` in `core/scraper.py` using `os.open()`.

### Code Quality & Structural Fixes (Second-Pass Code Audit)
- **Line Ending Normalization (D2-04)**: Normalized line endings from CRLF to LF in `core/moonraker_deployer.py` to match repository `.gitattributes`.
- **Pre-compiled Comment Regex (D2-03)**: Promoted inline comment matching regex `_INLINE_COMMENT_RE` to a module-level constant in `core/generator.py`.
- **Snapshot Exception Narrowing (R2-02)**: Narrowed exception catching in `capture_snapshot()` to network errors (`OSError`, `ConnectionError`, `TimeoutError`), preventing programming bugs from being silently swallowed.
- **Temp File Safety (R2-03)**: Ensured temporary file paths in `restore_snapshot()` are tracked before byte writes to guarantee cleanup on disk write failure.
- **Snapshot Deployment State (R2-01)**: Introduced explicit `snapshot_captured` boolean tracking in `deploy_moonraker()` in `core/deployer.py`.
- **Empty Comment Guard (R2-05)**: Added guard against empty comment lines during translation in `core/generator.py`.
- **CLI Stdin Guard (Q2-03)**: Wrapped interactive ENTER prompt in `deploy_moonraker()` in `try/except (KeyboardInterrupt, EOFError)` to prevent crashes in CI.
- **In-Memory Credential Zeroing (Q2-04)**: Added explicit password purging from `user_data` immediately following `deploy_config()` in `kace.py`.
- **Firmware Restart Disconnect Budget (Q2-05)**: Added dedicated `FIRMWARE_RESTART_DISCONNECT_TIMEOUT_S` constant (5.0s) for Phase 6 post-restart disconnect detection.

### Test Suite Expansions (Second-Pass Code Audit)
- **T2-01**: Created `tests/unit/test_snapshot.py` with full coverage for `capture_snapshot()` and `restore_snapshot()` (success, partial/total failures, upload order, cleanup).
- **T2-02**: Added unit tests for `verify_firmware=False` dev-deploy state handling in `tests/unit/test_moonraker_deployer.py`.
- **T2-03 / T2-04**: Added `PermissionError` tests for `deploy_local()` and `_preflight_check()` abort tests for `deploy_moonraker()` in `tests/unit/test_deployer.py`.

---

## [0.9.3.4] — 2026-07-23

### Security Hardening (Code Audit Phase 2)
- Removed runtime auto-install of `paramiko` via `pip` in `_require_paramiko()` to eliminate potential supply-chain Remote Code Execution (RCE) vectors. SSH deployment now prompts for manual installation via `pip install -r requirements-ssh.txt` (S-01).
- Updated Moonraker HTTP API key deployment to perform a hard abort instead of allowing a soft confirm when transmitting sensitive API keys over unencrypted `http://` connections (S-04).
- Enforced `0o600` (owner-only) file permissions on board database caches in `core/scraper.py` using `os.open()` to protect user hardware history on multi-user systems (S-05).
- Zeroed in-memory SSH reconnection passwords immediately after connection establishment in `core/deployer.py` (S-06).
- Cached `_KACE_VERSION` at module import time in `core/deployer.py` to eliminate dynamic `__import__` runtime lookups (S-07).
- Added least-privilege `sudoers` security documentation for non-interactive systemd Klipper service restarts (S-02).

### Architectural Improvements & Refactoring (Code Audit Phase 1 & 4)
- **Modular Translations Package (Q-01)**: Refactored the 2,500+ line `core/translations.py` monolith into a clean, modular package (`core/translations/`) comprising `__init__.py`, `_state.py`, `_strings.py`, and `_t.py`.
- **Standardized CLI Parsing (Q-03)**: Replaced manual `sys.argv` parsing in `kace.py` with `argparse.ArgumentParser(parse_known_args)` and added `--debug` CLI flag support.
- **Pin Resolution Extraction (D-01)**: Extracted BLTouch/CR-Touch pin resolution logic into `resolve_bltouch_pins()` in `core/wizard/__init__.py`.
- **DRY Deployment Logic (D-02)**: Extracted `_copy_artifacts()` helper in `core/deployer.py` to consolidate duplicate artifact copying code.
- **Decomposed Config Generator (D-03)**: Split `generate_config()` into focused private functions (`_validate_and_sanitize_geometry()`, `_render_display_blocks()`).
- **External Compiler Wrapper (D-06)**: Moved inline string compiler wrapper to `scripts/cc_wrapper.py`.
- **Line Ending Normalization (Q-04 / Q-05)**: Normalized line endings from CRLF to LF in `core/deployer.py` and `core/moonraker.py` to match repository `.gitattributes`.
- **Deepcopy Protection (Q-06)**: Replaced `dict()` shallow copy in `core/generator.py` with `copy.deepcopy()` to prevent nested fan-pin mutation leakage across calls.

### Reliability & Bug Fixes (Code Audit Phase 3)
- **YAML Loader Hardening (R-01 / R-02)**: Standardized `load_boards_yaml()`, `load_displays_yaml()`, and `load_advanced_modules_yaml()` to handle `FileNotFoundError`, `PermissionError`, and `yaml.YAMLError` cleanly by raising descriptive `RuntimeError`s. `read_version()` now falls back to `"v?.?.?"` on error.
- **URL & Comment Regex Alignment (R-04 / T-05)**: Replaced naive string splitting in `core/generator.py` with a whitespace-anchored inline comment regex (`(\s)(#)(.*)`), preventing corruption of URLs containing `#` fragment anchors (e.g. `http://host/#anchor`).
- **MCU Pin Namespace Validation (R-05)**: Restricted serial pin regex check to `[mcu]` blocks to avoid false-negatives across section boundaries.
- **Wizard Exit Signal Standardization (R-06)**: Replaced bare `sys.exit(0)` on Ctrl-C/EOF in `core/menu.py` with `raise WizardExit`.
- **Noexec `/tmp` Detection (R-07)**: Added `/proc/mounts` inspection in `firmware/builder.py` to trigger LTO retry heuristics when `/tmp` is mounted with `noexec`.
- **TOCTOU Elimination (R-08)**: Updated `core/scraper.py` to use `os.makedirs(..., exist_ok=True)`.

### Test Coverage Gaps Resolved (Code Audit Phase 5)
- **T-01**: Added tests for `_require_paramiko()` `ModuleNotFoundError` handling and `deploy_config()` short-circuiting when `paramiko` is absent (`tests/unit/test_deployer.py`).
- **T-02**: Added unit test suite `tests/unit/test_loader.py` covering error paths (`FileNotFoundError`, `PermissionError`, `YAMLError`) for all YAML loaders and version fallback.
- **T-03**: Added `TestDeployConfigRollback` integration tests in `tests/unit/test_ssh_operations.py` verifying full SSH backup creation, upload failure, and `sftp.rename` restoration.
- **T-04**: Added `TestDeployMoonrakerSSHFallbackMenuPrompts` in `tests/unit/test_deployer.py` patching `core.menu` prompt functions during Moonraker SSH fallback.
- **T-05**: Added `TestCommentAlignmentEdgeCases` in `tests/unit/test_generator.py` testing comment alignment with URLs, query strings, and multi-hash pin names.

### Added (Other)
- Integrated a state-machine-driven firmware deployment flow (`core/moonraker_deployer.py`) that handles reboot detection, Klipper readiness verification, and post-flash build identity checking.
- Added `get_klipper_state` and `get_mcu_versions` endpoints to `core/moonraker.py` to fetch exact Klipper status and active MCU compilation versions.
- Added automatic configuration SHA fingerprinting during firmware compilation and injected it as a `KLIPPER_VERSION` make override.

### Refactored (Other)
- Decoupled testing-specific environment variable checks (`KACE_TESTING`, `KACE_REAL_BUILD`) from the production codebase (`core/` and `firmware/`).
- Introduced generic dependency injection points (`make_command`, `env`, `concurrency`) in `build_firmware_orchestrator` to decouple build-tool resolution.
- Extracted and encapsulated compiler LTO bypass wrapping logic into a dedicated testing fixture module under `tests/fixtures/`.
- Reorganized the `docker/` folder structure, moving all CI-specific mocking files and scripts into `docker/ci/`.
- Simplified test configurations by initializing global test-runner mocks and prepends inside test harness setups (`conftest.py` and `run_tests.py`).
- Integrated the new state machine into `deploy_moonraker` in `core/deployer.py`, enabling verified deployments when a build manifest exists, while keeping standard config-only uploads unchanged.

### Cleaned (Other)
- Removed temporary root sketch file `deployer_state_machine.py` after migrating state machine components to production `core/moonraker_deployer.py`.
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
