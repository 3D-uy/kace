"""UART gates recognize Klipper's whitespace separator without changing names."""
import pytest

from core.exceptions import GenerationError
from core.tmc_uart import validate_uart_config, validate_uart_sections


def cfg(*sections):
    return "[mcu]\nserial: /dev/null\n" + "".join(
        f"\n[{name}]\n" + "".join(f"{k}: {v}\n" for k, v in fields.items())
        for name, fields in sections)


@pytest.mark.parametrize("separator", [" ", "\t"])
@pytest.mark.parametrize("model,address,valid", [
    ("tmc2209", 0, True), ("tmc2209", 3, True), ("tmc2209", 4, False),
    ("tmc2208", 0, True), ("tmc2208", 1, False),
    ("tmc2240", 7, True), ("tmc2240", 8, False),
])
def test_address_bounds(separator, model, address, valid):
    text = cfg((model + separator + "stepper_x", {"uart_pin": "PA1", "uart_address": str(address)}))
    if valid:
        validate_uart_config(text)
    else:
        with pytest.raises(GenerationError, match="uart_address"):
            validate_uart_config(text)


@pytest.mark.parametrize("separator", [" ", "\t"])
@pytest.mark.parametrize("second,reason", [
    ({"uart_pin": "PA1", "uart_address": "1"}, "unique address"),
    ({"uart_pin": "PA1", "uart_address": "2", "tx_pin": "PA3"}, "identical RX/TX"),
    ({"uart_pin": "PA1", "uart_address": "2", "select_pins": "PA4"}, "ordered mux"),
])
def test_shared_bus_conflict(separator, second, reason):
    first = {"uart_pin": "PA1", "uart_address": "1"}
    text = cfg(("tmc2209" + separator + "stepper_x", first),
               ("tmc2209" + separator + "stepper_y", second))
    with pytest.raises(GenerationError, match=reason):
        validate_uart_config(text)


@pytest.mark.parametrize("separator", [" ", "\t"])
def test_shared_bus_distinct_addresses_allowed(separator):
    validate_uart_config(cfg(
        ("tmc2209" + separator + "stepper_x", {"uart_pin": "PA1", "uart_address": "0"}),
        ("tmc2209" + separator + "stepper_y", {"uart_pin": "PA1", "uart_address": "3"})))


@pytest.mark.parametrize("separator", [" ", "\t"])
def test_uart2240_spi_option_rejected_in_direct_section_api(separator):
    sections = {"tmc2240" + separator + "stepper_x": {"uart_pin": "PA1", "cs_pin": "PA2"}}
    with pytest.raises(GenerationError, match="unused SPI"):
        validate_uart_sections({"mcu": {}}, sections)


@pytest.mark.parametrize("separator", [" ", "\t"])
def test_uart2240_selects_its_address_limit_in_direct_api(separator):
    sections = {"tmc2240" + separator + "stepper_x": {"uart_pin": "PA1", "uart_address": "7"}}
    validate_uart_sections({"mcu": {}}, sections)


@pytest.mark.parametrize("separator", [" ", "\t"])
def test_tmc2240_spi_without_uart_is_not_validated_as_uart(separator):
    validate_uart_config(cfg(("tmc2240" + separator + "stepper_x", {"cs_pin": "PA2"})))
