# Actual support scope and current boundaries

[README](../../README.md) · [Development and tests](../DEVELOPMENT.md)

## Installation lifecycle boundary

KACE is responsible for the effective configuration, includes and artifacts it
generates, preserves or publishes during initial installation/configuration and
resumptions of that unfinished flow. The checks described below apply within
that lifecycle, up to successful completion (`DONE`; firmware checkpoint
`COMPLETE`). No-change retries are retries of an unfinished deployment.

After successful completion, subsequent user changes to `printer.cfg`, includes,
macros or other files are outside KACE's responsibility. KACE does not monitor,
revalidate or manage those changes after completion. Starting a new installation
is a separate explicit workflow, not continuing supervision of the finished one.
Preservation checks and checks of saved generated payloads below do not extend
this boundary.

## Independent endstops on additional Z motors

For selected Z1/Z2/Z3 motors, active board `endstop_pin` options are retained,
including pullup/pulldown, inversion and pin identity. Klipper shares the primary
rail endstop when this option is omitted; KACE must not silently turn an
independent input into that shared behavior. Unselected motors are not required,
and commented discovery examples do not become active inputs. Existing source
and effective-artifact checks reject lost or changed inputs before initial DONE,
including nested includes and unfinished no-change retries. A secondary virtual
probe endstop requires a configured provider. Printer profiles do not authorize
GPIO migration. These checks do not qualify physical homing or sensorless tuning,
and do not manage user changes after installation.

## Guided replacement of a generic probe

The guided Custom Probe path may reuse the input of the `[probe]` it replaces,
just as it may replace an existing BLTouch sensor input and Z endstop. This
exception applies only to that transition: it does not free step/enable pins,
heaters, fan outputs, BLTouch control pins, unrelated sensors or firmware
reservations. The prompt rechecks the chosen pin and final generated config
retains its allocation checks. It does not infer a probe's physical type.

The user supplies geometry, signal flags and sampling answers through the
existing guided flow. Missing source offsets are not physical measurements.
No raw upstream macros are imported, and no extra question is introduced merely
to reproduce a profile. An omitted lift_speed follows the selected speed under
Klipper's contract; this does not support arbitrary independent lift settings.

## Probe sampling policy

Selected BLTouch/CR-Touch configs retain explicit active `speed`, `lift_speed`,
`samples`, `sample_retract_dist`, `samples_result`, `samples_tolerance` and
`samples_tolerance_retries` from the board/printer profile. Conflicting values
require resolution; omitted values remain Klipper defaults. Profile sampling
policy does not grant authority over GPIO, calibration offsets or print macros.
Comments cannot become active policy. Source/provenance and saved raw profile
text carry the policy through initial-installation recovery and publication;
changed caches, missing rendered fields and effective include overrides block.

Stock `[probe]` and `[bltouch]` values use the same official numeric/enum bounds,
with an additional KACE finiteness requirement. Custom probe text remains
user-selected and verbatim: these checks validate it without importing BLTouch
policy. Automatic inheritance into generic/inductive probe strategies is not
part of this change. Their selection/reconciliation remains separate. Z offset
still requires physical calibration; loading a config does not prove motion.

## BLTouch electrical mode and timing

For selected BLTouch/CR-Touch sections, KACE retains an explicitly active
`set_output_mode` and `pin_move_time` from the selected board source. Omitted
options retain Klipper defaults; commented examples do not enable a voltage.
The enum is case-sensitive (`5V`/`OD`) and movement duration must be positive
and finite. A printer profile alone cannot authorize these hardware settings:
it must agree with the board. Changing either declared sensor/control pin while
carrying these settings is blocked, including alias rewrites, until a reviewed
source describes the intended connection. Pin-name validity does not establish
5 V tolerance, and KACE does not infer tolerance or program EEPROM.

Generation records these settings in provenance and checks the final render.
Saved artifacts and effective includes are checked during initial installation
and unfinished resumes: invalid values and changes to selected-board settings
block before publication. Existing configurations without selected-source
context receive value validation, not a claim of electrical qualification.
Generic probe selection, calibration and profile sampling-policy reconciliation
remain separate concerns; a loader pass is not proof of physical operation.

