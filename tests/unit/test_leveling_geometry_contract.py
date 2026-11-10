"""Leveling examples must remain usable after their one-decimal rendering."""
import re

import pytest

from core.exceptions import GenerationError
from core.leveling import derive_leveling_points
from core.motion_model import PrinterMotionSpace
from core.pin_validator import _read_pin_config
from tests.unit.test_effective_xy_geometry import _generate


def _assert_points_fit(space, points):
    travel = space.nozzle_reachable_area()
    bed = space.probeable_bed_area()
    for point in points:
        for candidate in (point, tuple(round(value, 1) for value in point)):
            for axis, value, offset in zip(
                ("x", "y"), candidate, (space.probe_x_offset, space.probe_y_offset),
            ):
                assert travel[axis][0] <= value <= travel[axis][1]
                assert bed[axis][0] <= value + offset <= bed[axis][1]
    rendered = [tuple(round(value, 1) for value in point) for point in points]
    assert len(set(rendered)) == len(rendered)
    if len(rendered) >= 3:
        a, b, c = rendered[:3]
        assert (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]) != 0


@pytest.mark.parametrize("z_motors", [2, 3, 4])
@pytest.mark.parametrize("axis", ["x", "y"])
@pytest.mark.parametrize("offset", [230, -230])
def test_narrow_probeable_overlap_keeps_all_nozzle_and_probe_points_inside(z_motors, axis, offset):
    space = PrinterMotionSpace({f"probe_{axis}_offset": offset})
    result = derive_leveling_points(space, z_motors)

    assert len(result["z_tilt_points"]) == z_motors
    assert len(result["quad_gantry_level_points"]) == 4
    for points in result.values():
        _assert_points_fit(space, points)
    # The wide axis retains the existing 10mm margin.
    wide = 1 if axis == "x" else 0
    assert min(point[wide] for point in result["quad_gantry_level_points"]) == 10
    assert max(point[wide] for point in result["quad_gantry_level_points"]) == 225


@pytest.mark.parametrize("z_motors,expected", [
    (2, [(10, 127.5), (195, 127.5)]),
    (3, [(10, 30), (195, 30), (102.5, 225)]),
    (4, [(10, 30), (195, 30), (195, 225), (10, 225)]),
])
def test_normal_geometry_preserves_exact_points_and_order(z_motors, expected):
    space = PrinterMotionSpace({"probe_x_offset": 30, "probe_y_offset": -20})
    result = derive_leveling_points(space, z_motors)

    assert result["z_tilt_points"] == expected
    assert result["quad_gantry_level_points"] == [(10, 30), (10, 225), (195, 225), (195, 30)]
    for points in result.values():
        _assert_points_fit(space, points)


@pytest.mark.parametrize("z_motors", [2, 3, 4])
@pytest.mark.parametrize("geometry", [
    pytest.param({"probe_x_offset": 236}, id="empty-overlap"),
    pytest.param({"probe_y_offset": 235}, id="zero-width-overlap"),
    pytest.param({"printable_x_min": 0.011, "printable_x_max": 0.051}, id="rounded-points-collapse"),
    pytest.param({"printable_y_min": 0.01, "printable_y_max": 0.10}, id="rounded-point-outside-bed"),
])
def test_unusable_or_unrepresentable_geometry_rejects_leveling(z_motors, geometry):
    with pytest.raises(GenerationError):
        derive_leveling_points(PrinterMotionSpace(geometry), z_motors)


@pytest.mark.parametrize("span", [20, 20.2, 40])
def test_margin_transition_retains_distinct_points(span):
    space = PrinterMotionSpace({"printable_x_max": span})
    result = derive_leveling_points(space, 4)

    for points in result.values():
        _assert_points_fit(space, points)
    if span > 20:
        assert result["z_tilt_points"][0][0] == 10
        assert result["z_tilt_points"][1][0] == span - 10


@pytest.mark.parametrize("z_motors", [2, 3, 4])
def test_generated_narrow_leveling_examples_are_safe_and_stay_commented(tmp_path, z_motors):
    content = _generate(
        tmp_path, z_count=z_motors, probe_x_offset="230",
        kinematics="corexy" if z_motors == 4 else "cartesian",
    ).decode()
    section = "quad_gantry_level" if z_motors == 4 else "z_tilt"
    assert section not in _read_pin_config(content)[0]
    example = content[content.index(f"# [{section}]"):]
    points_block = example.split("# points:", 1)[1].split("# speed:", 1)[0]
    points = [
        (float(x), float(y))
        for x, y in re.findall(r"(?m)^#\s+(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)\s*$", points_block)
    ]
    assert len(points) == z_motors
    _assert_points_fit(PrinterMotionSpace({"probe_x_offset": 230}), points)
    pivot_label = "# z_positions:" if z_motors < 4 else "# gantry_corners:"
    assert pivot_label in example


@pytest.mark.parametrize("z_motors", [2, 3, 4])
def test_unrepresentable_leveling_preserves_existing_generated_files(tmp_path, z_motors):
    _generate(tmp_path, z_count=z_motors)
    paths = [tmp_path / "printer.cfg", tmp_path / "printer.cfg.provenance.json"]
    before = [path.read_bytes() for path in paths]

    with pytest.raises(GenerationError, match="leveling"):
        _generate(
            tmp_path, z_count=z_motors,
            printable_x_min="0", printable_x_max="20.04",
        )

    assert [path.read_bytes() for path in paths] == before
