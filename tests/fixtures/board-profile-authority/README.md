# Board/profile authority fixtures

These six files are byte-for-byte copies of the official Klipper `config/`
files at commit `fe4eb8650bd7de4c2100a14eaf09b0965c430e29` (GPL-3.0).
They are source inputs, not generated snapshots. Do not regenerate them from KACE.

Source: https://github.com/Klipper3d/klipper/tree/fe4eb8650bd7de4c2100a14eaf09b0965c430e29/config

K21 tests deliberately combine distinct STM32 boards to detect pinout mixing.
The physical setup in generation tests explicitly selects a board endstop and
no probe; passing the official loader does not prove CR6-SE/Neo wiring or probe
compatibility. Exact stock selections and explicit overrides have separate tests.

| File | SHA-256 |
|---|---|
| generic-bigtreetech-skr-mini-e3-v2.0.cfg | `efa67ff57b0f951ec611ab708532a8ac2f1b35a0390f707317a799d73a628fd6` |
| generic-creality-v4.2.7.cfg | `fb34f17e1512736ed0e70146e1c3af04e0710ebbeda45609a00851deaebbe4ca` |
| printer-creality-cr6se-2020.cfg | `b6b2a435d5b88ca7a23a6d9233871ca85b2e2ab9b9259ce4631eaa73620b412d` |
| printer-creality-cr6se-2021.cfg | `6cc12ededaa343be668a211cb75fa3fea82d6b1d747c42f9466478419f4e4ad5` |
| printer-creality-ender3-v2-2020.cfg | `fad7e0aee410b2829132f5c34a1d670c537dad857e4f97c9bc55645ff6fc9219` |
| printer-creality-ender3-v2-neo-2022.cfg | `cb41e8ae03748b88bf97f45ce041b4194036f07f03e6e33bc2480635046b8fdf` |
