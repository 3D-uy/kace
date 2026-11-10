# KACE development and maintenance

[README](../README.md) · [Roadmap](../ROADMAP.md) · [Release](RELEASE.md)

## 🧭 Architecture and authority

KACE/Python owns printer configuration, hardware decisions, installation and
unfinished recovery. Studio is an independent desktop provisioner, coupled through
`KACE/scripts/bootstrap.sh` and validated events/checkpoints, not a shared package.
Do not duplicate hardware decisions in Studio JavaScript.

| Responsibility | Source |
| --- | --- |
| CLI, wizard and localized outcomes | [kace.py](../kace.py), [core/wizard/](../core/wizard/), [core/translations/](../core/translations/), [core/workflow_outcome.py](../core/workflow_outcome.py) |
| Profile identity and provenance | [core/board_identity.py](../core/board_identity.py), [core/scraper.py](../core/scraper.py), [core/reviewed_source.py](../core/reviewed_source.py) |
| Model, generation and templates | [core/capabilities.py](../core/capabilities.py), [core/generator.py](../core/generator.py), [templates/](../templates/) |
| Effective review and ownership | [core/configuration_review.py](../core/configuration_review.py), [core/reconciler.py](../core/reconciler.py), [core/managed_config.py](../core/managed_config.py) |
| Publication and recovery | [core/config_transaction.py](../core/config_transaction.py), [core/deployer.py](../core/deployer.py), [core/snapshot.py](../core/snapshot.py) |
| Firmware and durable installation | [firmware/](../firmware/), [core/firmware_workflow.py](../core/firmware_workflow.py) |
| Installation and host bootstrap | [install.sh](../install.sh), [scripts/bootstrap.sh](../scripts/bootstrap.sh) |

[VERSION](../VERSION) owns the version; [data/klipper_contract.yaml](../data/klipper_contract.yaml)
owns the validated Klipper revision. [BoardContracts](../data/board_contracts/),
their [schema](../data/board_contracts.schema.json) and
[deployment profiles](../data/firmware_deployments.yaml) bind exact targets,
authority and delivery. [boards.yaml](../data/boards.yaml) supplies reviewed
metadata/overrides; an entry alone does not authorize generation or flashing.
Required sensors, buses, cooling, displays and firmware reservations remain
subject to their Python consumers and reviewed source evidence.

Configuration publication also runs an isolated, pinned Klipper preflight for
object loading and fan references. When launched by Studio, Docker runs on the
Windows PC, not on the Pi. Studio prepares its pinned image before bootstrap,
then KACE sends its effective tree through a session-scoped SSH reverse tunnel.
`core/studio_preflight.py` uses Python's standard library only. The three
`KACE_STUDIO_PREFLIGHT_{PORT,TOKEN,SESSION}` variables select this route; even a
partial or stale context fails closed, with no fallback to Docker on the Pi.
The response must match a fresh request ID, session, tree digest, Klipper pin and
canonical-LF SHA-256 identities of the engine, recipe and worker. Publication
uses protocol `kace-studio-preflight/v2`: both directions carry HMAC-SHA256 over
canonical JSON with separate request/response domains. The private session key
never travels in the request; a process rebinding a stale loopback port cannot
forge approval by echoing its public fields. Unsigned v1 responses are rejected.
Publication
still rechecks the plan and destination before writing. Studio does not own
hardware decisions or deploy the tree. Launching `kace` manually in a new shell
does not inherit this context; reconnect and use Studio's guarded launch for a
new session. No old validation receipt can authorize a different plan.

Standalone CLI operation retains the local Docker backend. Install its CLI and
daemon on the machine running KACE, then explicitly provision the local image
from the KACE root with `python -m core.klipper_preflight --provision`. This build requires
network access for the pinned Klipper checkout and image dependencies. It uses
a digest-pinned multi-architecture base and records the resulting local image
ID together with hashes of the recipe and worker in
`~/.local/share/kace/klipper-preflight.json`. Changing the recipe, worker or
Klipper contract requires provisioning again. If Docker, the image, its receipt
or the isolated loader is unavailable, preflight is **unverified** and the
publication gate stops before writes; it must not be treated as a CFG rejection.

The image runs without network, with a read-only root and configuration input,
dropped capabilities and resource limits. A temporary executable filesystem is
needed to compile Klipper's helper. The check covers the explicitly reviewed
include tree and fan references in the pinned image. It does not attest the
destination's installed extensions or Python environment, MCU behavior, physical
safety, or all runtime events. Constructors that require an active reactor and
unrecognized errors are unverified. The Docker backend has been exercised on
Linux/amd64; Raspberry Pi/ARM remains unverified. The image and daemon are local
dependencies, not evidence that a printer has loaded or accepted the plan.

The opt-in integration `tests/integration/test_config_transaction_klipper_preflight.py`
uses the real provisioned loader for twelve publication cases: root, include and
SAVE_CONFIG references, each with changed/no-op plans and valid/missing heaters.
It checks rejection before review, writes or activation and preserves original
destination bytes. The destination remains a simulated transport; positive cases
defer activation. After provisioning, set `KACE_C3_DOCKER_INTEGRATION=1` and run
`python -m pytest tests/integration/test_config_transaction_klipper_preflight.py -q`.
Without that explicit flag the tests are skipped, not counted as real-loader
verification. This uses the same opt-in as the firmware-boundary integration.

Hardware preflight checks explicit connection options on both primary and named
MCUs with `validate_mcu_connection_options`: serial baud is an integer >= 2400;
restart methods follow the pinned set. CAN, host and PRU connections do not
consume baud/restart options, so supplying them is rejected rather than silently
ignored. Omitted defaults and endpoint identity remain with their existing
owners; this check does not prove that a device is connected or correctly wired.

Preserved TMC2240 sections already use the UART/SPI transport validators. Their
current preflight now also checks finite `rref` in [12000, 60000] ohms (default
12000) and positive finite run/hold currents <= `(36000 / rref) / sqrt(2)` A RMS.
It preserves the pinned arithmetic at the inclusive boundary, including valid
currents above 2 A; it does not enable guided generation or sensorless support
for that model, or certify the motor, board or cooling ratings.

UART `select_pins` preserves an explicitly empty list, separately from omission,
through selected-board resolution, generation/provenance and effective review.
The pinned UART registry distinguishes no mux (`None`) from an empty mux tuple:
shared RX cannot mix those layouts, and empty mux instances still require unique
addresses. Empty tokens inside a nonempty selector list retain KACE's existing
nonempty-pin policy. This fixes a false rejection for guided TMC2208/TMC2209 and
preserved TMC2240 UART without enabling guided TMC2240 or changing SPI behavior.
Effective UART review recognizes tabs as well as spaces between model and target,
while retaining the literal section name and each model's address limits. This
does not establish guided source selection or SAVE_CONFIG identity for all TMCs.
SPI transport ownership likewise recognizes tab-separated TMC sections when
checking shared chip-selects and chain positions, while retaining literal names
and leaving TMC2240 UART on its existing route. This does not certify every SPI
peripheral, pin collision, sensorless path or physical bus.
Guided TMC source selection and profile-value extraction recognize spaces,
repeated spaces or tabs between model and target. Selection emits the existing
canonical generated section name, rejects ambiguous duplicate sections for the
selected model, and preserves the existing treatment of other models. SAVE_CONFIG
section identity and other TMC selection paths have separate contracts.
The current, SPI-option, register, auxiliary-option and sense-resistor gates in
`profile_values` recognize a tab between a TMC model and its target as well as
spaces; they retain the original section text. This does not verify every TMC
transport, sensorless or source-selection path with tabbed sections.
`tests/{unit,integration}/test_tmc_select_empty.py` checks these distinctions,
includes/SAVE_CONFIG, no-op review and rejection before publication. Acceptance
does not qualify a physical multiplexer, pinout, timings or driver communication.

`validate_heater_options` checks supplied fields of extruder, heater_bed and
heater_generic sections: finite temperature/power/timing values, min_temp >=
-273.15 Celsius, max_temp > min_temp when both are present, 0 < max_power <= 1,
and positive smooth_time/pwm_cycle_time. Active PID coefficients must be finite;
the pin accepts zero/negative coefficients, so KACE does not invent bounds for
them. With `control: watermark`, supplied `max_delta` must be positive and
finite; the positive bound follows the pinned controller, while finiteness is
KACE policy. Omission retains Klipper's 2 Celsius default, and positive decimals
are preserved without an invented maximum or any claim of safe thermal tuning.
Inactive controller options remain with their existing required/unused-option
validators. Partial fragments do not acquire missing required fields. Explicit heater
PWM periods must not exceed the selected sensor's report interval from the pin:
ADC (including custom thermistor/ADC curves), SPI MAX sensors, MCU and combined
sensors use 0.300 s; BME280 uses 0.8 s and temperature_host uses 1 s. DS18B20,
LM75, AHT, HTU/SI and SHT3X use their own configurable report interval, preserving
the pinned defaults, minimums and integer/float parsing. Consumed report values
must be finite. Unknown sensor factories remain subject to reference validation;
this check does not assume their timing or enable peripheral generation.
`temperature_fan.cycle_time` follows the fan contract, without a sensor-derived
PWM maximum. Output-provider limits, actual clocks and electrical capabilities
still require the pinned loader/connected MCU and independent qualification.
No temperature/power option certifies safe physical heating.
Explicit `min_extrude_temp` is also consumed by the shared Klipper Heater class,
including secondary extruders, the bed and generic heaters. The common gate
requires a finite value within the supplied min_temp/max_temp bounds, inclusive.
Zero and negative values within those bounds remain accepted. Omission retains
Klipper's 170 Celsius default without checking or materializing it, even when it
exceeds max_temp. Partial fragments do not acquire missing bounds. The existing
primary-extruder validator is preserved; `test_heater_min_extrude_temp.py` adds
common-gate and effective-publication regressions. This does not authorize cold
extrusion or establish a physical operating temperature.

