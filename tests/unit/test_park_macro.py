"""Parking preflight and artifact paths; official movement evidence is separate."""
import configparser
from pathlib import Path
from types import SimpleNamespace as NS

import jinja2
import pytest

from core.macro_generator import generate_starter_macros
from core.motion_model import PrinterMotionSpace


def park_script(tmp_path, geometry=None):
    text = Path(generate_starter_macros(str(tmp_path), PrinterMotionSpace(geometry or {}))).read_text(encoding="utf-8")
    cfg = configparser.RawConfigParser()
    cfg.read_string(text)
    return cfg.get("gcode_macro PARK_HEAD", "gcode")


def render(script, *, z=100., homed="xyz", x=100., maximum=250., mesh=None, extra=None, excluded=None, frame_offset=0.):
    def fail(msg): raise ValueError(msg)
    printer = {"toolhead": {"homed_axes": homed, "axis_minimum": NS(x=0., y=0., z=0.),
        "axis_maximum": NS(x=235., y=235., z=maximum), "position": NS(x=x+frame_offset, y=100., z=z)},
        "gcode_move": {"position": NS(x=x, y=100., z=z)}, "configfile": {"settings": extra or {}}}
    if mesh is not None:
        printer["bed_mesh"] = {"mesh_matrix": mesh}
    if excluded is not None:
        printer["exclude_object"] = {"excluded_objects": excluded}
    return jinja2.Environment('{%', '%}', '{', '}').from_string(script).render(printer=printer, action_raise_error=fail)


@pytest.mark.parametrize("z", [0., 100., 245.])
def test_vertical_lift_precedes_xy_without_return_move(tmp_path, z):
    lines = [l.strip() for l in render(park_script(tmp_path), z=z).splitlines() if l.strip()]
    assert lines == ["SAVE_GCODE_STATE NAME=KACE_PARK_HEAD", "G91", "G1 Z5 F3000",
                     "G1 X-90.0 Y-90.0 F3000", "RESTORE_GCODE_STATE NAME=KACE_PARK_HEAD MOVE=0"]


@pytest.mark.parametrize("settings,reason", [
    ({"homed": ""}, "homed"), ({"homed": "xy"}, "homed"), ({"homed": "xz"}, "homed"), ({"homed": "yz"}, "homed"),
    ({"z": 245.001}, "5 mm"), ({"z": 250.}, "5 mm"), ({"z": -1.}, "travel"), ({"x": -1.}, "travel"),
    ({"z": float("nan")}, "transformed position"), ({"mesh": [[0., .1], [0., .2]]}, "bed mesh"),
    ({"excluded": ["PART"]}, "object exclusion"), ({"frame_offset": 5.}, "transformed position"),
    *[({"extra": {key: {}}}, "transform") for key in ("bed_tilt", "skew_correction", "z_thermal_adjust")]])
def test_detectable_unsafe_park_aborts_before_commands(tmp_path, settings, reason):
    with pytest.raises(ValueError, match=reason):
        render(park_script(tmp_path), **settings)


def test_empty_official_mesh_status_does_not_block(tmp_path):
    assert "G1 Z5" in render(park_script(tmp_path), mesh=[[]], excluded=[])


def test_destination_is_checked_against_live_travel(tmp_path):
    with pytest.raises(ValueError, match="destination"):
        render(park_script(tmp_path, {"printable_x_min": "240", "printable_x_max": "250"}))


def test_small_bed_keeps_derived_xy_and_uses_relative_lift(tmp_path):
    script = park_script(tmp_path, {"x_size": "60", "y_size": "70", "z_size": "30"})
    assert "G1 X-94.0 Y-93.0 F3000" in render(script, z=20., maximum=30.)
    assert "G1 Z5 F3000" in render(script, z=20., maximum=30.)
