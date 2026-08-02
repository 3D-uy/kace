"""Deterministic pairwise cases and real KACE generation flow."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import itertools
import json
from pathlib import Path
import re
import sys
import time
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.custom_probe import parse_custom_probe_config  # noqa: E402
from core.generator import generate_config  # noqa: E402
from core.loader import load_boards_yaml  # noqa: E402
from core.scraper import parse_config  # noqa: E402


@dataclass(frozen=True)
class CaseSpec:
    board: str
    mcu: str
    kinematics: str
    bed: str
    homing: str
    probe: str
    display: str
    complexity: str
    expected: str = "valid"

    @property
    def case_id(self) -> str:
        canonical = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:10]
        slug = re.sub(r"[^a-z0-9]+", "-", f"{self.mcu}-{self.board}").strip("-")
        return f"{slug}-{digest}"


FACTOR_VALUES = {
    "kinematics": ("cartesian", "corexy"),
    "bed": ("compact", "standard", "large"),
    "homing": ("negative_min", "origin_min", "positive_max"),
    "probe": ("none", "bltouch", "cr_touch", "inductive", "custom", "dockable"),
    "display": ("none", "st7920"),
    "complexity": ("minimal", "common", "edge"),
}


def pair_tokens(row: tuple[str, ...]) -> set[tuple[int, str, int, str]]:
    return {
        (left, row[left], right, row[right])
        for left in range(len(row))
        for right in range(left + 1, len(row))
    }


def pairwise_rows(values: Iterable[Iterable[str]]) -> list[tuple[str, ...]]:
    """Return a deterministic greedy set-cover over all value pairs."""
    pools = [tuple(pool) for pool in values]
    candidates = list(itertools.product(*pools))
    uncovered = set().union(*(pair_tokens(row) for row in candidates))
    rows = []
    while uncovered:
        best = max(candidates, key=lambda row: (len(pair_tokens(row) & uncovered), tuple(row)))
        rows.append(best)
        uncovered -= pair_tokens(best)
        candidates.remove(best)
    return rows


def supported_boards() -> list[tuple[str, str]]:
    """Expand every MCU/search-term contract in boards.yaml."""
    return [
        (str(entry["mcu"]), str(term))
        for entry in load_boards_yaml().get("boards", [])
        for term in entry.get("search_terms", [])
    ]


def build_cases(profile: str) -> list[CaseSpec]:
    boards = supported_boards()
    factor_names = tuple(FACTOR_VALUES)
    rows = pairwise_rows(FACTOR_VALUES.values())
    if profile == "quick":
        selected = []
        seen_mcu = set()
        for board in boards:
            if board[0] not in seen_mcu:
                selected.append(board)
                seen_mcu.add(board[0])
            if len(selected) == 8:
                break
        boards = selected
        rows = rows[: max(8, len(boards))]

    cases = []
    for index in range(max(len(boards), len(rows))):
        mcu, board = boards[index % len(boards)]
        factors = dict(zip(factor_names, rows[index % len(rows)]))
        expected = "reject" if factors["probe"] == "dockable" else "valid"
        cases.append(CaseSpec(board=board, mcu=mcu, expected=expected, **factors))

    # Coverage is not credited merely because a board appeared in a rejected
    # row. Guarantee at least one loadable baseline for every board/MCU pair.
    valid_boards = {(case.mcu, case.board) for case in cases if case.expected == "valid"}
    for mcu, board in boards:
        if (mcu, board) not in valid_boards:
            cases.append(CaseSpec(
                board, mcu, "cartesian", "standard", "origin_min",
                "none", "none", "minimal",
            ))

    reject_mcu, reject_board = boards[0]
    cases.extend([
        CaseSpec(reject_board, reject_mcu, "cartesian", "invalid_numeric",
                 "origin_min", "none", "none", "edge", "reject"),
        CaseSpec(reject_board, reject_mcu, "corexy", "invalid_printable",
                 "origin_min", "bltouch", "none", "edge", "reject"),
        CaseSpec(reject_board, reject_mcu, "delta", "standard",
                 "origin_min", "none", "none", "common", "reject"),
    ])
    return cases


def _geometry(case: CaseSpec) -> dict[str, str]:
    sizes = {
        "compact": (120, 120, 120), "standard": (235, 235, 250),
        "large": (500, 500, 500), "invalid_numeric": (120, 120, 120),
        "invalid_printable": (120, 120, 120),
    }
    x_size, y_size, z_size = sizes[case.bed]
    geometry = {
        "x_size": str(x_size), "y_size": str(y_size), "z_size": str(z_size),
        "x_position_min": "0", "y_position_min": "0", "z_position_min": "0",
        "x_position_max": str(x_size), "y_position_max": str(y_size),
        "z_position_max": str(z_size), "x_position_endstop": "0",
        "y_position_endstop": "0", "z_position_endstop": "0",
    }
    if case.homing == "negative_min":
        geometry.update({"x_position_min": "-10", "y_position_min": "-8",
                         "x_position_endstop": "-10", "y_position_endstop": "-8"})
    elif case.homing == "positive_max":
        geometry.update({"x_position_endstop": str(x_size), "y_position_endstop": str(y_size)})
    if case.bed == "invalid_printable":
        geometry.update({"printable_x_min": "0", "printable_x_max": "200"})
    elif case.bed == "invalid_numeric":
        geometry["x_size"] = "not-a-number"
    return geometry


def _raw_board_config(case: CaseSpec) -> str:
    sections = [
        "[stepper_x]\nstep_pin: PA0\ndir_pin: PA1\nenable_pin: !PA2\nendstop_pin: ^PA3",
        "[stepper_y]\nstep_pin: PA4\ndir_pin: PA5\nenable_pin: !PA6\nendstop_pin: ^PA7",
        "[stepper_z]\nstep_pin: PB0\ndir_pin: PB1\nenable_pin: !PB2\nendstop_pin: ^PB3",
        "[extruder]\nstep_pin: PB4\ndir_pin: PB5\nenable_pin: !PB6\nheater_pin: PB7\nsensor_pin: PC0",
        "[heater_bed]\nheater_pin: PC1\nsensor_pin: PC2", "[fan]\npin: PC3",
        "[bltouch]\nsensor_pin: ^PC4\ncontrol_pin: PC5",
    ]
    for index in range(1, 4):
        offset = 6 + (index - 1) * 3
        sections.append(f"[stepper_z{index}]\nstep_pin: PC{offset}\n"
                        f"dir_pin: PC{offset + 1}\nenable_pin: !PC{offset + 2}")
    if case.display == "st7920":
        sections.append("[display]\nlcd_type: st7920\ncs_pin: PD0\nsclk_pin: PD1\n"
                        "sid_pin: PD2\nencoder_pins: ^PD3, ^PD4\nclick_pin: ^!PD5")
    return "\n\n".join(sections) + "\n"


def _user_data(case: CaseSpec) -> dict:
    probe_names = {"none": "None", "bltouch": "BLTouch", "cr_touch": "CR-Touch",
                   "inductive": "Inductive", "custom": "Custom Probe",
                   "dockable": "Custom Probe"}
    data = {
        "mcu_path": f"/dev/serial/by-id/usb-kace-matrix-{case.mcu}",
        "board": f"generic-{case.board}.cfg", "printer_profile": f"generic-{case.board}.cfg",
        "kinematics": case.kinematics, "probe": probe_names[case.probe],
        "probe_x_offset": "-18", "probe_y_offset": "7",
        "driver_type": "None (Standard)", "driver_mode": "Standalone",
        "hotend_thermistor": "EPCOS 100K B57560G104F",
        "bed_thermistor": "EPCOS 100K B57560G104F", "web_interface": "None",
        "display_choice": "recommended:display" if case.display != "none" else "none",
        "z_motors": {"minimal": "1", "common": "2", "edge": "4"}[case.complexity],
        "motors": "4", "extruder": "1", "runout": "No", "language": "en",
        "gear_ratio_x": None, "gear_ratio_y": None, "gear_ratio_z": None, "gear_ratio_e": None,
        "rotation_distance_x": None, "rotation_distance_y": None,
        "rotation_distance_z": None, "rotation_distance_e": None,
    }
    data.update(_geometry(case))
    if case.probe == "custom":
        data["custom_probe"] = parse_custom_probe_config(
            "[probe]\npin: ^PC4\nx_offset: -18\ny_offset: 7\nz_offset: 0\nspeed: 8\nsamples: 2\n")
    elif case.probe == "dockable":
        data["custom_probe"] = parse_custom_probe_config(
            "[dockable_probe]\npin: ^PC4\nx_offset: -18\ny_offset: 7\ndock_position: 5, 5\n")
    return data


def generate_case(case: CaseSpec, config_dir: Path) -> dict:
    output_path = config_dir / f"{case.case_id}.cfg"
    started = time.monotonic()
    try:
        parsed = parse_config(_raw_board_config(case), f"generic-{case.board}.cfg", keep_comments=True)
        generate_config(parsed, _user_data(case), output_path=str(output_path), verbose=False)
        if case.expected == "reject":
            return {"status": "unexpected_generation",
                    "reason": "KACE accepted a case marked for safe rejection",
                    "duration_seconds": round(time.monotonic() - started, 6)}
        return {"status": "generated", "reason": "KACE parser and generator completed",
                "sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
                "bytes": output_path.stat().st_size,
                "duration_seconds": round(time.monotonic() - started, 6)}
    except Exception as exc:
        if output_path.exists():
            output_path.unlink()
        return {"status": "expected_reject" if case.expected == "reject" else "kace_error",
                "reason": str(exc) or exc.__class__.__name__, "exception": exc.__class__.__name__,
                "duration_seconds": round(time.monotonic() - started, 6)}
