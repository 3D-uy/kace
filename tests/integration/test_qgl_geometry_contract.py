"""Generated QGL coordinates consumed by the pinned parser and QGL algorithm.

Only the upstream class is compiled from its AST: no MCU, reactor or motion.
This exercises its unmodified arithmetic, not Klipper's full object loader.
"""
import ast
import importlib.util
import logging
import os
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.klipper_contract import KLIPPER_REF
from tests.unit.test_effective_xy_geometry import _generate


@pytest.fixture(scope="module")
def upstream():
    source = Path(os.environ.get("KACE_KLIPPER_SOURCE", Path(__file__).resolve().parents[2] / ".klipper-contract-source"))
    if not source.is_dir():
        pytest.skip("Pinned Klipper checkout required")
    def git(*args):
        return subprocess.check_output(["git", "-C", str(source), *args], text=True).strip()
    assert git("rev-parse", "HEAD") == KLIPPER_REF
    assert not git("status", "--porcelain", "--untracked-files=no")
    path = source / "klippy/extras/quad_gantry_level.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "QuadGantryLevel")
    scope = {"logging": logging}
    exec(compile(ast.Module(body=[cls], type_ignores=[]), str(path), "exec"), scope)
    spec = importlib.util.spec_from_file_location("qgl_contract_configfile", source / "klippy/configfile.py")
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    return scope["QuadGantryLevel"], parser.ConfigFileReader


def _algorithm(cls):
    qgl = cls.__new__(cls)
    qgl.horizontal_move_z = 5
    qgl.gantry_corners = [(-60, -10), (295, 325)]
    qgl.max_adjust = 4
    qgl.gcode = Mock()
    qgl.probe_helper = Mock()
    qgl.probe_helper.get_lift_speed.return_value = 5
    qgl.z_helper = Mock()
    qgl.retry_helper = Mock()
    qgl.z_status = Mock()
    return qgl


@pytest.mark.parametrize("geometry", [
    pytest.param({}, id="default-bed"),
    pytest.param({
        "x_size": "220", "x_position_min": "-10", "x_position_max": "210",
        "x_position_endstop": "-10", "printable_x_min": "-10", "printable_x_max": "210",
        "y_size": "240", "y_position_min": "20", "y_position_max": "260",
        "y_position_endstop": "20", "printable_y_min": "20", "printable_y_max": "260",
    }, id="shifted-bed"),
])
@pytest.mark.parametrize("offset", [(30, -20), (-38, 15), (215, 0), (0, -230)])
@pytest.mark.parametrize("a,b,c", [(0.001, 0, 0), (0, 0.002, 0), (0.001, -0.002, 0.000001)])
def test_generated_qgl_matches_physical_motor_corrections(tmp_path, upstream, geometry, offset, a, b, c):
    cls, reader = upstream
    content = _generate(tmp_path, z_count=4, kinematics="corexy",
                        probe_x_offset=str(offset[0]), probe_y_offset=str(offset[1]),
                        **geometry).decode()
    assert "\n[quad_gantry_level]" not in content
    example = re.search(r"(?ms)^# \[quad_gantry_level\].*?^# max_adjust:[^\n]*", content).group()
    # Activate the actual generated options and coordinate lines, retaining
    # all explanatory comments. Do not replace corners with a test fixture.
    active = re.sub(
        r"(?m)^# (?=\[quad_gantry_level\]|gantry_corners:|points:|speed:|"
        r"horizontal_move_z:|retries:|retry_tolerance:|max_adjust:|  -?\d)",
        "", example,
    )
    (tmp_path / "mainsail.cfg").write_text("[pause_resume]\n", encoding="utf-8")
    (tmp_path / "fluidd.cfg").write_text("[pause_resume]\n", encoding="utf-8")
    active_content = content + "\n" + active + "\n"
    (tmp_path / "active-qgl.cfg").write_text(active_content, encoding="utf-8")
    config = reader().build_fileconfig_with_includes(active_content, str(tmp_path / "printer.cfg"))
    points = [tuple(map(float, line.split(','))) for line in config.get("quad_gantry_level", "points").strip().splitlines()]
    corners = [tuple(map(float, line.split(','))) for line in config.get("quad_gantry_level", "gantry_corners").strip().splitlines()]
    assert len(points) == 4
    assert len(corners) == 2
    assert points[0][0] == points[1][0] < points[2][0] == points[3][0]
    assert points[0][1] == points[3][1] < points[1][1] == points[2][1]
    def height(x, y):
        return a*x + b*y + c*x*y
    # Probe results are bed coordinates, not the commanded nozzle positions.
    results = [SimpleNamespace(bed_x=x+offset[0], bed_y=y+offset[1],
                               bed_z=height(x+offset[0], y+offset[1])) for x, y in points]
    qgl = _algorithm(cls)
    qgl.gantry_corners = corners
    qgl.horizontal_move_z = config.getfloat("quad_gantry_level", "horizontal_move_z")
    qgl.max_adjust = config.getfloat("quad_gantry_level", "max_adjust")
    qgl.probe_finalize(results)
    corrections, speed = qgl.z_helper.adjust_steppers.call_args.args
    # Independent physical order Z, Z1, Z2, Z3 from Klipper's gantry diagram.
    (left, front), (right, rear) = corners
    motor_heights = [height(x, y) for x, y in
                     [(left, front), (left, rear), (right, rear), (right, front)]]
    average = sum(motor_heights) / 4
    assert corrections == pytest.approx([h-average for h in motor_heights])
    assert speed == 5


def test_old_qgl_order_fails_with_unequal_heights(upstream):
    cls, _ = upstream
    qgl = _algorithm(cls)
    positions = [SimpleNamespace(bed_x=x, bed_y=y, bed_z=0.001*x+0.002*y)
                 for x, y in [(10,10), (225,10), (225,225), (10,225)]]
    with pytest.raises(ZeroDivisionError):
        qgl.probe_finalize(positions)
    qgl.z_helper.adjust_steppers.assert_not_called()
