# Current candidate notes

Only notes for the declared candidate remain here because version/release checks
use this file. Older release notes and audit narratives are archived locally;
Git history retains previously committed releases. These notes do not attest
uncommitted changes or current CI, packaging or physical qualification.

[README](README.md) covers current usage; [ROADMAP](ROADMAP.md) covers pending work.

## [0.10.0-rc.1] - 2026-11-16 (preparation; unpublished)

- Generate plain ASCII section headings, comments, display warnings and starter
  macro descriptions in English, Spanish and Portuguese. Preserve custom probe
  blocks, source values and G-code.
- Add explicit configuration-only generation and recovery from a completed
  installation, with separate operation receipts and fresh validation. Preserve
  the installation checkpoint and frozen recovery artifacts.
- New installation, configuration-only publication and export use a fresh
  generated tree. They do not merge old SAVE_CONFIG, calibration, macros or
  includes. Review the replacement and external backups before applying it;
  omitted macros become inert, and unrelated files are not deleted.
- Recover interrupted runtime publication using a durable journal and shared
  runtime locks. Official Studio launches and bootstrap diagnostic reads must
  cooperate with that lock; older launchers and external writers still require
  quiescence. Durable checkpoints and partial-publication diagnostics retain
  evidence rather than reporting an incomplete transaction as success.
- Disable force_move by default; enable it only after an explicit Advanced
  choice. Require printable-area review, including legacy configuration recovery;
  distinguish travel limits from unknown physical bed dimensions.
- Bound firmware subprocess output, cancellation and identity checks. Prepare
  the pinned Klipper source independently in each complete CI validation job.
- Verify bootstrap checkout identity and preserve recoverable Nginx state.
- Keep Docker preflight input copies readable inside the restricted container
  while retaining a private host-side parent, including restrictive POSIX umasks.
  Permission failures remain unverified; no extra container capabilities are added.
- This is source preparation only. Immutable distribution alignment, clean-runner
  CI, real firmware/ARM builds, package qualification and manual printer E2E are
  pending. No new package, signature, independent reproduction or physical
  safety qualification is claimed.

- Require loaded raw configuration to match the complete effective reviewed plan,
  including removed sections/options, before live DONE/COMPLETE; preserve pending
  activation and conservative recovery when verification fails.
- Require saved MCU verification evidence in checkpoints from MCU_VERIFIED onward,
  without renewing receipts or repeating hardware verification on read.
- Hide Moonraker API-key input; cancel before reading when terminal echo cannot
  be disabled, and preserve READY_TO_DEPLOY after cancelled secret entry.

## [0.9.4-rc.3] - 2026-10-03

- Review incompatible probe Z geometry in the wizard before preparing firmware,
  with an explicit minimum edit instead of silently changing imported limits.
- Review the saved Z minimum in pending `MCU_VERIFIED` workflows while preserving
  firmware and identity evidence; cancellation leaves the checkpoint unchanged
  and correction still requires configuration activation and verification.
- Reject probe-based Z homing when its trigger offset falls outside the effective
  travel limits, before publication or restart; preserve explicit geometry.
- Preserve and revalidate custom-probe input when resuming pending installation,
  including recovery of older guided-probe checkpoints.
- Retain bounded Linux system diagnostics across reboots; configure journald before package installation and stop on activation failure or a conflicting storage override.
- Select custom-probe inputs from the effective board/socket and driver choices;
  prioritize declared sensor and replaced Z-endstop inputs, with expansion aliases
  in an advanced menu. Keep actual pin collisions and firmware reservations blocked.
- Select automatic, minimum or maximum homing direction for each primary axis;
  automatic settings remain commented with EN/ES/PT guidance and are recalculated
  after geometry edits. Preserve explicitly imported or selected directions.
- Preserve verified relay settings when bootstrap is relaunched after its boot
  options were cleaned up; reject inconsistent saved state before file changes.
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
