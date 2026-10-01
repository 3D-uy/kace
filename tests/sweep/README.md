# Full sweep and reviewed scope

Run the original parse/generate/pinned-Klipper pipeline from the repository root:

```sh
python tests/sweep/full_sweep_runner.py --artifacts <new-output-directory>
```

`--without-display` exercises the existing explicit no-display wizard choice.
It does not supply a probe, additional Z motors, TMC mode, geometry or consent
to thermal policy. Neither scenario certifies a board or a physical machine.

Before generating any file, `scope_inventory.py` verifies all official
`generic-*.cfg` and `printer-*.cfg` sources against `support_inventory.json`:

- the revision must match the authoritative Klipper pin;
- filenames must match exactly, with no new, missing or duplicate entries;
- UTF-8 source content must match its reviewed SHA-256 after newline normalization;
- schema, disposition and scenario must be recognized and consistent.

Each source is checked again when read for generation. An inventory failure
blocks the run and is recorded in `infrastructure_error`; it cannot produce a
successful empty sweep. Reports and the loader manifest include the inventory
digest and source hashes. The default CLI and exit policy are unchanged.

## What the inventory means

The initial inventory records the pinned sources reviewed during the K04/K19
remediation and E7 reconciliation. Its source of review is the ecosystem's
E7-R evidence, derived from the E7-P complete scope reconciliation. These are
reviewed scenarios, **not expected-failure exemptions**:

| Disposition | Count | Remaining obligation |
| --- | ---: | --- |
| LOAD_EVIDENCE, baseline without display | 114 | Generate and validate output; preserve hardware contracts. |
| LOAD_EVIDENCE, explicit probe selection | 22 | Replay supported probe choices and validate preserved options. |
| LOAD_EVIDENCE, explicit motor selection | 6 | Replay supported TMC/Z choices and validate hardware associations. |
| LOAD_EVIDENCE, explicit thermal review | 2 | Replay explicit review and validate the policy/receipt. |
| NEEDS_USER_INPUT | 1 | Do not invent missing probe X/Y geometry. |
| SOURCE_DEPENDENCY_BLOCKED | 29 | Prove the specific hardware boundary and no emitted artifacts. |
| GENERATION_INPUT_INCOMPLETE | 6 | Do not invent an active bed circuit from missing/commented pins. |
| KACE_CAPABILITY_LIMIT | 12 | Preserve declared KACE limits; upstream support is not KACE support. |

`LOAD_EVIDENCE` describes the prior reviewed route; it is not a PASS awarded to
the current run. The runner still fails on generation errors, loader errors,
missing validator results and unavailable infrastructure, including rows whose
disposition says a dependency is blocked. No regex allowlist or blanket
`GenerationError` waiver is applied. The existing UNSUPPORTED/SAFE_ABORT policy
is unchanged.

When the upstream pin or a reviewed scenario changes, reconcile the sources,
support boundary and class tests before explicitly editing this inventory.
Do not regenerate it from failing results or add support solely to empty it.
Comments are hashed too; only CRLF/LF representation is normalized.

This inventory check is the first part of the supported-scenario CI contract.
The integrated contract below is the full-sweep CI gate and retains the raw
explicit-no-display outcomes. Exact hosted verification remains pending. Initial installation and unfinished
resumptions remain the product boundary; it introduces no post-DONE monitoring.

## Concrete negative scenario contract

```sh
python -m pytest tests/unit/test_sweep_boundaries.py -q
```

Prepare the clean authoritative Klipper checkout at `.klipper-contract-source`
as for the existing compatibility suites. Missing source, a wrong revision,
dirty source or inventory drift fails the tests; it is not a skip. No network
fetch or Docker loader is performed by this negative-only suite.

`boundary_contract.py` verifies all 192 source identities first, then exercises
all 47 reviewed negative rows grouped into seven functional classes:
electrical dependencies (21), homing (4), cooling classes (2), fan options (2),
absent bed circuit (6), unsupported kinematics (10), and motion policy (2).
Each row is hashed again at use, checked against active source dependencies,
and replayed through the real headless generation fixture. The observer records
the actual `GenerationError` before the raw runner formats it; an unrelated
exception with the same message cannot satisfy the contract. Delta must be
rejected before generation and by the direct capability validator.

