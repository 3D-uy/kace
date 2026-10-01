# KACE

🌐 [English](README.md) · [Español](docs/es/README.md) · [Português](docs/pt/README.md)

![KACE](docs/assets/kace_banner.png)

KACE is the Python CLI that runs on the printer host to prepare, review and deploy Klipper configuration and MCU firmware artifacts. [KACE Studio](https://github.com/3D-uy/KACE-studio) prepares the Raspberry Pi from Windows and provides SSH/SFTP access; KACE remains the configuration and installation authority.

**Pre-1.0; controlled qualification.** [VERSION](VERSION) declares the version; [CHANGELOG](CHANGELOG.md) records current candidate notes. Uncommitted source changes are not part of the pinned installer. Automated validation does not certify physical hardware or a stable release.

## Quick start

Requires Linux/Raspberry Pi, Python 3.11+, Git, network access for dependencies and the permissions needed by the chosen workflow. Docker/toolchains are needed only for their documented build and validation paths.

For a new Pi, use **KACE Studio**. For an existing Linux host, the installer below verifies the immutable installer before executing it. Review it before use: it installs the pinned revision, not necessarily the source tree you are reading.

```bash
KACE_COMMIT='56eb565d96b943e2d5824df2c1e6fced33377401'
KACE_INSTALL_SHA256='de7db74da6f6261bf28fa329067f9d3424bc3e5abde5db4dd91c3f66861f3500'
installer=$(mktemp)
trap 'rm -f "$installer"' EXIT
curl -fsSLo "$installer" "https://raw.githubusercontent.com/3D-uy/KACE/${KACE_COMMIT}/install.sh" &&
printf '%s  %s\n' "$KACE_INSTALL_SHA256" "$installer" | sha256sum -c - &&
KACE_SOURCE_REF="$KACE_COMMIT" KACE_EXPECTED_COMMIT="$KACE_COMMIT" bash "$installer"
```

To run the current source checkout instead:

```bash
git clone https://github.com/3D-uy/KACE.git
cd KACE
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements.txt
python kace.py
```

Manual host preparation is also possible: in Raspberry Pi Imager choose the exact Pi and a compatible OS, select target storage, configure hostname, user, network and SSH, then review and confirm the destructive write. Safely eject, boot the Pi and connect to its hostname or router-assigned IP. Install KACE there using the verified command above. Preparing the OS alone does not configure or commission the printer.

## 🧭 Use

1. Run `kace` after installation, or `python kace.py` from the activated source environment. Choose language and experience level.
2. Select the exact board/MCU, printer geometry, motors, probes and other supported resources; review pins and electrical requirements.
3. Review artifacts under `~/kace/`. Follow the selected firmware delivery procedure and physical identity verification.
4. Review the configuration diff and preserved settings, explicitly apply/activate and wait for verified completion. Local Moonraker on the Pi uses `127.0.0.1:7125`.
5. Commission sensors, endstops, motion and heating separately using the hardware guide. On interruption, follow the saved checkpoint and recovery instructions.

## ⚠️ Scope and limits

- Cartesian/CoreXY paths are implemented; searchable upstream profiles are not a compatibility guarantee. Runtime, provisional, prepare-only and configuration-only firmware paths remain distinct.
- Unknown displays, unsupported mandatory circuits and unreviewed profile dependencies remain blocked. Review [support scope](docs/en/SUPPORT_SCOPE.md) and [display limits](docs/en/DISPLAYS.md).
- Do not save edits from Mainsail/SSH during publication. Local writes use cooperative locks and atomic replacement per file, not a directory-wide transaction against arbitrary editors. Remote changed plans and existing-file replacement may require manual proposals.
- Rollback preserves live edits and durable snapshots when safe restoration cannot be proven. `Ready` alone is not success: activation, artifact and firmware evidence remain required.
- Responsibility covers initial installation and unfinished resumes through `DONE`/`COMPLETE`; no monitoring or revalidation of later user edits is promised.

## 🛠️ Development

Use [Development](docs/DEVELOPMENT.md) for architecture, contribution and tests. Run the narrowest regression first, then affected gates. The complete suite includes pytest functions that the unittest runner does not collect. Never update snapshots just to make a failure pass.

## 📚 Documentation

| Purpose | Guide |
| --- | --- |
| Development, architecture and tests | [DEVELOPMENT.md](docs/DEVELOPMENT.md) |
| Deployment and recovery | [DEPLOYMENT.md](docs/en/DEPLOYMENT.md) |
| Hardware qualification | [HARDWARE_TESTING.md](docs/HARDWARE_TESTING.md) |
| Support scope | [SUPPORT_SCOPE.md](docs/en/SUPPORT_SCOPE.md) |
| Displays | [DISPLAYS.md](docs/en/DISPLAYS.md) |
| Release | [RELEASE.md](docs/RELEASE.md) |
| Code of conduct | [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) |
| Roadmap | [ROADMAP.md](ROADMAP.md) |
| Current candidate notes | [CHANGELOG.md](CHANGELOG.md) |
| Security | [SECURITY.md](SECURITY.md) |

## License

[GPL-3.0](LICENSE).
