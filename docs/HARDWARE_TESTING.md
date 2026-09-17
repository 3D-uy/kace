# Controlled hardware qualification — 0.9.4-rc.1

This candidate is intended to collect the first controlled physical evidence.
Automated tests, valid checksums and Klipper `Ready` do not qualify wiring, thermal
behavior, motion or an entire printer. Record observations per exact board revision.

## What the candidate guarantees

- The installer, runtime and bootstrap are bound to immutable Git identities.
- Firmware records the pinned Klipper commit, resolved Kconfig, build identity and
  artifact checksum. Verification requires physical MCU evidence and the expected
  build fingerprint; another MCU of the same model is insufficient.
- Checkpoints reject stale writers. Configuration review precedes activation;
  completion requires the requested restart, Klipper Ready and firmware verification.
- Existing configuration is reconciled, including SAVE_CONFIG and explicit nested
  user includes. Missing, cyclic, wildcard or outside-root includes fail closed.
- Local/SFTP can create an absent file without replacing a concurrent creation.
  Existing-file replacement has no atomic content precondition in these transports;
  Moonraker upload has no equivalent conditional operation. A transaction needing
  those operations stops before writes/firmware and saves a `*-proposed` snapshot
  for operator review and application. This is an expected limitation, not success.
- Recovery preserves live edits and durable snapshots when safe restoration cannot
  be proven. Bootstrap power-reconciliation failures likewise preserve live files
  and backups and report manual recovery paths. Never blindly copy a backup over
  a file that may have changed.

## Before connecting a printer

1. Record the KACE runtime SHA, bootstrap SHA and Studio commit from the release
   contract/manifest. Verify the executable SHA-256 independently. An unsigned
   candidate is not an Authenticode-verified or stable release.
2. Review source tests, contract checks and packaged renderer smoke evidence. If a
   required CI job has not passed, record the gap and do not call it validated.
3. Choose one exact board/MCU/bootloader profile. Check its physical method in
   `data/firmware_deployments.yaml` and the BoardContract authority settings. A
   matching MCU family or a generated artifact does not authorize another method.
4. Preserve original host configuration and firmware recovery instructions outside
   the target. Plan manual configuration application if conditional replacement is
   unsupported. Resolve all proposal/recovery states before claiming completion.
5. Prepare one expendable, clearly identified SD/USB target. Confirm the host system
   disk is excluded. Do not use valuable storage for the first writer trial.

## Qualification sequence (manual; never run by CI)

| Stage | Evidence required before continuing |
| --- | --- |
| Studio imaging | Exact selected disk identity; checksum-approved image; successful writer exit, matching operation report, readback and injection; verified safe eject. |
| Pi first boot | Correct network, SSH host-key decision, active services, bootstrap revision and no terminal provisioning error. |
| Artifact review | Exact board revision, processor, pins, clock, bootloader offset, final filename, Kconfig and build identity. |
| Firmware delivery | Manufacturer's procedure, selected media/USB identity, operator power-cycle evidence, same physical MCU and expected firmware fingerprint. |
| Configuration | Reviewed proposed diff and includes; explicit application/activation; active config path, Klipper Ready and firmware identity. |
| Printer commissioning | Klipper's configuration checks: sensors, endstops, direction, travel and heating, one controlled operation at a time with an accessible power cutoff. |
| Recovery trial | Deliberate interruption at a safe stage; preserved external edit, durable checkpoint/snapshot, explicit recovery outcome and no false completion. |

Use the [Klipper configuration checks](https://www.klipper3d.org/Config_checks.html)
and the board manufacturer's documentation for physical commissioning. Do not
treat KACE's generated configuration as a substitute for those checks.

## Record and stop conditions

Record date, operator, OS/image hash, exact board revision, connection topology,
power setup, all source commits, native artifact hash, workflow/proof IDs and logs
with credentials removed. Distinguish automated evidence from physical observations.

Stop on changed/ambiguous device identity, serial or fingerprint mismatch, unsafe
media, unexpected sensor/motion behavior, failed readback, pending activation,
manual recovery or an unresolved transaction conflict. Do not bypass a gate to
finish a test. A successful trial qualifies only the recorded combination.
