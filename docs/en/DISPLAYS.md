# 🖥️ Display configuration and support

Reviewed 27 September 2026 against the two official Klipper revisions listed below.

## What KACE currently supports

Klipper driver support, valid configuration and electrical compatibility are three
separate requirements. A driver name or an EXP connector does not establish the
exact module, pinout, supply voltage, signal thresholds or wiring.

**No physical board/display pair in the current KACE catalog has sufficient
module and wiring evidence for guided active generation.** An unknown result
blocks generation even after manual selection or accepted risk. Existing unsafe
classifications remain restrictive. Legacy `supported`, `partial` or adapter
labels in the data files are not hardware qualifications.

KACE checks the effective configuration, includes and artifacts it generates,
preserves or publishes during initial installation and unfinished resumptions.
After successful `DONE` (`COMPLETE` in the firmware checkpoint), user edits are
outside KACE's responsibility: there is no monitoring, revalidation or management
of those changes. A deliberately started new installation is a separate flow.

## What happens to configuration

| Route | Current behavior |
|---|---|
| No display (`none`) | Omits display blocks from the new generated hardware. This is not an instruction to delete unrelated manual destination files. |
| Automatic detection or selected physical display with unknown evidence | Rejects generation; a complete-looking pin list and accepted risk do not supply hardware evidence. |
| Restrictive `unsafe` route | Explicit selection requires risk acknowledgement. The renderer can produce an inactive commented reference, never an electrically qualified active configuration. An automatic unsafe reference can also be commented. |
| Saved generated hardware, macros or their includes | Rechecked before publication and unfinished resume, including no-change retries. Saved labels cannot bypass the evidence gate. |
| Existing manual-only destination `[display]` or include | May be preserved after effective configuration and required driver/transport checks, with an electrical-verification warning. This does not certify every optional field or physical connection. |

An include reached from generated hardware/macros keeps the generated-origin
restrictions even if a manual file also references it. Preservation is conditional;
KACE does not promise to retain every source display section as active configuration.

## The 14 physical catalog entries

These are KACE selection keys, **not fourteen native Klipper section names**.
The same evidence restrictions above apply to all of them.

| KACE key | Official syntax or boundary |
|---|---|
| `display` | `[display]` with a supported `lcd_type` and its required options |
| `st7920` | `lcd_type: st7920` inside `[display]` |
| `emulated_st7920` | `lcd_type: emulated_st7920` inside `[display]` |
| `hd44780` | `lcd_type: hd44780` inside `[display]` |
| `hd44780_spi` | `lcd_type: hd44780_spi` inside `[display]` |
| `aip31068_spi` | `lcd_type: aip31068_spi` inside `[display]` |
| `uc1701` | `lcd_type: uc1701` inside `[display]` |
| `ssd1306` | `lcd_type: ssd1306` inside `[display]` |
| `sh1106` | `lcd_type: sh1106` inside `[display]` |
| `btt_tft35` | Product-family label; not a native section or driver. A mode/revision name does not qualify wiring. |
| `mks_mini12864` | Product-family label; not a native section or driver. No universal SPI/FSMC inference. |
| `dwin_set` | Legacy OEM label; not a native section or driver in the reviewed revisions. |
| `tft_serial` | Legacy OEM label; not a native section or driver in the reviewed revisions. |
| `t5uid1` | No native section/driver in the reviewed revisions; KACE retains its restrictive policy. |

For a manually maintained `[display]`, `lcd_type` is required. Examples of
additional required fields are `cs_pin`, `sclk_pin`, `sid_pin` for ST7920;
`rs_pin`, `e_pin`, `d4_pin` through `d7_pin` for HD44780; `latch_pin` for
HD44780_SPI/AIP31068_SPI; and `cs_pin`, `a0_pin` for UC1701. Emulated ST7920
requires `en_pin` and the three software SPI pin options. SSD1306/SH1106 can
use I2C or SPI; choosing SPI requires `cs_pin` and `dc_pin`. Software buses need
their complete pin set. Bus defaults and valid MCU pins still depend on the
selected hardware. These field lists are **not ready-to-enable configurations**.
Use the official reference for complete requirements and optional settings.

## OEM identity and auxiliary modules

The exact official names `printer-creality-ender3-2018.cfg` and
`printer-creality-ender3pro-2020.cfg` identify the generic Ender 3 advice;
`printer-creality-ender3-v2-2020.cfg` identifies V2 separately. Explicit historical
aliases are listed in `data/displays.yaml`. Neo, S1, Max, renamed files and future
variants do not inherit a display by substring. Recognizing a profile does not
identify or certify the physically connected screen, nor install community firmware.

Klipper software sections such as `[display_status]`, `[display_data ...]`,
`[display_template ...]` and `[menu ...]` are distinct from physical displays.
The legacy KACE label `lcd_menu` is not a native section to copy into a config.
These software features have their own configuration requirements.

Native `[neopixel ...]`, `[dotstar ...]`, `[adxl345 ...]` and `[sx1509 ...]`
modules are not unsupported by Klipper merely because KACE's generic advanced
handler emits them as comments. That handler preserves references, not complete
validated installations. Existing board-specific hardware-dependency contracts
remain separate. **`[pca9685]` is not a valid standalone section: do not uncomment
it.** PCA9685 is internal to Replicape; KACE does not convert it to `[replicape]`.

## Diagnosing a display problem

Read the actual Klipper error and identify the exact board, screen revision,
connection and effective config. A blank screen alone does not establish a
protocol conflict, damaged memory, MCU reset or Linux shutdown. Do not use generic
OEM-family advice as a wiring or firmware-flashing recipe. Mainsail/Fluidd are
separate web interfaces, normally communicating through Moonraker; using them
does not prove an attached display is electrically safe. Studio provisioning and
SSH connectivity are also separate from LCD driver compatibility.

## Official references and limits

- [Configuration reference at KACE's pinned revision](https://github.com/Klipper3d/klipper/blob/fe4eb8650bd7de4c2100a14eaf09b0965c430e29/docs/Config_Reference.md#display-support).
- [LCD driver registry at the pinned revision](https://github.com/Klipper3d/klipper/blob/fe4eb8650bd7de4c2100a14eaf09b0965c430e29/klippy/extras/display/display.py).
- [Configuration reference at the later archived revision](https://github.com/Klipper3d/klipper/blob/ce7002bedf37e938bb483572949f3703ac6476cb/docs/Config_Reference.md#display-support).
- [Official reference site](https://www.klipper3d.org/Config_Reference.html#display-support), which can change after those revisions.
- [KACE support scope](SUPPORT_SCOPE.md) and [testing guide](../DEVELOPMENT.md).

The later archived revision is not asserted to be today's upstream HEAD.
These checks do not constitute physical display qualification or an E2E hardware test.
