"""Preserve thermal circuits and check their effective configuration dependencies."""
import math
import json
import re
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

from core.exceptions import GenerationError


# Official factories in Klipper fe4eb865 / temperature_sensors.cfg and
# adc_temperature.py. Kept separate from the smaller wizard preset list.
BUILTIN_THERMISTORS = frozenset((
    "ATC Semitec 104GT-2", "ATC Semitec 104NT-4-R025H42G",
    "EPCOS 100K B57560G104F", "Generic 3950", "SliceEngineering 450",
    "TDK NTCG104LH104JT1", "Honeywell 100K 135-104LAG-J01",
    "NTC 100K MGB18-104F39050L32",
))
BUILTIN_VOLTAGE_SENSORS = frozenset((
    "AD595", "AD597", "AD8494", "AD8495", "AD8496", "AD8497", "PT100 INA826",
))
ADC_CIRCUIT_OPTIONS = frozenset(("pullup_resistor", "inline_resistor", "adc_voltage", "voltage_offset"))

# Reference recognition only. KACE does not generate these peripherals' bus,
# calibration or dependency options. Preservation is not hardware certification.
BUILTIN_NON_ADC_SENSORS = frozenset((
    "BME280", "DS18B20", "SI7013", "SI7020", "SI7021", "SHT21", "HTU21D",
    "SHT3X", "AHT10", "AHT1X", "AHT2X", "AHT3X", "LM75",
    "MAX6675", "MAX31855", "MAX31856", "MAX31865",
    "temperature_host", "temperature_mcu", "temperature_combined",
))
BUILTIN_ADC_SENSORS = BUILTIN_THERMISTORS | BUILTIN_VOLTAGE_SENSORS | {"PT1000"}


def _is_thermal_consumer(section):
    parts = str(section).split()
    kind = parts[0] if parts else ""
    return bool(re.fullmatch(r"extruder\d*", kind) or kind in (
        "heater_bed", "heater_generic", "temperature_sensor", "temperature_fan",
        "temperature_probe", "z_thermal_adjust"))


def validate_bed_circuit(sections, *, required=False):
    """Require the active bed circuit; never infer it from thermal defaults.

    Generation currently always emits a heated bed. Effective configurations
    without a bed remain outside this check. Only ADC factories require an ADC
    sensor pin here; non-ADC peripherals retain their separate contracts.
    """
    if "heater_bed" not in sections and not required:
        return
    options = sections.get("heater_bed", {})
    if not isinstance(options, Mapping):
        raise GenerationError("[heater_bed]: an active circuit is required.")
    adc_factories = set(BUILTIN_ADC_SENSORS)
    for section in sections:
        parts = str(section).split()
        if len(parts) >= 2 and parts[0] in ("thermistor", "adc_temperature"):
            adc_factories.add(" ".join(parts[1:]))
    fields = ["heater_pin", "sensor_type"]
    if options.get("sensor_type") in adc_factories:
        fields.append("sensor_pin")
    for field in fields:
        value = options.get(field)
        if (not isinstance(value, str) or not value.strip()
                or value.strip().casefold() in ("todo", "none", "null")):
            raise GenerationError(
                f"[heater_bed]: {field} is required for the active bed circuit; "
                "select or supply reviewed hardware instead of using commented examples or thermal defaults.",
                todos=[("heater_bed", field)] if field.endswith("_pin") else None)


def validate_adc_pin_dependencies(sections):
    """Reject dangling namespaced ADC pins in generated/effective configuration.

    Presence only: this does not validate a provider's options, load order,
    physical pin capabilities or scaled ADC reference circuit. Those contracts
    still require independent review. Unknown extension chips are unsupported.
    """
    factories = set(BUILTIN_ADC_SENSORS)
    providers = set()
    for section in sections:
        parts = str(section).split()
        if not parts:
            continue
        if len(parts) >= 2 and parts[0] in ("thermistor", "adc_temperature"):
            factories.add(" ".join(parts[1:]))
        if section == "mcu":
            providers.add("mcu")
        elif str(section).startswith("mcu "):
            providers.add(str(section)[4:].strip())
        elif len(parts) >= 2 and parts[0] == "adc_scaled":
            providers.add(parts[1])
        elif len(parts) >= 2 and parts[0] == "ads1x1x":
            providers.add(parts[-1])
    for section, options in sections.items():
        if not _is_thermal_consumer(section) or not isinstance(options, Mapping):
            continue
        if options.get("sensor_type") not in factories:
            continue
        pin = options.get("sensor_pin", "")
        if not isinstance(pin, str) or ":" not in pin:
            continue
        chip = pin.split(":", 1)[0].strip()
        if chip not in providers:
            raise GenerationError(
                f"{section}: ADC pin chip {chip!r} has no supported provider in the effective configuration; "
                "preserve its MCU/ADC dependency before generating or publishing this sensor.")


