# core/motion_model.py
# Klipper source: https://www.klipper3d.org/Config_Reference.html#stepper
# Klipper source: https://www.klipper3d.org/Config_Reference.html#printer
#
# Printer Motion Space Model — KACE
#
# Represents the printer's physical coordinate system and travel envelopes.
# Differentiates between printable area, nozzle reachable area, probe reachable
# area, and homed coordinate origin.
#
def _safe_float(val, default):
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

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

        # 3. Printable Area Limits
        # Derive X printable limits
        if "printable_x_min" in user_data and user_data["printable_x_min"] is not None:
            self.printable_x_min = _safe_float(user_data["printable_x_min"], self.x_min if self.x_min > 0.0 else 0.0)
        else:
            self.printable_x_min = self.x_min if self.x_min > 0.0 else 0.0

        if "printable_x_max" in user_data and user_data["printable_x_max"] is not None:
            self.printable_x_max = _safe_float(user_data["printable_x_max"], self.x_size)
        else:
            self.printable_x_max = self.x_size

        # Derive Y printable limits
        if "printable_y_min" in user_data and user_data["printable_y_min"] is not None:
            self.printable_y_min = _safe_float(user_data["printable_y_min"], self.y_min if self.y_min > 0.0 else 0.0)
        else:
            self.printable_y_min = self.y_min if self.y_min > 0.0 else 0.0

        if "printable_y_max" in user_data and user_data["printable_y_max"] is not None:
            self.printable_y_max = _safe_float(user_data["printable_y_max"], self.y_size)
        else:
            self.printable_y_max = self.y_size

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
        with the physical bed bounds [0, x_size] × [0, y_size].  The result
        is in probe-tip / bed coordinates, matching Klipper's convention for
        mesh_min / mesh_max and z_tilt / qgl probe points.

        This is the canonical geometry source for any configuration value that
        represents a probe point — mesh limits, z_tilt sample points, etc.
        """
        x_probe_min, x_probe_max = self.probe_reachable_area()["x"]
        y_probe_min, y_probe_max = self.probe_reachable_area()["y"]

        return {
            "x": (max(self.printable_x_min, x_probe_min), min(self.printable_x_max, x_probe_max)),
            "y": (max(self.printable_y_min, y_probe_min), min(self.printable_y_max, y_probe_max))
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
