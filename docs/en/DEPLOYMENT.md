# KACE Deployment System: SSH vs. Moonraker API

This document explains in detail how KACE deploys generated configuration files (`printer.cfg` and `macros.cfg`) to a Klipper-enabled 3D printer. It covers the underlying mechanisms, protocols, security considerations, verification processes, manual recovery policy, and a comparison to help you choose the best deployment method.

---

## Transaction safety and MCU identity

Firmware checkpoint deployments verify the running build fingerprint inside the
configuration transaction, after activation and Klipper `Ready`, before emitting
`DONE` or returning `COMMITTED`. A mismatched or unavailable fingerprint triggers
configuration recovery. Idempotent deployments still require review acceptance,
explicit activation and fingerprint verification, but have no new writes to roll
back. Matching files and an already-Ready service do not prove those files were
loaded. Explicitly deferred activation remains pending, including on retries.
The physical installation transaction rechecks its firmware targets after the
final restart as well.

The normal configuration review lists existing settings that will be replaced or
removed, including their file, section, option and previous/planned values. This
also covers removed managed sections and customized managed macro bodies; opening
the advanced diff is not required to see these warnings. Established tuning
preservation rules and user-owned sections still apply.

Checkpoint publication compares the exact revision originally read while holding
the shared cross-process file lock. Stale writers fail even if they locally
advanced to a higher sequence. Starting a new workflow uses an explicit expected
revision captured before the wizard; it cannot overwrite a concurrent update.
Persistence failure stops the CLI before subsequent actions. Runtime revision
evidence is not serialized, so existing v1 checkpoint consumers remain compatible.

Manual MCU verification compares all compatible, present serial candidates with
the physical identity captured when the original MCU was selected: USB topology,
VID/PID and serial evidence. A matching model alone is insufficient. Missing or
changed evidence requires explicit cable-tracing confirmation; multiple ambiguous
candidates require disconnecting the other devices and retrying. Older checkpoints
without captured physical evidence require the same confirmation. Auto mode cannot
confirm ambiguity. Accepted evidence and any manual confirmation are persisted.

Automatic recovery never performs a read-then-write restore. The current local,
SFTP and Moonraker file APIs provide no atomic content-conditional replacement or
deletion against independent editors. When an attempted write differs from its
snapshot, KACE preserves current files, reports `ROLLBACK_FAILED` (or a failed
physical recovery), retains the durable snapshot and does not restart services
as if restoration had succeeded. Files already restored externally are verified
without mutation.

For manual recovery, stop deployment and coordinate with other editors. Open the
reported snapshot directory: `snapshot.json` lists original files, SHA-256 values
and originally absent paths. Original bytes are stored there with `/` encoded as
`__` in filenames. Compare live edits before restoring the chosen originals or
removing newly created files; then restart and verify Klipper and the firmware
identity. Do not blindly copy the entire snapshot over a concurrently edited
configuration.

Both configuration and physical rollback use `snapshot.verify_snapshot_restored`
to compare each attempted target to the
snapshot before restarting and again before reporting recovery success. Files
originally absent must be absent, and unreadable state cannot count as successful
recovery. Klipper `Ready` alone does not prove that restoration succeeded.

Hardware-free regression command:
`python -m unittest tests.unit.test_deployment_p1 tests.unit.test_stabilization_p2 -v`.

### Maintenance decision after P1/P2 stabilization

The two rollback routes had diverged: physical recovery rechecked restored bytes
after restart, while configuration-only recovery could report success after an
external edit during that restart. They now share the exact snapshot postcondition
and check it before activation and before reporting recovery success. Their distinct
physical/configuration orchestration remains separate.

The remaining size and concentration of orchestration in `core/deployer.py`,
`kace.py` and Studio's `main.py` are maintenance debt, not a demonstrated reason
to split modules or unify state machines. No broad refactor is scheduled on size
alone; revisit extraction when a concrete behavioral divergence requires it.

## 1. Overview of KACE Deployment

After KACE generates `printer.cfg` and `macros.cfg` (stored locally in `~/kace/`), it offers two primary methods to push these configurations directly to your printer:

1. **SSH / SFTP (Push to Host)**: Transfers configuration through the host filesystem; Moonraker handles activation and readiness.
2. **Moonraker API (Web Push & Control)**: Communicates with Moonraker (the API server for Klipper web interfaces like Mainsail/Fluidd) via HTTP.