`validate_pwm_outputs` checks proven MCU providers for fan, fan_generic,
controller_fan, heater_fan, temperature_fan and PWM output_pin consumers.
Software PWM shutdown must be 0 or 1 after the consumer's max_power/scale and
pin inversion. Fan/controller/generic defaults are zero; heater/temperature
fan defaults are one. Named MCUs and multi_pin leaves retain their own provider
and inversion; ADC provider mappings are not reused for PWM. Hardware PWM and
unproved providers do not acquire this software-only bound. PWM output_pin has
the pinned MCU nominal-period ceiling of 3 seconds, even for hardware PWM;
this is not a universal fan/heater period limit. No clock frequency is inferred
from board names or firmware build metadata. Actual tick limits, hardware PWM
timers and unrecognized providers remain separate.
Consumer scalar validation and provider availability are still required; this
bounded gate does not certify every option or enable new generation routes.
The MCU and SX1509 PWM gates also recognize named fan sections with a tab
separator. `test_pwm_fan_tabs.py` covers their provider checks and simulated
publication; other tab-separated consumer families retain separate coverage.
These provider checks also recognize tab-separated heater_generic, output_pin,
pwm_tool and pwm_cycle_time consumers; they preserve the original section name
and retain each provider's existing limits and separate admission checks.
Queued PWM sections preserve literal case and tab separators during SAVE_CONFIG
merging so saved options reach the same section in the effective review.
`tests/{unit,integration}/test_pwm_output_contract.py` covers these checks before
CFG/sidecar writes and effective publication, with simulated transport only.

Queued `pwm_tool` and variable-frequency `pwm_cycle_time` consumers construct
MCU objects directly; they cannot delegate through multi_pin. For known direct
MCUs the same gate checks their finite scalar ranges, 3 s nominal period and
normalized shutdown. Only pwm_tool has hardware_pwm. Its omitted
maximum_mcu_duration remains zero, while an explicit value must be in [0.5, 3]
seconds and requires equal effective start/shutdown levels. Inversion follows
the pinned floating-point arithmetic. Runtime SET_PIN and clock-dependent
limits stay with Klipper; this does not enable guided generation of these tools.

`validate_sx1509_pwm` recognizes declared SX1509 providers and multi_pin leaves.
Fan/PWM output_pin consumers require hardware_pwm; Heater consumers are rejected
because SX1509 does not support their watchdog duration/mode. Fractional levels
remain compatible with this provider. Its requested cycle and cached shutdown
are not proof of physical frequency or shutdown behavior. PWM output_pin still
has its own 3 s ceiling through the SX1509's underlying MCU; fan periods do not
acquire that ceiling. I2C, pin availability, firmware and physical behavior
remain separate checks. Named pwm_tool, pwm_cycle_time, fan_generic and
temperature_fan sections preserve their exact names when merging SAVE_CONFIG,
so saved options reach the original consumer. Other section identity rules are
unchanged. `test_queued_pwm_contract.py` and `test_sx1509_pwm_contract.py` cover
these gates, compatible values and rejected publication without hardware IO.

`validate_part_fan_options` applies the common Fan scalar bounds to all five fan
consumers, including preserved controller/generic/temperature fans. Tachometer
PPR must be an integer >= 1 and its polling interval finite and > 0. Explicit
tachometer parameters require tachometer_pin, otherwise the pinned loader rejects
them as unused. These checks do not enable guided generation of auxiliary pins.
`validate_fan_consumers` checks controller fan speeds and integer idle_timeout,
and complete temperature fan sections: temperature bounds, target, speeds and
watermark/PID options. Finite values are an additional KACE admission policy.
Omitted defaults retain Klipper's behavior; in particular target_temp may default
below min_temp, and the constructor does not require min_speed <= max_speed.
Negative/zero PID coefficients remain accepted by the pinned constructor.
Runtime SET_TEMPERATURE_FAN_TARGET has different bounds and remains Klipper's
responsibility. Controller heater/stepper registry resolution, comprehensive
auxiliary-pin capability checks, clock timing and physical cooling remain
separate requirements. `tests/{unit,integration}/test_fan_common_contract.py`
and `test_fan_consumers_contract.py` cover the admission gates and preservation
of compatible values, including includes, SAVE_CONFIG and pre-write rejection.

`validate_fan_auxiliary` checks enable_pin and tachometer_pin in the same five
fan consumers before writing or approving an effective plan. Enable accepts
inversion, whereas the tachometer accepts pullup/pulldown without inversion.
The tachometer constructs an MCU_counter directly; declared multi_pin/SX1509
output providers do not implement that interface. Digital enable may delegate
through those providers. Named MCUs keep their own identity; no same-MCU rule
is inferred for these auxiliary pins. Unknown extension providers, actual pin
availability, sharing/aliases, timing and physical capability remain separate
checks. Empty pin names can pass the pinned parser and are not qualified here.
`heater_fan` preserves an explicitly empty heater list, while an omitted list
retains the extruder default. Empty tokens inside a nonempty list still fail.
`tests/{unit,integration}/test_fan_auxiliary_contract.py` and
`test_heater_fan_empty_contract.py` cover these distinctions and publication
boundaries. Ordinary object loading stops before connect/ready and cannot
certify deferred heater/stepper references or physical cooling.
The heater_fan reference gate recognizes a heater_generic name separated by
spaces or a tab, as Klipper's section loader does. It still uses a bounded
header-based inventory and does not prove completeness for extension-produced
heaters; `test_heater_fan_header_whitespace.py` covers the separator in review
and simulated publication without changing case-sensitive heater names.

`validate_controller_fan_references` rejects empty elements inside nonempty
heater/stepper lists before writing or approving the effective configuration.
Omitted options, explicit empty lists, exact case and full registered names
retain their meaning. This is a list-structure gate, not a complete registry
resolver: missing names, conditional motor construction and external object
registration remain subject to Klipper's connect-time validation. In particular,
manual_stepper and extruder_stepper names must not be shortened by inference.
`tests/{unit,integration}/test_controller_fan_references.py` covers this scope.
For named fan sections separated by a tab, effective review retains the exact
section identity and applies the same common fan, auxiliary pin, consumer and
heater-reference checks as for space-separated sections. This does not certify
all source-selection, PWM-provider or extension paths for tabbed headers.

The container matrix validator now resolves deferred fan references after
Klipper's real object loading and unused-option checks. It uses the constructed
heater/stepper registry, invokes only ControllerFan's lookup-only handle_connect,
and performs HeaterFan's heater lookups without its timer-registering
handle_ready. Result metadata separates object_load from fan_references; a
reference failure is a failed configuration validation. No global connect/ready,
MCU identification, reactor loop or physical commissioning is performed.
This strengthens automated CFG validation, not the static Core preflight: unknown
names preserved by Core still need this registry check. Section names alone
cannot prove conditional extruder motors or sequential numbered objects exist.
`tests/unit/test_klipper_fan_registry_validation.py` covers phase ordering,
registry use and absence of startup/timer execution.
The matrix validator enumerates the loaded object registry and recognizes fan
families with tabs or spaces, matching Klipper's section loader; the narrower
`lookup_objects(module)` prefix lookup alone omits tab-separated names.
`test_klipper_fan_registry_whitespace.py` covers that distinction using the
pinned registry method. This remains a test-matrix check, not a Core deploy gate.

Object loading is not a read-only operation: the pinned `save_variables`
constructor can create its configured file before MCU identification. The matrix
therefore mounts a disposable copy of the input tree and publishes only its fresh
result file. Changes to existing staged inputs invalidate that run as an
infrastructure error; constructor-created files are discarded with the copy.
The offline loader refuses reactor pauses required by asynchronous constructors
and reports `infrastructure_error` (unverified), even if a constructor wraps that
failure. This is a validator capability limit, not a rejected Klipper option.
The reactor must not be started to bypass it: Printer schedules its connection
callback during construction. These limits also prevent treating this worker as
a safe native pre-write validator on a live Pi. Core publication remains partial.
`tests/unit/test_matrix_input_isolation.py` covers input preservation, stale
results, altered inputs and the distinction between unavailable validation and
configuration errors. Direct worker invocation does not provide file isolation;
use the matrix runner or an equivalently confined environment.

