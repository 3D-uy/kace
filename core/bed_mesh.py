# core/bed_mesh.py
# Klipper source: https://www.klipper3d.org/Bed_Mesh.html
#
# Bed Mesh Auto-Configuration Generator — KACE
#
# Auto-derives optimal [bed_mesh] limits, grid size, and interpolation
# settings based on declared travel and printable bounds.
#

import math
from collections.abc import Mapping

from core.motion_model import PrinterMotionSpace
from core.exceptions import GenerationError


def _mesh_pair(value, option, minimum):
    try:
        pair = tuple(int(part.strip()) for part in str(value).split(","))
    except (ValueError, TypeError):
        raise GenerationError(f"bed_mesh: {option} requires one or two integers.") from None
    if len(pair) not in (1, 2) or min(pair) < minimum:
        raise GenerationError(f"bed_mesh: {option} requires one or two integers >= {minimum}.")
    return pair * 2 if len(pair) == 1 else pair


def validate_mesh_options(sections):
    """Check scalar options before rendering/publication, including NaN.

    The pinned loader's comparisons alone accept NaN. Fade and adaptive margin
    have no static lower bound upstream; explicit zero must not select defaults.
    Constraints depending on a measured mesh remain Klipper runtime checks.
    """
    mesh = sections.get("bed_mesh", {})
    minimums = {"scan_overshoot": 1.0, "split_delta_z": .01,
                "move_check_distance": 3.0}
    for option in ("speed", "fade_start", "fade_end", "fade_target",
                   "adaptive_margin", *minimums):
        if option not in mesh:
            continue
        try:
            value = float(str(mesh[option]).strip())
        except (TypeError, ValueError):
            raise GenerationError(f"bed_mesh: {option} requires a finite number.") from None
        if not math.isfinite(value):
            raise GenerationError(f"bed_mesh: {option} requires a finite number.")
        if option == "speed" and value <= 0:
            raise GenerationError("bed_mesh: speed must be greater than zero.")
        if option in minimums and value < minimums[option]:
            raise GenerationError(f"bed_mesh: {option} must be at least {minimums[option]:g} when specified.")


def validate_mesh_interpolation(sections):
    """Validate the declared tuple and return Klipper's effective algorithm.

    Both mesh_pps axes must be zero to bypass interpolation restrictions.
    Bicubic with 3 points and at most 6 on the other axis falls back upstream
    to Lagrange; it is not an invalid configuration or a four-point guarantee.
    """
    if "bed_mesh" not in sections:
        return None
    mesh = sections["bed_mesh"]
    if "mesh_radius" in mesh:
        try:
            count = int(str(mesh.get("round_probe_count", "5")).strip())
        except ValueError:
            raise GenerationError("bed_mesh: round_probe_count must be an odd integer >= 3.") from None
        if count < 3 or count % 2 == 0:
            raise GenerationError("bed_mesh: round_probe_count must be an odd integer >= 3.")
        counts = (count, count)
    else:
        counts = _mesh_pair(mesh.get("probe_count", "3"), "probe_count", 3)
    pps = _mesh_pair(mesh.get("mesh_pps", "2"), "mesh_pps", 0)
    algorithm = str(mesh.get("algorithm", "lagrange")).strip().lower()
    if algorithm not in ("lagrange", "bicubic"):
        raise GenerationError(f"bed_mesh: unknown algorithm {algorithm!r}.")
    try:
        tension = float(str(mesh.get("bicubic_tension", ".2")).strip())
    except ValueError:
        raise GenerationError("bed_mesh: bicubic_tension must be finite and between 0 and 2.") from None
    if not math.isfinite(tension) or not 0 <= tension <= 2:
        raise GenerationError("bed_mesh: bicubic_tension must be finite and between 0 and 2.")
    if "mesh_radius" not in mesh and "mesh_min" in mesh and "mesh_max" in mesh:
        try:
            low, high = (tuple(float(v.strip()) for v in str(mesh[k]).split(","))
                         for k in ("mesh_min", "mesh_max"))
            if len(low) != 2 or len(high) != 2 or not all(math.isfinite(v) for v in low + high):
                raise ValueError()
            spacing = [math.floor((b - a) / (count - 1) * 100) / 100
                       for a, b, count in zip(low, high, counts)]
        except (ValueError, OverflowError):
            raise GenerationError("bed_mesh: mesh_min/mesh_max require finite coordinate pairs.") from None
        if min(spacing) < 1:
            raise GenerationError("bed_mesh: min/max points too close together for probe_count (minimum spacing 1 mm).")
    if max(pps) == 0:
        return "direct"
    if algorithm == "lagrange" and max(counts) > 6:
        raise GenerationError("bed_mesh: lagrange requires probe_count <= 6 on both axes; resolve the explicit mesh settings.")
    if algorithm == "bicubic" and min(counts) < 4:
        if max(counts) > 6:
            raise GenerationError("bed_mesh: bicubic cannot combine 3 points with more than 6 on the other axis; resolve the explicit mesh settings.")
        return "lagrange"
    return algorithm


