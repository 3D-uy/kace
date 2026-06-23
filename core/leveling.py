# core/leveling.py
#
# Leveling Foundation & Probing Geometry helpers — KACE
#
# Validates coordinate reachability for bed leveling screw adjustments,
# dual/triple Z alignment, and quad gantry leveling.
#

from core.motion_model import PrinterMotionSpace

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

    This ensures that derived points for bed meshes, z_tilt, or quad_gantry_level
    are guaranteed to be safe and reachable by the probe tip during Klipper homing/leveling.

    Args:
        motion_space: An instance of PrinterMotionSpace.
        target_points: A list of desired probing (x, y) coordinates.
        margin: A safety distance (in mm) from the edges of the probeable bed.

    Returns:
        A list of clamped, safe (x, y) coordinates.
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
    """Derive safe, clamped probing coordinates for z_tilt and quad_gantry_level adjustments.

    A safety margin of 10mm is applied to ensure probe remains on-bed.
    The returned coordinates are nozzle coordinates, as required by Klipper's
    z_tilt and quad_gantry_level configuration options.
    """
    probeable = motion_space.probeable_bed_area()
    px_min, px_max = probeable["x"]
    py_min, py_max = probeable["y"]
    margin = 10.0

    # Define safe probe coordinates (on-bed with margin)
    safe_probe_x_min = min(px_min + margin, px_max - margin)
    safe_probe_x_max = max(px_max - margin, px_min + margin)
    safe_probe_y_min = min(py_min + margin, py_max - margin)
    safe_probe_y_max = max(py_max - margin, py_min + margin)

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

    quad_gantry_points = [
        (zt_x_min, zt_y_min),
        (zt_x_max, zt_y_min),
        (zt_x_max, zt_y_max),
        (zt_x_min, zt_y_max)
    ]

    return {
        "z_tilt_points": z_tilt_points,
        "quad_gantry_level_points": quad_gantry_points
    }


