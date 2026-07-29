# Release Engineering Guide

This document explains how to cut a KACE release, maintain semantic versioning,
and roll back safely if a release introduces regressions.

---

## Semantic Versioning

KACE follows [Semantic Versioning 2.0.0](https://semver.org/):

```
vMAJOR.MINOR.PATCH
```

| Part | When to bump | Example |
|------|-------------|---------|
| `MAJOR` | Breaking change to YAML schema, wizard flow, or generated output format | `v0.x.x → v1.0.0` |
| `MINOR` | New feature, new board family, new command-line flag | `v0.1.0 → v0.2.0` |
| `PATCH` | Bug fix, documentation update, snapshot refresh | `v0.1.0 → v0.1.1` |

### Current milestone targets

| Version | Goal |
|---------|------|
| `v0.9.x` | Release candidates, full Klipper sweep validation, hardware DB expansion |
| `v1.0.0` | Stable production release, frozen schema, Moonraker API integration |

---

## Cutting a Release

### Step 1 — Pass the full test suite

```bash
python3 tests/run_tests.py --verbose
python3 tests/run_tests.py --yaml-check
python3 tests/run_tests.py --full-klipper-sweep   # on main only
```

All jobs must pass with zero FAILUREs before tagging.

### Step 2 — Bump the version

Edit the `VERSION` file (single line, no `v` prefix):

```
1.0.0
```

`kace.py` reads this file at startup — no other change needed.

### Step 3 — Update CHANGELOG.md

Move items from `[Unreleased]` into a new dated section:

```markdown
## [1.0.0] — YYYY-MM-DD

### Added
- …

### Fixed
- …
```

Add the comparison link at the bottom:

```markdown
[1.0.0]: https://github.com/3D-uy/kace/compare/v0.9.0...v1.0.0
```

### Step 4 — Commit and tag

```bash
git add VERSION CHANGELOG.md
git commit -m "chore: release v1.0.0"
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin main --tags
```

### Step 5 — Create GitHub Release

On GitHub → Releases → Draft a new release:
- Tag: `v1.0.0`
- Title: `KACE v1.0.0`
- Body: paste the CHANGELOG section for this version
- Generate the installer checksum and attach `install.sh.sha256` to the release:

  ```bash
  sha256sum install.sh > install.sh.sha256
  ```

- Include the checksum value in the release body as well. Users must be able to obtain it separately from the tagged `install.sh` download used by the verified-install instructions.

---

## Rollback Strategy

### Option A — Pin to a previous tag (recommended)

Users can install or revert to any tagged release:

```bash
git fetch --tags
git checkout v0.9.0
```

Or the installer can be pointed at a specific tag:

```bash
git clone --depth 1 --branch v0.9.0 https://github.com/3D-uy/kace.git
```

### Option B — Revert a bad commit on main

If a regression is caught after merging:

```bash
git revert <bad-commit-sha>
git push origin main
```

Then cut a PATCH release immediately.

### Option C — Hotfix branch

For urgent production fixes:

```bash
git checkout -b hotfix/v0.9.1 v0.9.0
# apply fix
git commit -m "fix: ..."
git tag -a v0.9.1 -m "Hotfix v0.9.1"
git push origin hotfix/v0.9.1 --tags
```

Then merge back to `main`.

---

## Snapshot Management on Release

Before every release:

1. Run the full test suite — all snapshots must match.
2. If a **deliberate** change to output format is made, update snapshots intentionally:
   ```bash
   python3 tests/run_tests.py --update-snapshots
   ```
3. Review the diff of every changed fixture file before committing.
4. Never silently update snapshots as part of a non-output change.

---

## CI Gate

The GitHub Actions CI pipeline blocks merges to `main` if any of the following fail:

- Python syntax check (lint)
- Unit tests
- YAML integrity check
- Regression snapshot tests

The `--full-klipper-sweep` runs only on pushes to `main` (not on PRs) to keep
contributor iteration fast. See `.github/workflows/ci.yml` for the full pipeline.