def _clearance_number(value, label):
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        raise GenerationError(f"horizontal_move_z: {label} must be a finite number.") from None
    if not math.isfinite(number):
        raise GenerationError(f"horizontal_move_z: {label} must be a finite number.")
    return number


def validate_mesh_clearance(sections):
    """Check finite height and configured probe/Z-travel constraints.

    Klipper's config reader has no static lower bound. ProbePointsHelper checks
    the probe's z_offset at runtime and the kinematics checks travel. Validate
    those known constraints early without asserting physical clearance. Eddy
    rapid_scan also approaches its configured height from 0.5 mm above it.
    Command-time overrides and the initial physical position are not known here.
    """
    if "bed_mesh" not in sections:
        return
    height = _clearance_number(sections["bed_mesh"].get("horizontal_move_z", "5"), "height")
    for name in ("probe", "bltouch"):
        options = sections.get(name, {})
        if "z_offset" in options:
            offset = _clearance_number(options["z_offset"], f"[{name}] z_offset")
            if height < offset:
                raise GenerationError(f"horizontal_move_z cannot be less than [{name}] z_offset.")
    if "stepper_z" in sections:
        z = sections["stepper_z"]
        minimum = _clearance_number(z.get("position_min", "0"), "Z position_min")
        if height < minimum:
            raise GenerationError("horizontal_move_z is below Z position_min.")
        if "position_max" in z:
            maximum = _clearance_number(z["position_max"], "Z position_max")
            if height > maximum:
                raise GenerationError("horizontal_move_z exceeds Z position_max.")
            # Pinned RapidScanHelper._raise_tool/_move_to_scan_height use +0.5.
            # Only eddy providers select that path; ordinary/manual probes do not.
            if any(name.startswith("probe_eddy_current ") for name in sections):
                if height + 0.5 > maximum:
                    raise GenerationError(
                        f"horizontal_move_z: rapid_scan approach ({height + 0.5:g} mm) "
                        f"exceeds Z position_max ({maximum:g} mm). Leave at least "
                        "0.5 mm above the configured scan height."
                    )


