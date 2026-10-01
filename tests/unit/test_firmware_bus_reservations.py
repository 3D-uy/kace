"""Selected hardware buses reserve only their exact firmware mapping."""
import json
import zlib

import pytest

from firmware.identity import FirmwareIdentityError
from firmware.pin_reservations import read_reserved_pins
from tests.unit.test_firmware_pin_reservations import artifact, dictionary


def bus_artifact(tmp_path, *, enums=None, constants=None, fmt="BIN"):
    data = dictionary(constants)
    if enums is not None:
        data["enumerations"] = enums
    return artifact(tmp_path, fmt=fmt, payload=zlib.compress(json.dumps(data).encode()))


@pytest.mark.parametrize("fmt", ["BIN", "UF2", "IHEX"])
def test_only_selected_bus_augments_static_reservations(tmp_path, fmt):
    built = bus_artifact(tmp_path, fmt=fmt, enums={"spi_bus": {"spi1": 0, "spi2": 1}},
        constants={"RESERVE_PINS_USB": "PA11,PA12", "BUS_PINS_spi1": "PA5,PA6,PA7",
                   "BUS_PINS_spi2": "PB13,PB14,PB15"})
    static = {"PA11": "USB", "PA12": "USB"}
    assert read_reserved_pins(built.path, built.firmware_identity) == static
    assert read_reserved_pins(built.path, built.firmware_identity, buses=[("spi_bus", "spi2")]) == {
        **static, "PB13": "spi2", "PB14": "spi2", "PB15": "spi2"}


@pytest.mark.parametrize("enums,requested,expected", [
    ({"spi_bus": {"spi1": 0, "spi1_alt": 0}}, None, "spi1_alt"),
    ({"spi_bus": {"spi1": 0, "spi1_alt": 0}}, "spi1", "spi1"),
    ({"bus": {"spi1": 0}}, None, "spi1"),
    ({"spi_bus": {"spi1": 2}, "bus": {"spi1_alt": 0}}, "spi1", "spi1"),
    ({"spi_bus": {"spi1": [0, 3]}}, None, "spi1"),
    ({"spi_bus": {"spi1": [0, 3]}}, "spi3", "spi3"),
    ({"spi_bus": {"spi": [0, 2]}}, None, "spi0"),
])
def test_enumeration_order_ranges_and_legacy_fallback(tmp_path, enums, requested, expected):
    built = bus_artifact(tmp_path, enums=enums, constants={f"BUS_PINS_{expected}": "PB8"})
    assert read_reserved_pins(built.path, built.firmware_identity,
                              buses=[("spi_bus", requested)]) == {"PB8": expected}


@pytest.mark.parametrize("enums,requested", [
    ({"spi_bus": {"spi1": 1}}, None),
    ({"spi_bus": {}}, None),
    ({"spi_bus": {}, "bus": {"spi1": 0}}, "spi1"),
    ({"spi_bus": {"spi1": 0}}, "SPI1"),
    ({"spi_bus": {"spi1": 0}}, "other"),
])
def test_unknown_or_missing_default_is_rejected(tmp_path, enums, requested):
    built = bus_artifact(tmp_path, enums=enums)
    with pytest.raises(FirmwareIdentityError, match="bus"):
        read_reserved_pins(built.path, built.firmware_identity, buses=[("spi_bus", requested)])


@pytest.mark.parametrize("requested", [None, "spi1"])
def test_no_enumeration_does_not_infer_bus_pin_reservations(tmp_path, requested):
    # Upstream returns before consulting BUS_PINS when no enumeration exists.
    built = bus_artifact(tmp_path, constants={"BUS_PINS_spi1": "PB8"})
    assert read_reserved_pins(built.path, built.firmware_identity,
                              buses=[("spi_bus", requested)]) == {}


def test_selected_bus_without_pin_constant_has_no_inferred_pins(tmp_path):
    built = bus_artifact(tmp_path, enums={"i2c_bus": {"i2c1": 0}})
    assert read_reserved_pins(built.path, built.firmware_identity,
                              buses=[("i2c_bus", None)]) == {}