## 🧭 Supported paths

KACE supports the configuration paths its wizard and generator implement. An
official Klipper profile being searchable does not mean every resource, transport
or host platform in that profile is supported end to end.

Wizard suggestions and MCU-based pin checks use exact reviewed profile names
and explicit MCU candidates. A multivariant profile alone does not select a
processor. While unresolved, pin checks retain constraints for every candidate;
a known model narrows them. Only explicit official Kconfig aliases normalize
model names. Historical search hints, similar names and broad families do not
establish identity. This metadata does not add firmware, host-platform or
flashing support; the full manual catalog remains searchable.

Display qualification is currently limited: no physical board/display pair in
the catalog has sufficient reviewed module and wiring evidence for guided active
generation. Known EXP mappings remain available as connector evidence; they do
not establish electrical compatibility. Unknown selections are blocked even
with risk consent, while unsafe classifications remain unsafe. Existing manual
`[display]` sections may be preserved and published with required driver/transport
checks and an explicit electrical-verification warning. Those checks do not
certify all optional fields or physical hardware. See [display limits](DISPLAYS.md).
Saved generated hardware/macros are rechecked before publication or CLI resume;
an old compatibility label or accepted risk cannot bypass that boundary. Content
edited in `~/kace/printer.cfg` is still a generated payload for these APIs, not
automatically classified as preserved manual destination content.
Includes originating in generated payloads obey the same evidence gate after
destination files are read. A file shared with a manual include, or named after
a dashboard, is not exempt. Includes reached only from the preserved manual
root retain the manual structural-review contract.

The current generation flow always emits a heated bed and therefore requires
its active heater pin, selected sensor factory and, for ADC sensors, sensor pin.
Missing circuits, empty pins and unresolved placeholders stop generation before
writing; commented examples and thermal presets never supply hardware pins.
Effective installation plans with a bed receive the same presence check,
including nested includes and unfinished no-op resumes. A preserved configuration
without a bed is not forced to add one; this does not add a bedless generation
workflow or qualify non-ADC sensor peripherals.

Primary extruder limits and heater smoothing follow explicit profile/user values
and Klipper defaults when omitted. Existing valid destination tuning is retained;
invalid effective values block publication even on a no-change retry. Custom
thermistors and scaled ADC dependencies retain their bounded generation contract.
SPI/RTD heater generation remains unsupported; recognizing a preserved sensor
factory does not certify its bus/circuit. Resource-level checks do not certify a whole board or secondary extruder.

| Layer | Current responsibility | Boundary |
|---|---|---|
| Printer configuration | Cartesian/CoreXY, primary extruder and bed, selected motors/probes/displays/fans; validation and reviewed publication | No general migration of every official profile feature or multiple extruders |
| Required hardware dependencies | Keep required pins, sensors, buses, enables and reviewed callbacks with their consumers | An unsupported mandatory circuit must not be silently dropped to produce a deployable configuration |
| Firmware | Exact declared targets and reviewed legacy preparation paths, with build/image identity checks | Runtime-supported, provisional, configuration-only and prepare-only are distinct; none alone certifies physical hardware |
| Robin | Reviewed native/final image preparation; original USB bridge recovery for USART3 | Sapphire USART1 preparation does not provide host-UART provisioning or complete direct-UART installation/recovery |
| Linux host | Existing bootstrap stack/services and explicitly configured optional power integration | No general UART console/Bluetooth/pinmux, Beaglebone PRU or device-tree provisioning |
| Linux MCU / host ADC | Existing Linux build selectors and bounded configuration/pipe preservation | Does not install, start or prove the separate host MCU service |
| Optional peripherals | Only explicitly implemented active paths; some advanced modules are retained as comments | Commented examples, runout devices, arbitrary lighting/sound and expansion modules are not automatically configured |
| Print strategy | User macros remain user-owned; KACE retains its own macro validation | No automatic migration of upstream PRINT_START/START_PRINT or slicer start recipes, except indispensable hardware initialization reviewed separately |