def validate_sensor_references(sections, *, generating=False):
    """Resolve thermal names against official defaults and effective definitions.

    Custom names use Klipper's whitespace normalization, but lookup remains
    case-sensitive. Definitions must precede their consumers as documented by
    Klipper. This is not an emulation of recursive module loading. Unknown
    extension factories require a separate support contract.
    """
    factories = set(BUILTIN_ADC_SENSORS | BUILTIN_NON_ADC_SENSORS)
    generated = set(BUILTIN_ADC_SENSORS)
    custom_positions = {}
    for position, section in enumerate(sections):
        parts = str(section).split()
        if not parts or parts[0] not in ("thermistor", "adc_temperature"):
            continue
        if parts == ["adc_temperature"]:
            continue  # Official default-factory loader, not a custom curve.
        name = " ".join(parts[1:])
        if not name:
            raise GenerationError(f"{section}: custom sensor name is required.")
        if name in factories:
            raise GenerationError(f"{section}: ambiguous sensor factory name; resolve the duplicate definition.")
        factories.add(name)
        custom_positions[name] = position
        if parts[0] == "thermistor":
            generated.add(name)
    for position, (section, options) in enumerate(sections.items()):
        # sensor_type is also used by load cells and eddy probes in unrelated
        # registries. Only consumers of heaters.setup_sensor belong here.
        if not _is_thermal_consumer(section) or not isinstance(options, Mapping) or "sensor_type" not in options:
            continue
        sensor = options["sensor_type"]
        if not isinstance(sensor, str) or sensor not in factories:
            raise GenerationError(f"{section}: Unknown temperature sensor {sensor!r}; provide its definition or a supported factory name.")
        if sensor in custom_positions and custom_positions[sensor] >= position:
            raise GenerationError(f"{section}: define custom sensor {sensor!r} before its first use, including across includes.")
        if generating and sensor not in generated:
            raise GenerationError(f"{section}: sensor {sensor!r} is not supported for generated heaters; its peripheral configuration requires separate review.")


@lru_cache(maxsize=1)
def _voltage_samples():
    # Only sample voltages needed for the official >=2 usable points rule.
    # Conversion tables/equations are still owned by Klipper.
    path = Path(__file__).resolve().parents[1] / "data" / "adc_voltage_samples.json"
    return json.loads(path.read_text(encoding="utf-8"))["voltage_samples"]


def _custom_adc_tables(sections):
    """Read upstream's contiguous 1..999 pairs and reject unused fields.

    Finiteness and physical sample bounds are additional KACE policies.
    Voltage range filtering is consumer-specific, not a property of the table.
    """
    tables = {}
    for section, options in sections.items():
        parts = str(section).split()
        if len(parts) < 2 or parts[0] != "adc_temperature":
            continue
        if not isinstance(options, Mapping):
            raise GenerationError(f"{section}: invalid ADC calibration table.")
        kind = "resistance" if "resistance1" in options else "voltage"
        samples, used = [], set()
        for index in range(1, 1000):
            temperature = f"temperature{index}"
            if temperature not in options:
                break
            pair = (temperature, f"{kind}{index}")
            values = []
            for key in pair:
                try:
                    value = float(str(options[key]).strip())
                except (KeyError, TypeError, ValueError) as exc:
                    raise GenerationError(f"{section}: {key} must be specified as a finite number.") from exc
                if not math.isfinite(value):
                    raise GenerationError(f"{section}: {key} must be finite.")
                if ((key.startswith("temperature") and value < -273.15)
                        or (key.startswith("resistance") and value < 0)):
                    raise GenerationError(f"{section}: {key} is outside physical calibration bounds.")
                used.add(key)
                values.append(value)
            samples.append(tuple(values))
        unused = set(options) - used
        if unused:
            raise GenerationError(f"{section}: unused ADC calibration options: {', '.join(sorted(unused))}.")
        if len(samples) < 2:
            raise GenerationError(f"{section}: ADC calibration requires at least two complete samples.")
        tables[" ".join(parts[1:])] = (kind, samples)
    return tables


