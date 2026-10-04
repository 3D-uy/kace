# KACE development and maintenance

[README](../README.md) · [Roadmap](../ROADMAP.md) · [Release](RELEASE.md)

## 🧭 Architecture and authority

KACE/Python owns printer configuration, hardware decisions, installation and
unfinished recovery. Studio is an independent desktop provisioner, coupled through
`KACE/scripts/bootstrap.sh` and validated events/checkpoints, not a shared package.
Do not duplicate hardware decisions in Studio JavaScript.

| Responsibility | Source |
| --- | --- |
| CLI, wizard and localized outcomes | [kace.py](../kace.py), [core/wizard/](../core/wizard/), [core/translations/](../core/translations/), [core/workflow_outcome.py](../core/workflow_outcome.py) |
| Profile identity and provenance | [core/board_identity.py](../core/board_identity.py), [core/scraper.py](../core/scraper.py), [core/reviewed_source.py](../core/reviewed_source.py) |
| Model, generation and templates | [core/capabilities.py](../core/capabilities.py), [core/generator.py](../core/generator.py), [templates/](../templates/) |
| Effective review and ownership | [core/configuration_review.py](../core/configuration_review.py), [core/reconciler.py](../core/reconciler.py), [core/managed_config.py](../core/managed_config.py) |
| Publication and recovery | [core/config_transaction.py](../core/config_transaction.py), [core/deployer.py](../core/deployer.py), [core/snapshot.py](../core/snapshot.py) |
| Firmware and durable installation | [firmware/](../firmware/), [core/firmware_workflow.py](../core/firmware_workflow.py) |
| Installation and host bootstrap | [install.sh](../install.sh), [scripts/bootstrap.sh](../scripts/bootstrap.sh) |

[VERSION](../VERSION) owns the version; [data/klipper_contract.yaml](../data/klipper_contract.yaml)
owns the validated Klipper revision. [BoardContracts](../data/board_contracts/),
their [schema](../data/board_contracts.schema.json) and
[deployment profiles](../data/firmware_deployments.yaml) bind exact targets,
authority and delivery. [boards.yaml](../data/boards.yaml) supplies reviewed
metadata/overrides; an entry alone does not authorize generation or flashing.
Required sensors, buses, cooling, displays and firmware reservations remain
subject to their Python consumers and reviewed source evidence.

The flow selects sources and user choices, validates, renders under `~/kace/`,
reviews effective destination settings/includes, snapshots, publishes and verifies
activation, loaded configuration and running firmware before `DONE` / checkpoint
`COMPLETE`. Receipts cannot be invented or silently renewed. Stale checkpoint
writers fail; reconnecting or seeing `Ready` does not replace completion evidence.
This applies to initial installation and unfinished resumes, not monitoring later
user edits. See [support](en/SUPPORT_SCOPE.md) and [deployment](en/DEPLOYMENT.md).

[PrinterMotionSpace](../core/motion_model.py) separates mechanical travel,
printable bounds and probe reach. Current keys include `x_position_min`,
`x_position_max`, `x_position_endstop`, `printable_x_min` and `printable_x_max`,
with Y equivalents and Z bounds. Probe-tip position is nozzle position plus offset;
probeable bed is printable area intersected with probe reach. Consumers must use
the shared model and reject an empty intersection. These bounds do not imply
IDEX/toolchanger support or authorize motion outside mechanical travel.

Studio source mode prefers the sibling bootstrap; packaged mode uses its bundled
copy. Preserve stage/error markers, installer tuple, workflow schemas, receipts
and terminal states. Bootstrap changes need checks in both repositories and the
source/packaged gates in [Release](RELEASE.md). Local publication is atomic per
file with a cooperative lock, not directory-wide CAS against external editors.
Recovery preserves live edits when restoration cannot be proven. Do not refactor
state machines solely because modules are large; use a demonstrated need.

## 🛠️ Environment and dependencies