def generate_bed_mesh_config(
    motion_space: PrinterMotionSpace,
    user_data: dict,
    parsed_data: dict,
    probe_configuration=None,
) -> dict:
    """Derive [bed_mesh] settings from declared printer geometry.

    Args:
        motion_space: An instance of PrinterMotionSpace.
        user_data: The user wizard data dictionary.
        parsed_data: The parsed board/printer configuration data.

    Returns:
        A dictionary of derived bed_mesh parameters, or an empty dict if no probe is configured.
    """
    probe_type = user_data.get("probe", "None")
    probe_kind = getattr(probe_configuration, "kind", None)
    generates_bed_mesh = (
        probe_configuration.generates_bed_mesh
        if probe_configuration is not None
        else probe_type != "None"
    )
    if not generates_bed_mesh:
        return {}

    # 1. Derive mesh_min / mesh_max using probeable_bed_area().
    #
    # Klipper's mesh_min / mesh_max are PROBE-TIP coordinates (per Klipper docs:
    # "This coordinate is relative to the probe's location"), NOT nozzle coords.
    #
    # probeable_bed_area() returns the intersection of:
    #   probe_reachable_area (nozzle_travel + probe_offset)
    #   declared_bed         resolved printable XY bounds (possibly shifted)
    # This checks declared coordinates, not measured clearance or collisions.
    #
    # Using nozzle_range_for_probing() here was wrong: it returns nozzle coords
    # and never clamps against the bed bounds, producing negative mesh_min when
    # x_position_min < 0 (e.g. Octopus Pro with x_min=-30 and offset=0 → -20).
    try:
        probeable = motion_space.validate_probeable_area()
    except ValueError as exc:
        raise GenerationError(str(exc)) from exc
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

    x_bed_size = motion_space.printable_x_max - motion_space.printable_x_min
    y_bed_size = motion_space.printable_y_max - motion_space.printable_y_min
    probe_count_x = get_axis_probe_count(x_bed_size)
    probe_count_y = get_axis_probe_count(y_bed_size)

    profile = user_data.get("_profile_parsed")
    profile_mesh = parsed_data.get("bed_mesh", {})
    selected_mesh = profile.get("bed_mesh", {}) if isinstance(profile, Mapping) else profile_mesh
    if "mesh_radius" in selected_mesh:
        raise GenerationError("bed_mesh: circular mesh generation is outside KACE's rectangular geometry contract.")
    if "probe_count" in selected_mesh:
        probe_count_x, probe_count_y = _mesh_pair(selected_mesh["probe_count"], "probe_count", 3)
    selected_pps = _mesh_pair(selected_mesh.get("mesh_pps", "2"), "mesh_pps", 0)
    if ("probe_count" not in selected_mesh and "algorithm" not in selected_mesh
            and max(selected_pps) > 0 and max(probe_count_x, probe_count_y) > 6):
        # Add a point on the short axis; do not shrink the probed area or cap
        # the long axis to work around Lagrange's six-point limit.
        probe_count_x, probe_count_y = max(4, probe_count_x), max(4, probe_count_y)

    # Algorithm selection
    algorithm = str(selected_mesh.get("algorithm",
        "bicubic" if min(probe_count_x, probe_count_y) >= 4 else "lagrange")).strip().lower()
    bicubic_tension = selected_mesh.get("bicubic_tension", ".2" if algorithm == "bicubic" else None)
    mesh_pps = selected_pps if "mesh_pps" in selected_mesh or algorithm == "bicubic" else None
    interpolation = {"probe_count": f"{probe_count_x}, {probe_count_y}", "algorithm": algorithm,
                     "mesh_pps": f"{selected_pps[0]}, {selected_pps[1]}"}
    if "bicubic_tension" in selected_mesh or bicubic_tension is not None:
        interpolation["bicubic_tension"] = bicubic_tension
    validate_mesh_interpolation({"bed_mesh": interpolation})

    # 3. adaptive mesh support
    # An explicit selection (including zero) overrides the selected profile.
    # Do not coerce millimetres to integers or replace malformed input by 5.
    adaptive_margin = None
    if "adaptive_margin" in user_data:
        adaptive_margin = user_data["adaptive_margin"]
    elif "adaptive_margin" in selected_mesh:
        adaptive_margin = selected_mesh["adaptive_margin"]
    elif user_data.get("adaptive_mesh"):
        adaptive_margin = 5
    if "adaptive_margin" in user_data or "adaptive_margin" in selected_mesh or adaptive_margin is not None:
        validate_mesh_options({"bed_mesh": {"adaptive_margin": adaptive_margin}})

    # 4. horizontal_move_z
    # BLTouch/CR-Touch/contact probes: 5
    # Inductive/contactless: 3
    # Unknown: 5
    # Check if the printer profile has an explicit override
    # Clearance is mechanical profile data, not a different board's wiring.
    clearance_mesh = selected_mesh
    if "horizontal_move_z" in clearance_mesh:
        value = clearance_mesh["horizontal_move_z"]
        _clearance_number(value, "height")
        horizontal_move_z = str(value).strip()
    else:
        if probe_kind in ("bltouch", "cr_touch") or probe_type in ("BLTouch", "CR-Touch"):
            horizontal_move_z = 5
        elif probe_kind == "inductive" or probe_type == "Inductive":
            horizontal_move_z = 3
        else:
            horizontal_move_z = 5

    # The selected mechanical profile owns these settings, just like clearance
    # and interpolation. An empty selected profile must not reuse board tuning.
    speed = selected_mesh.get("speed", "120")
    fade_start = selected_mesh.get("fade_start", "1")
    fade_end = selected_mesh.get("fade_end", "10")
    fade_target = selected_mesh.get("fade_target", "0")
    validate_mesh_options({"bed_mesh": {
        "speed": speed, "fade_start": fade_start,
        "fade_end": fade_end, "fade_target": fade_target,
    }})

    result = {
        "speed": str(speed).strip(),
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
        result["bicubic_tension"] = str(bicubic_tension).strip() if "bicubic_tension" in selected_mesh else "0.2"
    if mesh_pps is not None:
        result["mesh_pps"] = f"{mesh_pps[0]}, {mesh_pps[1]}"
    if adaptive_margin is not None:
        result["adaptive_margin"] = str(adaptive_margin).strip()

    # Formatting must not put a generated point outside the probeable area or
    # collapse a narrow interval. Reject instead of emitting unusable geometry.
    low = tuple(float(v) for v in result["mesh_min"].split(","))
    high = tuple(float(v) for v in result["mesh_max"].split(","))
    if not (px_min <= low[0] < high[0] <= px_max and py_min <= low[1] < high[1] <= py_max):
        raise GenerationError("bed_mesh: formatted mesh bounds exceed or collapse the probeable area.")
    validate_mesh_interpolation({"bed_mesh": result})
    offset = probe_configuration.resolved_offsets.z if probe_configuration is not None else None
    validate_mesh_clearance({
        "bed_mesh": result,
        "probe": {"z_offset": offset if offset is not None else "0"},
        "stepper_z": {"position_min": motion_space.z_min, "position_max": motion_space.z_max},
    })
    return result