def _validate_linear_curve(samples, section):
    """Check interpolation preconditions, without converting temperatures.

    Klipper rejects duplicate coordinates and insufficient points. KACE also
    requires an invertible, finite curve for min/max ADC conversion.
    """
    if len(samples) < 2:
        raise GenerationError(f"{section}: fewer than two usable ADC calibration samples.")
    ordered = sorted(samples)
    direction = None
    for (x0, t0), (x1, t1) in zip(ordered, ordered[1:]):
        if x1 == x0:
            raise GenerationError(f"{section}: duplicate ADC calibration coordinates.")
        gain = (t1 - t0) / (x1 - x0)
        offset = t0 - x0 * gain
        if not math.isfinite(gain) or not math.isfinite(offset) or gain == 0:
            raise GenerationError(f"{section}: ADC calibration must have finite, nonzero slopes and finite offsets.")
        increasing = gain > 0
        if direction is not None and direction != increasing:
            raise GenerationError(f"{section}: ADC calibration must be strictly monotonic for reverse conversion.")
        direction = increasing


def validate_adc_sensor_options(sections):
    """Check which ADC circuit options a known factory consumes.

    Unknown/non-ADC factories are outside this check. Custom adc_temperature
    definitions follow upstream's resistance1 dispatch. Section names must retain
    their original case. Tables are checked with each consumer's circuit values.
    """
    factories = {name: "thermistor" for name in BUILTIN_THERMISTORS}
    factories.update({name: "voltage" for name in BUILTIN_VOLTAGE_SENSORS})
    factories["PT1000"] = "resistance"
    for section, options in sections.items():
        parts = str(section).split()
        if len(parts) < 2 or parts[0] not in ("thermistor", "adc_temperature") or not isinstance(options, Mapping):
            continue
        kind, name = parts[0], " ".join(parts[1:])
        if name in factories:
            raise GenerationError(f"{section}: ambiguous sensor factory name; resolve the duplicate definition.")
        factories[name] = ("thermistor" if kind == "thermistor" else
                           "resistance" if "resistance1" in options else "voltage")
    tables = _custom_adc_tables(sections)
    allowed = {"thermistor": {"pullup_resistor", "inline_resistor"},
               "resistance": {"pullup_resistor"}, "voltage": {"adc_voltage", "voltage_offset"}}
    for section, options in sections.items():
        if not isinstance(options, Mapping):
            continue
        sensor = options.get("sensor_type")
        kind = factories.get(sensor)
        if kind is None:
            continue
        unused = ADC_CIRCUIT_OPTIONS.intersection(options) - allowed[kind]
        if unused:
            raise GenerationError(f"{section}: {sensor} does not consume ADC options: {', '.join(sorted(unused))}.")
        for option in ("adc_voltage", "voltage_offset"):
            if option not in options:
                continue
            try:
                value = float(str(options[option]).strip())
            except (TypeError, ValueError) as exc:
                raise GenerationError(f"{section}: {option} must be finite.") from exc
            if not math.isfinite(value) or option == "adc_voltage" and value <= 0:
                raise GenerationError(f"{section}: {option} must be finite" + (" and > 0." if option == "adc_voltage" else "."))
        if sensor in BUILTIN_VOLTAGE_SENSORS:
            voltage = float(options.get("adc_voltage", 5.))
            offset = float(options.get("voltage_offset", 0.))
            # Match LinearVoltage's arithmetic and inclusive ADC range.
            samples = [(sample - offset) / voltage for sample in _voltage_samples()[sensor]]
            usable = [sample for sample in samples if 0. <= sample <= 1.]
            if len(usable) < 2:
                raise GenerationError(f"{section}: adc_voltage/voltage_offset leave fewer than two calibration samples for {sensor}.")
            if len(set(usable)) != len(usable):
                raise GenerationError(f"{section}: adc_voltage/voltage_offset collapse calibration samples for {sensor}.")
        if sensor in tables:
            table_kind, samples = tables[sensor]
            if table_kind == "voltage":
                voltage = float(options.get("adc_voltage", 5.))
                offset = float(options.get("voltage_offset", 0.))
                coordinates = [((value - offset) / voltage, temp) for temp, value in samples]
                coordinates = [(adc, temp) for adc, temp in coordinates if 0. <= adc <= 1.]
            else:
                coordinates = [(value, temp) for temp, value in samples]
            _validate_linear_curve(coordinates, section)


