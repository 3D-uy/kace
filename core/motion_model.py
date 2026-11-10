# core/motion_model.py
# Klipper source: https://www.klipper3d.org/Config_Reference.html#stepper
# Klipper source: https://www.klipper3d.org/Config_Reference.html#printer
#
# Printer Motion Space Model — KACE
#
# Represents the printer's physical coordinate system and travel envelopes.
# Differentiates between printable area, nozzle reachable area, probe reachable
# area, and homed coordinate origin.
import math


def _safe_float(val, default):
    if val is None:
        return default
    try:
        number = float(val)
        return number if math.isfinite(number) else default
    except (ValueError, TypeError):
        return default


class ProbeGeometryError(ValueError):
    """Raised when nozzle/probe geometry has no physically usable overlap."""


class PrintableGeometryError(ValueError):
    """Printable bounds cannot be resolved without an explicit bed decision."""


def resolve_printable_xy(user_data: dict, axes: dict) -> tuple[dict, dict]:
    """Resolve bed bounds without translating them to fit mechanical travel.

    ``axes`` maps X/Y to (nominal size, travel minimum, travel maximum).
    Materialized defaults retain their origin until edited or explicitly accepted.
    Explicit bounds may exceed travel here: effective review intersects the bed
    with probe reach, while generation separately validates its printable area.
    """
    previous = user_data.get("_printable_bounds_defaults")
    previous = previous if isinstance(previous, dict) else {}
    ownership = user_data.get("_value_provenance")
    ownership = ownership if isinstance(ownership, dict) else {}
    resolved, defaults = {}, {}
    for axis, (size, travel_min, travel_max) in axes.items():
        implicit = []
        for bound, fallback in (("min", max(travel_min, 0.0)), ("max", size)):
            key = f"printable_{axis}_{bound}"
            supplied = user_data.get(key)
            inherited = False
            if key in previous and ownership.get(key) not in ("USER_OVERRIDE", "PROFILE"):
                try:
                    inherited = float(supplied) == float(previous[key])
                except (TypeError, ValueError):
                    pass
            use_default = supplied is None or inherited
            try:
                value = float(fallback if use_default else supplied)
            except (TypeError, ValueError):
                raise PrintableGeometryError(f"{key} must be a finite number.") from None
            if not math.isfinite(value):
                raise PrintableGeometryError(f"{key} must be a finite number.")
            resolved[key] = value
            if use_default:
                defaults[key] = f"{value:g}"
                implicit.append(key)
        low, high = resolved[f"printable_{axis}_min"], resolved[f"printable_{axis}_max"]
        if implicit and (low < travel_min or high > travel_max or low >= high):
            raise PrintableGeometryError(
                f"Printable {axis.upper()} origin is unresolved: default bounds [{low:g}, {high:g}] "
                f"do not fit travel [{travel_min:g}, {travel_max:g}]. Set explicit "
                f"printable_{axis}_min and printable_{axis}_max; the bed was not shifted."
            )
        if low >= high:
            raise PrintableGeometryError(
                f"printable_{axis}_min ({low:g}) must be less than printable_{axis}_max ({high:g})."
            )
    return resolved, defaults


