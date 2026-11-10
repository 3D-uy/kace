# core/leveling.py
# Klipper source: https://www.klipper3d.org/Config_Reference.html#z_tilt
# Klipper source: https://www.klipper3d.org/Config_Reference.html#quad_gantry_level
#
# Leveling Foundation & Probing Geometry helpers — KACE
#
# Validates coordinate reachability for bed leveling screw adjustments,
# dual/triple Z alignment, and quad gantry leveling.
#

import math

from core.exceptions import GenerationError
from core.motion_model import PrinterMotionSpace


def validate_leveling_adjustment_options(sections):
    """Validate configured adjustment policy, not command overrides or results."""
    for name in ("z_tilt", "quad_gantry_level"):
        options = sections.get(name, {})
        if "retries" in options:
            try:
                retries = int(str(options["retries"]).strip())
            except (TypeError, ValueError, OverflowError):
                raise GenerationError(f"[{name}] retries must be a nonnegative integer.") from None
            if retries < 0:
                raise GenerationError(f"[{name}] retries must be a nonnegative integer.")
        # RetryHelper allows an omitted tolerance (default zero), but an
        # explicit value must be positive. Its command maxima do not apply
        # to configured defaults. QGL's max_adjust bounds positive corrections,
        # not absolute motor travel or physical clearance.
        for option in ("retry_tolerance", "max_adjust") if name == "quad_gantry_level" else ("retry_tolerance",):
            if option not in options:
                continue
            try:
                value = float(str(options[option]).strip())
            except (TypeError, ValueError, OverflowError):
                raise GenerationError(f"[{name}] {option} must be finite and greater than zero.") from None
            if not math.isfinite(value) or value <= 0:
                raise GenerationError(f"[{name}] {option} must be finite and greater than zero.")


def validate_leveling_clearance(sections):
    """Check configured ProbePointsHelper moves, not measured motor corrections.

    Active z_tilt/QGL use the ordinary helper, including with eddy. They do not
    use the bed-mesh rapid_scan approach. Runtime height overrides remain
    outside this static check.
    """
    for name in ("z_tilt", "quad_gantry_level"):
        if name not in sections:
            continue

        def number(value, option):
            try:
                result = float(str(value).strip())
            except (TypeError, ValueError):
                raise GenerationError(f"[{name}] {option} must be a finite number.") from None
            if not math.isfinite(result):
                raise GenerationError(f"[{name}] {option} must be a finite number.")
            return result

        options = sections[name]
        height = number(options.get("horizontal_move_z", "5"), "horizontal_move_z")
        speed = number(options.get("speed", "50"), "speed")
        if speed <= 0:
            raise GenerationError(f"[{name}] speed must be greater than zero.")
        for provider in ("probe", "bltouch"):
            probe = sections.get(provider, {})
            if "z_offset" in probe and height < number(probe["z_offset"], f"[{provider}] z_offset"):
                raise GenerationError(f"[{name}] horizontal_move_z cannot be less than [{provider}] z_offset.")
        if any(section.startswith("probe_eddy_current ") for section in sections) and height < 0:
            raise GenerationError(f"[{name}] horizontal_move_z cannot be less than eddy's zero Z offset.")
        if "stepper_z" in sections:
            rail = sections["stepper_z"]
            if height < number(rail.get("position_min", "0"), "Z position_min"):
                raise GenerationError(f"[{name}] horizontal_move_z is below Z position_min.")
            if "position_max" in rail and height > number(rail["position_max"], "Z position_max"):
                raise GenerationError(f"[{name}] horizontal_move_z exceeds Z position_max.")


def validate_probe_reachability(motion_space: PrinterMotionSpace, points: list[tuple[float, float]]) -> dict:
    """Validates whether the probe can physically reach a list of coordinates.

    A coordinate (x, y) is reachable by the probe if the nozzle can move to a position
    such that the probe is centered at (x, y). This requires that the coordinate
    falls within the probe's reachable travel limits.

    Args:
        motion_space: An instance of PrinterMotionSpace.
        points: A list of (x, y) coordinates to check.

    Returns:
        A dictionary mapping each coordinate tuple to a boolean (True if reachable, else False).
    """
    reach = motion_space.probe_reachable_area()
    rx_min, rx_max = reach["x"]
    ry_min, ry_max = reach["y"]

    results = {}
    for pt in points:
        x, y = pt
        try:
            fx, fy = float(x), float(y)
            reachable = (rx_min <= fx <= rx_max) and (ry_min <= fy <= ry_max)
            results[pt] = reachable
        except (ValueError, TypeError):
            results[pt] = False
    return results

