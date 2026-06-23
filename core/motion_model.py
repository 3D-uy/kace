# core/motion_model.py
#
# Printer Motion Space Model — KACE
#
# Represents the printer's physical coordinate system and travel envelopes.
# Differentiates between printable area, nozzle reachable area, probe reachable
# area, and homed coordinate origin.
#

class PrinterMotionSpace:
    """Represents the printer's physical coordinate system and motion space.

    Differentiates between printable bed area, nozzle reachable area,
    probe reachable area, and the homed coordinate origin.
    """
    def __init__(self, user_data: dict):
        # Printable bed size (from wizard user_data)
        try:
            self.x_size = float(user_data.get("x_size", 235.0))
            self.y_size = float(user_data.get("y_size", 235.0))
            self.z_size = float(user_data.get("z_size", 250.0))
        except (ValueError, TypeError):
            self.x_size, self.y_size, self.z_size = 235.0, 235.0, 250.0

        # Stepper X travel limits & endstop position
        try:
            self.x_min = float(user_data.get("x_position_min", 0.0))
            self.x_max = float(user_data.get("x_position_max", self.x_size))
            self.x_endstop = float(user_data.get("x_position_endstop", 0.0))
        except (ValueError, TypeError):
            self.x_min, self.x_max, self.x_endstop = 0.0, self.x_size, 0.0

        # Stepper Y travel limits & endstop position
        try:
            self.y_min = float(user_data.get("y_position_min", 0.0))
            self.y_max = float(user_data.get("y_position_max", self.y_size))
            self.y_endstop = float(user_data.get("y_position_endstop", 0.0))
        except (ValueError, TypeError):
            self.y_min, self.y_max, self.y_endstop = 0.0, self.y_size, 0.0

        # Stepper Z travel limits & endstop position
        try:
            self.z_min = float(user_data.get("z_position_min", 0.0))
            self.z_max = float(user_data.get("z_position_max", self.z_size))
            self.z_endstop = float(user_data.get("z_position_endstop", 0.0))
        except (ValueError, TypeError):
            self.z_min, self.z_max, self.z_endstop = 0.0, self.z_size, 0.0

        # Probe offsets relative to nozzle (probe_x = nozzle_x + x_offset)
        try:
            self.probe_x_offset = float(user_data.get("probe_x_offset", 0.0))
            self.probe_y_offset = float(user_data.get("probe_y_offset", 0.0))
        except (ValueError, TypeError):
            self.probe_x_offset, self.probe_y_offset = 0.0, 0.0

    def printable_bed_area(self) -> dict:
        """Returns the [min, max] range for the printable bed area."""
        return {
            "x": (0.0, self.x_size),
            "y": (0.0, self.y_size)
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
        nozzle_x_min = max(self.x_min, 0.0 - self.probe_x_offset)
        nozzle_x_max = min(self.x_max, self.x_size - self.probe_x_offset)
        nozzle_y_min = max(self.y_min, 0.0 - self.probe_y_offset)
        nozzle_y_max = min(self.y_max, self.y_size - self.probe_y_offset)
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
            "x": (max(0.0, x_probe_min), min(self.x_size, x_probe_max)),
            "y": (max(0.0, y_probe_min), min(self.y_size, y_probe_max))
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
            "homed_origin": self.homed_origin()
        }