The static Core gates run after rendering before CFG/sidecar writes and during effective
plan review, including preserved includes, SAVE_CONFIG and no-op attempts.
`tests/{unit,integration}/test_mcu_connection_contract.py`,
`test_tmc2240_current_contract.py` and `test_heater_options_contract.py` cover
incompatible values, compatible boundaries and rejection before publication.
`test_heater_pwm_sensor_contract.py` adds sensor-specific boundaries, configurable
periods, custom sensor names and pre-write gates across includes/SAVE_CONFIG.
`test_heater_watermark_delta.py` covers the selected controller's deadband,
preservation and rejection before generation/publication writes, including
includes, SAVE_CONFIG and no-op attempts.
Custom thermistor validation rejects an exactly zero logarithmic denominator
before computing its three-point determinant: distinct resistance floats can
round to the same logarithm. This produces a controlled configuration error
instead of an uncaught division by zero; no minimum sample spacing or numerical
tolerance is imposed. `test_thermistor_log_singularity.py` covers permutations,
compatible curves and rejection before generation/publication writes. The
existing guard checks definitions even when unused; Klipper fits coefficients
when the sensor factory is consumed. Neither check proves physical calibration.
Custom `thermistor` and `adc_temperature` section names keep their exact case
through source parsing, ownership reconciliation and effective SAVE_CONFIG
merging. Active options override saved options only in the same exact section;
case-distinct curves do not share values. Internal header whitespace is retained.
`test_saved_sensor_case.py` covers root/includes, preserved autosave bytes and
case-distinct ownership. For generation, `selected_custom_thermistors` first
matches the exact factory name across board and profile, normalizing header
whitespace as Klipper does for factory registration. Only if no exact match exists
does it bridge legacy case-folded mappings. Conflicting definitions within the
chosen group still fail before CFG/sidecar writes; exact names take precedence
over differently cased entries, without assigning priority to either source.
Rejecting conflicting definitions of the same normalized factory is KACE policy;
Klipper's factory registry assigns by key and does not enforce that conflict rule.
`test_thermistor_selection.py` covers separate hotend/bed curves, profiles,
checkpoint round trips, conflicts and provenance. Legacy mappings carry no parser
version: without an exact match, the fallback cannot distinguish a historical
folded name from a differently cased current name. Resolving that ambiguity needs
a separate provenance/migration contract; no physical calibration is inferred.
This factory-name normalization does not alter literal SAVE_CONFIG identities.
Other section families retain their rules, and definition order remains required.
The six reviewed TMC section families also retain exact case and internal
whitespace in source extraction and SAVE_CONFIG reconciliation. A saved option
supplements only the same literal section, not a differently cased driver. Old
profile maps already folded by earlier versions cannot recover lost spelling.
The real pinned loader remains necessary for options/dependencies outside these
bounded validators and does not replace physical commissioning.

The flow selects sources and user choices, validates, renders under `~/kace/`,
reviews effective destination settings/includes, snapshots, publishes and verifies
activation, loaded configuration and running firmware before `DONE` / checkpoint
`COMPLETE`. Receipts cannot be invented or silently renewed. Stale checkpoint
writers fail; reconnecting or seeing `Ready` does not replace completion evidence.
This applies to initial installation and unfinished resumes, not monitoring later
user edits. See [support](en/SUPPORT_SCOPE.md) and [deployment](en/DEPLOYMENT.md).

Include discovery follows the pinned Klipper parser's section-header matching
before applying KACE's existing restrictions on paths. Firmware/configuration
deployment binds staged files to the reviewed plan: it checks them before power
and firmware actions, then reads all checked bytes before any upload and verifies
the uploaded content against the plan. These checks do not provide an isolated
Klipper preflight or guarantee atomicity across external editors and files.

Interrupting the initial recovery menu with Ctrl+C or EOF exits through the normal
cancelled outcome (code 2), without a traceback, opening the dashboard or writing
the saved checkpoint. `tests/unit/test_installation_recovery.py` covers this path.

Both configuration-only and combined firmware/configuration completion require
loaded raw configuration to match the effective reviewed plan, including removed
sections and options. Verification runs after readiness and required firmware
checks, before the final file recheck and `DONE`. A transport without that
verification capability fails before writing when completion is requested;
offline publication with explicitly deferred activation remains pending. Missing,
malformed or stale loaded evidence is a verification failure, never a substitute
for readiness. Preserve current files and snapshots under the existing recovery
rules when a failure cannot be restored safely.

Managed-macro migration warnings compare the previous active include with the
final effective configuration. Relocating or deselecting an include can remove
a custom macro's effect even when its old file remains untouched; report that
loss before publication. Identical macros retained at another managed path and
unreferenced user-owned files must not produce false replacement warnings.
`tests/unit/test_stabilization_p2.py` covers both layouts and ownership cases.

[PrinterMotionSpace](../core/motion_model.py) separates mechanical travel,
printable bounds and probe reach. Current keys include `x_position_min`,
`x_position_max`, `x_position_endstop`, `printable_x_min` and `printable_x_max`,
with Y equivalents and Z bounds. Probe-tip position is nozzle position plus offset;
probeable bed is printable area intersected with probe reach. Consumers must use
the shared model and reject an empty intersection. These bounds do not imply
IDEX/toolchanger support or authorize motion outside mechanical travel.

Effective XY review also uses `PrinterMotionSpace`, through
`core/config_geometry.py`, after destination includes and SAVE_CONFIG have been
resolved. Generation records the four resolved printable XY bounds and the
generated CFG's SHA-256 in the existing `.provenance.json` sidecar. Deployment
binds that context to the source bytes before planning, then uses effective rail
limits and probe offsets rather than the original generated values. Do not
reconstruct bed bounds from travel, mesh limits, comments or mutable wizard data.

Config-only, local export and combined firmware/configuration preflight enforce
the same check, including no-op and unfinished recovery. Rectangular mesh,
safe-home XY and active leveling points must fit their respective nozzle/probe
envelopes; physical pivots are not probing points. Physical-endstop homing does
not require a probe, and manual mesh remains supported. Pin-only fragments are
not treated as complete XY geometry. Preserved circular meshes use their origin
and Klipper's radius rounding against the same XY envelopes; circular generation
remains unsupported.

Full XY plans with probing operations require bound printable limits. An older
sidecar without geometry, a missing sidecar, or mismatching CFG bytes cannot
accredit those bounds: review the bed dimensions and regenerate the proposal.
This preserves destination files/calibration and does not renew MCU evidence.
The hash binds inputs to generated bytes; it is not physical calibration or a
signature. New generation keeps CFG bytes and existing sidecar fields unchanged
apart from the additional geometry metadata. Tests in
`tests/unit/test_effective_xy_geometry.py` exercise invalid includes before writes
and valid publication, SAVE_CONFIG, no-op and concurrent edits.

Leveling examples retain the 10mm margin where it leaves distinct points. For
an axis at most 20mm wide, the margin is one quarter of the available span.
Derivation checks nozzle travel and probe-on-bed coordinates before and after
the template's one-decimal rounding, and rejects collapsed or collinear point
sets for the selected method. Examples remain commented and physical pivots
still require measurement. Printers without probe-based leveling do not derive
unused examples.

QGL examples use the pinned Klipper algorithm's physical order: Z front-left,
Z1 rear-left, Z2 rear-right, Z3 front-right. Its X fits use point pairs 0-3
and 1-2; the independent z_tilt example order is unchanged. Before enabling
the commented QGL section, verify actual motor assignment and measure gantry
corners. Declared bed/travel envelopes and offsets are not proof of physical
clearance, wiring, calibration or the initial unhomed position.
`tests/integration/test_qgl_geometry_contract.py` parses generated examples
with the pinned parser and runs the unmodified upstream QGL arithmetic with
simulated probe results. It consumes the emitted corners and points, including
shifted beds and narrow intersections with positive or negative probe offsets.
Tilted and twisted surfaces check corrections in Z/Z1/Z2/Z3 order; the previous
point order reproduces division by zero. This
test checks source identity and tracked cleanliness, but does not instantiate
Klipper hardware. Run the documented quick matrix separately for full object
loading and unused-option validation. Effective XY review also requires exactly
four active QGL points and nonzero X spans for pairs 0-3 and 1-2, and a nonzero
Y span for pair 0-1, matching the pinned algorithm's divisors. Invalid includes
fail before approval or writes. Non-rectangular point sets remain allowed;
existing hand-edited configurations are never automatically reordered.
These checks do not verify physical motor numbering, measured gantry corners,
or numerical conditioning for extremely small nonzero spans. Runtime parameter
overrides and arbitrary movement macros remain outside the static geometry
contract, as do collisions and clearance from an unknown initial position.

