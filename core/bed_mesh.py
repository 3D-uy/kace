# core/bed_mesh.py
#
# Bed Mesh Auto-Configuration Generator — KACE
#
# Auto-derives optimal [bed_mesh] limits, grid size, and interpolation
# settings based on the printer's physical travel constraints.
#

from core.motion_model import PrinterMotionSpace

def generate_bed_mesh_config(motion_space: PrinterMotionSpace, user_data: dict, parsed_data: dict) -> dict:
    """Auto-generates intelligent [bed_mesh] settings from real printer geometry.

    Args:
        motion_space: An instance of PrinterMotionSpace.
        user_data: The user wizard data dictionary.
        parsed_data: The parsed board/printer configuration data.

    Returns:
        A dictionary of derived bed_mesh parameters, or an empty dict if no probe is configured.
    """
    probe_type = user_data.get("probe", "None")
    if probe_type == "None":
        return {}

    # 1. Derive mesh_min / mesh_max using probeable_bed_area().
    #
    # Klipper's mesh_min / mesh_max are PROBE-TIP coordinates (per Klipper docs:
    # "This coordinate is relative to the probe's location"), NOT nozzle coords.
    #
    # probeable_bed_area() returns the intersection of:
    #   probe_reachable_area (nozzle_travel + probe_offset)
    #   physical_bed         [0, x_size] × [0, y_size]
    # giving probe coordinates guaranteed to be on the physical bed.
    #
    # Using nozzle_range_for_probing() here was wrong: it returns nozzle coords
    # and never clamps against the bed bounds, producing negative mesh_min when
    # x_position_min < 0 (e.g. Octopus Pro with x_min=-30 and offset=0 → -20).
    probeable = motion_space.probeable_bed_area()
    px_min, px_max = probeable["x"]
    py_min, py_max = probeable["y"]

    margin = 10.0
    mesh_min_x = px_min + margin
    mesh_max_x = px_max - margin
    mesh_min_y = py_min + margin
    mesh_max_y = py_max - margin

    # Ensure validity: if the margin makes the range negative or too small, fall back to smaller margins.
    if (mesh_max_x - mesh_min_x) < 10.0:
        mesh_min_x = px_min + 2.0
        mesh_max_x = px_max - 2.0
    if (mesh_max_x - mesh_min_x) < 2.0:
        mesh_min_x = px_min
        mesh_max_x = px_max

    if (mesh_max_y - mesh_min_y) < 10.0:
        mesh_min_y = py_min + 2.0
        mesh_max_y = py_max - 2.0
    if (mesh_max_y - mesh_min_y) < 2.0:
        mesh_min_y = py_min
        mesh_max_y = py_max

    # 2. probe_count auto-sizing
    # Very small beds (<100mm): 3x3  → triggers lagrange interpolation
    # Small beds (100mm-<180mm): 4x4 → bicubic
    # Medium beds (180mm to 300mm): 5x5
    # Large beds (>300mm): 7x7
    def get_axis_probe_count(axis_size: float) -> int:
        if axis_size < 100.0:
            return 3
        elif axis_size < 180.0:
            return 4
        elif axis_size <= 300.0:
            return 5
        else:
            return 7

    probe_count_x = get_axis_probe_count(motion_space.x_size)
    probe_count_y = get_axis_probe_count(motion_space.y_size)

    # Algorithm selection
    if probe_count_x >= 4 and probe_count_y >= 4:
        algorithm = "bicubic"
        bicubic_tension = 0.2
        mesh_pps = (2, 2)
    else:
        algorithm = "lagrange"
        bicubic_tension = None
        mesh_pps = None

    # 3. adaptive mesh support
    # Automatically include adaptive_margin if requested/enabled via flags
    adaptive_margin = None
    if user_data.get("adaptive_mesh") or user_data.get("adaptive_margin"):
        try:
            adaptive_margin = int(user_data.get("adaptive_margin", 5))
        except (ValueError, TypeError):
            adaptive_margin = 5

    # 4. horizontal_move_z
    # BLTouch/CR-Touch/contact probes: 5
    # Inductive/contactless: 3
    # Unknown: 5
    # Check if the printer profile has an explicit override
    profile_mesh = parsed_data.get("bed_mesh", {})
    if "horizontal_move_z" in profile_mesh:
        try:
            horizontal_move_z = int(profile_mesh["horizontal_move_z"])
        except ValueError:
            horizontal_move_z = 5
    else:
        if probe_type in ("BLTouch", "CR-Touch"):
            horizontal_move_z = 5
        elif probe_type == "Inductive":
            horizontal_move_z = 3
        else:
            horizontal_move_z = 5

    # Speed
    if "speed" in profile_mesh:
        try:
            speed = float(profile_mesh["speed"])
        except ValueError:
            speed = 120.0
    else:
        speed = 120.0

    # 5. Fade defaults
    fade_start = profile_mesh.get("fade_start", "1")
    fade_end = profile_mesh.get("fade_end", "10")
    fade_target = profile_mesh.get("fade_target", "0")

    result = {
        "speed": f"{speed:g}",
        "horizontal_move_z": str(horizontal_move_z),
        "mesh_min": f"{mesh_min_x:.1f}, {mesh_min_y:.1f}",
        "mesh_max": f"{mesh_max_x:.1f}, {mesh_max_y:.1f}",
        "probe_count": f"{probe_count_x}, {probe_count_y}",
        "algorithm": algorithm,
        "fade_start": str(fade_start),
        "fade_end": str(fade_end),
        "fade_target": str(fade_target)
    }

    if bicubic_tension is not None:
        result["bicubic_tension"] = f"{bicubic_tension:.1f}"
    if mesh_pps is not None:
        result["mesh_pps"] = f"{mesh_pps[0]}, {mesh_pps[1]}"
    if adaptive_margin is not None:
        result["adaptive_margin"] = str(adaptive_margin)

    return result
