"""Reviewed connector wiring for explicitly selected removable TMC modules.

A commented chip example can document a socket bus without authorizing that
chip's currents, resistor, DIAG wiring or registers for a different module.
"""
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

SOURCE = "_tmc_socket_source"
REVIEWED = json.loads((Path(__file__).resolve().parent.parent / "data/tmc_sockets.json")
                      .read_text(encoding="utf-8"))["profiles"]
TRANSPORT_KEYS = frozenset(("uart_pin", "tx_pin", "uart_address", "select_pins",
                            "cs_pin", "spi_bus", "spi_speed", "spi_software_miso_pin",
                            "spi_software_mosi_pin", "spi_software_sclk_pin",
                            "chain_length", "chain_position"))


def capture_socket_source(raw, filename):
    if filename not in REVIEWED:
        return None
    return {"profile": filename,
            "sha256": hashlib.sha256(raw.replace("\r\n", "\n").encode("utf-8")).hexdigest()}


def selected_socket_sections(parsed, user):
    """Return a new mapping with missing selected-chip sections, wiring only.

    Exact chip sections, including invalid/partial ones, are never repaired.
    Adaptation needs the reviewed source, selected board, unchanged transport
    and physical motor pins. Custom/integrated/unreviewed circuits get no donor.
    """
    result = dict(parsed)
    model = str(user.get("driver_type", "")).lower()
    if model == "tmc2225":
        model = "tmc2208"
    mode = user.get("driver_mode")
    expected = {"tmc2208": "UART", "tmc2209": "UART", "tmc2130": "SPI", "tmc5160": "SPI"}
    if mode != expected.get(model) or model not in expected:
        return result
    source = parsed.get(SOURCE)
    if not isinstance(source, Mapping) or source.get("profile") != user.get("board"):
        return result
    entry = REVIEWED.get(source.get("profile"))
    if entry is None or source.get("sha256") != entry["sha256"]:
        return result
    assignments = user.get("z_socket_assignments") or {}
    try:
        z_count = int(user.get("z_motors") or 1)
    except (TypeError, ValueError):
        return result  # The shared model validator reports invalid motor counts.
    if not 1 <= z_count <= 4:
        return result
    targets = ["stepper_x", "stepper_y", "stepper_z", "extruder"]
    targets += [f"stepper_z{i}" for i in range(1, z_count)]
    for target in targets:
        name = f"{model} {target}"
        if name in result:
            continue
        socket = entry["sockets"].get(assignments.get(target, target))
        if socket is None:
            continue
        motor = parsed.get(target, {})
        if not isinstance(motor, Mapping):
            continue
        # Direction reversal is an explicit mechanical choice on the same pin.
        actual_pins = {key: motor.get(key) for key in socket["motor_pins"]}
        expected_pins = dict(socket["motor_pins"])
        actual_pins["dir_pin"] = str(actual_pins["dir_pin"]).lstrip("!")
        expected_pins["dir_pin"] = expected_pins["dir_pin"].lstrip("!")
        if actual_pins != expected_pins:
            continue
        transport = socket["transports"].get(mode)
        if transport is None:
            continue
        donor = parsed.get(transport["section"])
        if not isinstance(donor, Mapping):
            continue
        if {key: value for key, value in donor.items() if key in TRANSPORT_KEYS} != transport["options"]:
            continue
        # Reassigning the same chip preserves its complete electrical circuit.
        # A different chip receives connector wiring only.
        same_model = transport["section"].split(" ", 1)[0] == model
        result[name] = dict(donor if same_model else transport["options"])
    return result