def validate_custom_thermistors(sections):
    """Validate the beta/three-point definition, not physical calibration.

    Finite values, strictly positive resistance and temperatures strictly above
    absolute zero also exclude singular inputs accepted by upstream getfloat.
    Distinct sample coordinates are a KACE policy for three-point curves.
    """
    for name, options in sections.items():
        parts = str(name).split(maxsplit=1)
        if len(parts) < 2 or parts[0] != "thermistor":
            continue
        sensor = parts[1]
        if not sensor.strip() or any(c in sensor for c in "[]\r\n"):
            raise GenerationError(f"Invalid custom thermistor name: {name!r}.")
        if not isinstance(options, Mapping):
            raise GenerationError(f"{name}: temperature1 and resistance1 are required.")
        fields = ("temperature1", "resistance1", "beta") if "beta" in options else (
            "temperature1", "resistance1", "temperature2", "resistance2", "temperature3", "resistance3")
        unused = set(options) - set(fields)
        if unused:
            raise GenerationError(f"{name}: unused custom thermistor options: {', '.join(sorted(unused))}.")
        values = {}
        for field in fields:
            try:
                value = float(str(options.get(field)).strip())
            except (ValueError, TypeError) as exc:
                raise GenerationError(f"{name}: {field} must be specified as a finite number.") from exc
            minimum = -273.15 if field.startswith("temperature") else 0.
            if not math.isfinite(value) or value <= minimum:
                raise GenerationError(f"{name}: {field} must be finite and > {minimum}.")
            values[field] = value
        if "beta" not in options:
            for prefix in ("temperature", "resistance"):
                if len({values[prefix + str(i)] for i in (1, 2, 3)}) != 3:
                    raise GenerationError(f"{name}: three-point {prefix} samples must be distinct.")
            # The official Steinhart-Hart solver divides by this determinant.
            logs = [math.log(values["resistance" + str(i)]) for i in (1, 2, 3)]
            a, b, c = logs
            determinant = (a**3 - b**3) - (a**3 - c**3) * (a - b) / (a - c)
            if determinant == 0 or not math.isfinite(determinant):
                raise GenerationError(f"{name}: singular three-point resistance curve.")


def selected_custom_thermistors(board, user):
    """Copy only curves referenced by the two generated heater selections.

    Curves describe sensors and may come from a printer profile; ADC resistors
    continue to belong to the board. Conflicting same-name curves need review.
    """
    profile = user.get("_profile_parsed")
    sources = (board, profile) if isinstance(profile, Mapping) else (board,)
    selected = {}
    for key in ("hotend_thermistor", "bed_thermistor"):
        name = "thermistor " + str(user[key])
        # The profile scraper case-folds section names; emit the selected
        # sensor spelling because Klipper's factory lookup is case-sensitive.
        matches = [options for source in sources for section, options in source.items()
                   if str(section).casefold() == name.casefold()]
        if any(not isinstance(options, Mapping) for options in matches):
            raise GenerationError(f"{name}: invalid custom thermistor definition.")
        candidates = [dict(options) for options in matches]
        if not candidates:
            continue  # Built-in and other sensor factories are handled separately.
        if any(candidate != candidates[0] for candidate in candidates[1:]):
            raise GenerationError(f"conflicting custom thermistor definition: {name}.")
        selected[name] = candidates[0]
    validate_custom_thermistors(selected)
    return selected