Additionally, KACE supports **local copying** and **USB/SD card export** for manual installations.

---

## 2. Shared configuration transaction

SSH/SFTP and Moonraker use `ConfigDeploymentTransaction`. Both read the root,
managed includes and existing Moonraker configuration, build the same plan,
present the semantic review and diff, and capture a persistent snapshot before
writing. Snapshots contain original bytes and explicit evidence of absent files;
they are not `.bak` renames or memory-only backups.

KACE revalidates the reviewed state after snapshot persistence and each file
immediately before replacing it. Includes are uploaded before the root. Every
planned artifact is read back and compared with its planned bytes. Activation
uses Moonraker for both transports: firmware restart, Klipper service restart,
or explicit deferred activation. SFTP has no automatic systemd fallback.

After activation, KACE waits for stable Klipper Ready, checks the expected MCU
build fingerprint when a firmware checkpoint is involved, and rechecks config
bytes before committing. Deferred activation remains pending. A failure invokes
recovery only for files still owned by KACE's attempted writes; external edits
are preserved and reported as conflicts. Restored bytes are checked before and
after the recovery restart. The physical deployment route has equivalent upload
and post-activation checks.

These checks detect changes between workflow stages. Remote HTTP/SFTP APIs do
not provide atomic compare-and-swap against arbitrary external editors: avoid
editing configuration during deployment. A conflict requires operator review;
KACE does not claim successful recovery when another writer's content survives.

## 3. Calibration and generated macros

Klipper `SAVE_CONFIG` calibration values must remain effective. KACE keeps
calibratable defaults (heater PID, probe offset, endstop position and input
shaper settings) in its marked root block rather than in generated includes.
Existing autosave values suppress corresponding generated defaults. Klipper can
then comment root values out on a later SAVE_CONFIG without include conflicts.
The semantic review considers root calibration and effective autosave values.
A saved heater calibration conflicting with a newly selected control mode
requires explicit resolution before deployment.

A macros artifact is loaded only when the current generated configuration
includes it. An old `~/kace/macros.cfg` is not implicitly reactivated by a later
run that omitted macros. User-owned includes retain their existing ownership.

## 4. Choosing the transport

| Property | SSH/SFTP | Moonraker |
| --- | --- | --- |
| Upload access | OS account, verified SSH host key, Paramiko | Moonraker endpoint and optional API key |
| File destination | Explicit host configuration directory | Moonraker config root |
| Activation and Ready checks | Moonraker | Moonraker |
| Recovery | Preserve live files and durable snapshot; manual reconciliation when restoration is needed | Same conservative recovery policy via HTTP |
| Publication | Atomic creation of absent files only; replacements require manual application | Reviewed proposal requires manual application |
| API unavailable | Cannot bind destination to active Klipper; deployment stops | Cannot review or confirm activation |

Unknown SSH host keys require explicit fingerprint confirmation and are stored
in known_hosts. API keys sent over unencrypted HTTP require confirmation.
Neither route claims success from systemd status alone or automatically fetches
journalctl logs. A Moonraker connection failure may offer the SFTP transport;
this changes file transfer, not the activation authority.

## 5. Firmware staging and first installation

The legacy builder serializes use of its shared Klipper checkout through artifact
publication and rejects build inputs that changed during compilation. USB serial
bridges may retain their Arduino-style by-id name after flashing; accepting one
requires the contracted bridge identity and positive evidence of the originally
selected physical device. The final MCU fingerprint check is still required.

During first installation, the opt-in BoardContract SD path may produce a
`MCU_REENUMERATED` proof while configuration is still absent. That proof is not
`VERIFIED`; the main workflow continues through generation and the configuration
transaction, which verifies the running firmware before completion. Standalone
physical execution retains its full Klipper/fingerprint verification behavior.

The legacy editor's MCU/offset fields are translated to writable Klipper
Kconfig choices before `olddefconfig`. Resolution must retain every requested
choice and application address; unsupported or ambiguous targets fail closed.
Build fingerprints use Klipper's `buildcommands.py --extra` API and are checked
in the binary metadata before publication (including UF2 and Intel HEX payloads).
Runtime verification accepts the exact build marker as Klipper's version suffix.