Safe-Z homing preserves KACE's default `z_hop=10` only when compatible with the
Z limits. An explicit `safe_z_home_z_hop` selection, or an unambiguous imported
`[safe_z_home] z_hop`, is preserved, including zero to disable the lift. Conflicting
board/profile values require explicit selection. Generation and effective review
reject non-finite/negative values or a positive target outside the Z rail.
Discovery comments never select a hop: the parser records active source options.
Saved raw source recovers legacy activity; disagreement with its parsed copy
requires reload before any override can be used.
Klipper moves to this coordinate from an assumed zero when Z is unhomed, or when
a homed Z is below it, including after homing; checking rail length alone is
insufficient. This does not guarantee clearance from an unknown physical start.
Existing probe-trigger and mesh-clearance validations remain separate.

Bed-mesh speed and fade settings follow the same mechanical-source selection
as clearance/interpolation: a selected `_profile_parsed` owns them, including an
empty profile; otherwise the board/source configuration supplies them. KACE's
defaults remain speed 120 and fade 1/10/0. Explicit numeric text and zero-valued
fade options are retained. These are KACE defaults, not Klipper defaults.
Adaptive margin keeps decimal precision: an explicit user key (including zero)
overrides the selected profile, then the `adaptive_mesh` flag supplies 5 only
when neither source provides a margin. The option alone does not enable adaptive
calibration. Negative finite fade/margin values are not forbidden by the pin;
runtime mesh-dependent constraints and physical suitability remain separate.

Managed plans retain existing speed, fade_start/end/target and adaptive_margin,
as well as the existing mesh tuning whitelist. This does not expand the
homing-only `replace_preserved` permission. Invalid preserved settings must be
reviewed; they are not silently replaced by defaults. `validate_mesh_options`
runs during derivation, after rendering and over effective destination settings
before approval/writes. It rejects non-finite active mesh scalars (the pinned
loader itself accepts `speed: nan`) and checks the pin's scalar bounds without
claiming that a loaded config can move safely. Saved mesh profiles, arbitrary
macros and command-time overrides are not a universal finite-number guarantee.
`tests/unit/test_mesh_scalar_contract.py` and
`tests/integration/test_mesh_scalar_contract.py` cover source switching, explicit
zero/decimals, generation/postprocessing, preservation, includes/SAVE_CONFIG and
rejection before confirmation or writes, including no-op publication attempts.

For a preserved `probe_eddy_current` provider, effective XY review now enumerates
the pinned `rapid_scan` path, including initial overshoot, segmented arcs,
faulty-region detours, circular grids and the zero-reference leg. It subtracts
the provider's XY offsets and checks every movement vertex against declared
mechanical travel. Connecting line segments stay within that convex rectangle;
this does not prove clearance from obstacles or an unknown initial position.
BLTouch, ordinary probes and manual probing do not execute this path upstream,
so their existing XY review is retained even if scan_overshoot is present.
Explicit scan_overshoot still requires a finite value >= 1; omission means zero.

`core/mesh_scan_geometry.py` contains the pure geometry subset attributed to
the pinned GPLv3 Klipper source, without a runtime checkout dependency. Its
version must track `data/klipper_contract.yaml`. Integration tests compare every
vertex/sample marker against the unmodified official algorithm, with both offset
signs and travel bounds clipped at each extremum. This isolated model avoids
approximating curves with arbitrary margins; it does not refactor generation.
`tests/unit/test_mesh_scan_geometry.py` covers the effective-review boundary and
rejection before writes. `tests/integration/test_mesh_scan_contract.py` covers
the pinned paths. Reading preserved eddy offsets does not enable generation,
electrical support or calibration of that hardware. Command overrides, adaptive
object bounds, runtime scan Z/initial position and physical collisions remain outside
this static XY contract. The pinned loader still must check unsupported options;
accepting a configuration does not execute these trajectories.

For a preserved named `probe_eddy_current` provider, `validate_mesh_clearance`
also checks the configured rapid-scan Z approach: `horizontal_move_z + 0.5`
must not exceed a known `stepper_z.position_max`. The additional 0.5 mm comes
from the pinned `RapidScanHelper._raise_tool` and `_move_to_scan_height`, not
from a physical safety margin. The exact boundary is accepted. Existing finite
height, Z minimum and ordinary probe offset checks still apply; ordinary probes,
BLTouch and manual meshes do not inherit an eddy-only constraint. Partial
fragments without a known Z maximum do not acquire an invented limit.

Static homing review also requires explicit `safe_z_home.speed` and
`z_hop_speed` to be finite and positive, even with `z_hop: 0`: the pinned
constructor reads both options before any move. Omitted defaults remain intact.
For ordinary probe/BLTouch virtual Z homing, the effective trigger is `z_offset`;
direction parsing, quarter-range inference and endpoint contradictions follow
the pinned `GenericPrinterRail`. A compatible explicit positive direction is
allowed; KACE does not infer wiring or physical homing safety from that value.

Active `z_tilt` and `quad_gantry_level` sections use
`validate_leveling_clearance` after rendering and during effective-plan review.
Configured `horizontal_move_z` (default 5 mm) must be finite, within known Z
limits and at least the probe Z offset; `speed` (default 50 mm/s) must be finite
and positive. Ordinary ProbePointsHelper uses a zero Z offset for eddy and does
not inherit the bed-mesh rapid-scan 0.5 mm approach. Missing partial-fragment
limits are not invented. Invalid values stop generation before CFG/sidecar writes
and stop publication, including no-op plans, includes and SAVE_CONFIG.
Tests: `tests/{unit,integration}/test_homing_z_pending.py` and
`test_leveling_z_contract.py`. Command-time HORIZONTAL_MOVE_Z overrides,
measurement-dependent motor adjustments, an unhomed physical Z position and
collision clearance remain outside this static validation.

`validate_leveling_adjustment_options` checks active Z tilt/QGL configuration
after rendering and before effective-plan publication: `retries` is an integer
>= 0, explicit `retry_tolerance` is finite and > 0, and QGL `max_adjust` is finite
and > 0. An omitted tolerance retains Klipper's zero default; it is different
from explicit zero. Do not apply the command-only RETRIES <= 30 and
RETRY_TOLERANCE <= 1 bounds to configuration defaults: the pinned parser accepts
larger configured values and uses them when the command omits those options.
Unknown macros and command overrides remain outside KACE's static contract.

The optional examples describe retries as additional probing cycles and tolerance
as the range of probed Z values. Pinned QGL compares `max(adjustments)` against
`max_adjust`, not the largest absolute adjustment. Starting at H, the adjustment
helper can request `H + max(adjustments) - min(adjustments)`; a configured H within
the Z rail is not proof that a later measured correction fits. KACE does not
invent a smaller limit to mask this runtime behavior. Probe lift-speed overrides
and physical motor correspondence remain Klipper/runtime or commissioning work.
`tests/{unit,integration}/test_leveling_adjustment_options.py` covers configured
values and pre-write rejection; `test_leveling_adjustment_guidance.py` covers
generated EN/ES/PT comments without activating examples. The integration
`test_leveling_dynamic_contract.py` runs unmodified pinned algorithms with device
doubles to record command/default differences, retries, positive-only adjustment
limits and motor correction requests; it does not perform physical leveling.

This gate runs after rendering, before writing the CFG/sidecar, and on effective
destination settings including includes and SAVE_CONFIG before publication,
even for no-op plans. Invalid review results cannot be overridden by an accepting
review callback; a review callback may still be invoked to display the errors.
`tests/unit/test_mesh_scan_z_contract.py` covers the scope and boundaries;
`tests/integration/test_mesh_scan_z_contract.py` covers preservation, pre-write
rejection and the unchanged pinned approach methods with simulated devices.

KACE owns generated/preserved configuration and specific generated macros such
as PARK_HEAD. It does not produce or semantically validate BED_MESH_CALIBRATE
command overrides (SCAN_SPEED, HORIZONTAL_MOVE_Z, METHOD, ADAPTIVE or dynamic
mesh bounds). Generic shell/SSH transport is not authority over those values.
The pinned Klipper runtime still owns these commands, measured meshes, fade
transforms and G-Code offsets. In particular, its zero SCAN_SPEED division and
initial approach using configured height despite a runtime height override are
upstream limitations, not reasons to forbid compatible CFG values in KACE.
Passing the static approach check does not prove physical clearance, sensor
calibration, homing correctness or safety of later commands.

Printable XY bounds use one origin policy in normalization and the motion
model. KACE no longer translates an implicit bed to fit a shifted rail:
for example width220/travel[-10,210] requires explicit bed bounds. The profile
editor's printable-XY option stages all four bounds together, marks accepted
values as user overrides and leaves the rail unchanged; Back discards them.
Confirmed [-10,210] bounds remain valid and preserve center100. Materialized
defaults carry `_printable_bounds_defaults` through saving and checkpoints so
they do not become explicit measurements merely by serialization. Edited or
explicitly accepted values retire their default marker. Older values without
this trace cannot have their historical origin reconstructed. Generation still
requires its printable area inside travel, while effective review can retain
an explicit bed larger than a reduced rail and validate only reachable points.
Summary/preview diagnose unresolved origins without inventing a bed position.
The profile review and editor display the same saved printable XY coordinates,
separately from mechanical travel. Missing bounds are shown as undefined rather
than inferred from rail limits. The editor explains coordinates with a standard
220 x 220 mm example; editing still uses the existing staged geometry validation.

