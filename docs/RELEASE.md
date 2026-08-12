# KACE release engineering guide

KACE is currently pre-1.0. This guide describes the intended maintainer procedure; it does not imply that a stable release or binary distribution exists.

## Version source

`VERSION` is the project version source. `kace.py` reads it at runtime. A release commit must update `VERSION` and `CHANGELOG.md` together; ordinary maintenance work must not change either value unnecessarily.

KACE uses semantic versioning:

- Major: incompatible schema, workflow, installation, or generated-output contract.
- Minor: backward-compatible capability or supported hardware family.
- Patch: backward-compatible correction or documentation-only release.

## Pre-release gates

Run the complete source validation:

```bash
python tests/run_tests.py --verbose
python tests/run_tests.py --yaml-check
python tests/run_tests.py --full-klipper-sweep --verbose
python tests/matrix/run_matrix.py --profile full
```

Confirm the containerized MCU build job passes, review all matrix JSON/Markdown results, and verify there are no `KACE_ERROR`, `KLIPPER_ERROR`, or `INFRA_ERROR` results. Expected safe rejections are not passes and must match the intended unsupported combinations.

Automated validation does not replace documented physical qualification on representative supported hardware.

## Cross-repository publishing order

KACE must be published before KACE Studio:

1. Finalize and publish the KACE commit.
2. Choose the immutable KACE commit that Studio will package.
3. Calculate the SHA-256 of `scripts/bootstrap.sh` from that exact remote commit.
4. Update KACE Studio's CI bootstrap reference and hash as a pair.
5. Fetch the remote file and verify the pair independently.
6. Run Studio tests and build the Windows executable.
7. Verify the built executable contains the same bootstrap bytes selected by the contract.

Inside `scripts/bootstrap.sh`, `KACE_INSTALL_URL`, `KACE_INSTALL_REF`, and `KACE_INSTALL_SHA256` form a second indivisible contract. The referenced KACE commit must already exist remotely, and the remote `install.sh` bytes must match before Studio pins the bootstrap.

Never construct a release contract from a mutable `main` URL plus a checksum calculated at a different time.

## Release commit and tag

After every gate passes:

1. Move the relevant `CHANGELOG.md` entries from Unreleased into the dated release section.
2. Update `VERSION`.
3. Commit only the release metadata.
4. Create a signed or annotated tag from that exact commit.
5. Push the commit first, then the tag.
6. Confirm the remote tag resolves to the locally validated commit.

Do not rewrite or move a published release tag.

## Installer checksum

Generate the installer checksum from the tagged bytes:

```bash
git show <release-tag>:install.sh | sha256sum
```

Publish that value through the release metadata and verify it again from the raw GitHub URL for the immutable tag or commit. The checksum must not be obtained solely from the same mutable location as the file being verified.

## GitHub release

The release page should contain:

- The immutable tag and commit.
- The matching `CHANGELOG.md` section.
- The SHA-256 of the tagged `install.sh`.
- Supported environments and known limitations.
- Hardware-validation scope.
- Upgrade and rollback notes.

CI installs the committed dependency locks with `--require-hashes`, pins third-party Actions to full commits, and pins the firmware-validation container base by digest. These controls make inputs auditable; they do not by themselves demonstrate that an output is signed or bit-for-bit reproducible. Do not make either claim without separate evidence.

## Rollback

Prefer a forward corrective release. If a published commit must be undone on `main`, use a normal revert commit so the history and contract remain auditable. Existing installations can be diagnosed against their immutable commit or tag.

If KACE Studio has already pinned a bad KACE bootstrap, publish the corrected KACE commit first and then update Studio's reference/hash contract in a separate commit.

## Snapshot policy

Snapshots may change only when the generated-output contract changes intentionally:

```bash
python tests/run_tests.py --update-snapshots
git diff -- tests/fixtures
python tests/run_tests.py --verbose
```

Review and commit the generator change, regression test, and affected fixtures together.

## CI evidence

Record the URLs and conclusions for:

- KACE CI, quick matrix, full sweep, full manual matrix, and Docker firmware build.
- KACE Studio test matrix and Windows build.
- Remote installer and bootstrap SHA-256 verification.
- Packaged bootstrap verification.
- Any manual physical-hardware qualification.

A release is blocked if local and remote commits, hashes, generated reports, or packaged bootstrap bytes differ.
