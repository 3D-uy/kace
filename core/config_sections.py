"""Section identity shared by source extraction and deployment planning."""


def section_identity(name: str) -> str:
    """Keep supported output, fan, heater-reference and sensor names exact.

    Klipper's output/fan objects, heater references and custom sensor factories
    are case-sensitive. Keep the existing folded
    identities for other families; this is not a general parser replacement.
    """
    name = name.strip()
    kind = name.split(None, 1)[0] if name else ""
    return name if kind in ("thermistor", "adc_temperature", "heater_fan", "controller_fan", "fan_generic", "temperature_fan", "pwm_tool", "pwm_cycle_time",
                            "tmc2208", "tmc2209", "tmc2130", "tmc2240", "tmc2660", "tmc5160") or name.startswith("verify_heater ") or name.casefold().startswith("output_pin ") else name.casefold()