Profile and final reviews also show a read-only nozzle/bed schematic from
`core/nozzle_bed_visualizer.py`, using `PrinterMotionSpace`. The two views
separate the configured XY endstop reference from maximum travel beyond each
printable edge. They never represent live position or promise the final position
after Z homing/macros. Unknown bounds/travel do not produce inferred distances;
unknown endstops do not prevent displaying otherwise known travel. The drawing
is explicitly not to scale, and probe offsets do not change nozzle overhang.
`tests/unit/test_nozzle_bed_visualizer.py` covers quadrants, edges, shifted beds,
missing inputs, localized layout and non-mutation.

Generated pin comments explain input pull-ups/inversion and each motor signal
in EN/ES/PT. The template's comment-only endstop helper distinguishes physical
inputs from probe/TMC virtual endstops, including optional Z1-Z3 inputs. Values
and prefixes remain owned by the existing pin contracts. Inline comments use
the existing column 49 (one-based), or one space after longer values; imported
custom probe blocks remain verbatim. `tests/unit/test_generated_pin_comments.py`
covers generation, translation, alignment and preservation of pin values.

Sensorless homing uses the existing TMC virtual-endstop validator in generation
and effective review. An active sensorless rail requires explicit
`homing_retract_dist=0` on its primary stepper section (Klipper defaults to 5).
Participating TMC motors must omit `hold_current`; CoreXY X/Y homing involves
both rails. Physical endstops and unrelated motors retain their settings.
Manual steppers do not use PrinterRail's retract default. DIAG, aliases, MCU
identity and pin reservations remain separate enforced requirements.
The sensorless review recognizes tabs and repeated spaces between TMC model and
target for driver association and participating-motor checks. The hold-current
restriction is KACE's existing admission policy; these checks do not qualify
physical homing or establish compatibility of every TMC source-selection route.

Folder export (`deploy_usb`, `deploy_local`, `_copy_artifacts`) accepts only
`artifact_type="config"`. Legacy `firmware`/`all`, including the public default
`all`, fail before prompts or writes instead of silently exporting a subset.
Firmware must use the existing verified deployment service with its artifact,
target, method and transformation evidence; a source filename is insufficient.
Configuration export keeps its managed transaction and geometry review.

The contract audit distinguishes active authorities from compatibility helpers:

| Component or data | Current role |
|---|---|
| `verify_upstream_content` | The BoardContract test gate checks the seven contracts against the local pinned source and requires `.ok`; no network request is added to generation. |
| `verify_checkout_commit` | Builder checks already compare exact checkout commit and cleanliness. Retain the helper without adding a duplicate runtime gate. |
| `validate_motor_power` | Compatibility wrapper for the same digital-output validator used by active `validate_board_digital_outputs`. |
| `_validate_and_sanitize_geometry` | Compatibility surface; normalization remains the active authority, sharing printable-bound resolution with the motion model. |
| `verify_remote_file_exists` | Retained helper; deployment relies on content/hash and loaded-configuration verification, not mere existence. |
| Reachability/filter/`derive_probing_points` helpers | Retained helpers, not publication gates. Do not connect their raw travel/clamping results as bed-safety evidence; effective review uses the validated model intersection. |
| `data/overrides.yaml` | Inactive placeholder. Editing it does not apply motor directions or change generated pins. |
| `boards.yaml::printer_profiles/features` | Legacy catalog/compatibility metadata, not an operative MCU/board validation authority. Do not confuse this with the separately consumed display profiles. |
| `search_terms` | Used by catalog loaders, compatibility exports, YAML checks and matrix tooling; not proof of board, wiring or firmware compatibility. |
| `test_stock_validation` | Includes historical literal-data examples and tests of current reviewed filename suggestions. Literal matching examples do not establish a runtime gate; exact board/MCU authority is `board_identity` and its consumer tests. |

Retained helpers are not automatically reactivated or removed. Reconsider one
only for an identified caller with tests for its intended semantics. Arbitrary
macro movement, automatic physical-bed inference and new board/firmware support
remain outside these corrections.

Primary XYZ homing direction is selectable in the profile editor and motion
wizard: automatic, toward minimum or toward maximum. A reviewed profile reuses
those choices; only an ambiguous automatic direction requires another question.
The no-profile motion flow still collects each choice. Automatic uses Klipper's
endstop/travel inference, recalculated after geometry edits, and leaves a localized
commented `homing_positive_dir` example for physical endstops. For probe-based Z,
the comment leaves the optional Boolean blank because Klipper uses the probe's
effective trigger position rather than the replaced physical endstop. Imported
or user-selected explicit directions remain active; an ambiguous automatic
physical direction requires a minimum/maximum choice. Existing destination and
user-include overrides retain their ownership and are checked by the effective
configuration review, which rejects invalid ranges and contradictory directions.
Motor rotation is a separate choice in the profile editor, or after Z mechanics
for the no-profile route. Each mapped active motor (X/Y/Z, independent Z1–Z3 and
the primary extruder) offers Keep or Invert relative to the selected board/socket's
original `dir_pin`. CoreXY identifies A/stepper_x and B/stepper_y. Motors on one
shared driver cannot be inverted independently. These choices do not change
`homing_positive_dir`, mechanics, geometry or wiring, and perform no motion.

[core/motor_direction.py](../core/motor_direction.py) stores only explicit
inversions in `motor_directions`, with the board, socket, source pins and resolved
direction-pin identity. The existing wizard checkpoint persists that JSON data.
An absent entry keeps the source; choosing Keep removes the override. Generation
projects inversions onto its deep-copied pin context, never the board source, so
repeated selection/generation/resumption does not toggle again. A changed source
or inactive motor requires review rather than silently rebasing an old choice.
Both editor and no-profile review stage changes until Save/Continue; Back or Quit
discards that review's edits. Existing generated artifacts remain unchanged when
no inversion is selected. Destination overrides retain their existing ownership
and effective-review rules; a questionnaire choice does not bypass those checks.
Physical direction still needs verification during commissioning.

For probe-based Z homing, the effective probe `z_offset` must also lie within
the Z travel limits (`position_min` defaults to zero). Generation and deployment
review reject an incompatible range before publishing files or restarting Klipper;
explicit profile/user limits are not silently adjusted. The wizard checks this
geometry after probe selection, before firmware preparation. An incompatible
range shows the Z minimum/maximum and effective probe offset, then offers an
explicit minimum edit or, for a custom probe, entry of a known Z offset directly
from that review. Both edits validate a copy and require confirmation before
continuing; cancellation preserves the accepted values. A valid profile remains
unchanged. This does not measure
or calibrate the probe offset, permit motion, or replace effective include review.

An interactive pending `MCU_VERIFIED` workflow offers **Review Z minimum**;
continuing also rechecks the saved geometry before generation. The review edits
the selected Z minimum or known custom-probe offset, validates a copy, and persists an accepted change with the
existing checkpoint's revision guard in the same state. Cancellation leaves the
saved checkpoint unchanged. Hardware, firmware artifact, delivery and identity
evidence are preserved, not renewed; the edit does not clear a saved error or
establish `COMPLETE`. Generation, effective review, activation and loaded
configuration/firmware verification remain required. Custom-probe checkpoints
retain the original raw block and reparse it when resuming; older guided checkpoints
reconstruct and validate their saved settings before generation.

Custom-probe input selection uses the selected board/socket assignments and the
same reviewed TMC projection as generation. Commented examples of other drivers
do not claim pins. Declared probe/BLTouch sensor inputs and a physical Z endstop
that the probe replaces are offered before manual entry; other declared aliases
are available through an advanced menu. Every choice is revalidated against
real consumers, MCU/alias identity and firmware reservations. Reusing an endstop
GPIO does not copy its inversion to a different sensor or establish electrical
compatibility. Klipper's [probe contract](https://www.klipper3d.org/Config_Reference.html#probe)
remains authoritative; generated and effective include validation stay required.

`boards.yaml.probe_connector_mappings` supplements omitted connectors only for
an exact config filename and identified MCU. SKR 1.4/Turbo PROBE P0.10 uses a
separately attributed, commit-pinned BIGTREETECH connector map; Z-STOP remains
P1.27 from the Klipper example. The selector checks active pins, aliases, firmware
reservations and I²C2 usage. This metadata does not add a BLTouch section, infer
signal polarity, or establish a probe's electrical compatibility.