All output directories must remain empty, including provenance or unexpected
files. The 29 source-dependency rows also exercise selected-source artifact
validation and a JSON-roundtripped unfinished checkpoint. A rejection during
source recovery is valid; it must have the concrete expected hardware reason.
Tests attack the harness with unrelated exceptions, missing rejection, partial
files, parser failures, source drift and revision/cleanliness failures.

Passing this suite proves these rejection boundaries only. It does not convert
the raw sweep's FAILURE/UNSUPPORTED records to PASS, prove positive generation,
load configuration in Klipper, or qualify boards. The guided positive routes
are separate from this negative-only suite.

## Guided probe contract

```sh
python -m pytest tests/unit/test_sweep_probes.py -q
python -m tests.sweep.probe_contract --artifacts <new-output-directory>
```

The unit suite replays generation and checks the harness. Only the second
command additionally requires the existing Docker validator to load every
generated config with pinned Klipper; Docker failure, missing/extra results,
failed loads or incomplete coverage prevent success. It writes a source-bound
manifest and report. An existing output directory is refused to prevent stale
artifacts/results being reused. The CI-wide gate is not yet reconciled.

The complete inventory is checked before selecting 23 reviewed probe scenarios:
13 BLTouch, nine guided custom probes and one missing-X/Y case. Fixture answers
come from the reviewed source; custom defaults are explicitly accepted by the
test, and a generic `[probe]` is never relabeled as Inductive. The actual wizard
offset prompts and confirmation run with test answers. Every explicit source
option is checked, including pins, flags, timing and sampling. A generic
`lift_speed` can use the Klipper speed default only when numerically identical.
Unknown guided options fail rather than silently disappearing.

BLTouch `z_offset: 0` remains the existing calibration placeholder with a
PROBE_CALIBRATE instruction. It is recorded separately from hardware-option
preservation. Recorded offsets for these tests are not physical measurements.
For the incomplete profile, cancelling the real geometry prompt leaves no typed
payload; the wizard retries and direct generation rejects with the concrete
missing-configuration error, without writing files. No geometry is invented.

Results cover these scenarios only. The integrated gate below also checks the other classes.
Raw sweep results are unchanged;
successful guided loads do not turn the original no-probe fixture into PASS.

## Guided motor/TMC contract

```sh
python -m pytest tests/unit/test_sweep_motors.py -q
python -m tests.sweep.motor_contract --artifacts <new-output-directory>
```

The complete source inventory precedes six guided scenarios grouped into four
UART, one SPI and one without TMC selection. Existing wizard steps select the
reviewed driver/mode and Z count. Unexpected socket/current prompts fail instead
of inventing answers. Required probes reuse the guided probe helper; physical Z
endstop routes do not qualify optional probing.

All explicit TMC options and selected motor hardware fields are compared, as
are every explicit controller-fan option and any required probe options. Motor
and TMC section inventories must match. The six configs then require both the
existing official loader and `motor_objects.py` in that same pinned image.
The latter checks actual Z rail motors, physical endstop ownership and
controller-fan consumers using its object-resolution callback only.

Virtual probe endstops use upstream `HomingViaProbeHelper`, whose get_steppers()
is deliberately empty. The contract separately checks that helper's type and
the rail's Z motors; it does not dispatch mcu_identify or claim verification of
later probe/MCU attachment. No global connect/ready event, homing or G-code runs.

Two control copies must fail for concrete reasons: removing an independent
Z endstop must change ownership, and a nonexistent fan consumer must be rejected
by the official callback. Original generated files remain intact. Missing,
extra, incorrect or unavailable official results block success; the fresh
output-directory rule also applies here. Unit tests alone are not official
loads; the integrated gate below includes this CLI. No physical motor
tuning or board qualification is implied.

## Explicit thermal-review contract