Replicape is an explicit unsupported host-platform route. An active or legacy
selected [replicape] dependency blocks generation, and effective installation
plans or saved artifacts cannot publish that platform or orphaned replicape:*
pins. Commented examples remain inert. A separately declared MCU named
replicape is an ordinary namespace, not evidence of the Replicape platform;
its normal MCU/pin contracts still apply. Linux host ADC endpoint preservation
remains supported within its existing bounds and does not provision PRU,
pinmux, device trees or Replicape SPI/PWM services.

Unsupported does not mean safe to omit: a dependent selected resource may require
a rejection. Existing DAC/PWM and firmware-recovery guards remain enabled. Other
support boundaries remain explicit limits; resource coverage
does not assert that every selectable profile has an end-to-end supported route.

KACE's configuration safety fixes remain applicable when an old or uncommon
profile exposes a general problem. Board age or popularity does not decide scope.
New host-platform responsibilities require a separate product decision; the mere
presence of an upstream example is not that decision.

The Sapphire direct-USART1 choice explicitly offers firmware preparation only.
The same limit is shown when reusing a saved choice, including automatic mode.
Host UART provisioning and complete direct-UART installation/recovery remain
unsupported; USB identity cannot establish that transport.

## Thermal protection

Preserved `verify_heater` sections are checked before publication for finite
values, official lower bounds, supported options and exact heater references.
Passing these checks does not certify the selected thermal protection against
physical hardware. KACE does not automatically import or lengthen protection
times from upstream profiles; non-default policies require explicit review.
Generation rejects silent loss of active source verification settings from the
selected board or printer profile. Saved/effective publication with selected-board
context checks that policy too, accepting implicit defaults only when equivalent.
Affected non-default sources block generation without a current confirmation.
Independent printer-profile verification requirements travel
through saved-artifact recovery, effective review, publication and export, without
importing profile circuits. Conflicts with saved decisions or board policy are
rejected. New non-default source policies for the primary extruder/heater_bed can
now be generated after explicit review of rendered heater, MCU and sensor details.
The stored confirmation becomes stale when those definitions or sources change;
automatic mode cannot create consent. This records a user's hardware decision,
not calibration or physical certification. Receiptless manual artifacts retain
the existing validation and are not retroactively marked confirmed. Original
Sunlu S8 and Tronxy X5S CFG routes have generation/recovery and simulated-publication
evidence with their source fans explicitly selected, plus pinned Klipper object
loads. Unselected Sunlu PH4 cooling follows its exact reviewed source obligation,
as described below. This does not cover firmware installation or
physical calibration. Adimlab thermal settings work as a separate profile on a
supported selected circuit; its original board remains blocked by mandatory PWM
current dependencies. That limit is not permission to omit those dependencies.

## Firmware transport and identity

For Creality v4.2.7, the default runtime target uses MCU USART1 PA10/PA9 with
a USB serial bridge connection from the host. This is not native USB firmware.
The direct LCD IDC connection belongs to the separate PROVISIONAL USART3
PB11/PB10 target; KACE does not provision the host UART for it. The selected
observed serial endpoint remains authoritative, not the example path in a profile.
The corrected contract metadata has a new digest. Previous proof/artifact
identities are not migrated or relabeled; obtain current evidence through the
normal build and verification flow before deployment.

## Required cooling

Cooling is governed by a shared behavior contract and a reviewed-source
obligation index (`data/required_cooling.json`). The reviewed cooling inventory
is classified without treating all searchable upstream profiles as supported
platforms. The index binds active A/B hardware dependencies to exact source
filenames/content hashes; source changes require review, and old checkpoints
without source evidence require a board reload. BX retains its existing coupled
panel/boot/cooling contract. It is not replaced by an isolated fan policy.