class PrinterMotionSpace:
    """Represents the printer's physical coordinate system and motion space.

    Differentiates between printable bed area, nozzle reachable area,
    probe reachable area, and the homed coordinate origin.
    """
    def __init__(self, user_data: dict):
        # 1. Stepper Limits (Machine Geometry)
        x_sz_fallback = _safe_float(user_data.get("x_size"), 235.0)
        self.x_min = _safe_float(user_data.get("x_position_min"), 0.0)
        self.x_max = _safe_float(user_data.get("x_position_max"), x_sz_fallback)
        self.x_endstop = _safe_float(user_data.get("x_position_endstop"), 0.0)

        y_sz_fallback = _safe_float(user_data.get("y_size"), 235.0)
        self.y_min = _safe_float(user_data.get("y_position_min"), 0.0)
        self.y_max = _safe_float(user_data.get("y_position_max"), y_sz_fallback)
        self.y_endstop = _safe_float(user_data.get("y_position_endstop"), 0.0)

        z_sz_fallback = _safe_float(user_data.get("z_size"), 250.0)
        self.z_min = _safe_float(user_data.get("z_position_min"), 0.0)
        self.z_max = _safe_float(user_data.get("z_position_max"), z_sz_fallback)
        self.z_endstop = _safe_float(user_data.get("z_position_endstop"), 0.0)

        # 2. Legacy size attributes (kept for backward compatibility with templates/tests)
        self.x_size = _safe_float(user_data.get("x_size"), self.x_max)
        self.y_size = _safe_float(user_data.get("y_size"), self.y_max)
        self.z_size = _safe_float(user_data.get("z_size"), self.z_max)

        # 3. Printable Area Limits: the same origin policy used by generation.
        printable, _ = resolve_printable_xy(user_data, {
            "x": (self.x_size, self.x_min, self.x_max),
            "y": (self.y_size, self.y_min, self.y_max),
        })
        for key, value in printable.items():
            setattr(self, key, value)

        # Derive Z printable limits
        if "printable_z_max" in user_data and user_data["printable_z_max"] is not None:
            self.printable_z_max = _safe_float(user_data["printable_z_max"], self.z_size)
        else:
            self.printable_z_max = self.z_size

        # Probe offsets relative to nozzle (probe_x = nozzle_x + x_offset)
        self.probe_x_offset = _safe_float(user_data.get("probe_x_offset"), 0.0)
        self.probe_y_offset = _safe_float(user_data.get("probe_y_offset"), 0.0)

    def printable_bed_area(self) -> dict:
        """Returns the [min, max] range for the printable bed area."""
        return {
            "x": (self.printable_x_min, self.printable_x_max),
            "y": (self.printable_y_min, self.printable_y_max)
        }

    def nozzle_reachable_area(self) -> dict:
        """Returns the [min, max] range for physical nozzle travel limits."""
        return {
            "x": (self.x_min, self.x_max),
            "y": (self.y_min, self.y_max),
            "z": (self.z_min, self.z_max)
        }

    def probe_reachable_area(self) -> dict:
        """Returns the bed coordinates the probe tip can physically reach.

        Klipper convention: probe_position = nozzle_position + offset.
        The nozzle travels within [x_min, x_max].  The probe (mounted at
        nozzle + offset) therefore covers [x_min + offset, x_max + offset].
        This is the raw probe-reachable envelope — it may extend outside the
        physical bed.  Use probeable_bed_area() for the clamped intersection.
        """
        return {
            "x": (self.x_min + self.probe_x_offset, self.x_max + self.probe_x_offset),
            "y": (self.y_min + self.probe_y_offset, self.y_max + self.probe_y_offset)
        }

    def nozzle_range_for_probing(self) -> dict:
        """Returns the nozzle travel range required to probe the full physical bed.

        To place the probe-tip at a bed coordinate B, the nozzle must move to
        B - offset.  To cover the full bed [0, x_size], the nozzle must reach
        [0 - offset, x_size - offset].  Intersected with the actual nozzle
        travel limits this gives the range of valid nozzle positions.

        Returns nozzle coordinates (not probe/bed coordinates).  This is useful
        for probe reachability validation and motion planning, but NOT for
        deriving mesh_min/max — Klipper's mesh limits are probe-tip coordinates.
        Use probeable_bed_area() for mesh and probe-point derivations.
        """
        nozzle_x_min = max(self.x_min, self.printable_x_min - self.probe_x_offset)
        nozzle_x_max = min(self.x_max, self.printable_x_max - self.probe_x_offset)
        nozzle_y_min = max(self.y_min, self.printable_y_min - self.probe_y_offset)
        nozzle_y_max = min(self.y_max, self.printable_y_max - self.probe_y_offset)
        return {
            "x": (nozzle_x_min, nozzle_x_max),
            "y": (nozzle_y_min, nozzle_y_max),
        }

    def probeable_bed_area(self) -> dict:
        """Returns the intersection of the physical bed and probe-reachable area.

        Computes probe_reachable_area() (probe-tip coordinates) intersected
        with the resolved printable bed bounds. The result is in probe-tip /
        bed coordinates, matching Klipper's mesh_min / mesh_max convention.

        This is the canonical geometry source for any configuration value that
        represents a probe point. z_tilt and quad_gantry_level points instead
        require nozzle coordinates: subtract probe offsets before rendering.
        """
        x_probe_min, x_probe_max = self.probe_reachable_area()["x"]
        y_probe_min, y_probe_max = self.probe_reachable_area()["y"]

        return {
            "x": (max(self.printable_x_min, x_probe_min), min(self.printable_x_max, x_probe_max)),
            "y": (max(self.printable_y_min, y_probe_min), min(self.printable_y_max, y_probe_max))
        }

    def validate_probeable_area(self) -> dict:
        """Return a non-empty probeable rectangle or fail with axis details."""
        area = self.probeable_bed_area()
        for axis in ("x", "y"):
            minimum, maximum = area[axis]
            if minimum >= maximum:
                raise ProbeGeometryError(
                    f"Probeable {axis.upper()} area is empty or inverted "
                    f"[{minimum:g}, {maximum:g}]; check travel limits and probe_{axis}_offset."
                )
        return area

    def safe_z_home_position(self) -> tuple[float, float]:
        """Derive a nozzle coordinate whose probe tip is centered on reachable bed."""
        area = self.validate_probeable_area()
        probe_x = sum(area["x"]) / 2.0
        probe_y = sum(area["y"]) / 2.0
        nozzle_x = probe_x - self.probe_x_offset
        nozzle_y = probe_y - self.probe_y_offset
        if not (self.x_min <= nozzle_x <= self.x_max):
            raise ProbeGeometryError(
                f"Derived safe_z_home X ({nozzle_x:g}) is outside nozzle travel [{self.x_min:g}, {self.x_max:g}]."
            )
        if not (self.y_min <= nozzle_y <= self.y_max):
            raise ProbeGeometryError(
                f"Derived safe_z_home Y ({nozzle_y:g}) is outside nozzle travel [{self.y_min:g}, {self.y_max:g}]."
            )
        return nozzle_x, nozzle_y

    def starter_macro_positions(self) -> dict[str, tuple[float, ...]]:
        """Return conservative, in-range coordinates for generated starter macros."""
        center_x = (self.printable_x_min + self.printable_x_max) / 2.0
        center_y = (self.printable_y_min + self.printable_y_max) / 2.0
        margin_x = min(10.0, max(0.0, (self.printable_x_max - self.printable_x_min) / 10.0))
        margin_y = min(10.0, max(0.0, (self.printable_y_max - self.printable_y_min) / 10.0))
        park_x = self.printable_x_min + margin_x
        park_y = self.printable_y_min + margin_y
        safe_z = min(self.printable_z_max, max(self.z_min, min(50.0, self.printable_z_max * 0.2)))
        movement_z = min(self.printable_z_max, max(self.z_min, min(20.0, self.printable_z_max * 0.1)))
        return {
            "center": (center_x, center_y, safe_z),
            "park": (park_x, park_y, safe_z),
            "test": (center_x, center_y, movement_z),
        }

    def homed_origin(self) -> dict:
        """Returns the homed coordinate origin (endstop positions)."""
        return {
            "x": self.x_endstop,
            "y": self.y_endstop,
            "z": self.z_endstop
        }

    def to_dict(self) -> dict:
        """Helper to serialize the motion space model for output/diagnostics."""
        return {
            "printable_bed_area": self.printable_bed_area(),
            "nozzle_reachable_area": self.nozzle_reachable_area(),
            "probe_reachable_area": self.probe_reachable_area(),
            "probeable_bed_area": self.probeable_bed_area(),
            "homed_origin": self.homed_origin(),
            "printable_x_min": self.printable_x_min,
            "printable_x_max": self.printable_x_max,
            "printable_y_min": self.printable_y_min,
            "printable_y_max": self.printable_y_max,
            "printable_z_max": self.printable_z_max
        }
