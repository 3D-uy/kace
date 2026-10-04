# Current candidate notes

Only notes for the declared candidate remain here because version/release checks
use this file. Older release notes and audit narratives are archived locally;
Git history retains previously committed releases. These notes do not attest
uncommitted changes or current CI, packaging or physical qualification.

[README](README.md) covers current usage; [ROADMAP](ROADMAP.md) covers pending work.

## [0.9.4-rc.3] - 2026-10-03

- Resolve UART/SPI wiring by reviewed removable-driver socket when an official
  board profile uses another TMC chip example, including SKR 1.4 Turbo with Z1
  connected to E1. Cross-model mappings still require explicit motor currents.
- Compare multi-Z mechanics and connector assignments in a compact terminal
  review, with explicit confirmation, edit and navigation actions in EN/ES/PT.
- Use monotonic first-boot readiness deadlines so wall-clock corrections do not
  abort Moonraker, relay or MCU waits. Preserve terminal bootstrap failure events.
- Add pinned Klipper loader coverage for 50 board/driver pairs in direct and
  managed configurations. Existing generated-config snapshots are preserved.
- Candidate for controlled hardware qualification; physical motion, heating and
  the exact user's printer remain unverified.

## [0.9.4-rc.2] — 2026-09-17

- Localize wizard search, input feedback, MCU detection and probe/driver labels
  in EN/ES/PT. Add homing headings and concise custom-probe titles with guidance
  for the field-by-field flow, preserving internal values and navigation.
- Supersedes rc.1 before hardware qualification. The standalone-installer regression
  now reads the authoritative bootstrap pin instead of asserting an obsolete
  release SHA; hash verification against the immutable Git object is unchanged.
- Runtime safety fixes are unchanged. Repin the versioned candidate and bootstrap
  so Studio installs this exact release.
- CI runs the Pytest stabilization regressions against real pinned Klipper
  components; STM32 compilation fixtures provide their explicit reference clocks
  instead of relying on the removed unsafe MCU-wide default.
