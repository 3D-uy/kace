# Controlled hardware qualification — 0.9.4-rc.3

This candidate is intended to collect the first controlled physical evidence.
Automated tests, valid checksums and Klipper `Ready` do not qualify wiring, thermal
behavior, motion or an entire printer. Record observations per exact board revision.

## Required software contracts

- Distribution must bind installer, runtime and bootstrap to immutable Git
  identities. A modified source tree does not prove the pinned candidate
  contains those changes; resolve that gap through the release gates.
- Firmware records the pinned Klipper commit, resolved Kconfig, build identity and
  artifact checksum. Verification requires physical MCU evidence and the expected
  build fingerprint; another MCU of the same model is insufficient.
- Checkpoints reject stale writers. Configuration review precedes activation;
  completion requires the requested restart, Klipper Ready and firmware verification.
- Existing configuration is reconciled, including SAVE_CONFIG and explicit nested
  user includes. Missing, cyclic, wildcard or outside-root includes fail closed.
- Local activation on the printer host uses a cooperative destination lock,
  comparison of reviewed bytes after staging, atomic replacement per file and
  readback verification. KACE writers using the lock are serialized. An external
  writer ignoring it can still race between comparison and replacement; its edit
  may be lost. Do not save configuration from Mainsail, SSH or another tool during
  deployment. See the [publication contract](en/DEPLOYMENT.md#conditional-publication-and-final-readiness-gates).
- Offline local/SFTP export can create an absent file exclusively but cannot
  replace existing files under this contract. Remote Moonraker upload remains
  blocked for changed plans. Unsupported operations retain a `*-proposed`
  snapshot for operator review; they are not reported as success.
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
   the target. Coordinate with other editors so none save during local deployment.
   Plan manual application for unsupported transports. Resolve all proposal/recovery
   states before claiming completion.
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

### BLTouch and CR-Touch modes

KACE preserves explicit `pin_up_touch_mode_reports_triggered`,
`probe_with_touch_mode`, `pin_up_reports_not_triggered` and `stow_on_each_sample`
from the selected board configuration or printer profile. Conflicting explicit
sources stop generation; compatible values are recorded in the provenance sidecar.
Absent options remain absent, allowing Klipper to choose its defaults. Selecting
BLTouch or CR-Touch does not establish clone identity or physical compatibility.

Existing explicit flags are retained during reconciliation when generation omits
them. This includes flags that an older KACE may have inserted: their origin
cannot be reliably inferred from their values. Review the effective configuration
and follow the [official BLTouch initial tests and clone guidance](https://www.klipper3d.org/BLTouch.html)
before using it on a printer. Do not disable the pin-up checks merely to bypass an
error. Touch mode and probing without stowing require device-specific accuracy
and clearance checks. Parser/loader acceptance and Klipper `Ready` do not supply
this physical evidence. No such operations are performed by the automated tests.

### Mesh clearance

Mesh clearance is a Z coordinate, not a relative lift distance. KACE retains
finite decimal `horizontal_move_z` values from the selected printer profile
(or the parsed configuration when no separate profile is selected). Invalid
values stop generation instead of falling back to a smaller height. Without an
explicit value, the existing KACE policy remains 5 mm for contact/custom probes
and 3 mm for inductive probes; Klipper's absent-option default is 5 mm.

An existing `bed_mesh.horizontal_move_z` is preserved as user tuning, including
when it differs from a newly selected profile. An old KACE fallback cannot be
distinguished reliably from an intentional setting. Review and correct that
existing value explicitly if needed. KACE checks finite values, known Z travel
and the effective standard probe's z_offset, including SAVE_CONFIG, before
publication. These checks do not measure bed tilt, clamps or other obstacles,
and do not qualify runtime HORIZONTAL_MOVE_Z overrides or physical probing.

### Rectangular mesh selection

KACE's automatic mesh selection uses 4x7 or 7x4 bicubic for narrow/long beds that
previously received an invalid 3x7 or 7x3 tuple. Bounds remain unchanged. Explicit
profile counts, algorithm, mesh_pps and tension retain priority over inference;
incompatible choices stop generation. Existing values are preserved as user
tuning during reconciliation, even when a newly generated tuple differs. An old
invalid tuple must be explicitly resolved; KACE does not infer its origin and
silently replace it. Review the effective include configuration when resolving it.

The effective rectangular mesh must allow at least 1 mm between points after
Klipper's hundredth-millimetre spacing truncation. Rounded generated bounds must
remain within the known probeable area. These software checks do not establish
probe accuracy or clearance from clamps, and do not qualify runtime overrides,
adaptive meshes, faulty regions or scan overshoot. Circular mesh generation is
outside KACE's rectangular contract. Continue to follow official physical checks.

### Starter extrusion macros

Newly generated TEST_EXTRUDER, LOAD_FILAMENT and UNLOAD_FILAMENT save the caller's
G-code state, select relative extrusion with M83, and restore with MOVE=0. They
retain their existing 50/50/-50 mm commands and 100/300/300 mm/min feed rates;
M221 and M220 still scale extrusion and feed. They do not heat automatically.
An absent active extruder, cold extrusion status or distance exceeding its
configured limit stops template evaluation before modal changes. Do not raise
the extrusion limit or disable thermal checks just to run a macro.

These guards cannot guarantee that a later command will succeed. An unexpected
toolhead, transport or thermal failure can abort execution before RESTORE;
G-code macros have no automatic finally handler. Stop and establish the intended
machine/mode state before resuming after such an error. Saved names
KACE_TEST_EXTRUDER, KACE_LOAD_FILAMENT and KACE_UNLOAD_FILAMENT belong to these
macros; avoid reusing them in calling macros.

An included user-owned macros.cfg is deliberately preserved and may still contain
an older unsafe body. KACE reports that its starter macros were not deployed;
review that file explicitly before physical use. The K05 correction applies to
newly generated and managed starter macros, not arbitrary user overrides or
macros supplied by Mainsail, Fluidd or other extensions.

### Starter parking macro

New PARK_HEAD requires XYZ homed and a full 5 mm of remaining Z travel. It lifts
vertically first, then moves to the existing derived XY parking point, keeps Z
raised, and restores modal state with MOVE=0. Less than 5 mm remaining causes a
preflight error; the lift is never silently reduced. G92/SET_GCODE_OFFSET do not
shift the XY destination because the macro uses relative machine-space deltas.
The 5 mm choice is KACE policy, not a measured clearance from the printed object.

The generic macro rejects active bed mesh (even when faded), a nonempty excluded
object list, differing toolhead/GCodeMove XYZ positions, and configured bed_tilt,
skew_correction or z_thermal_adjust. The latter three are rejected even when their
current correction is zero/disabled. Those configurations need a separately
reviewed parking macro; do not clear compensation or exclusions automatically
just to bypass this guard. An inactive bed mesh and an empty exclusion list with
matching coordinates are allowed. Third-party transformations are not qualified.

An unexpected command/transport error after the lift can leave the head raised
and the caller's mode unrestored. Establish actual machine and modal state before
recovery. KACE_PARK_HEAD is reserved for this macro. Existing user-owned parking
macros are preserved, so regeneration alone does not prove that an installed
legacy macro changed. Software limits do not prove freedom from physical obstacles.

Record date, operator, OS/image hash, exact board revision, connection topology,
power setup, all source commits, native artifact hash, workflow/proof IDs and logs
with credentials removed. Distinguish automated evidence from physical observations.

Stop on changed/ambiguous device identity, serial or fingerprint mismatch, unsafe
media, unexpected sensor/motion behavior, failed readback, pending activation,
manual recovery or an unresolved transaction conflict. Do not bypass a gate to
finish a test. A successful trial qualifies only the recorded combination.

### Auxiliary electrical outputs: K19-A boundary

Generation preserves active selected-board static digital outputs, including the
SKR Mini E3 V2 USB pullup. Their polarity comes from the source (`!` selects low).
Software checks do not measure levels or prove electrical compatibility. Old
static definitions without active-source evidence require reloading the board;
do not turn commented examples into active circuitry to bypass that check.

Active DAC084S085, AD5206, MCP4451 and MCP4018 currently block generation rather
than silently losing their function. Alligator remains blocked. K19-B2 preserves
digital `output_pin motor_power`, including SKR 2 PC13, with source polarity and
start/shutdown semantics. K19-B3 extends that digital contract to BIQU B1 SE Plus
`probe_enable` and BX `screen`. BX beeper PWM and screen-related button/macros
remain pending: loading successfully does not certify complete board function.
PWM and extra options of the three named outputs are unsupported. Preserve the source and record the
limitation; do not remove the dependency or force a GPIO level to continue.
K19-B1 now checks this subset against the selected board even when recovering an
existing artifact/checkpoint, and against effective destination includes. Missing
board source requires reload/regeneration; a syntactically valid opposite GPIO
level is not equivalent. Remaining peripheral dependencies still need original-
source reconciliation before K19 can close. See ecosystem reports `E5-K19-A.md`
and `E5-K19-B1.md` / `E5-K19-B2.md` / `E5-K19-B3.md` for software evidence and limits; none is an E2E approval.

K19-B4 blocks active selected-board output_pin PWM before generation and saved-
artifact deployment, including BX beeper. The catalog contains 35 such sections
in 14 profiles; some control current, heater enable or expanders. Twenty-six
profiles are guarded in the union with DAC/digipots. Do not omit or convert those
signals to bypass the boundary. Implementation, pin-name case, hardware PWM and
consumers remain pending. Three catalog M300 macros use CYCLE_TIME with output_pin;
the audited official handler does not apply that argument. See `E5-K19-B4.md`.


## 📝 End-to-end evidence and interrupted sessions

For each stage record operator action, visible state, host/MCU evidence and result.
Record commits, time, IP, `cat /proc/sys/kernel/random/boot_id`, uptime, services,
selected by-id/by-path endpoints, checkpoint and before/after configuration.
Remove credentials, keys and Wi-Fi secrets from logs/screenshots.

Use a clean expendable card or preserve its contents first. Record write, readback,
provisioning and native eject separately. Observe discovery and SSH progress without
assuming an old IP. Compare boot IDs around RESTART; an unexpected Pi reboot is
a separate anomaly. Do not toggle a relay merely to exercise the UI; bootstrap
power behavior must match the reviewed physical setup.

On the Pi, local Moonraker uses `127.0.0.1:7125`; a LAN address selects the remote
boundary, not local filesystem authority. New root-v1 installations put hardware
in `printer.cfg`, with provenance separate; existing roots may retain the managed
include layout. Verify loaded settings and firmware identity.

After verified completion, repeat an unchanged proposal and confirm no unnecessary
restart. Test unfinished-session recovery separately at a safe stage, without
interrupting writing/building or cutting power. Resume should retain language/mode
and completed firmware steps. Preserve failures before repair. `Ready` and
`COMPLETE` do not certify endstops, motors, probes or heaters.
