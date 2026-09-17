# KACE release engineering guide

KACE is currently pre-1.0. The `0.9.4-rc.2` candidate is for controlled hardware qualification, not a stable compatibility promise. See [HARDWARE_TESTING.md](HARDWARE_TESTING.md) for the qualification sequence and operational limits.

## Version source

`VERSION` is the project version source. `kace.py` reads it at runtime. A release commit must update `VERSION` and `CHANGELOG.md` together; ordinary maintenance work must not change either value unnecessarily.

KACE uses semantic versioning:

- Major: incompatible schema, workflow, installation, or generated-output contract.
- Minor: backward-compatible capability or supported hardware family.
- Patch: backward-compatible correction or documentation-only release.

Use an explicit prerelease suffix (for example `-rc.1`) when physical qualification
is still pending. Publish the validation gaps with the candidate; do not describe
unexecuted CI, firmware builds or hardware checks as passed.

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

1. Commit runtime fixes, tests and version metadata. This immutable runtime commit
   is `candidate_ref` and `installer_ref` in Studio's `release-contract.json`.
2. Hash `install.sh` from that commit's Git bytes. Update bootstrap and every public
   installer example to that commit/hash pair, then commit the bootstrap separately.
   A bootstrap cannot embed the hash of its own commit.
3. Publish KACE's commits; record the second commit as Studio's `bootstrap_ref` and
   calculate `bootstrap_sha256` from that commit's exact bytes.
4. Synchronize Studio's bootstrap and required-runtime-file hashes. Verify the
   local committed candidate, remote installer, every required remote runtime file
   and bootstrap before changing `runtime_status` from `pending_commit` to `pinned`.
5. Validate and publish the final Studio source/contract commit before its final
   build. Keep source mode and packaged mode resource checks.
6. Build from a clean checkout with the contracted Python/PyInstaller/dependency
   lock and environment, then verify bundled bytes, PE metadata and renderer smoke.
7. Write an external manifest identifying the published Studio/KACE commits and
   executable SHA-256. Signing and independent reproduction are separate claims;
   a single local build cannot attest either of them.

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
