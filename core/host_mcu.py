"""Preserve board-owned Linux host MCU endpoints used by primary ADC sensors."""
import re
from collections.abc import Mapping

from core.exceptions import GenerationError


_HOST_PIPE = re.compile(r"/tmp/klipper_host_[A-Za-z0-9_.-]+")


def selected_host_adc_mcus(board, pins):
    """Select referenced host pipes only; other transports need separate support.

    This does not install/identify a Linux MCU or import a printer profile's
    connection. The primary MCU remains owned by the existing wizard workflow.
    """
    selected = {}
    for consumer in ("extruder", "heater_bed"):
        pin = pins.get(consumer, {}).get("sensor_pin", "")
        if not isinstance(pin, str) or ":" not in pin:
            continue
        chip = pin.split(":", 1)[0].strip()
        if chip == "mcu":
            continue
        name = "mcu " + chip
        matches = [options for section, options in board.items()
                   if str(section).casefold() == name.casefold()]
        if not matches:
            continue  # The ADC reference check rejects a missing provider.
        if any(not isinstance(value, Mapping) or dict(value) != dict(matches[0]) for value in matches):
            raise GenerationError(f"Host ADC MCU: conflicting board definition [{name}].")
        _validate_connection(name, matches[0])
        selected[name] = dict(matches[0])
    return selected


def _validate_connection(name, options):
    chip = name[4:]
    if not re.fullmatch(r"[A-Za-z0-9_]+", chip):
        raise GenerationError(f"Host ADC MCU: invalid namespace [{name}].")
    serial = options.get("serial")
    if not isinstance(serial, str) or not _HOST_PIPE.fullmatch(serial):
        raise GenerationError(f"Host ADC MCU: [{name}] requires an explicit /tmp/klipper_host_* pipe; other generated secondary MCU transports require separate review.")
    unused = set(options) - {"serial"}
    if unused:
        # Klipper's host-pipe branch does not consume baud/restart_method.
        raise GenerationError(f"Host ADC MCU: [{name}] unused or conflicting host-pipe options: {', '.join(sorted(unused))}.")


def validate_host_adc_mcus(sections, *, expected=None):
    """Check host-pipe definitions and prevent late includes changing ownership.

    Other preserved MCU transports are outside this host-pipe check. Matching a
    literal endpoint is not device identity, pipe existence or firmware proof.
    """
    expected = expected or {}
    hosts = {name: options for name, options in sections.items()
             if name.startswith("mcu ") and isinstance(options, Mapping)
             and (name in expected or str(options.get("serial", "")).startswith("/tmp/klipper_host_"))}
    for name, options in expected.items():
        if name not in sections:
            raise GenerationError(f"Host ADC MCU: generated [{name}] is missing from the effective configuration.")
        if sections[name].get("serial") != options.get("serial"):
            raise GenerationError(f"Host ADC MCU: an include overrides [{name}] serial; resolve the endpoint before deployment.")
    for name, options in hosts.items():
        _validate_connection(name, options)
        endpoint = options["serial"]
        for other, values in sections.items():
            if (other != name and (other == "mcu" or other.startswith("mcu "))
                    and isinstance(values, Mapping) and values.get("serial") == endpoint):
                raise GenerationError(f"Host ADC MCU: [{name}] and [{other}] use the same endpoint {endpoint!r}.")
