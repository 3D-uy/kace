# Removable TMC driver socket mapping

KACE resolves the selected chip independently from the example chip in a reviewed
board profile. For SKR V1.4 / Turbo with TMC2209 UART and the second Z motor on E1,
this emits `[tmc2209 stepper_z1]` with `uart_pin: P1.1`; the motor pins are P1.15,
P1.14 and !P1.16. Motor direction remains an explicit mechanical choice.

## Source and scope

`data/tmc_sockets.json` indexes 68 sockets from these ten exact Klipper profiles:

- `generic-bigtreetech-octopus-max-ez.cfg`
- `generic-bigtreetech-octopus-pro-v1.0.cfg`
- `generic-bigtreetech-octopus-pro-v1.1.cfg`
- `generic-bigtreetech-octopus-v1.1.cfg`
- `generic-bigtreetech-skr-2.cfg`
- `generic-bigtreetech-skr-pro.cfg`
- `generic-bigtreetech-skr-v1.3.cfg`
- `generic-bigtreetech-skr-v1.4.cfg`
- `generic-fysetc-spider.cfg`
- `generic-mks-sgenl.cfg`

The sources are copied unchanged from Klipper commit
`fe4eb8650bd7de4c2100a14eaf09b0965c430e29` into `tests/fixtures/tmc-sockets/`.
The catalog stores normalized source hashes, motor pins and commented transport
examples. The shared SKR V1.4 source covers LPC1768 and LPC1769 (Turbo); firmware
identity selection remains separate.

- [Pinned SKR V1.4 source](https://github.com/Klipper3d/klipper/blob/fe4eb8650bd7de4c2100a14eaf09b0965c430e29/config/generic-bigtreetech-skr-v1.4.cfg)
- [BIGTREETECH SKR V1.4 driver documentation](https://global.bttwiki.com/zh/SKR%20V1.4.html)
- [Klipper TMC driver setup](https://www.klipper3d.org/TMC_Drivers.html)

The resolver supplies UART wiring for selected TMC2208, TMC2209 and TMC2225
(Klipper's TMC2208 name), or SPI wiring for selected TMC2130 and TMC5160. It never
converts UART into SPI or transfers current, hold current, stealthChop threshold,
sense resistor, DIAG pins or driver registers between chip models. A missing
current must be entered and confirmed for the selected motor/module. Module
variants, jumpers, supply voltage and physical communication still need hardware
verification; this catalog establishes connector wiring, not physical qualification.

## Resolution and boundaries

`core.scraper` captures source identity. `core.tmc_socket.selected_socket_sections`
is used by the wizard, value/current confirmation and generation paths, keeping
API calls and saved wizard data consistent. The selected board, source digest,
transport and motor pins must match; direction polarity may change on the same
physical pin. Reused E sockets resolve to their selected Z motor. Existing exact
chip sections retain their settings and are still validated, including partial
or invalid sections. Repeated wizard mapping preserves the existing result.

Integrated drivers, unknown profiles, modified source text, altered wiring and
custom sockets do not gain an automatic fallback. Do not extend this catalog by
board-name similarity or MCU family. Review exact source evidence and add positive
and rejection tests. The generator records the socket source alongside normal
TMC option provenance. No snapshot, firmware contract, bootstrap or release pin
is changed by this correction.

Empty commented DIAG examples (present in SKR 2) are omitted during parsing.
Active empty DIAG options remain errors; no sensorless wiring is inferred.

## Validation

Run `python -m pytest tests/unit/test_tmc_socket.py -q`, followed by the affected
TMC, scraper, wizard, profile-authority and generator suites described in
[Development](DEVELOPMENT.md). Fixtures provide explicit motor currents and Z
mechanics; they are test inputs, not recommended printer settings. The regression
covers all 50 board/model pairs, the reported E1 case, direct generation, wizard
confirmation/back, repeated mapping, modified wiring and integrated-driver refusal.
Run `python -m tests.regression.validate_tmc_sockets --artifacts <new-directory>`
for the 100 real pinned-Klipper loads: each of the 50 board/model pairs as a direct
configuration and as managed includes under a preserved user root. The latter
also checks that a repeated configuration plan makes no changes. This gate runs
in CI with retained reports. Physical commissioning remains a separate check.
