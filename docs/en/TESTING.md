# KACE testing guide

KACE uses complementary test layers. A passing unit suite is necessary, but generated Klipper configuration also has to match project snapshots and load through the parser from the pinned Klipper revision.

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --require-hashes -r requirements.txt
```

Docker is additionally required for the configuration matrix and containerized firmware builds.

## Core commands

```bash
# Unit and regression discovery
python tests/run_tests.py --verbose

# boards.yaml schema and pattern precedence only
python tests/run_tests.py --yaml-check

# Reduced generated-config matrix against pinned Klipper
python tests/matrix/run_matrix.py --profile quick

# Full pairwise matrix for manual or pre-release validation
python tests/matrix/run_matrix.py --profile full

# Broad sweep of upstream Klipper generic/printer configs
python tests/run_tests.py --full-klipper-sweep --verbose

# Hardware-free physical-workflow integration lab
python -m unittest tests.integration.test_simulated_firmware_lab -v
```

Use the narrowest command that covers a change, then run the complete relevant gate before submitting it.

## Test layers

### Unit tests — `tests/unit/`

Unit tests cover the wizard model, validation, board data, generation helpers, firmware derivation, deployment, Moonraker, SSH, translations, CLI contracts, bootstrap/install contracts, and matrix construction. Hardware, prompts, network calls, subprocesses, and external files are mocked where applicable.

Firmware orchestration fixtures that mock `MoonrakerConfigTransport` must use an
explicit remote host (for example, `fixture-printer.invalid`). On POSIX, a
loopback host selects `LocalMoonrakerConfigTransport` and discovers Klipper's
active `config_file` through Moonraker before acquiring the destination lock.
Leaving the default `localhost` in a remote fixture can therefore pass on
Windows but attempt a real HTTP request in Linux CI. Tests of local discovery
must provide the Moonraker responses and a temporary configuration directory;
do not bypass production target validation to make remote fixtures pass.

Export-prompt fixtures also select host versus container execution explicitly.
Mocking `platform.system()` alone does not hide the runner's `/.dockerenv`;
host prompts and Docker's mounted-path guidance have separate regression cases.

Configuration retry regressions distinguish matching files from active Klipper
settings: an explicit activation choice still applies to an unverified retry,
while a verified no-op checks the loaded settings without prompting or
restarting. New/root-v1 installations publish hardware in `printer.cfg`; existing
user roots retain `kace/generated-hardware.cfg`. Ownership and concurrent-edit
regressions cover both layouts and preserve external edits for manual recovery.

### Regression tests — `tests/regression/`

Regression tests exercise complete generation paths, CLI integration, runtime behavior, firmware build orchestration, and byte-level snapshots in `tests/fixtures/`.

The default runner discovers every `test_*.py` file under `tests/`. Environment-dependent real firmware builds skip when their required toolchain is unavailable; CI separately runs representative builds in the development container.

### Simulated hardware integration — `tests/integration/`

The deterministic integration lab runs the production Moonraker HTTP adapter,
Power API controller, firmware deployment strategies, MCU presence monitor,
firmware build-identity verification, configuration upload, and rollback
against stateful loopback Moonraker and udev simulators. It covers successful
SD and AVRDUDE workflows plus stale firmware, wrong VID/PID, ambiguous identity,
timeouts, corrupted uploads, and failed activation.

This gate never opens a physical serial device, GPIO, or removable disk. A pass
proves software ordering and failure semantics, not electrical behavior, Linux
permissions, real USB timing, bootloader behavior, or media compatibility.

### YAML integrity

```bash
python tests/run_tests.py --yaml-check
```

This gate parses `data/boards.yaml`, checks required top-level and entry fields, detects a generic firmware pattern that would shadow a more specific pattern later in the file, and validates `data/firmware_deployments.yaml` through the deployment-profile loader.

### Generated-config matrix — `tests/matrix/`

The matrix generates each accepted case through KACE, stores it with a deterministic ID, and loads it inside Docker with the exact Klipper commit declared by `data/klipper_contract.yaml` (consumed through `tests/klipper_contract.py`).

Results are classified as:

| Result | Meaning |
| --- | --- |
| `PASS` | KACE generated the case and pinned Klipper accepted it |
| `EXPECTED_REJECT` | KACE safely rejected a deliberately unsupported combination |
| `KACE_ERROR` | Generation failed unexpectedly |
| `KLIPPER_ERROR` | Generation succeeded but Klipper rejected the result |
| `INFRA_ERROR` | Docker or the validation environment failed |

An expected rejection is not counted as a pass. Reports and generated configurations are written under `tests/matrix/artifacts/` as Markdown and JSON; this directory is ignored by Git.

`--skip-docker` is only a matrix self-test and reports generated cases as infrastructure errors. It must not be presented as Klipper validation.

### Full Klipper sweep — `tests/sweep/`

The release-supported Klipper revision is `validated_commit` in `data/klipper_contract.yaml`, already used by BoardContract. The scraper (including revision-scoped caches), sweep, matrix and legacy MCU build tests consume this contract. Standalone bootstrap mirrors it because it runs before KACE is installed; `tests/unit/test_klipper_sweep_contract.py` rejects divergence. To update a release, review the YAML pin and per-board evidence, synchronize `scripts/bootstrap.sh` and Studio's bundled copy/hash, and rerun the contract and compatibility checks. Promote Studio's `bootstrap_ref` to the resulting KACE commit when committing the release. Upstream `master` monitoring remains read-only. Pre-baked installations and user-managed local Klipper checkouts retain their existing ownership policy; these tests do not certify arbitrary installed revisions.

The sweep clones the Klipper `config/` tree at the exact commit declared by `data/klipper_contract.yaml` (consumed through `tests/klipper_contract.py`), verifies the detached checkout's `HEAD`, parses its `generic-*.cfg` and `printer-*.cfg` files, and classifies known unsupported inputs separately from unhandled failures. It requires Git and network access. The sweep and generated-config matrix deliberately share the same immutable upstream identity: the sweep tests breadth of upstream examples, while the matrix tests representative KACE output through Klipper's real loader.

The sweep report is generated output and is not committed.

## Snapshot policy

Snapshot fixtures are public output contracts. When an intentional generator change alters output:

```bash
python tests/run_tests.py --update-snapshots
git diff -- tests/fixtures
python tests/run_tests.py --verbose
```

Review every changed fixture. Never update snapshots to hide an unexplained failure or as part of an unrelated change.

## Docker validation

Build the development image with:

```bash
docker build -f docker/ci/Dockerfile -t kace-dev .
```

For the interactive simulation menu, Compose provides the same image and mounts
the repository at `/workspace`. Run these commands from the repository root:

```bash
docker compose -f docker/docker-compose.yml config --quiet
docker compose -f docker/docker-compose.yml build
docker compose -f docker/docker-compose.yml run --rm --service-ports kace
```

The simulated Moonraker API is available only on `127.0.0.1:7125`. Stop any other
local service using that port before starting the menu. Select `12` to exit;
`--rm` removes the container. Generated files under `/workspace` remain in your
checkout. No host devices are passed through to the container.

Run the representative MCU build suite with the same layout as CI:

```bash
docker run --rm -v "$PWD:/workspace" kace-dev \
  python3 -m unittest tests/regression/test_mcu_builds.py -v
```

Mock firmware created by the interactive development container is not flashable. Only a successful real-toolchain build can produce a candidate firmware artifact, and even that artifact must be verified for the exact controller before use.

## CI mapping

`.github/workflows/ci.yml` currently provides these gates:

| Job | Trigger | Validation |
| --- | --- | --- |
| `lint` | Push, pull request, and manual dispatch | Compile every Python file; run `bash -n` and pinned ShellCheck over critical scripts |
| `unit-tests` | Push and pull request | Full default test discovery |
| `simulated-hardware-integration` | Push and pull request | Stateful Moonraker/power/udev firmware workflow without physical devices |
| `yaml-integrity` | Push and pull request | Board schema and precedence |
| `regression-tests` | Push and pull request | Snapshot regression gate |
| `config-matrix-quick` | Push and pull request | Reduced pinned-Klipper matrix |
| `full-klipper-sweep` | Push to `main`, or manual dispatch with `full_klipper_sweep=true` | Broad pinned upstream config sweep |
| `config-matrix-full` | Manual dispatch | Full pairwise pinned-Klipper matrix |
| `docker-firmware-build` | Push and pull request | Representative real MCU builds in Docker |

CI never updates snapshots and no test job flashes physical hardware.
