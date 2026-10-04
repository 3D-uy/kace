# KACE — Roadmap

🌐 [English](ROADMAP.md) · [Español](docs/es/ROADMAP.md) · [Português](docs/pt/ROADMAP.md)

Priorities for this source tree, not release dates or a claim of completed qualification. Release documents remain authoritative for gates; this roadmap does not change versions, hashes, firmware targets or pins.

## 📍 Available in source

Guided configuration, reviewed publication, durable recovery, firmware identity checks and layered automated validation exist. Their supported boundaries are documented in [Support scope](docs/en/SUPPORT_SCOPE.md). Source behavior must be distinguished from the immutable distributed candidate.

Reviewed removable TMC socket mapping covers ten exact source profiles; cross-model electrical settings still require user review. See [mapping scope](docs/TMC_SOCKET_MAPPING.md).

## 🧭 Priorities

| Priority | Required result | Reference |
| --- | --- | --- |
| 1 · Source validation | Reconcile the complete source suite, pinned Klipper loads and reviewed scenario gate against the final tree; retain failures and skips with causes. | [Testing](docs/DEVELOPMENT.md) |
| 2 · Controlled qualification | Record exact board/MCU, storage, firmware delivery, activation, recovery and physical commissioning evidence. Parser acceptance is insufficient. | [Hardware testing](docs/HARDWARE_TESTING.md) |
| 3 · Release alignment | In a separately authorized release, align committed runtime, installer and bootstrap identities, then validate the Studio pair. Do not publish while required evidence is missing. | [Release](docs/RELEASE.md) |
| 4 · Maintenance | Keep EN/ES/PT entry points aligned; add narrow regressions for demonstrated defects and reviewed support, preserving safety contracts. | [Contributing](docs/DEVELOPMENT.md) |

## Scope boundaries

New host platforms, arbitrary upstream-profile migration, multiple extruders and post-installation management require separate design and evidence. They are not promised by catalog visibility. Geometry already separates printable and reachable areas; this does not imply IDEX/toolchanger support.

[Back to README](README.md)
