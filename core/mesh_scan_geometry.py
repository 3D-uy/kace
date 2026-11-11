"""Static XY path of rapid_scan for the pinned Klipper configuration.

The path methods below are the pure geometry subset of Klipper bed_mesh.py at
fe4eb8650bd7de4c2100a14eaf09b0965c430e29. Keep them aligned with that pin; the
integration test compares full paths against its unmodified ProbeManager.
No printer, probe, command or checkout is loaded at runtime. Runtime command
parameters, adaptive objects, scan Z height and physical collisions are outside
this static path contract. The caller checks every emitted segmented-move vertex.
"""
# Mesh Bed Leveling geometry derived from Klipper.
# Copyright (C) 2018-2019 Eric Callahan <arksine.code@gmail.com>
# This file may be distributed under the terms of the GNU GPLv3 license.
import collections
import math


KLIPPER_SCAN_REF = 'fe4eb8650bd7de4c2100a14eaf09b0965c430e29'
BedMeshError = ValueError
_MISSING = object()


def isclose(a, b, rel_tol=1e-09, abs_tol=0.0):
    return abs(a-b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)


def within(coord, min_c, max_c, tol=0.0):
    return (max_c[0] + tol) >= coord[0] >= (min_c[0] - tol) and \
        (max_c[1] + tol) >= coord[1] >= (min_c[1] - tol)


class ZrefMode:
    DISABLED = 0
    IN_MESH = 1
    PROBE = 2


class _MeshOptions:
    error = ValueError

    def __init__(self, options):
        self.options = options

    def number(self, option, default=None):
        value = self.options.get(option, default)
        if value is None and option not in self.options:
            return None
        try:
            number = float(value)
            if not math.isfinite(number):
                raise ValueError()
            return number
        except (TypeError, ValueError):
            raise ValueError(f'[bed_mesh] {option} requires a finite number.') from None

    def getfloatlist(self, option, default=_MISSING, count=2):
        if option not in self.options:
            if default is _MISSING:
                raise ValueError(f'[bed_mesh] {option} is required.')
            return default
        try:
            result = tuple(float(v) for v in str(self.options[option]).split(','))
            if len(result) != count or not all(math.isfinite(v) for v in result):
                raise ValueError()
            return result
        except (TypeError, ValueError):
            raise ValueError(f'[bed_mesh] {option} requires {count} finite coordinates.') from None

    def count(self, option, default):
        try:
            values = tuple(int(v.strip()) for v in str(self.options.get(option, default)).split(','))
            if not values or any(v < 3 for v in values):
                raise ValueError()
            return values
        except (TypeError, ValueError):
            raise ValueError(f'[bed_mesh] {option} requires integers >= 3.') from None


