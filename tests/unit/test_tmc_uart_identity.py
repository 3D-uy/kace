"""Shared UART must retain the official bus and pin-sharing contracts."""
from copy import deepcopy

import pytest

from core.exceptions import GenerationError
from core.profile_values import resolve_tmc_sections
from tests.unit.test_generator import _user, _parsed


CASES = [
    ("four-addresses", [{"uart_address": str(i)} for i in range(4)], True),
    ("duplicate", [{}, {}], False),
    ("qualified-duplicate", [{}, {"uart_pin": "mcu:PC11"}], False),
    ("qualified-valid", [{}, {"uart_pin": "mcu:PC11", "uart_address": "1"}], True),
    ("same-alias", [{"uart_pin": "RX"}, {"uart_pin": "RX", "uart_address": "1"}], True),
    ("mixed-alias", [{"uart_pin": "RX"}, {"uart_address": "1"}], False),
    ("alias-chain-duplicate", [{"uart_pin": "RX"}, {"uart_pin": "CHAIN"}], False),
    ("different-mcus", [{}, {"uart_pin": "tool:PC11"}], True),
    ("cross-mcu-tx", [{"tx_pin": "tool:PC10"}], False),
    ("changed-tx", [{"tx_pin": "PC10"}, {"tx_pin": "PC9", "uart_address": "1"}], False),
    ("explicit-rx-as-tx", [{"tx_pin": "PC11"}], False),
    ("changed-pullup", [{"uart_pin": "^PC11"}, {"uart_address": "1"}], False),
    ("same-pullup", [{"uart_pin": "^PC11"}, {"uart_pin": "^PC11", "uart_address": "1"}], True),
    ("mux-polarity", [{"select_pins": "PD0"}, {"select_pins": "!PD0"}], True),
    ("mux-duplicate", [{"select_pins": "PD0"}, {"select_pins": "mcu:PD0"}], False),
    ("changed-mux-pins", [{"select_pins": "PD0"}, {"select_pins": "!PD1"}], False),
    ("changed-mux-order", [{"select_pins": "PD0,PD1"}, {"select_pins": "PD1,PD0"}], False),
    ("changed-mux-presence", [{}, {"select_pins": "PD0", "uart_address": "1"}], False),
    ("cross-mcu-mux", [{"select_pins": "tool:PD0"}], False),
    ("mux-pin-used-twice", [{"select_pins": "PD0,PD0"}], False),
    ("mux-reuses-rx", [{"select_pins": "PC11"}], False),
    ("reserved-alias", [{"uart_pin": "GND"}], False),
    ("rx-inversion", [{"uart_pin": "!PC11"}], False),
    ("tx-pullup", [{"tx_pin": "^PC10"}], False),
    ("select-pullup", [{"select_pins": "^PD0"}], False),
]


def case_sections(changes):
    sections = {"mcu tool": {}, "board_pins headers": {
        "aliases": "RX=PC11,CHAIN=RX,GND=<GND>"}}
    for target, change in zip(("stepper_x", "stepper_y", "stepper_z", "extruder"), changes):
        sections[f"tmc2209 {target}"] = {"uart_pin": "PC11", **change}
    return sections


@pytest.mark.parametrize("name,changes,accepted", CASES, ids=[c[0] for c in CASES])
def test_shared_bus_contract(name, changes, accepted):
    sections = case_sections(changes)
    before = deepcopy(sections)
    if accepted:
        result = resolve_tmc_sections(sections, _user(driver_type="TMC2209", driver_mode="UART"))
        assert result == {k: v for k, v in sections.items() if k.startswith("tmc")}
    else:
        with pytest.raises(GenerationError):
            resolve_tmc_sections(sections, _user(driver_type="TMC2209", driver_mode="UART"))
    assert sections == before


def test_invalid_bus_fails_before_config_write(tmp_path):
    from core.generator import generate_config
    board = _parsed()
    board.update(case_sections([{}, {"uart_pin": "mcu:PC11"}]))
    for name, options in board.items():
        if name.startswith("tmc2209 "):
            options["run_current"] = "0.580"
    destination = tmp_path / "printer.cfg"
    with pytest.raises(GenerationError, match="UART"):
        generate_config(board, _user(driver_type="TMC2209", driver_mode="UART"), output_path=str(destination))
    assert not destination.exists()