def test_same_bus_shares_but_overlapping_different_bus_rejects(tmp_path):
    built = bus_artifact(tmp_path, enums={"spi_bus": {"spi1": 0}, "i2c_bus": {"i2c1": 0}},
        constants={"BUS_PINS_spi1": "PB8,PB9", "BUS_PINS_i2c1": "PB8,PB9"})
    assert read_reserved_pins(built.path, built.firmware_identity,
        buses=[("spi_bus", None), ("spi_bus", "spi1")]) == {"PB8": "spi1", "PB9": "spi1"}
    with pytest.raises(FirmwareIdentityError, match="conflicting"):
        read_reserved_pins(built.path, built.firmware_identity,
                          buses=[("spi_bus", None), ("i2c_bus", None)])


def test_bus_conflicting_with_compiled_transport_is_rejected(tmp_path):
    built = bus_artifact(tmp_path, enums={"spi_bus": {"spi1": 0}},
        constants={"BUS_PINS_spi1": "PB8", "RESERVE_PINS_CAN": "PB8,PB9"})
    with pytest.raises(FirmwareIdentityError, match="conflicting"):
        read_reserved_pins(built.path, built.firmware_identity, buses=[("spi_bus", "spi1")])


@pytest.mark.parametrize("enums", [[], {"spi_bus": []}, {"spi_bus": None},
    {"spi_bus": {"spi1": True}}, {"spi_bus": {"spi1": "0"}},
    {"spi_bus": {"spi1": [0]}}, {"spi_bus": {"spi1": [0, -1]}},
    {"spi_bus": {"spi1": [0, 1000000000]}}, {"spi_bus": {"spi1": [False, 2]}}])
def test_malformed_or_unbounded_bus_metadata_is_rejected(tmp_path, enums):
    built = bus_artifact(tmp_path, enums=enums)
    with pytest.raises(FirmwareIdentityError, match="enumeration"):
        read_reserved_pins(built.path, built.firmware_identity, buses=[("spi_bus", None)])


@pytest.mark.parametrize("pins", ["", "PB8,", "PB8, PB9", "toolhead:PB8", 12])
def test_malformed_selected_bus_pins_are_not_silently_ignored(tmp_path, pins):
    built = bus_artifact(tmp_path, enums={"spi_bus": {"spi1": 0}},
                         constants={"BUS_PINS_spi1": pins})
    with pytest.raises(FirmwareIdentityError, match="pin|reservation"):
        read_reserved_pins(built.path, built.firmware_identity, buses=[("spi_bus", None)])


@pytest.mark.parametrize("buses", [[("uart_bus", None)], [("spi_bus", 0)],
                                  [("spi_bus",)], ["spi_bus"]])
def test_invalid_request_contract_is_rejected(tmp_path, buses):
    built = bus_artifact(tmp_path)
    with pytest.raises(FirmwareIdentityError, match="bus"):
        read_reserved_pins(built.path, built.firmware_identity, buses=buses)


def test_changed_bytes_are_rechecked_for_bus_read(tmp_path):
    built = bus_artifact(tmp_path, enums={"spi_bus": {"spi1": 0}})
    with open(built.path, "ab") as stream:
        stream.write(b"changed")
    with pytest.raises(FirmwareIdentityError, match="changed"):
        read_reserved_pins(built.path, built.firmware_identity, buses=[("spi_bus", None)])


def test_aggregate_expansion_limit_is_enforced(tmp_path):
    built = bus_artifact(tmp_path,
        enums={"spi_bus": {"spi0": [0, 40000], "alternate0": [0, 40000]}})
    with pytest.raises(FirmwareIdentityError, match="enumeration exceeds"):
        read_reserved_pins(built.path, built.firmware_identity, buses=[("spi_bus", None)])


def test_unselected_mapping_is_not_reserved_or_validated(tmp_path):
    built = bus_artifact(tmp_path, enums={"spi_bus": {"spi1": 0, "spi2": 1}},
        constants={"BUS_PINS_spi1": "PB8", "BUS_PINS_spi2": "bad:pin"})
    assert read_reserved_pins(built.path, built.firmware_identity,
                              buses=[("spi_bus", "spi1")]) == {"PB8": "spi1"}