class _ScanPath:
    def __init__(self, mesh):
        config = _MeshOptions(mesh)
        self.cfg_overshoot = config.number('scan_overshoot', 0)
        if 'scan_overshoot' in mesh and self.cfg_overshoot < 1:
            raise ValueError('[bed_mesh] explicit scan_overshoot must be >= 1 mm.')
        self.zero_ref_pos = config.getfloatlist('zero_reference_position', None)
        self.zref_mode = ZrefMode.DISABLED
        self.faulty_regions = []
        self.base_points = []
        self.substitutes = collections.OrderedDict()
        self.is_round = 'mesh_radius' in mesh
        radius, origin = None, (0., 0.)
        if self.is_round:
            radius = config.number('mesh_radius')
            if radius <= 0 or not math.isfinite(radius * 10):
                raise ValueError('[bed_mesh] mesh_radius must be positive and representable.')
            radius = math.floor(radius * 10) / 10
            origin = config.getfloatlist('mesh_origin', (0., 0.))
            counts = config.count('round_probe_count', 5)
            if len(counts) != 1 or not counts[0] & 1:
                raise ValueError('[bed_mesh] round_probe_count must be one odd integer >= 3.')
            x_count = y_count = counts[0]
            low, high = (-radius, -radius), (radius, radius)
        else:
            low = config.getfloatlist('mesh_min')
            high = config.getfloatlist('mesh_max')
            counts = config.count('probe_count', '3,3')
            if len(counts) == 1:
                counts = counts * 2
            if len(counts) != 2 or low is None or high is None:
                raise ValueError('[bed_mesh] mesh limits and one/two probe_count integers are required.')
            x_count, y_count = counts
        if any(a >= b or not math.isfinite(b-a) for a, b in zip(low, high)):
            raise ValueError('[bed_mesh] mesh limits require finite positive spans.')
        self.orig_config = {'mesh_min': low, 'mesh_max': high}
        self._init_faulty_regions(config)
        # Klipper reads consecutive regions; its unused-option check rejects gaps.
        for option in mesh:
            if option.startswith('faulty_region_'):
                try:
                    number, bound = option[len('faulty_region_'):].rsplit('_', 1)
                    if bound not in ('min', 'max') or not 1 <= int(number) <= len(self.faulty_regions):
                        raise ValueError()
                except ValueError:
                    raise ValueError('[bed_mesh] faulty regions must be consecutive complete pairs 1..99.') from None
        self.generate_points({'x_count': x_count, 'y_count': y_count}, low, high, radius, origin)

    def _init_faulty_regions(self, config):
        for i in list(range(1, 100, 1)):
            start = config.getfloatlist("faulty_region_%d_min" % (i,), None,
                                        count=2)
            if start is None:
                break
            end = config.getfloatlist("faulty_region_%d_max" % (i,), count=2)
            # Validate the corners.  If necessary reorganize them.
            # c1 = min point, c3 = max point
            #  c4 ---- c3
            #  |        |
            #  c1 ---- c2
            c1 = [min([s, e]) for s, e in zip(start, end)]
            c3 = [max([s, e]) for s, e in zip(start, end)]
            c2 = [c1[0], c3[1]]
            c4 = [c3[0], c1[1]]
            # Check for overlapping regions
            for j, (prev_c1, prev_c3) in enumerate(self.faulty_regions):
                prev_c2 = [prev_c1[0], prev_c3[1]]
                prev_c4 = [prev_c3[0], prev_c1[1]]
                # Validate that no existing corner is within the new region
                for coord in [prev_c1, prev_c2, prev_c3, prev_c4]:
                    if within(coord, c1, c3):
                        raise config.error(
                            "bed_mesh: Existing faulty_region_%d %s overlaps "
                            "added faulty_region_%d %s"
                            % (j+1, repr([prev_c1, prev_c3]),
                               i, repr([c1, c3])))
                # Validate that no new corner is within an existing region
                for coord in [c1, c2, c3, c4]:
                    if within(coord, prev_c1, prev_c3):
                        raise config.error(
                            "bed_mesh: Added faulty_region_%d %s overlaps "
                            "existing faulty_region_%d %s"
                            % (i, repr([c1, c3]),
                               j+1, repr([prev_c1, prev_c3])))
            self.faulty_regions.append((c1, c3))

    def generate_points(
        self, mesh_config, mesh_min, mesh_max, radius, origin,
        probe_method="automatic"
    ):
        x_cnt = mesh_config['x_count']
        y_cnt = mesh_config['y_count']
        min_x, min_y = mesh_min
        max_x, max_y = mesh_max
        x_dist = (max_x - min_x) / (x_cnt - 1)
        y_dist = (max_y - min_y) / (y_cnt - 1)
        # floor distances down to next hundredth
        x_dist = math.floor(x_dist * 100) / 100
        y_dist = math.floor(y_dist * 100) / 100
        if x_dist < 1. or y_dist < 1.:
            raise BedMeshError("bed_mesh: min/max points too close together")

        if radius is not None:
            # round bed, min/max needs to be recalculated
            y_dist = x_dist
            new_r = (x_cnt // 2) * x_dist
            min_x = min_y = -new_r
            max_x = max_y = new_r
        else:
            # rectangular bed, only re-calc max_x
            max_x = min_x + x_dist * (x_cnt - 1)
        pos_y = min_y
        points = []
        for i in range(y_cnt):
            for j in range(x_cnt):
                if not i % 2:
                    # move in positive direction
                    pos_x = min_x + j * x_dist
                else:
                    # move in negative direction
                    pos_x = max_x - j * x_dist
                if radius is None:
                    # rectangular bed, append
                    points.append((pos_x, pos_y))
                else:
                    # round bed, check distance from origin
                    dist_from_origin = math.sqrt(pos_x*pos_x + pos_y*pos_y)
                    if dist_from_origin <= radius:
                        points.append(
                            (origin[0] + pos_x, origin[1] + pos_y))
            pos_y += y_dist
        if self.zero_ref_pos is None or probe_method == "manual":
            # Zero Reference Disabled
            self.zref_mode = ZrefMode.DISABLED
        elif within(self.zero_ref_pos, mesh_min, mesh_max):
            # Zero Reference position within mesh
            self.zref_mode = ZrefMode.IN_MESH
        else:
            # Zero Reference position outside of mesh
            self.zref_mode = ZrefMode.PROBE
        self.base_points = points
        self.substitutes.clear()
        # adjust overshoot
        og_min_x = self.orig_config["mesh_min"][0]
        og_max_x = self.orig_config["mesh_max"][0]
        add_ovs = min(max(0, min_x - og_min_x), max(0, og_max_x - max_x))
        self.overshoot = self.cfg_overshoot + math.floor(add_ovs)
        min_pt, max_pt = (min_x, min_y), (max_x, max_y)
        self._process_faulty_regions(min_pt, max_pt, radius)

    def _process_faulty_regions(self, min_pt, max_pt, radius):
        if not self.faulty_regions:
            return
        # Cannot probe a reference within a faulty region
        if self.zref_mode == ZrefMode.PROBE:
            for min_c, max_c in self.faulty_regions:
                if within(self.zero_ref_pos, min_c, max_c):
                    opt = "zero_reference_position"
                    raise BedMeshError(
                        "bed_mesh: Cannot probe zero reference position at "
                        "(%.2f, %.2f) as it is located within a faulty region."
                        " Check the value for option '%s'"
                        % (self.zero_ref_pos[0], self.zero_ref_pos[1], opt,)
                    )
        # Check to see if any points fall within faulty regions
        last_y = self.base_points[0][1]
        is_reversed = False
        for i, coord in enumerate(self.base_points):
            if not isclose(coord[1], last_y):
                is_reversed = not is_reversed
            last_y = coord[1]
            adj_coords = []
            for min_c, max_c in self.faulty_regions:
                if within(coord, min_c, max_c, tol=.00001):
                    # Point lies within a faulty region
                    adj_coords = [
                        (min_c[0], coord[1]), (coord[0], min_c[1]),
                        (coord[0], max_c[1]), (max_c[0], coord[1])]
                    if is_reversed:
                        # Swap first and last points for zig-zag pattern
                        first = adj_coords[0]
                        adj_coords[0] = adj_coords[-1]
                        adj_coords[-1] = first
                    break
            if not adj_coords:
                # coord is not located within a faulty region
                continue
            valid_coords = []
            for ac in adj_coords:
                # make sure that coordinates are within the mesh boundary
                if radius is None:
                    if within(ac, min_pt, max_pt, .000001):
                        valid_coords.append(ac)
                else:
                    dist_from_origin = math.sqrt(ac[0]*ac[0] + ac[1]*ac[1])
                    if dist_from_origin <= radius:
                        valid_coords.append(ac)
            if not valid_coords:
                raise BedMeshError(
                    "bed_mesh: Unable to generate coordinates"
                    " for faulty region at index: %d" % (i)
                )
            self.substitutes[i] = valid_coords

    def get_std_path(self):
        path = []
        for idx, pt in enumerate(self.base_points):
            if idx in self.substitutes:
                for sub_pt in self.substitutes[idx]:
                    path.append(sub_pt)
            else:
                path.append(pt)
        if self.zref_mode == ZrefMode.PROBE:
            path.append(self.zero_ref_pos)
        return path

    def iter_rapid_path(self):
        ascnd_x = True
        last_base_pt = last_mv_pt = self.base_points[0]
        # Generate initial move point
        if self.overshoot:
            overshoot = min(8, self.overshoot)
            last_mv_pt = (last_base_pt[0] - overshoot, last_base_pt[1])
            yield last_mv_pt, False
        for idx, pt in enumerate(self.base_points):
            # increasing Y indicates direction change
            dir_change = not isclose(pt[1], last_base_pt[1], abs_tol=1e-6)
            if idx in self.substitutes:
                fp_gen = self._gen_faulty_path(
                    last_mv_pt, idx, ascnd_x, dir_change
                )
                for sub_pt, is_smp in fp_gen:
                    yield sub_pt, is_smp
                    last_mv_pt = sub_pt
            else:
                if dir_change:
                    for dpt in self._gen_dir_change(last_mv_pt, pt, ascnd_x):
                        yield dpt, False
                yield pt, True
                last_mv_pt = pt
            last_base_pt = pt
            ascnd_x ^= dir_change
        if self.zref_mode == ZrefMode.PROBE:
            if self.overshoot:
                ovs = min(4, self.overshoot)
                ovs = ovs if ascnd_x else -ovs
                yield (last_mv_pt[0] + ovs, last_mv_pt[1]), False
            yield self.zero_ref_pos, True

    def _gen_faulty_path(self, last_pt, idx, ascnd_x, dir_change):
        subs = self.substitutes[idx]
        sub_cnt = len(subs)
        if dir_change:
            for dpt in self._gen_dir_change(last_pt, subs[0], ascnd_x):
                yield dpt, False
        if self.is_round:
            # No faulty region path handling for round beds
            for pt in subs:
                yield pt, True
            return
        # Check to see if this is the first corner
        first_corner = False
        sorted_sub_idx = sorted(self.substitutes.keys())
        if sub_cnt == 2 and idx < len(sorted_sub_idx):
            first_corner = sorted_sub_idx[idx] == idx
        yield subs[0], True
        if sub_cnt == 1:
            return
        last_pt, next_pt = subs[:2]
        if sub_cnt == 2:
            if first_corner or dir_change:
                # horizontal move first
                yield (next_pt[0], last_pt[1]), False
            else:
                yield (last_pt[0], next_pt[1]), False
            yield next_pt, True
        elif sub_cnt >= 3:
            if dir_change:
                # first move should be a vertical switch up.  If overshoot
                # is available, simulate another direction change.  Otherwise
                # move inward 2 mm, then up through the faulty region.
                if self.overshoot:
                    for dpt in self._gen_dir_change(last_pt, next_pt, ascnd_x):
                        yield dpt, False
                else:
                    shift = -2 if ascnd_x else 2
                    yield (last_pt[0] + shift, last_pt[1]), False
                    yield (last_pt[0] + shift, next_pt[1]), False
                yield next_pt, True
                last_pt, next_pt = subs[1:3]
            else:
                # vertical move
                yield (last_pt[0], next_pt[1]), False
                yield next_pt, True
                last_pt, next_pt = subs[1:3]
                if sub_cnt == 4:
                    # Vertical switch up within faulty region
                    shift = 2 if ascnd_x else -2
                    yield (last_pt[0] + shift, last_pt[1]), False
                    yield (next_pt[0] - shift, next_pt[1]), False
                    yield next_pt, True
                    last_pt, next_pt = subs[2:4]
            # horizontal move before final point
            yield (next_pt[0], last_pt[1]), False
            yield next_pt, True

    def _gen_dir_change(self, last_pt, next_pt, ascnd_x):
        if not self.overshoot:
            return
        # overshoot X beyond the outer point
        xdir = 1 if ascnd_x else -1
        overshoot = 2. if self.overshoot >= 3. else self.overshoot
        ovr_pt = (last_pt[0] + overshoot * xdir, last_pt[1])
        yield ovr_pt
        if self.overshoot < 3.:
            # No room to generate an arc, move up to next y
            yield (next_pt[0] + overshoot * xdir, next_pt[1])
        else:
            # generate arc
            STEP_ANGLE = 3
            START_ANGLE = 270
            ydiff = abs(next_pt[1] - last_pt[1])
            xdiff = abs(next_pt[0] - last_pt[0])
            max_radius = min(self.overshoot - 2, 8)
            radius = min(ydiff / 2, max_radius)
            origin = [ovr_pt[0], last_pt[1] + radius]
            next_origin_y = next_pt[1] - radius
            # determine angle
            if xdiff < .01:
                # Move is aligned on the x-axis
                angle = 90
                if next_origin_y - origin[1] < .05:
                    # The move can be completed in a single arc
                    angle = 180
            else:
                angle = int(math.degrees(math.atan(ydiff / xdiff)))
                if (
                    (ascnd_x and next_pt[0] < last_pt[0]) or
                    (not ascnd_x and next_pt[0] > last_pt[0])
                ):
                    angle = 180 - angle
            count = int(angle // STEP_ANGLE)
            # Gen first arc
            step = STEP_ANGLE * xdir
            start = START_ANGLE + step
            for arc_pt in self._gen_arc(origin, radius, start, step, count):
                yield arc_pt
            if angle == 180:
                # arc complete
                return
            # generate next arc
            origin = [next_pt[0] + overshoot * xdir, next_origin_y]
            # start at the angle where the last arc finished
            start = START_ANGLE + count * step
            # recalculate the count to make sure we generate a full 180
            # degrees.  Add a step for the repeated connecting angle
            count = 61 - count
            for arc_pt in self._gen_arc(origin, radius, start, step, count):
                yield arc_pt

    def _gen_arc(self, origin, radius, start, step, count):
        end = start + step * count
        # create a segent for every 3 degrees of travel
        for angle in range(start, end, step):
            rad = math.radians(angle % 360)
            opp = math.sin(rad) * radius
            adj = math.cos(rad) * radius
            yield (origin[0] + adj, origin[1] + opp)


def iter_rapid_scan_points(mesh):
    """Yield every static probe-space movement vertex, including non-samples."""
    path = _ScanPath(mesh)
    yield from path.iter_rapid_path()


def validate_rapid_scan_geometry(mesh, travel, offsets):
    """Check all vertices after probe->nozzle conversion; no hardware guarantee.

    Klipper emits the arcs as straight segments. A rectangular travel envelope
    is convex, so checking both vertices also bounds each connecting segment.
    The position before the command is unknown and is not certified here.
    """
    try:
        for index, (point, _) in enumerate(iter_rapid_scan_points(mesh), 1):
            for axis, value, offset in zip(('x', 'y'), point, offsets):
                nozzle = value - offset
                low, high = travel[axis]
                if not math.isfinite(nozzle) or not low <= nozzle <= high:
                    raise ValueError(
                        f'[bed_mesh] rapid_scan move #{index}: {axis.upper()} nozzle={nozzle:g} '
                        f'outside [{low:g}, {high:g}] (probe={value:g}, offset={offset:g}). '
                        'Review mesh bounds, scan_overshoot, faulty regions and mechanical limits.'
                    )
    except (OverflowError, ZeroDivisionError) as exc:
        raise ValueError('[bed_mesh] rapid_scan path is not numerically representable.') from exc
