"""Review scan movement coordinates, not only probed mesh points."""
from unittest.mock import Mock

import pytest

from core.config_geometry import GeometryContext, validate_effective_xy_geometry
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.managed_config import build_managed_config_plan
from core.mesh_scan_geometry import iter_rapid_scan_points
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_effective_xy_geometry import (
    _generate, _context, _destination, _assert_no_destination_mutations,
)


def _hardware(mesh, *, provider='probe_eddy_current sensor', offset=(0, 0),
              travel=(0, 200, 0, 200)):
    return (f'[stepper_x]\nposition_min: {travel[0]}\nposition_max: {travel[1]}\n'
            f'[stepper_y]\nposition_min: {travel[2]}\nposition_max: {travel[3]}\n'
            f'[{provider}]\nx_offset: {offset[0]}\ny_offset: {offset[1]}\n'
            f'[bed_mesh]\n{mesh}\n')


@pytest.mark.parametrize('mesh,offset,travel', [
    ('mesh_min: 0,0\nmesh_max: 200,200\nscan_overshoot: 8', (0, 0), (0, 200, 0, 200)),
    ('mesh_min: 20,0\nmesh_max: 199,200\nscan_overshoot: 8', (0, 0), (0, 200, 0, 200)),
    ('mesh_min: 0,0\nmesh_max: 200,200', (20, 0), (0, 200, 0, 200)),
    ('mesh_min: 0,0\nmesh_max: 2,2\nprobe_count: 3,3\n'
     'faulty_region_1_min: .5,.5\nfaulty_region_1_max: 1.5,1.5',
     (0, 0), (0, 2, 0, 2)),
])
def test_scan_path_outside_travel_rejected(mesh, offset, travel):
    with pytest.raises(ValueError, match='(rapid_scan|probe travel)'):
        validate_effective_xy_geometry(
            _hardware(mesh, offset=offset, travel=travel),
            GeometryContext('', travel[0], travel[1], travel[2], travel[3]),
        )


@pytest.mark.parametrize('offset', [(10, -10), (-10, 10), (0, 0)])
def test_scan_path_with_clearance_remains_valid(offset):
    validate_effective_xy_geometry(
        _hardware('mesh_min: 20,20\nmesh_max: 180,180\nscan_overshoot: 8', offset=offset),
        GeometryContext('', 0, 200, 0, 200),
    )


@pytest.mark.parametrize('provider', ['probe', 'bltouch'])
def test_non_scanning_probe_keeps_overshoot_without_hypothetical_path(provider):
    # Klipper falls back to standard probing for these providers, even if
    # METHOD=rapid_scan and scan_overshoot are supplied.
    validate_effective_xy_geometry(
        _hardware('mesh_min: 0,0\nmesh_max: 200,200\nscan_overshoot: 8', provider=provider),
        GeometryContext('', 0, 200, 0, 200),
    )


def test_manual_mesh_keeps_overshoot_without_hypothetical_path():
    hardware = _hardware('mesh_min: 0,0\nmesh_max: 200,200\nscan_overshoot: 8')
    hardware = hardware.replace('[probe_eddy_current sensor]\nx_offset: 0\ny_offset: 0\n', '')
    validate_effective_xy_geometry(hardware, GeometryContext('', 0, 200, 0, 200))


@pytest.mark.parametrize('extra', [
    'scan_overshoot: nan', 'scan_overshoot: inf', 'scan_overshoot: 0',
    'zero_reference_position: nan,100',
    'faulty_region_1_min: 40,40\nfaulty_region_1_max: inf,60',
    'faulty_region_1_min: 40,40',
    'faulty_region_2_min: 40,40\nfaulty_region_2_max: 60,60',
    'faulty_region_1_min: 40,40\nfaulty_region_1_max: 60,60\n'
    'faulty_region_2_min: 50,50\nfaulty_region_2_max: 80,80',
    'probe_count: 3,nan',
])
def test_malformed_or_non_finite_scan_parameters_reject(extra):
    with pytest.raises(ValueError):
        validate_effective_xy_geometry(
            _hardware('mesh_min: 20,20\nmesh_max: 180,180\n' + extra),
            GeometryContext('', 0, 200, 0, 200),
        )


def test_multiple_probe_providers_reject_instead_of_ignoring_eddy_offsets():
    with pytest.raises(ValueError, match='multiple active probe'):
        validate_effective_xy_geometry(
            _hardware('mesh_min: 20,20\nmesh_max: 180,180') + '[probe]\nx_offset: 0\n',
            GeometryContext('', 0, 200, 0, 200),
        )


def test_explicit_none_scan_value_is_a_validation_error():
    with pytest.raises(ValueError, match='scan_overshoot.*finite'):
        list(iter_rapid_scan_points({'mesh_min': '20,20', 'mesh_max': '180,180',
                                     'scan_overshoot': None}))


def test_invalid_scan_in_include_fails_before_approval_and_writes(tmp_path):
    content = _generate(tmp_path, probe='None')
    context = _context(tmp_path, content)
    remote = _destination(content,
        '[probe_eddy_current sensor]\nx_offset: 0\ny_offset: 0\n'
        '[bed_mesh]\nmesh_min: 0,0\nmesh_max: 235,235\nscan_overshoot: 8\n')
    validation = validate_configuration_plan(build_managed_config_plan(content, None, remote, geometry_context=context))
    assert any('rapid_scan' in error.message for error in validation.errors)
    assert all('rapid_scan' in error.message for error in validation.errors)
    transport = FakeTransport(remote)
    before = dict(transport.files)
    confirm = Mock(return_value=True)
    result = ConfigDeploymentTransaction(
        transport, content, None, geometry_context=context, activation='none',
        confirm=confirm, output=lambda _: None,
        snapshot_root=str(tmp_path / 'snapshots'), poll_interval=0,
    ).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    confirm.assert_not_called()
    _assert_no_destination_mutations(transport, before)