Final configuration verification includes unchanged reviewed files. Explicit
active calibration overrides retain precedence over older SAVE_CONFIG values;
generated defaults do not override saved calibration. Installer recovery leaves
the original runtime untouched when its backup rename fails, and retains both
transaction directories if restoration fails.

STM32 legacy builds require an explicit board reference clock. The exact Octopus
v1.1 F446/F429 selections use the pinned upstream 12/8 MHz crystal requirements;
other legacy STM32 boards require an operator selection and cannot guess in auto
mode. The selected clock survives real Kconfig resolution and enters build identity.
Deployment profiles understand resolved MCU models and application addresses.

Checkpoint artifact hashes come from immutable build identity, never from
re-baselining a potentially replaced output file. Staged/transformed hashes and
sizes must agree before checkpoint publication, and contradictory saved evidence
is rejected on resume. Missing generated printer.cfg is regenerated from the
verified checkpoint without repeating firmware compilation or flashing.

## Conditional publication and final readiness gates

When the deployment menu offers Moonraker on this Raspberry, KACE fixes the
Moonraker host to `127.0.0.1` and asks only for the port (default `7125`). Saved LAN
hosts and remote API keys are not reused for this local action. The existing
active-config and config-root checks still determine filesystem authority.

In root-v1 layouts, `[include mainsail.cfg]` appears below the layout header and
before the generated hardware block, so printer settings follow Mainsail defaults.
Reconciliation also moves an existing trailing Mainsail directive to that position;
other user includes retain their order and SAVE_CONFIG remains at the end.

The accepted local publication contract (19 September 2026) uses cooperative
locking, a final content comparison and atomic replacement. On the printer host,
`LocalMoonrakerConfigTransport` binds the loopback Moonraker endpoint to the active
config root and holds `.kace-deploy.lock` from review through activation. KACE
transactions using that destination lock are serialized across processes.
Originals are snapshotted before publication; each replacement is staged and
fsynced on the same filesystem, compared against the reviewed live bytes, then
published atomically and read back before restart. Creating an absent file uses
exclusive creation, so a file created meanwhile is not replaced.

This is not an atomic compare-and-swap (CAS) against arbitrary external writers.
An editor that ignores the lock can write between the final comparison and
replacement, and its edit may be overwritten without detection. Mainsail edits,
SSH editors and other tools must not save configuration during KACE deployment.
The lock does not disable them. Conflicts detected during review or staging abort
publication and retain live content and a recoverable proposal. Atomicity is per
file, not an all-or-nothing update of the entire config directory; interrupted
multi-file publication may need recovery from the snapshot.

Offline local export and SFTP support exclusive creation of absent files but
still reject replacement of existing files. Remote Moonraker upload supports
neither guarded operation and remains blocked for changed plans. Unsupported
plans are rejected before live writes and retain a `*-proposed` snapshot using
the layout described above. Manual application requires comparing current files
with the proposal before rerunning KACE. Automatic rollback is not enabled by
the cooperative publication contract: failed activation preserves live files and
snapshots rather than blindly restoring earlier content.

Preflight reads explicit relative user includes recursively and reviews their
actual linear precedence, matching Klipper. Included files remain user-owned and
are revalidated through activation. Missing, cyclic, wildcard, absolute and
out-of-root includes fail closed; enumerate wildcard dependencies explicitly
before retrying. An include cannot override the selected MCU serial. SFTP checks
the destination's resolved `printer.cfg` against Moonraker `/printer/info`'s
active `config_file`; Moonraker checks its `config` file root against that path.
Unavailable or mismatched activation evidence prevents deployment.

Bootstrap power recovery likewise preserves `moonraker.conf`, `power.json` and
their adjacent `.kace-power-backup.*` backups. It reports prior absence or each
backup path and requires manual recovery when bytes differ, without restarting
Moonraker under a false restoration claim.

AVRDUDE consumes the exact bytes rehashed after operator confirmation through
stdin (`flash:w:-:i`); it never reopens the staged filename. Legacy Octopus v1.1
F446/F429 verification accepts only the pinned Kconfig model spellings for those
same variants. Model aliases do not weaken physical identity checks, and a build
for another model cannot advance the original hardware checkpoint.