Menu selection numbers and inline recommendation labels use the shared light
yellow style. Boards share one searchable catalog, and search accepts visible
labels, exact values and Back/Quit controls. The wizard tracks prompted steps so
Back skips automatic processing and reaches an editable question. Cancelling the
probe-range review returns to probe settings; the range check remains mandatory.
The board selector initially shows only reviewed candidates for the exact detected
MCU; an explicit action opens the complete catalog without weakening variant
resolution. Printer search initially asks for a name without listing arbitrary
models. Catalog previews are bounded by terminal height, reserving space for the
header, result count, help and Back/Quit. The printer and board-search results use
consecutive visible numbers from one, followed by Back/Quit. Filtering searches
the complete catalog; exact labels/values can still address any item. `/` clears
the filter. Printer model selection requires an explicit choice; Enter does not
select the first catalog item. Ordinary menus remain continuous even in short terminals. Styled
labels wrap without changing their choice values. Turquoise questions/headings
use normal weight. The boxed step header retains its complete explanation at
every height, wrapping to the available width. Visual QA must use the actual
terminal dimensions and record whether SSH reaches the Pi or a disposable
Docker fixture; terminal scrollback remains available for longer screens.

The profile editor is a deliberate single-line exception: short localized values
and hints are sized for the numbered-menu prefix on each redraw. Hints are omitted
before a display value needs an ellipsis; the full value and explanation appear
when its field is opened. Stored values, detailed profile review, staged edits,
Save and discard retain their contracts. There is no global motor-direction reset;
each mapped motor keeps its own Keep/Invert selection. The compact probe-polarity
guide preserves all five menu actions and their order. Unknown polarity remains
provisional without `!`, preserves pull-up and still requires `QUERY_PROBE` before
movement. Cover terminal width, resize, Unicode and EN/ES/PT with
`tests/unit/test_profile_editor_single_line.py`. Source tests do not update the Pi.

Questionnaire text enables standard-library readline editing on real TTYs:
Up recalls the last submitted text (including a rejected value), and Left/Right
and Backspace edit the line. Text history is bounded to 50 entries in process
memory, isolated from and restoring any pre-existing readline history. Menu
numbers, yes/no answers, passwords and API keys are not recorded; secrets retain
the existing non-echoing `password_input` path. Other private text can opt out
with `simple_input(..., history=False)`. No history file is read or written.
Pipes, mocked input, redirected streams and hosts without readline retain the
plain-input fallback. Linux real-PTY regressions cover editing, validation retries,
wrapped ANSI prompts, secret isolation, cancellation and EOF.