def filter_reachable_points(motion_space: PrinterMotionSpace, points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Filters a list of coordinates, returning only those reachable by the probe.

    Args:
        motion_space: An instance of PrinterMotionSpace.
        points: A list of (x, y) coordinates to filter.

    Returns:
        A list of reachable (x, y) coordinates. Unreachable points are discarded.
    """
    validated = validate_probe_reachability(motion_space, points)
    return [pt for pt in points if validated.get(pt, False)]

def derive_probing_points(
    motion_space: PrinterMotionSpace,
    target_points: list[tuple[float, float]],
    margin: float = 0.0
) -> list[tuple[float, float]]:
    """Clamps desired probing coordinates to the printer's physical probeable bed area.

    Compatibility helper only: this does not validate malformed points, an empty
    intersection or physical clearance. Publication uses the validated geometry
    model instead. Returned points are probe coordinates, not leveling nozzle points.

    Args:
        motion_space: An instance of PrinterMotionSpace.
        target_points: A list of desired probing (x, y) coordinates.
        margin: A safety distance (in mm) from the edges of the probeable bed.

    Returns:
        Candidate probe coordinates; malformed inputs remain unchanged.
    """
    probeable = motion_space.probeable_bed_area()
    px_min, px_max = probeable["x"]
    py_min, py_max = probeable["y"]

    clamped_points = []
    for x, y in target_points:
        try:
            fx, fy = float(x), float(y)
            # Clamp with safety margin
            cx = max(px_min + margin, min(px_max - margin, fx))
            cy = max(py_min + margin, min(py_max - margin, fy))
            clamped_points.append((cx, cy))
        except (ValueError, TypeError):
            # Pass through malformed coordinates unchanged or skip them
            clamped_points.append((x, y))
    return clamped_points


def derive_leveling_points(motion_space, z_motors: int) -> dict:
    """Derive points within declared travel and bed bounds for leveling examples.

    Keep the existing 10mm margin when it leaves distinct points. On an axis
    at most 20mm wide, use a quarter of its span so half remains for sampling.
    The returned coordinates are nozzle coordinates, as required by Klipper's
    z_tilt and quad_gantry_level configuration options. Check the template's
    one-decimal representation as well as the unrounded coordinates.
    """
    try:
        probeable = motion_space.validate_probeable_area()
    except ValueError as exc:
        raise GenerationError(f"Cannot derive leveling points: {exc}") from exc
    px_min, px_max = probeable["x"]
    py_min, py_max = probeable["y"]
    margin_x = 10.0 if px_max - px_min > 20.0 else (px_max - px_min) / 4.0
    margin_y = 10.0 if py_max - py_min > 20.0 else (py_max - py_min) / 4.0

    # Define safe probe coordinates (on-bed with margin)
    safe_probe_x_min = px_min + margin_x
    safe_probe_x_max = px_max - margin_x
    safe_probe_y_min = py_min + margin_y
    safe_probe_y_max = py_max - margin_y

    # Convert probe coordinates to nozzle coordinates:
    # Nozzle_Coord = Probe_Coord - Probe_Offset
    probe_x_offset = motion_space.probe_x_offset
    probe_y_offset = motion_space.probe_y_offset

    zt_x_min = safe_probe_x_min - probe_x_offset
    zt_x_max = safe_probe_x_max - probe_x_offset
    zt_y_min = safe_probe_y_min - probe_y_offset
    zt_y_max = safe_probe_y_max - probe_y_offset

    z_tilt_points = []
    if z_motors == 2:
        y_mid = (zt_y_min + zt_y_max) / 2
        z_tilt_points = [
            (zt_x_min, y_mid),
            (zt_x_max, y_mid)
        ]
    elif z_motors == 3:
        x_mid = (zt_x_min + zt_x_max) / 2
        z_tilt_points = [
            (zt_x_min, zt_y_min),
            (zt_x_max, zt_y_min),
            (x_mid, zt_y_max)
        ]
    elif z_motors >= 4:
        z_tilt_points = [
            (zt_x_min, zt_y_min),
            (zt_x_max, zt_y_min),
            (zt_x_max, zt_y_max),
            (zt_x_min, zt_y_max)
        ]

    # Klipper fits X along pairs 0-3 and 1-2, then Y along 0-1.
    # Physical motor order: Z front-left, Z1 rear-left, Z2 rear-right,
    # Z3 front-right. This differs from the independent z_tilt example order.
    quad_gantry_points = [
        (zt_x_min, zt_y_min),
        (zt_x_min, zt_y_max),
        (zt_x_max, zt_y_max),
        (zt_x_max, zt_y_min)
    ]

    travel = motion_space.nozzle_reachable_area()
    for point in z_tilt_points + quad_gantry_points:
        for candidate in (point, tuple(round(value, 1) for value in point)):
            for axis, value, offset in zip(
                ("x", "y"), candidate, (probe_x_offset, probe_y_offset),
            ):
                if (not math.isfinite(value)
                        or not travel[axis][0] <= value <= travel[axis][1]
                        or not probeable[axis][0] <= value + offset <= probeable[axis][1]):
                    raise GenerationError(
                        f"Cannot derive leveling points: {axis.upper()} nozzle={value:g}, "
                        f"probe={value + offset:g} is outside travel {travel[axis]} "
                        f"or probeable bed {probeable[axis]}, including one-decimal rendering."
                    )
    rendered = [tuple(round(value, 1) for value in point) for point in z_tilt_points]
    if len(set(rendered)) != len(rendered):
        raise GenerationError("Cannot derive leveling points: points collapse at one-decimal rendering.")
    if len(rendered) >= 3:
        a, b, c = rendered[:3]
        area = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        if not math.isfinite(area) or area == 0:
            raise GenerationError("Cannot derive leveling points: one-decimal points are collinear.")

    return {
        "z_tilt_points": z_tilt_points,
        "quad_gantry_level_points": quad_gantry_points
    }


