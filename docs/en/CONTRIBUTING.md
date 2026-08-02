# Contributing to KACE

KACE generates configuration and firmware artifacts for physical machines. Keep contributions small, reviewable, and backed by the narrowest test that proves the intended behavior.

## Development setup

```bash
git clone https://github.com/3D-uy/KACE.git
cd KACE
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --require-hashes -r requirements.txt
python tests/run_tests.py --verbose
```

Python 3.11 is the CI baseline. Docker is required for the pinned-Klipper matrix and containerized firmware validation.

## Repository contracts

- `VERSION` is the single project-version source.
- `data/boards.yaml` owns board detection, BLTouch pin overrides, and firmware patterns.
- `templates/` and generator code jointly define generated output; snapshots protect that contract.
- Generated user artifacts remain under `~/kace/`.
- `scripts/bootstrap.sh` is an integration contract with KACE Studio. Its stage/error markers and pinned installer tuple must be changed deliberately and tested in both repositories.

Read the root README and the ecosystem architecture documents before changing a cross-repository flow.

## Dependency changes

Top-level dependency intent lives in:

- `requirements.in` for runtime dependencies.
- `requirements-ssh.in` for optional Paramiko support.

The matching `.txt` files are generated lock files with hashes. Do not edit only the lock file.

```bash
python -m pip install pip-tools
pip-compile --generate-hashes requirements.in
pip-compile --generate-hashes requirements-ssh.in
```

Review and commit each input together with its regenerated lock.

## Board and generator changes

For a board-data change:

1. Add or update the narrowest `data/boards.yaml` entry.
2. Keep specific firmware match patterns before generic parents.
3. Run the YAML gate.
4. Add unit coverage for detection/derivation.
5. Add or review a generated-output snapshot when the board introduces distinct output.
6. Confirm the board is represented by the full configuration matrix.

```bash
python tests/run_tests.py --yaml-check
python tests/run_tests.py --verbose
python tests/matrix/run_matrix.py --profile quick
```

Use the full matrix before release-sensitive board or template changes:

```bash
python tests/matrix/run_matrix.py --profile full
```

Unsupported combinations should be rejected explicitly and classified as expected rejections; they must not be counted as passing generated configurations.

## Snapshot changes

Only update snapshots for an intentional output contract change:

```bash
python tests/run_tests.py --update-snapshots
git diff -- tests/fixtures
python tests/run_tests.py --verbose
```

Review every changed line. Never use snapshot update mode to hide an unexplained regression.

## Pull request checklist

- [ ] The change has one clear purpose and no unrelated cleanup.
- [ ] User-visible behavior and documentation agree.
- [ ] `python tests/run_tests.py --verbose` passes.
- [ ] `python tests/run_tests.py --yaml-check` passes when board data is affected.
- [ ] The quick matrix passes when generation, boards, probes, motion, or templates are affected.
- [ ] Snapshot differences are intentional and reviewed.
- [ ] No physical hardware is accessed by automated tests.
- [ ] New user-facing strings follow the translation system.
- [ ] Dependency inputs and hashed locks are updated together.
- [ ] Bootstrap changes are validated against KACE Studio source and packaged delivery.
- [ ] `CHANGELOG.md` is updated when the change is user-visible.

## Style and safety

- Follow the existing module's style before introducing an abstraction.
- Keep board facts in YAML instead of duplicating them in Python.
- Preserve explicit error paths and rollback behavior.
- Do not weaken identity, checksum, raw-image, firmware-size, or deployment validation.
- Distinguish mocked validation from real Klipper parsing and physical qualification.
- Open an issue before a schema change or a broad wizard/generator redesign.

## Reporting issues

Include the KACE revision, Python version, board/MCU, upstream Klipper config name, selected workflow, generated output or error, and the smallest reproducible steps. Do not include credentials, API keys, private hostnames, or SSH material.

Security issues should follow [SECURITY.md](../../SECURITY.md).