MCU candidate presentation is separate from board confirmation: detected
LPC1769 offers SKR 1.4 Turbo and SKR E3 Turbo when their exact profiles exist
in the fetched catalog. The operator must choose a board before its profile or
firmware authority is loaded; empty interactive input does not select the first
candidate. Reviewed conflicting MCU models are rejected even in manual search.
Automatic mode may reuse an explicit board already present in the current
catalog after checking its reviewed MCU identity; without that choice it stops
instead of selecting the first candidate. Explicit prompt fixtures remain usable.
Friendly labels retain the exact filename as the selection value. Candidate
identity does not add connector, generation or firmware qualification; SKR E3
Turbo retains its existing legacy firmware authority without a new BoardContract.
Evidence is the header of
[`config/generic-bigtreetech-skr-e3-turbo.cfg`](https://github.com/Klipper3d/klipper/blob/fe4eb8650bd7de4c2100a14eaf09b0965c430e29/config/generic-bigtreetech-skr-e3-turbo.cfg)
at the validated Klipper revision, alongside the shared
[`generic-bigtreetech-skr-v1.4.cfg`](https://github.com/Klipper3d/klipper/blob/fe4eb8650bd7de4c2100a14eaf09b0965c430e29/config/generic-bigtreetech-skr-v1.4.cfg)
header. At that same pin,
[`generic-mks-sgenl.cfg`](https://github.com/Klipper3d/klipper/blob/fe4eb8650bd7de4c2100a14eaf09b0965c430e29/config/generic-mks-sgenl.cfg)
explicitly names LPC1768 and there is no separate SGEN_L V2 config. It must not
be relabelled or offered as an LPC1769/V2 candidate. Device discovery reads a
complete Klipper MCU token in the selected device basename, not a substring or
parent directory. `test_mcu_board_candidates.py` covers these boundaries.

The firmware target review highlights its right-hand values in light yellow
after measuring and wrapping plain text, preserving aligned columns. Prepared
firmware guidance separates the copyable, highlighted path from numbered board
instructions and follow-up actions; viewing an already verified artifact does
not reissue flashing instructions. Artifact verification and staging are unchanged.

After the operator confirms a new hardware flow, `discard_checkpoint` archives
the observed revision with its existing concurrency guard. Only after that archive
succeeds, machine output emits a schema-2 `DISCARDED` observation for the old
workflow ID at sequence + 1. Studio may retire its old panel without claiming
completion or creating a hardware checkpoint before the questionnaire finishes.
No event is emitted for cancellation, a revision conflict or an archive failure.
`DISCARDED` is an observation, not a persisted firmware checkpoint state.

The generated summary resolves the typed probe strategy on a copy, uses the
motion model's explicit printable bounds and displays the configured probe
trigger offset for virtual Z homing. Imported probe offsets remain authoritative;
the summary does not change the draft or establish physical calibration.

Profile review retains the full explanations of axis limits, homing, build volume
and thermistors before its Continue/Edit/Back actions. Section titles and review
controls are translated in EN/ES/PT; presentation does not change geometry or
provenance. Offset preview retains the bed diagram, signed coordinates and
nozzle-relative directions, including overlap/reach warnings. Profile editor
separators follow the terminal width. The generated-configuration summary keeps
its existing sections, wraps values and paths, and identifies application and
installation verification as pending; generating files is not completion.
The completed-installation card appears only after a successful verified live
deployment and a persisted COMPLETE checkpoint. Verified checks, commissioning
guidance and pending physical calibration are separate; HAPPY PRINTING! is the
last human-facing banner, after the machine outcome. Pending activation, exports,
failures and failed checkpoint persistence never display that card.

In root-v1, the Mainsail default include sits inside the managed block under the
generated Includes heading (EN/ES/PT), ahead of every hardware section. Minimal
inputs without that heading keep defaults before their first option section.
Moving the directive preserves its inline comment, user content, SAVE_CONFIG and
its precedence; split-file user layouts keep their existing include order.
Initial/root-v1 installations publish selected starter macros as `macros.cfg`
beside `printer.cfg`. Its include follows Mainsail under Includes, before hardware,
instead of being appended after calibration guidance. A generated-file marker
identifies KACE ownership on retries; declining macros removes the owned include
without deleting the file. Existing unknown root macros are never overwritten:
referenced user macros remain authoritative, and an unreferenced name collision
uses the established `kace/generated-macros.cfg` path. Existing split-file user
layouts retain that path. Older unused managed files are not deleted.

After RESTART, readiness polling permits the previous error/shutdown state to
transition during the existing bounded timeout. Two consecutive Ready samples,
firmware evidence, uploaded checksums and loaded-configuration verification remain
mandatory. A persistent non-ready state still fails; Moonraker's `/printer/info`
diagnostic is retained when available, without treating an API failure as a host
diagnosis. Normal failure output now includes a bounded, credential-filtered cause;
typed outcomes, exit codes and opt-in machine markers are unchanged.

Destination reconciliation preserves existing homing endpoints and probe offsets
by default. When they differ from the questionnaire, interactive deployment
shows file, section, option, saved value and proposed value before semantic review.
The comparison identifies endstops by axis and explains their coordinates separately
from bed size and maximum travel. Probe-offset guidance appears only for probe
conflicts. Each field keeps its source visible above aligned saved/questionnaire
rows, with yellow values and millimetre units; text wraps to the terminal width.
The screen explains that selection precedes validation and final review, and
identifies protected SAVE_CONFIG calibration before the choice.
The operator can preserve them, explicitly use the displayed questionnaire values,
or cancel. Replacement authority is limited to the observed active homing values;
it does not delete or rewrite SAVE_CONFIG calibration. An incompatible preserved
calibration still blocks deployment and must be reviewed separately. No consent
is inferred in automatic mode. Both configuration-only and combined firmware
paths resolve these differences before any write or firmware action, then retain
the normal final review, snapshot, conditional writes and loaded verification.
Normal EN/ES/PT review keeps individual changed values and the axis/fields of
homing errors instead of hiding them behind repeated generic messages.
The main review groups planned setting replacements by source and axis, combines
changed minimum/maximum pairs as travel ranges, and summarizes retired settings
by source and section. These are presented as changes, separately from semantic
warnings, commissioning guidance and blocking errors. Only exact recognized
planner messages are summarized; unknown messages remain visible. Both modes
offer every original changed/removed setting in optional technical details before
final consent, while Advanced retains its separate full-diff option. This changes
presentation counts only, not validation, reconciliation, snapshots or publication.

Switching an inline `root-v1` installation from virtual probe Z homing to a
physical Z endstop without a selected probe retires the previous probe, mesh and
safe-Z sections inside the KACE managed block. Their removed settings are shown
in the normal final review before the existing confirmation and snapshot. Probe
sections in user-owned root content or includes remain preserved and validated;
an independent mesh probe with physical Z homing is not treated as this retired
branch. SAVE_CONFIG bytes remain unchanged. A saved offset without a complete
active probe blocks publication with a specific calibration message. Pin errors
retain their GPIO and consumer in EN/ES/PT, and unmapped validation errors retain
their original cause rather than becoming generic settings-change warnings.

Web-interface selection chooses the macro configuration, not which dashboard is
installed. When both Mainsail and Fluidd are detected, the wizard explains that
both remain available. Existing explicit nested includes are inspected through
the shared bounded configuration reader. An unresolved include graph requires
preserving the current configuration or going back; it never authorizes adding
duplicate macros. Firmware preparation shows the exact target and delivery method;
raw Kconfig selections remain available in optional technical details.

The profile editor stages printable volume separately from mechanical travel.
Increasing a volume beyond an axis maximum also proposes that maximum in its
existing axis row for review before **Save & Continue**. Accepted maximum changes
are `USER_OVERRIDE`; unchanged or larger physical limits keep their source
provenance. Saving resolves the effective values with generation's source rules
before geometry validation. The original imported profile remains source evidence;
discarding the editor or cancelling volume entry does not publish staged changes.
This review records the user's geometry choices, not a physical travel measurement.

Guided custom probe blocks place localized parameter comments inline at one
aligned column, retaining the provisional-zero calibration warning. Imported raw
blocks retain their original content. Unknown signal polarity remains explicitly
pending verification with Klipper's `QUERY_PROBE`, not an inferred hardware fact.
Probe review shows individual parameters with units and brief explanations,
plus optional full configuration text with its original comments.
Its labels and group headings are cyan; values, units and explanations are yellow.
Values start at one shared column, with aligned units/explanations in wide terminals.
Wrapping precedes ANSI styling and retains the narrow-terminal guidance and draft.
The final Software question records the optional KACE starter `macros.cfg`
choice independently from the Mainsail/Fluidd include. It is saved before a
firmware pause and reused at generation without a second question, including
an explicit No. Older checkpoints without that choice keep the existing late
prompt before generation; already-generated checkpoints retain their decision.
Deployment readers use that saved choice rather than expecting a legacy include
in generated hardware: the managed planner owns the include. A requested missing
bundle fails before publication; a declined choice ignores stale local macros.
Existing destination macros retain their ownership and review rules.

The guided Z question first distinguishes a known offset from calibration later.
A supplied zero is a known value; an unknown value remains the existing optional
setting and renders a clearly commented provisional zero. Checkpoint restoration
preserves that distinction. Choosing calibration later resolves any incompatible
Z minimum in that same offset question, using a temporary probe payload and the
existing range review. Only the offset decision and explicitly confirmed minimum
are committed; later sample questions still own their values. Cancelling the range
review returns to the offset choice without altering the accepted draft.
The later homing gate revalidates effective values and stays silent (including its
header) when compatible. Changed or older unresolved values reopen the review;
there is no cached approval that bypasses validation. Known and imported offsets retain
their direct editor, with trigger height explained separately from travel limits.
Explicit manual range review remains available even for a compatible range.
All paths retain the same validator and explicit physical-clearance confirmation
for a changed limit.
For deferred calibration with an incompatible minimum, the wizard asks directly
for physical-clearance confirmation of the validated minimum change. There is no
intervening minimum-selection menu. The answer defaults to No; only an explicit
Yes publishes the staged change. Declining offers manual editing or Back, keeping
the deferred decision and accepted limits intact. Compatible ranges remain silent.
The optional unknown offset, shared geometry validator and explicit manual review
retain their existing contracts. Cover this with `test_probe_z_step_completion.py`
and `test_probe_deferred_z_review.py`.
For a conflicting zero offset, Z preparation offers minimum 0 only when that
staged change passes the existing geometry validator. An explicit clearance
confirmation accepts the change; cancelling preserves the original range and
offset. This does not measure calibration. Manual review never defaults to a
known incompatible minimum. Entering a known custom-probe offset preserves the
travel limits; incompatible or non-finite values cannot advance. Imported probe
edits replace only the active `z_offset` value, retaining other lines and comments;
guided settings and saved draft mappings remain consistent with that value.
`_wizard_review.py`, `_probe_review_actions.py` and
`_wizard_presentation.py` own the focused EN/ES/PT guidance and presentation strings.

Crowsnest dashboard detection separately reports directory-only evidence and
systemd active, inactive, failed, not-found or unavailable state. It does not
infer installation provenance from a directory or mutate services. The Imager's
unchecked Crowsnest option skips installation and preserves pre-existing files
and services. Cover these contracts with `test_board_catalog_menu.py`,
`test_terminal_colors.py`, navigation/probe regressions and `test_dashboard.py`;
source results do not qualify the native package or physical installation.

Optional automatic leveling examples follow the resolved probe selection, not
the presence of probe pins in a board file. Without a selected probe, KACE omits
the commented `z_tilt` and `quad_gantry_level` examples. With a probe and multiple
independent Z motors, it offers `z_tilt`, except for CoreXY with exactly four Z
motors, which receives `quad_gantry_level`. These examples remain commented and
their physical pivot/corner coordinates require review before use; this policy
does not exclude Klipper's separately configured manual probing workflows.

Studio source mode prefers the sibling bootstrap; packaged mode uses its bundled
copy. Preserve stage/error markers, installer tuple, workflow schemas, receipts
and terminal states. Bootstrap changes need checks in both repositories and the
source/packaged gates in [Release](RELEASE.md). Local publication is atomic per
file with a cooperative lock, not directory-wide CAS against external editors.
Recovery preserves live edits when restoration cannot be proven. Do not refactor
state machines solely because modules are large; use a demonstrated need.

The durable v1 checkpoint reader requires saved MCU verification evidence from
`MCU_VERIFIED` onward: a non-empty serial path and a positive integer flash
evidence timestamp. This preserves the transition's existing invariant when a
checkpoint is read with `verify_artifact=False`, including historical COMPLETE.
It checks the saved structure without renewing receipts or accessing hardware.
Studio mirrors this wire requirement and retains historical optional identity
fields. Producer-generated fixtures and recovery tests verify the boundary;
BoardContracts, MCU aliases and physical verification remain KACE authority.

## 🛠️ Environment and dependencies

Use Python 3.11 for the KACE CI baseline. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements-dev.txt
```

Runtime intent is in `requirements.in`, optional SSH in `requirements-ssh.in`,
and test dependencies in `requirements-dev.in`. Update an input with its hashed
lock only when dependency changes are intended. With `pip-tools` available:

```bash
pip-compile --generate-hashes requirements.in
pip-compile --generate-hashes requirements-ssh.in
pip-compile --generate-hashes requirements-dev.in
```

The full suite needs a clean `.klipper-contract-source` at the exact
`KLIPPER_REPO_URL` / `KLIPPER_REF` from `tests.klipper_contract`. Follow the source
preparation in [CI](../.github/workflows/ci.yml): fetch the exact revision, detach
and verify HEAD/cleanliness. Do not reset another checkout's work or waive a
missing source. Docker is additionally needed for loader/scenario and build gates.

## 🧪 Validation

Run `python -m pytest <affected-test-file> -q` first, then the affected gates.
Find current suites in [tests/unit/](../tests/unit/),
[regression](../tests/regression/) and [integration](../tests/integration/);
assertions and source inventories are authoritative, not a duplicated test list.

```bash
python -m pytest tests --ignore=tests/results -q -rs
python tests/run_tests.py --verbose
python tests/run_tests.py --yaml-check
python tests/matrix/run_matrix.py --profile quick
python tests/matrix/run_matrix.py --profile full
python tests/regression/validate_snapshots.py
python -m tests.sweep.scenario_contract --artifacts tests/results/reviewed-scenarios
python -m unittest tests.integration.test_simulated_firmware_lab -v
python scripts/check_portability.py
```

The standard `tests/run_tests.py` entrypoint delegates to pytest, collecting both
functions and unittest.TestCase classes with their fixtures; its verbose flag
controls pytest verbosity and its existing board/snapshot environment flags are
preserved. YAML-only and full-sweep modes retain their separate implementations.
The entrypoint and direct pytest command use the same collector and must not be
counted as independent coverage. Unittest alone misses module-level pytest
functions and does not apply pytest fixtures. Matrix/snapshot loading uses
the pinned Klipper parser: byte equality alone is insufficient. `EXPECTED_REJECT`
is not a successful generated config; `KACE_ERROR`, `KLIPPER_ERROR` and
`INFRA_ERROR` fail validation. `--skip-docker` does not prove Klipper acceptance.
The [reviewed-scenario contract](../tests/sweep/README.md) requires a **fresh**
output directory and preserves raw sweep failures while proving supported loads,
concrete boundaries and required input separately. The legacy diagnostic command
`python tests/run_tests.py --full-klipper-sweep --verbose` keeps its own failure
policy; the parser-only helper is not the integrated CI gate.

Record exact source, environment, command, skips and failures with each run.
Generated results belong to ignored output directories while investigating and
must be archived outside the repositories when closed. Keep fixtures, inventories
and their provenance in source control. No automated test may access real storage,
GPIO or printer controllers. Loader acceptance and simulated HTTP/udev/power
behavior do not qualify physical hardware.

Regression fixtures must choose their transport/environment explicitly: a remote
Moonraker mock uses a non-loopback host such as `fixture-printer.invalid`; on POSIX,
loopback selects the local transport and resolves the active config root. Mock
local HTTP responses and temporary directories instead of bypassing validation.
Host/container export tests must control container detection as well as OS name.
Exercise new root-v1 hardware in `printer.cfg` and preserved-root managed includes,
no-change retries with loaded-state verification, cancellation and external edits.

[CI](../.github/workflows/ci.yml) defines triggers and dependencies for lint,
unit/pytest, simulated integration, YAML, snapshots, quick/full matrices, reviewed
scenarios and real firmware builds. Missing infrastructure is not a passing gate.
On Windows, if pytest's shared temporary directory is inaccessible, use
`--basetemp` with a new disposable directory; pytest may clear that target.

Reviewed removable TMC wiring is resolved by `core/tmc_socket.py` from
`data/tmc_sockets.json`, shared by wizard and generation. See the
[TMC socket mapping contract](TMC_SOCKET_MAPPING.md) for scope and focused tests.

## Development container and firmware builds

```bash
docker compose -f docker/docker-compose.yml config --quiet
docker compose -f docker/docker-compose.yml build
docker compose -f docker/docker-compose.yml run --rm --service-ports kace
```

The simulated API uses `127.0.0.1:7125`; avoid a conflicting local service. Select
`12` to exit. `/workspace` is mounted, so generated files there persist. Host
devices are not passed through. The development image's mock make emits text
placeholders, not firmware. Mock provenance is rejected by deployment; do not
copy mock output onto MCU media or assume an external bootloader will reject it.
Size thresholds are plausibility checks, never authorization to flash.

For the **legacy** real-build path, `KACE_REAL_BUILD=1 python3 kace.py` or
`python3 kace.py --real-build` selects `/usr/bin/make` when present. It does not
prove compiler availability or a successful build; no green banner is required.
BoardContract builds use their own exact configuration/proof pipeline.

```bash
docker build -f docker/ci/Dockerfile -t kace-dev .
docker run --rm -v "$PWD:/workspace" kace-dev python3 -m unittest tests/regression/test_mcu_builds.py -v
```

The [build fixtures](../tests/regression/test_mcu_builds.py) fetch the pinned source
into temporary checkouts without changing `~/klipper`, require real compilers and
record skips when unavailable. Fixture clocks, transports and outputs are not MCU
family defaults or a firmware distribution channel. A copied real output from
`~/kace/` still needs its identity/proof, exact board/variant/clock/transport and
bootloader method; do not rename it to a trigger filename merely because it built.

BoardContract builds use persistent bare sources in `~/.cache/kace/sources/` and
disposable workspaces in `~/.cache/kace/workspaces/`. `KACE_CACHE_HOME` or
`XDG_CACHE_HOME` can relocate them. The cache requires its repository marker,
exact commit, bare state and Git integrity; failed validation causes atomic rebuild.
Each build uses a clean detached checkout. Config, fingerprint edits, logs and
outputs are not cached. Explicit tmpfs/ramfs/devtmpfs staging is rejected; require
at least 1 GiB before source preparation and 2 GiB before checkout/build. Per-run
workspaces are cleaned afterward. Pi 3 uses `make -j2`; other hosts use bounded
CPU/memory-aware jobs and periodic progress instead of flooding the terminal.

Legacy `BuildArtifact` and BoardContract proof/plan/executor authorities are
separate. A valid BoardContract proof cannot enter legacy execution by changing
`flashable`. Selected artifact bytes, target/media and route are rechecked before
writes; USB reappearance alone does not prove the running build. See
[hardware qualification](HARDWARE_TESTING.md) and the upstream instructions at the
[reviewed Klipper pin](https://github.com/Klipper3d/klipper/blob/fe4eb8650bd7de4c2100a14eaf09b0965c430e29/docs/Bootloaders.md).

## Contribution, snapshots and documentation

### Commit subjects

Every commit subject, including merge commits, must use `<emoji> <type>: <summary>` with exactly one of the mappings below. Choose the type for the main purpose of the change. Do not invent emojis, replace the assigned emoji or use an emoji from another type. `wip` commits must not reach `main`. Tags and release preparation use `🚀 release`; `📦` is not an allowed commit prefix.

| Prefix | Main change |
| --- | --- |
| ✨ feat | New functionality |
| 🔧 fix | Bug fix |
| 🧹 chore | Maintenance, cleanup or internal tasks |
| 🧪 test | Tests |
| 📚 docs | Documentation |
| ♻️ refactor | Refactoring without behavior changes |
| ⚡ perf | Performance improvements |
| 🎨 style | Formatting, style or lint without functional changes |
| 🔒 security | Security |
| 🔨 build | Build system, packaging or build dependencies |
| 🤖 ci | CI/CD, workflows or GitHub Actions |
| 🚀 release | Releases, tags or version preparation |
| 🔀 merge | Branch merges |
| ⏪ revert | Reverting changes |
| 🗃️ data | Data, fixtures, catalogs or datasets |
| 🧩 config | Configuration |
| 🗑️ remove | Removing code, files or functionality |
| 🚧 wip | Incomplete work; must not reach main |

Keep changes scoped and backed by defect coverage. For board/generator changes,
review exact identity, all mandatory dependencies, YAML pattern precedence,
generation/publication/recovery and matrix coverage; do not add support by dropping
unsupported circuits. Preserve gates, receipts, rejections and rollback.

Only intentionally changed output contracts may update snapshots. Review every
fixture; never regenerate to hide a failure. When explicitly authorized:

```bash
python tests/run_tests.py --update-snapshots
git diff -- tests/fixtures
python tests/run_tests.py --verbose
python tests/regression/validate_snapshots.py
```

Use branches and PRs; respect required checks, updated-branch and protected-main
rules. Report pre-existing release failures rather than repinning or waiving them.
Keep personal paths and secrets out of all tracked files, including fixtures.
Issues need revision, environment, exact board/MCU, source profile, workflow and
sanitized reproduction; vulnerabilities follow [Security](../SECURITY.md).

README and ROADMAP are the primary EN/ES/PT entry points. Change all three for
user steps, limits or priorities. Link detailed engineering procedures to one
canonical source. Keep current candidate notes in [CHANGELOG](../CHANGELOG.md);
archive old audits, run results and superseded guides locally outside both repos.

## Remote HTTP and SSH contracts

The configuration route menu treats `~/printer_data/config/` as a local-install
candidate even before `printer.cfg` exists. This does not establish Moonraker
availability or filesystem authority: the loopback transport still validates the
active config path and reported config root before the existing transaction runs.
Folder export is explicitly separate from installation/activation. Optional SSH
support is checked before credentials; an unavailable dependency is explained and
omitted from the route menu without runtime package installation. Cancelling this
menu returns the existing CANCELLED outcome, including Ctrl+C.

The probe polarity guide explains `!` separately from `^`, uses both QUERY_PROBE
states, and retains the unverified choice without inferring wiring. Deferred Z
calibration keeps its step-6 review: only an incompatible range needs a separate
physical-clearance confirmation. Its explanatory heading and spacing do not change
the staged edits, numeric validators or default-No confirmation.

Durably published CONFIG_GENERATED/READY_TO_DEPLOY/DEPLOYING/COMPLETE events add
the observational `data.configuration_download_available` flag for Studio. It
permits export of generated files, not activation or completion. Existing event
schema, checkpoint identity, sequence and installation gates remain unchanged.

Moonraker requests reject all HTTP redirects with a local urllib opener. Configure
an explicit final endpoint when using a reverse proxy; credentials and operation
methods must never be forwarded by redirects. Image downloads have their own
separate transport policy. Tests exercise real loopback endpoints with synthetic
credentials.

SFTP deployment bounds channel opening, subsystem acknowledgement and protocol
initialization to 10 seconds; channel reads/writes also have a 10-second timeout.
A timeout fails deployment and never establishes COMMITTED. Trust-store checks
and conditional publication remain unchanged. Optional SSH regression tests need
`requirements-ssh.txt` in addition to the development lock.

Regenerate the runtime lock before the development lock, whose constraints use
`requirements.txt`. Shared versions, including wcwidth, must agree; the
`test_dependency_locks.py` regression enforces this. Dependency updates must be
validated on Python 3.11 and by installing the hashed locks in clean environments.

## Persistent restart diagnostics

Bootstrap owns `/etc/systemd/journald.conf.d/60-kace-diagnostics.conf` and enables
it before package installation. It sets persistent storage, a 64 MiB disk budget,
128 MiB free-space reserve, seven-day retention and 30-second synchronization.
Only systemd-journald is restarted; flushing/synchronization failures and a later
administrator override of Storage stop bootstrap with `SYSTEM_JOURNAL`. Existing
unowned files at that path are not replaced. The regression uses fake services
and temporary directories: `tests/regression/test_bootstrap_journal.py`.

This captures future boots only and cannot recover volatile history or guarantee
the last records before a hard lock/power loss. Confirm persistence across a real
reboot separately during hardware E2E. `journalctl -b -1` reads the prior boot.
