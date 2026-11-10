"""Bind generated bed bounds to a CFG and review its effective XY geometry.

This adapter uses PrinterMotionSpace for coordinate envelopes. It does not infer
the physical bed from travel, a mesh, or comments in a destination-owned file.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path

from core.motion_model import PrinterMotionSpace
from core.pin_validator import _read_pin_config
from core.probe_configuration import is_probe_virtual_endstop


@dataclass(frozen=True)
class GeometryContext:
    source_sha256: str
    printable_x_min: float
    printable_x_max: float
    printable_y_min: float
    printable_y_max: float

    @classmethod
    def from_generated(cls, content: bytes, space: PrinterMotionSpace):
        return cls(hashlib.sha256(content).hexdigest(),
                   space.printable_x_min, space.printable_x_max,
                   space.printable_y_min, space.printable_y_max)

    def validate_source(self, content: bytes):
        if self.source_sha256 != hashlib.sha256(content).hexdigest():
            raise ValueError("XY geometry provenance does not match the generated CFG; review and regenerate it.")
        for axis in ("x", "y"):
            low, high = (getattr(self, f"printable_{axis}_{bound}") for bound in ("min", "max"))
            if (isinstance(low, bool) or isinstance(high, bool)
                    or not isinstance(low, (int, float)) or not isinstance(high, (int, float))
                    or not math.isfinite(low) or not math.isfinite(high) or low >= high):
                raise ValueError(f"XY geometry provenance has invalid printable {axis.upper()} limits.")


def load_geometry_context(path, content: bytes) -> GeometryContext | None:
    """Read the existing sidecar; legacy absence is handled by semantic review."""
    sidecar = Path(str(path) + ".provenance.json")
    if not sidecar.exists():
        return None
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema") != "kace-config-provenance/v1":
            raise ValueError("unsupported provenance schema")
        geometry = payload.get("geometry")
        if geometry is None:
            return None
        context = GeometryContext(**geometry)
        context.validate_source(content)
        return context
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Cannot use XY geometry provenance from {sidecar}: {exc}") from exc


def validate_effective_xy_geometry(hardware: str, context: GeometryContext | None):
    """Reject impossible effective destinations and missing required bed bounds.

    Pin-only fragments do not claim complete printer geometry. Full XY plans
    with probing operations require bound bed provenance, including manual mesh.
    """
    sections, _ = _read_pin_config(hardware)
    if not any(name in sections for name in (
            "safe_z_home", "bed_mesh", "z_tilt", "quad_gantry_level", "screws_tilt_adjust")):
        # Rail/endstop validity is already checked independently by review.
        # Do not demand a second axis from an unrelated partial configuration.
        return
    axes = {axis: sections.get(f"stepper_{axis}", {}) for axis in ("x", "y")}
    if not any({"position_min", "position_max"} & options.keys() for options in axes.values()):
        return

    def number(value, label):
        try:
            result = float(value)
            if not math.isfinite(result):
                raise ValueError()
            return result
        except (TypeError, ValueError):
            raise ValueError(f"{label} requires a finite number, got {value!r}.") from None

    data = {}
    for axis, options in axes.items():
        for bound in ("min", "max"):
            data[f"{axis}_position_{bound}"] = number(
                options.get(f"position_{bound}", 0 if bound == "min" else None),
                f"[stepper_{axis}] position_{bound}")
        if data[f"{axis}_position_min"] >= data[f"{axis}_position_max"]:
            raise ValueError(f"[stepper_{axis}] position_min must be below position_max.")

    # Eddy providers preserved from an existing config can select rapid_scan.
    # Reading their offsets here does not add generation/electrical support.
    providers = [name for name in sections if name in ("probe", "bltouch")
                 or name.startswith("probe_eddy_current ")]
    if len(providers) > 1:
        raise ValueError("XY probe geometry has multiple active probe providers.")
    probe = sections[providers[0]] if providers else {}
    for axis in ("x", "y"):
        data[f"probe_{axis}_offset"] = number(probe.get(f"{axis}_offset", 0), f"probe {axis}_offset")
    if context is not None:
        for axis in ("x", "y"):
            for bound in ("min", "max"):
                key = f"printable_{axis}_{bound}"
                data[key] = getattr(context, key)
    space = PrinterMotionSpace(data)
    travel = space.nozzle_reachable_area()
    reach = space.probe_reachable_area()
    virtual_z = is_probe_virtual_endstop(sections.get("stepper_z", {}).get("endstop_pin", ""))
    home_probes = virtual_z and bool(providers)
    probing = any(name in sections for name in ("bed_mesh", "z_tilt", "quad_gantry_level", "screws_tilt_adjust"))
    needs_bed = probing or ("safe_z_home" in sections and home_probes)
    bed = space.validate_probeable_area() if needs_bed and context is not None else None

    def pair(value, label):
        parts = str(value).split(",")
        if len(parts) != 2:
            raise ValueError(f"{label} requires an XY pair, got {value!r}.")
        return tuple(number(part, label) for part in parts)

    def within(point, envelope, label):
        for axis, value in zip(("x", "y"), point):
            low, high = envelope[axis]
            if not low <= value <= high:
                raise ValueError(f"{label}: {axis.upper()}={value:g} outside [{low:g}, {high:g}].")

    def nozzle_point(point, label, uses_probe, *, on_bed=False):
        within(point, travel, label + " nozzle travel")
        if (uses_probe or on_bed) and bed is not None:
            sample = ((point[0] + space.probe_x_offset, point[1] + space.probe_y_offset)
                      if uses_probe else point)
            within(sample, bed, label + (" probe on bed" if uses_probe else " manual point on bed"))

    if "safe_z_home" in sections:
        nozzle_point(pair(sections["safe_z_home"].get("home_xy_position"), "[safe_z_home] home_xy_position"),
                     "[safe_z_home] home_xy_position", home_probes)

    if "bed_mesh" in sections:
        mesh = sections["bed_mesh"]
        if "mesh_radius" in mesh:
            # Preserved circular meshes can run on a supported XY machine even
            # though KACE only generates rectangular meshes. Check their extent
            # against the same envelopes without enabling circular generation.
            radius = number(mesh["mesh_radius"], "[bed_mesh] mesh_radius")
            if radius <= 0 or not math.isfinite(radius * 10):
                raise ValueError("[bed_mesh] mesh_radius must be positive and representable.")
            # Klipper's MeshConfig rounds the configured radius down to 0.1mm.
            radius = math.floor(radius * 10) / 10
            origin = pair(mesh.get("mesh_origin", "0,0"), "[bed_mesh] mesh_origin")
            low, high = (tuple(value - radius for value in origin),
                         tuple(value + radius for value in origin))
        else:
            low = pair(mesh.get("mesh_min"), "[bed_mesh] mesh_min")
            high = pair(mesh.get("mesh_max"), "[bed_mesh] mesh_max")
        if any(a >= b for a, b in zip(low, high)):
            raise ValueError("[bed_mesh] mesh_min must be below mesh_max on both axes.")
        for point, label in ((low, "mesh_min"), (high, "mesh_max")):
            within(point, reach, f"[bed_mesh] {label} probe travel")
            if bed is not None:
                within(point, bed, f"[bed_mesh] {label} probe on bed")
        # Review the default operation; runtime METHOD=manual can disable this.
        if "zero_reference_position" in mesh:
            point = pair(mesh["zero_reference_position"], "[bed_mesh] zero_reference_position")
            within(point, reach, "[bed_mesh] zero_reference_position probe travel")
            if bed is not None:
                within(point, bed, "[bed_mesh] zero_reference_position probe on bed")

        if any(name.startswith("probe_eddy_current ") for name in providers):
            from core.mesh_scan_geometry import validate_rapid_scan_geometry
            validate_rapid_scan_geometry(
                mesh, travel, (space.probe_x_offset, space.probe_y_offset),
            )

    for name in ("z_tilt", "quad_gantry_level"):
        if name not in sections:
            continue
        points = sections[name].get("points", "").strip().splitlines()
        if not points:
            raise ValueError(f"[{name}] points are required for XY review.")
        parsed_points = []
        for index, line in enumerate(points, 1):
            label = f"[{name}] points #{index}"
            point = pair(line, label)
            nozzle_point(point, label, bool(providers), on_bed=True)
            parsed_points.append(point)
        if name == "quad_gantry_level":
            if len(parsed_points) != 4:
                raise ValueError("[quad_gantry_level] requires exactly four points in Z/Z1/Z2/Z3 order.")
            # The pinned QGL algorithm fits X across 0-3 and 1-2, then Y
            # across 0-1. Constant probe offsets do not change these spans.
            # Do not infer physical motor assignment or require a rectangle.
            for axis, first, second in ((0, 0, 3), (0, 1, 2), (1, 0, 1)):
                if parsed_points[first][axis] == parsed_points[second][axis]:
                    raise ValueError(
                        f"[quad_gantry_level] points #{first + 1} and #{second + 1} "
                        f"must differ in {'XY'[axis]}: the pinned Klipper fit divides by this span. "
                        "Review point order and physical Z/Z1/Z2/Z3 assignment."
                    )

    screws = sections.get("screws_tilt_adjust", {})
    for option, value in screws.items():
        if option.startswith("screw") and option[5:].isdigit():
            nozzle_point(pair(value, f"[screws_tilt_adjust] {option}"),
                         f"[screws_tilt_adjust] {option}", bool(providers), on_bed=True)

    if needs_bed and context is None:
        raise ValueError("XY bed geometry cannot be verified: printable limits are missing from bound "
                         "CFG provenance. Review the bed bounds and regenerate the configuration; "
                         "destination files and calibration were preserved.")
