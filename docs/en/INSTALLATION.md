# Installing and starting KACE

[README](../../README.md) · [Development](../DEVELOPMENT.md) · [Deployment](DEPLOYMENT.md)

## Choose a starting point

- **Existing Linux printer host:** use the [Quick start](../../README.md#quick-start). It clones the default branch and passes that checkout's full commit to `install.sh`, which installs the same revision under `~/kace/`.
- **Fixed candidate:** use the [verified installation command](../../README.md#verified-installation-pinned). Its immutable reference and SHA256 come from the existing bootstrap installer contract; they are not necessarily the current source revision.
- **New Raspberry Pi:** prepare it with [KACE Studio](https://github.com/3D-uy/KACE-studio) or the manual steps below.

Run the installer as the intended Linux user so `~/kace/` belongs to that account.
It may request sudo to install missing dependencies or create `/usr/local/bin/kace`.
Without sudo, its command fallback is `~/.local/bin/kace`; ensure that directory is in your PATH.

KACE requires Python 3.11+, Git, Bash, venv support, network access for dependencies and the permissions needed by the chosen workflow. The installer also checks for `flock` and can install missing system dependencies through apt.
The verified download additionally uses `curl` and `sha256sum`.
Docker and compiler toolchains are needed only for their documented firmware build and validation paths.

Installation of KACE itself does not provision a complete Klipper/Moonraker stack.
Applying and verifying configuration requires that stack to be running.

## Prepare a Raspberry Pi manually

1. In Raspberry Pi Imager, select the exact Pi model and a compatible OS with Python 3.11+.
2. Select the target SD/USB storage and configure hostname, user, network and SSH.
3. Review the target and confirm the write; it erases the selected storage.
4. Safely eject the storage, boot the Pi and connect over SSH using its hostname or router-assigned IP.
5. Prepare Klipper and Moonraker if the chosen image does not already include them, then install KACE using either README installation option.

Preparing the OS does not configure or commission the printer. Studio's supported image/model combinations are documented in the Studio repository.

## Run a source checkout without the installer

For source exploration, from a separate checkout:

```bash
git clone https://github.com/3D-uy/KACE.git kace-source
cd kace-source
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements.txt
python kace.py
```

This runs the checkout directly and does not create the `kace` launcher.
For optional SSH/SFTP deployment dependencies in this environment:

```bash
python -m pip install --require-hashes -r requirements-ssh.txt
```

Use the [development environment](../DEVELOPMENT.md) for contributing and running tests.

## From the wizard to a printer

1. Run `kace` after installation, or `python kace.py` in the activated source environment. Choose language and experience level.
2. Select the exact board/MCU, printer geometry, motors, probes and other supported resources; review pins and electrical requirements.
3. Review artifacts under `~/kace/`. Follow the selected firmware delivery procedure and physical identity verification.
4. Review the configuration diff and preserved settings, explicitly apply/activate and wait for verified completion. Local Moonraker on the Pi uses `127.0.0.1:7125`.
5. Commission sensors, endstops, motion and heating separately using the [hardware guide](../HARDWARE_TESTING.md). On interruption, follow the saved checkpoint and [recovery instructions](DEPLOYMENT.md).

Do not save configuration edits from Mainsail, SSH or another tool during KACE publication.
Local publication uses cooperative locking and atomic replacement per file; external editors can still race.
Remote changed plans or existing-file replacement may require manual proposals.
Recovery retains live edits and snapshots when safe restoration cannot be proven; `Ready` alone does not establish successful installation.
The [deployment guide](DEPLOYMENT.md) defines those behaviors in detail.

KACE's responsibility covers initial installation and unfinished resumes through `DONE` / `COMPLETE`, not monitoring later user changes.
See the [support scope](SUPPORT_SCOPE.md) for feature boundaries and the [release guide](../RELEASE.md) for immutable references, checksums and source-versus-distributed-candidate validation.