Required heater_fan and controller_fan resources retain their exact names, roles,
MCU/GPIO and polarity, supported electrical options and heater/motor associations,
even when the wizard fan selection is omitted or says "No additional fan".
A heater_fan named controller_fan remains a heater_fan. Controller idle behavior
and default shutdown differ from thermal cooling and are preserved separately.
The actual generated heaters and explicit motors must exist; KACE does not invent
additional motors or heaters to satisfy a source reference. Required source heater
circuits remain bound. Pin collisions and firmware reservations remain checked.

Generation, recovery and effective publication (including no-change retries and
user includes) enforce that contract. Semantically equivalent aliases, numeric
formatting and Klipper shutdown clamping are accepted. Changed roles, missing
resources, altered associations and malformed lists are rejected. An include is
not evidence of a reviewed hardware change. Mechanical-profile use does not
import the original board's required fan pins into another board.

Manual part cooling remains optional. Selecting the original source socket keeps
its power, startup, threshold, cycle, PWM and shutdown settings. Alternate spellings
of that socket cannot bypass source authority. Unselected optional manual fans are
not made mandatory by this change. Explicitly selected heater fans and present
source-bound saved fans retain the earlier selection/equivalence protections.
Distinct custom sockets and unknown sources do not imply whole-source coverage.

Required temperature_fan, automated fan_generic and auxiliary tachometer/enable
circuits not covered by the implemented contract block their selected-board route;
they are not silently dropped or classified as restored. Optional unsupported
manual dependencies block selection of that resource. Existing DAC/current/PWM
and other board dependency gates remain independent. Thus a preserved fan does
not imply the rest of its source platform is supported or deployable.

Cooling resource conservation does not certify a whole source platform. Other
electrical or unreviewed homing dependencies may still block a covered resource.
Platform UART/pinmux/PRU/services, new firmware targets, multiple extruders,
upstream PRINT_START/START_PRINT strategies and physical PWM/cooling qualification
remain outside this contract.

Historical warnings remain: the Mini MZ thermistor accuracy warning is not
compensated or physically certified, and its PA13 red LED is not counted as
restored. GTR and other external transport/sensor dependencies are not certified
by this cooling contract. C classifications are scope boundaries, not authorization
to discard a required dependency of an otherwise supported path.

## Homing procedure boundaries

Active selected-board or printer-profile `homing_override` procedures are not
silently replaced with ordinary G28 or generated `safe_z_home`. KACE currently
has no reviewed migration/equivalence contract for their temporary TMC currents,
axis order, probe preparation or virtual belt-Z reset. Generation and source-bound
recovery/publication reject those sources; exact copied G-code in an include does
not certify compatibility with the selected hardware. Proven commented examples
are not activated. Older parsed maps with unknown activity require source reload;
saved raw text can establish that an old discovery entry was only a comment.

This is a support boundary, not implementation of those procedures; CR-30 belt
behavior also remains an explicit limit. No infinite-belt platform or PRINT_START strategy is added.
Source-agnostic manual configurations retain existing review responsibilities.
All effective configurations must reject simultaneous `safe_z_home` and
`homing_override`, including nested user includes and no-change retries, because
Klipper rejects that composition.


## Provisional targets and display identity

Printrboard rev B-D remains a provisional BoardContract. Its explicit AVR
clock/USB choices satisfy Kconfig and real builds at the audited revisions,
including pinned-builder Intel HEX identity checks. This evidence does not
promote runtime authority or certify bootloader entry, physical flashing or
communication with a board. Initial-installation lifecycle limits still apply.

OEM display advice uses exact config filenames and explicitly listed legacy
aliases. A family name, suffix, renamed file or unlisted model is not evidence
that it carries the same display. Ender 3 V2 2020 resolves separately from Ender 3
and Pro; Neo/S1/Max do not inherit its identity. Unbound names still receive
section-based analysis when display sections are present. These bindings do not
identify a physically connected module or qualify wiring; the unknown-hardware
and publication controls remain in effect. `dwin_set` is a legacy OEM label, not
a supported native Klipper `lcd_type` or permission to generate one.