```sh
python -m pytest tests/unit/test_sweep_thermal.py -q
python -m tests.sweep.thermal_contract --artifacts <new-output-directory>
```

The full reviewed inventory precedes two scenarios with explicit nondefault
heater-bed verification policies (240/600 seconds). They must reject unreviewed
generation, automatic consent and declined review. Simulated test acceptance
defaults to No, previews must not write, unchanged receipts can be reused, and
MCU changes require review again. Saved JSON checkpoints preserve the receipt;
changed policy or heater circuitry in the recovered artifact must reject.

The command requires official loading for both generated files, six numeric
controls (two valid, four rejected for their specific official bounds), and
nine synthetic HeaterCheck traces. `thermal_traces.py` runs in the pinned loader
image with artificial temperature readings/event times and captures the shutdown
request. It never connects an MCU, heats hardware or measures real-time safety.
The traces cover a non-heating fault, target zero and temperature at target for
the default 60-second bed policy and the two reviewed policies. Extruder defaults
and the other HeaterCheck parameters are also checked.

Incomplete/incorrect traces or loader results, infrastructure failures and stale
output directories cannot pass. Source choices and simulated consent do not
certify a heater, recommend policy values or approve a real user's installation.
All prior raw sweep outcomes remain unchanged. The integrated local command
below includes this class in the full-sweep CI gate.

## Integrated reviewed-scenario contract

```sh
python -m pytest tests/unit/test_scenario_contract.py -q
python -m tests.sweep.scenario_contract --artifacts <new-output-directory>
```

This command verifies every one of the 192 reviewed sources in one run. It
requires a clean pinned `.klipper-contract-source`, the exact source inventory
and Docker. Existing output directories are refused. The sequence is:

1. Replay the unchanged explicit-no-display raw fixture for all 192 sources.
   Preserve original codes, details and artifacts. Load all 114 baseline
   outputs with pinned Klipper; missing/extra/invalid results fail the contract.
2. Independently replay the 47 concrete boundaries through the negative class
   contract, requiring typed rejection, active dependencies, empty output and
   applicable artifact/recovery guards. The raw reason/code must match.
3. Execute the existing probe, motor and thermal contracts, including all their
   official loader, object, numeric and synthetic-temperature controls.
4. Require exact, disjoint scenario membership, source identity and complete
   evidence. Verify the source inventory again before accepting the run.

Success requires **144 LOAD_VERIFIED**, **47 BOUNDARY_VERIFIED** and
**one INPUT_REQUIRED_VERIFIED**. Those labels are scenario proof results, not
raw sweep PASS or board qualification. `raw-headless-results.json` still reports
114 PASS, 68 FAILURE and ten UNSUPPORTED, with `successful: false`. The existing
raw sweep commands and their exit policy are unchanged. The original automatic
display-selection fixture is not rerun by this explicit-no-display command.

`report.json` contains the partition, raw observation for every source, source
receipt and hashes of the underlying artifacts/reports. The class folders retain
their detailed evidence. Failed generation, unexpected success of an unreviewed
raw fixture, incomplete class coverage, wrong source or unavailable infrastructure
cannot be turned into an accepted expected failure. Partial runs save a failed
report and available observations; no empty run can pass.

The `full-klipper-sweep` CI job now runs this command after checking out the
pinned source. Its existing required-check name, PR/main/manual triggers,
regression dependency, action pins and locked runtime dependencies remain intact.
The artifact directory is `tests/results/reviewed-scenarios/`; `always()` uploads
the entire tree, including partial failures, raw observations, generated configs,
loader reports, class controls and hashes. Missing evidence is an upload error.
There is no `continue-on-error`, expected-failure allowlist or successful empty run.

The legacy raw CLI remains available with its original failure exit policy. The
CI acceptance criterion is the reviewed scenario contract, not approval of the
old automatic-display/no-probe/one-Z fixture. That default fixture is not executed
by this job; display coverage remains in the existing matrix and source tests.
Exact hosted execution and physical qualification are separate from local gate
validation; this change adds no post-DONE supervision or support expansion.
