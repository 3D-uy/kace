"""Project reviewed consumers onto Klipper hardware bus selections.

Input sections must describe the effective configuration, not optional board
examples. Host-dependent Replicape resources require evidence not available here.
"""
from core.pin_validator import PinAliases, PinAliasError


def _software_pins(section, options, aliases, chip, bus, signals):
    for signal in signals:
        field = f"{bus}_software_{signal}_pin"
        token = options.get(field, "")
        if not isinstance(token, str) or not token.strip():
            raise PinAliasError(f"[{section}] requires {field} for software {bus.upper()}")
        if aliases.resolve(token)[0] != chip:
            raise PinAliasError(f"[{section}] {bus.upper()} pins must be on the same MCU")


def _spi_request(section, options, aliases, pin_field="cs_pin"):
    cs = options.get(pin_field, "")
    if not isinstance(cs, str) or not cs.strip():
        raise PinAliasError(f"[{section}] requires {pin_field} for SPI bus ownership")
    chip, _ = aliases.resolve(cs)
    if "spi_software_sclk_pin" in options:
        _software_pins(section, options, aliases, chip, "spi", ("miso", "mosi", "sclk"))
        return None
    return chip, ("spi_bus", options.get("spi_bus"))


def _i2c_request(section, options, aliases):
    chip = options.get("i2c_mcu", "mcu")
    if not isinstance(chip, str) or not chip or any(c.isspace() or c == ":" for c in chip):
        raise PinAliasError(f"[{section}] invalid i2c_mcu")
    if "i2c_software_scl_pin" in options:
        _software_pins(section, options, aliases, chip, "i2c", ("scl", "sda"))
        return None
    return chip, ("i2c_bus", options.get("i2c_bus"))


def _add_request(requests, request):
    if request is not None:
        chip, selection = request
        selections = requests.setdefault(chip, [])
        if selection not in selections:
            selections.append(selection)


def tmc_bus_requests(sections):
    """Return MCU -> SPI selections; software SPI never selects a hardware bus."""
    aliases = PinAliases(sections)
    from core.tmc_spi import spi_transport_owners
    from core.exceptions import GenerationError
    try:
        owners = spi_transport_owners(sections)
    except GenerationError as exc:
        raise PinAliasError(str(exc)) from exc
    requests = {}
    for section, options in sections.items():
        model = section.split(" ", 1)[0]
        if model not in ("tmc2130", "tmc2660", "tmc5160", "tmc2240"):
            continue
        # tmc2240.py selects UART by presence, even if cs_pin also exists.
        if model == "tmc2240" and "uart_pin" in options:
            continue
        if owners.get(section, section) != section:
            continue
        _add_request(requests, _spi_request(section, options, aliases))
    return requests


def peripheral_bus_selection(section, options):
    """Classify reviewed peripheral dispatch for reservations and SPI validation.

    Return (kind, CS field or reason). Unverified host/sensor paths remain an
    explicit result so hardware reservation callers cannot silently omit them.
    """
    kind = section.split(" ", 1)[0]
    pin_field = None
    i2c = False
    if kind == "replicape":
        return "unverified", (
            "Replicape pin reservations require host-specific SPI/PWM and PRU evidence; "
            "the firmware artifact alone cannot validate them")
    if kind in ("load_cell", "load_cell_probe"):
        sensor = options.get("sensor_type")
        if sensor in ("ads1220", "ads131m02", "ads131m04"):
            pin_field = "cs_pin"
        elif sensor not in ("hx711", "hx717"):
            return "unverified", (f"[{section}] unsupported load-cell sensor_type for bus validation: {sensor!r}")
    elif kind == "probe_eddy_current":
        if options.get("sensor_type") != "ldc1612":
            return "unverified", (f"[{section}] unsupported eddy sensor_type for bus validation")
        i2c = True
    elif kind in ("adxl345", "angle"):
        pin_field = "cs_pin"
    elif kind in ("ad5206", "dac084S085"):
        pin_field = "enable_pin"
    elif kind in ("icm20948", "mpu9250", "mcp4018", "mcp4451", "mcp4728",
                  "pca9533", "pca9632", "sx1509", "ads1x1x"):
        i2c = True
    elif kind in ("bmi160", "lis2dw", "lis3dh"):
        pin_field, i2c = ("cs_pin", False) if "cs_pin" in options else (None, True)
    elif kind == "display":
        lcd = options.get("lcd_type")
        if lcd in ("hd44780_spi", "aip31068_spi"):
            pin_field = "latch_pin"
        elif lcd == "uc1701":
            pin_field = "cs_pin"
        elif lcd in ("ssd1306", "sh1106"):
            pin_field, i2c = ("cs_pin", False) if "cs_pin" in options else (None, True)
    elif kind in ("heater_bed", "heater_generic", "temperature_sensor", "temperature_fan",
                  "temperature_probe", "extruder") or (kind.startswith("extruder") and kind[8:].isdigit()):
        sensor = options.get("sensor_type")
        if sensor in ("MAX6675", "MAX31855", "MAX31856", "MAX31865"):
            pin_field = "sensor_pin"
        elif sensor in ("BME280", "AHT10", "AHT1X", "AHT2X", "AHT3X",
                        "HTU21D", "SI7013", "SI7020", "SI7021", "SHT21", "SHT3X", "LM75"):
            i2c = True
    if pin_field is not None:
        return "spi", pin_field
    return ("i2c", None) if i2c else (None, None)


def hardware_bus_requests(sections):
    """Project TMC and reviewed standard peripherals; never infer from a key alone."""
    requests = tmc_bus_requests(sections)
    aliases = PinAliases(sections)
    for section, options in sections.items():
        kind, detail = peripheral_bus_selection(section, options)
        if kind == "spi":
            _add_request(requests, _spi_request(section, options, aliases, detail))
        elif kind == "i2c":
            _add_request(requests, _i2c_request(section, options, aliases))
        elif kind == "unverified":
            raise PinAliasError(detail)
    return requests