Use Python 3.11 for the KACE CI baseline. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements-dev.txt
```

Runtime intent is in `requirements.in`, optional SSH in `requirements-ssh.in`,
and test dependencies in `requirements-dev.in`. Update an input with its hashed
lock only when dependency changes are intended. With `pip-tools` available:

```bash
pip-compile --generate-hashes requirements.in
pip-compile --generate-hashes requirements-ssh.in
pip-compile --generate-hashes requirements-dev.in
```

The full suite needs a clean `.klipper-contract-source` at the exact
`KLIPPER_REPO_URL` / `KLIPPER_REF` from `tests.klipper_contract`. Follow the source
preparation in [CI](../.github/workflows/ci.yml): fetch the exact revision, detach
and verify HEAD/cleanliness. Do not reset another checkout's work or waive a
missing source. Docker is additionally needed for loader/scenario and build gates.

## 🧪 Validation

Run `python -m pytest <affected-test-file> -q` first, then the affected gates.
Find current suites in [tests/unit/](../tests/unit/),
[regression](../tests/regression/) and [integration](../tests/integration/);
assertions and source inventories are authoritative, not a duplicated test list.

```bash
python -m pytest tests --ignore=tests/results -q -rs
python tests/run_tests.py --verbose
python tests/run_tests.py --yaml-check
python tests/matrix/run_matrix.py --profile quick
python tests/matrix/run_matrix.py --profile full
python tests/regression/validate_snapshots.py
python -m tests.sweep.scenario_contract --artifacts tests/results/reviewed-scenarios
python -m unittest tests.integration.test_simulated_firmware_lab -v
python scripts/check_portability.py
```

Unittest alone misses module-level pytest functions. Matrix/snapshot loading uses
the pinned Klipper parser: byte equality alone is insufficient. `EXPECTED_REJECT`
is not a successful generated config; `KACE_ERROR`, `KLIPPER_ERROR` and
`INFRA_ERROR` fail validation. `--skip-docker` does not prove Klipper acceptance.
The [reviewed-scenario contract](../tests/sweep/README.md) requires a **fresh**
output directory and preserves raw sweep failures while proving supported loads,
concrete boundaries and required input separately. The legacy diagnostic command
`python tests/run_tests.py --full-klipper-sweep --verbose` keeps its own failure
policy; the parser-only helper is not the integrated CI gate.

Record exact source, environment, command, skips and failures with each run.
Generated results belong to ignored output directories while investigating and
must be archived outside the repositories when closed. Keep fixtures, inventories
and their provenance in source control. No automated test may access real storage,
GPIO or printer controllers. Loader acceptance and simulated HTTP/udev/power
behavior do not qualify physical hardware.

Regression fixtures must choose their transport/environment explicitly: a remote
Moonraker mock uses a non-loopback host such as `fixture-printer.invalid`; on POSIX,
loopback selects the local transport and resolves the active config root. Mock
local HTTP responses and temporary directories instead of bypassing validation.
Host/container export tests must control container detection as well as OS name.
Exercise new root-v1 hardware in `printer.cfg` and preserved-root managed includes,
no-change retries with loaded-state verification, cancellation and external edits.

[CI](../.github/workflows/ci.yml) defines triggers and dependencies for lint,
unit/pytest, simulated integration, YAML, snapshots, quick/full matrices, reviewed
scenarios and real firmware builds. Missing infrastructure is not a passing gate.
On Windows, if pytest's shared temporary directory is inaccessible, use
`--basetemp` with a new disposable directory; pytest may clear that target.

Reviewed removable TMC wiring is resolved by `core/tmc_socket.py` from
`data/tmc_sockets.json`, shared by wizard and generation. See the
[TMC socket mapping contract](TMC_SOCKET_MAPPING.md) for scope and focused tests.

## Development container and firmware builds

```bash
docker compose -f docker/docker-compose.yml config --quiet
docker compose -f docker/docker-compose.yml build
docker compose -f docker/docker-compose.yml run --rm --service-ports kace
```

The simulated API uses `127.0.0.1:7125`; avoid a conflicting local service. Select
`12` to exit. `/workspace` is mounted, so generated files there persist. Host
devices are not passed through. The development image's mock make emits text
placeholders, not firmware. Mock provenance is rejected by deployment; do not
copy mock output onto MCU media or assume an external bootloader will reject it.
Size thresholds are plausibility checks, never authorization to flash.

For the **legacy** real-build path, `KACE_REAL_BUILD=1 python3 kace.py` or
`python3 kace.py --real-build` selects `/usr/bin/make` when present. It does not
prove compiler availability or a successful build; no green banner is required.
BoardContract builds use their own exact configuration/proof pipeline.

```bash
docker build -f docker/ci/Dockerfile -t kace-dev .
docker run --rm -v "$PWD:/workspace" kace-dev python3 -m unittest tests/regression/test_mcu_builds.py -v
```

The [build fixtures](../tests/regression/test_mcu_builds.py) fetch the pinned source
into temporary checkouts without changing `~/klipper`, require real compilers and
record skips when unavailable. Fixture clocks, transports and outputs are not MCU
family defaults or a firmware distribution channel. A copied real output from
`~/kace/` still needs its identity/proof, exact board/variant/clock/transport and
bootloader method; do not rename it to a trigger filename merely because it built.

BoardContract builds use persistent bare sources in `~/.cache/kace/sources/` and
disposable workspaces in `~/.cache/kace/workspaces/`. `KACE_CACHE_HOME` or
`XDG_CACHE_HOME` can relocate them. The cache requires its repository marker,
exact commit, bare state and Git integrity; failed validation causes atomic rebuild.
Each build uses a clean detached checkout. Config, fingerprint edits, logs and
outputs are not cached. Explicit tmpfs/ramfs/devtmpfs staging is rejected; require
at least 1 GiB before source preparation and 2 GiB before checkout/build. Per-run
workspaces are cleaned afterward. Pi 3 uses `make -j2`; other hosts use bounded
CPU/memory-aware jobs and periodic progress instead of flooding the terminal.

Legacy `BuildArtifact` and BoardContract proof/plan/executor authorities are
separate. A valid BoardContract proof cannot enter legacy execution by changing
`flashable`. Selected artifact bytes, target/media and route are rechecked before
writes; USB reappearance alone does not prove the running build. See
[hardware qualification](HARDWARE_TESTING.md) and the upstream instructions at the
[reviewed Klipper pin](https://github.com/Klipper3d/klipper/blob/fe4eb8650bd7de4c2100a14eaf09b0965c430e29/docs/Bootloaders.md).

## Contribution, snapshots and documentation

Keep changes scoped and backed by defect coverage. For board/generator changes,
review exact identity, all mandatory dependencies, YAML pattern precedence,
generation/publication/recovery and matrix coverage; do not add support by dropping
unsupported circuits. Preserve gates, receipts, rejections and rollback.

Only intentionally changed output contracts may update snapshots. Review every
fixture; never regenerate to hide a failure. When explicitly authorized:

```bash
python tests/run_tests.py --update-snapshots
git diff -- tests/fixtures
python tests/run_tests.py --verbose
python tests/regression/validate_snapshots.py
```

Use branches and PRs; respect required checks, updated-branch and protected-main
rules. Report pre-existing release failures rather than repinning or waiving them.
Keep personal paths and secrets out of all tracked files, including fixtures.
Issues need revision, environment, exact board/MCU, source profile, workflow and
sanitized reproduction; vulnerabilities follow [Security](../SECURITY.md).

README and ROADMAP are the primary EN/ES/PT entry points. Change all three for
user steps, limits or priorities. Link detailed engineering procedures to one
canonical source. Keep current candidate notes in [CHANGELOG](../CHANGELOG.md);
archive old audits, run results and superseded guides locally outside both repos.
