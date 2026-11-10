"""Differential full paths against pinned Klipper, without MCU or motion.

The official ProbeManager and RapidScanHelper classes are compiled unchanged
from AST. Only the non-geometric ProbePointsHelper/printer are stubbed.
"""
import ast
import collections
import importlib.util
import math
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from core.mesh_scan_geometry import (
    KLIPPER_SCAN_REF, iter_rapid_scan_points, validate_rapid_scan_geometry,
)
from tests.klipper_contract import KLIPPER_REF


@pytest.fixture(scope='module')
def official(tmp_path_factory):
    root = Path(os.environ.get('KACE_KLIPPER_SOURCE', Path(__file__).resolve().parents[2] / '.klipper-contract-source'))
    if not root.is_dir():
        pytest.skip('Pinned Klipper source required')
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()
    assert git('rev-parse', 'HEAD') == KLIPPER_REF == KLIPPER_SCAN_REF
    assert not git('status', '--porcelain', '--untracked-files=no')
    path = root / 'klippy/extras/bed_mesh.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    names = {'BedMeshError', 'isclose', 'within', 'ZrefMode', 'ProbeManager', 'RapidScanHelper'}
    selected = [node for node in tree.body if getattr(node, 'name', '') in names]
    class ProbePoints:
        def __init__(self, *args):
            pass
        def use_xy_offsets(self, use):
            assert use
        def update_probe_points(self, points, count):
            assert len(points) >= count
    scope = {'math': math, 'collections': collections,
             'probe': SimpleNamespace(ProbePointsHelper=ProbePoints)}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), 'exec'), scope)
    spec = importlib.util.spec_from_file_location('mesh_contract_configfile', root / 'klippy/configfile.py')
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    temp = tmp_path_factory.mktemp('official-mesh')

    def generate(mesh):
        content = '[bed_mesh]\n' + '\n'.join(f'{k}: {v}' for k, v in mesh.items()) + '\n'
        fc = parser.ConfigFileReader().build_fileconfig_with_includes(content, str(temp / 'printer.cfg'))
        config = parser.ConfigWrapper(SimpleNamespace(config_error=ValueError), fc, {}, 'bed_mesh')
        radius = config.getfloat('mesh_radius', None)
        origin = config.getfloatlist('mesh_origin', (0., 0.), count=2)
        if radius is None:
            low = config.getfloatlist('mesh_min', count=2)
            high = config.getfloatlist('mesh_max', count=2)
            counts = config.getintlist('probe_count', (3, 3))
            if len(counts) == 1:
                counts = counts * 2
        else:
            radius = math.floor(radius * 10) / 10
            low, high = (-radius, -radius), (radius, radius)
            count = config.getint('round_probe_count', 5)
            counts = count, count
        manager = scope['ProbeManager'](config, {'radius': radius, 'mesh_min': low, 'mesh_max': high}, lambda _: None)
        manager.generate_points({'x_count': counts[0], 'y_count': counts[1]}, low, high, radius, origin)
        return list(manager.iter_rapid_path())
    return generate, scope['RapidScanHelper']


MESHES = [
    {'mesh_min': '0,0', 'mesh_max': '200,200', 'probe_count': '3,3'},
    {'mesh_min': '-40,20', 'mesh_max': '174.37,181.79', 'probe_count': '5,7'},
    {'mesh_radius': '70.19', 'mesh_origin': '100,90', 'round_probe_count': '7'},
    {'mesh_radius': '50', 'mesh_origin': '0,0', 'round_probe_count': '5',
     'faulty_region_1_min': '-1,-1', 'faulty_region_1_max': '1,1'},
    {'mesh_min': '0,0', 'mesh_max': '4,4', 'probe_count': '5,5',
     'faulty_region_1_min': '.5,.5', 'faulty_region_1_max': '1.5,1.5'},
    {'mesh_min': '10,10', 'mesh_max': '190,190', 'probe_count': '3,3',
     'faulty_region_1_min': '5,5', 'faulty_region_1_max': '15,15',
     'faulty_region_2_min': '185,95', 'faulty_region_2_max': '195,105'},
    {'mesh_min': '20,20', 'mesh_max': '180,180', 'probe_count': '4,4',
     'zero_reference_position': '195,195'},
]


@pytest.mark.parametrize('mesh', MESHES)
@pytest.mark.parametrize('overshoot', [None, '1', '2.5', '3', '8', '20'])
def test_full_path_matches_official_algorithm(official, mesh, overshoot):
    generate, helper = official
    options = dict(mesh)
    if overshoot is not None:
        options['scan_overshoot'] = overshoot
    upstream = generate(options)
    actual = list(iter_rapid_scan_points(options))
    assert len(actual) == len(upstream)
    for (point, sample), (expected, expected_sample) in zip(actual, upstream):
        assert point == pytest.approx(expected, abs=1e-12)
        assert sample == expected_sample
    # Validate the complete path in nozzle coordinates for offsets of both signs.
    for offset in [(0., 0.), (23., -17.), (-31., 12.)]:
        nozzle = [helper._apply_offsets(None, point, offset) for point, _ in upstream]
        envelope = {axis: (min(p[i] for p in nozzle), max(p[i] for p in nozzle))
                    for i, axis in enumerate(('x', 'y'))}
        validate_rapid_scan_geometry(options, envelope, offset)
        # A travel bound 0.001mm inside any extremum must reject, including
        # extrema that occur on arcs, substituted paths or the reference leg.
        for axis in ('x', 'y'):
            for bound in (0, 1):
                clipped = dict(envelope)
                limits = list(clipped[axis])
                limits[bound] += .001 if bound == 0 else -.001
                clipped[axis] = tuple(limits)
                with pytest.raises(ValueError, match='rapid_scan'):
                    validate_rapid_scan_geometry(options, clipped, offset)


def test_old_bounding_box_review_misses_faulty_path_without_overshoot(official):
    generate, _ = official
    options = {'mesh_min': '0,0', 'mesh_max': '2,2', 'probe_count': '3,3',
               'faulty_region_1_min': '.5,.5', 'faulty_region_1_max': '1.5,1.5'}
    path = generate(options)
    assert any(not 0 <= p[0] <= 2 for p, sample in path if not sample)
    with pytest.raises(ValueError, match='rapid_scan'):
        validate_rapid_scan_geometry(options, {'x': (0, 2), 'y': (0, 2)}, (0, 0))
