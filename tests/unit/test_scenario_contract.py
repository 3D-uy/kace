"""Complete scenario partition, original observations and failure propagation."""
import copy
import hashlib
import json
from unittest.mock import patch

import pytest

from core.exceptions import GenerationError
from tests.sweep import scenario_contract as contract
from tests.sweep.scope_inventory import InventoryError


@pytest.fixture
def evidence():
    _, inventory = contract.load_inventory()
    receipt = {'profile_count': 192}
    raw, boundaries, guided = [], [], {}
    for row in inventory.values():
        blocked = row['headless_class'] in contract.boundary_contract.CLASSES
        base = row['classification'] == 'LOAD_EVIDENCE' and row['scenario'] == 'baseline_without_display'
        code = 'PASS' if base else 'UNSUPPORTED' if row['headless_class'] == 'unsupported_kinematics' else 'FAILURE'
        raw.append(dict(filename=row['filename'], source_sha256_lf=row['source_sha256_lf'],
                        code=code, detail='observed', generated=base, klipper={'valid': True} if base else None))
        if blocked:
            boundaries.append(dict(row, raw_code=code, raw_detail='observed', emitted_artifacts=[],
                active_dependencies={'source': 'present'}, artifact_check='rejected', recovery_check='rejected', boundary_check='rejected'))
        elif not base:
            report = guided.setdefault(row['scenario'], dict(successful=True, infrastructure_error=None,
                klipper_ref=contract.KLIPPER_REF, source_inventory=receipt, qualified_boards=[], profiles=[]))
            missing = row['classification'] == 'NEEDS_USER_INPUT'
            report['profiles'].append(dict(row, status='NEEDS_USER_INPUT' if missing else 'PASS',
                missing=['x_offset', 'y_offset'] if missing else [], config_path=None if missing else 'generated.cfg',
                generation_rejection='no validated custom probe configuration' if missing else None, klipper={'valid': True}))
    return inventory, receipt, raw, boundaries, guided


def test_complete_partition_keeps_raw_failures_separate(evidence):
    result = contract.reconcile(*evidence)
    assert len(result) == 192
    assert sum(r['contract_result'] == 'LOAD_VERIFIED' for r in result) == 144
    assert sum(r['raw_code'] == 'FAILURE' for r in result) == 68
    assert sum(r['raw_code'] == 'UNSUPPORTED' for r in result) == 10


@pytest.mark.parametrize('mutation', ['missing_raw', 'duplicate_raw', 'extra_raw', 'wrong_source',
    'missing_boundary', 'emitted', 'missing_recovery', 'wrong_raw_reason', 'missing_guided',
    'guided_failure', 'guided_infra', 'wrong_revision', 'wrong_inventory', 'wrong_identity',
    'missing_geometry_reason', 'missing_baseline_load', 'truthy_baseline', 'guided_not_loaded'])
def test_partial_or_false_class_evidence_fails(evidence, mutation):
    inventory, receipt, raw, boundaries, guided = evidence
    probe = guided['explicit_probe_selection']
    if mutation == 'missing_raw':
        raw.pop()
    elif mutation == 'duplicate_raw':
        raw[-1] = copy.deepcopy(raw[0])
    elif mutation == 'extra_raw':
        raw.append(dict(raw[0], filename='unexpected.cfg'))
    elif mutation == 'wrong_source':
        raw[0]['source_sha256_lf'] = '0' * 64
    elif mutation == 'missing_boundary':
        boundaries.pop()
    elif mutation == 'emitted':
        boundaries[0]['emitted_artifacts'] = ['partial.cfg']
    elif mutation == 'missing_recovery':
        next(r for r in boundaries if r['classification'] == 'SOURCE_DEPENDENCY_BLOCKED')['recovery_check'] = ''
    elif mutation == 'wrong_raw_reason':
        boundaries[0]['raw_detail'] = 'other failure'
    elif mutation == 'missing_guided':
        probe['profiles'].pop()
    elif mutation == 'guided_failure':
        probe['successful'] = False
    elif mutation == 'guided_infra':
        probe['infrastructure_error'] = 'Docker unavailable'
    elif mutation == 'wrong_revision':
        probe['klipper_ref'] = '0' * 40
    elif mutation == 'wrong_inventory':
        probe['source_inventory'] = {'profile_count': 191}
    elif mutation == 'wrong_identity':
        probe['profiles'][0]['source_sha256_lf'] = '0' * 64
    elif mutation == 'missing_geometry_reason':
        next(r for r in probe['profiles'] if r['status'] == 'NEEDS_USER_INPUT')['generation_rejection'] = 'unrelated'
    elif mutation == 'guided_not_loaded':
        next(r for r in probe['profiles'] if r['status'] == 'PASS')['klipper']['valid'] = False
    else:
        next(r for r in raw if r['code'] == 'PASS')['klipper']['valid'] = 'true' if mutation == 'truthy_baseline' else False
    with pytest.raises(AssertionError):
        contract.reconcile(inventory, receipt, raw, boundaries, guided)


@pytest.mark.parametrize('mode', ['missing', 'extra', 'invalid', 'truthy', 'infra'])
def test_baseline_loader_requires_exact_complete_results(mode):
    rows = [dict(filename='example.cfg', generated=True)]
    results, error = {'example.cfg': {'valid': True}}, None
    if mode == 'missing':
        results = {}
    elif mode == 'extra':
        results['other.cfg'] = {'valid': True}
    elif mode == 'infra':
        error = 'Docker unavailable'
    else:
        results['example.cfg']['valid'] = 'true' if mode == 'truthy' else False
    with pytest.raises(AssertionError):
        contract.validate_raw(rows, results, error)


@pytest.mark.parametrize('error', [RuntimeError(contract.INPUT_REASONS['probe_selection_missing']),
                                  GenerationError('unrelated generator failure')])
def test_raw_missing_input_requires_typed_concrete_rejection(tmp_path, error):
    source = tmp_path / 'source'
    (source / 'config').mkdir(parents=True)
    output = tmp_path / 'out'
    output.mkdir()
    raw = '[printer]\nkinematics: cartesian\n'
    name = 'generic-fixture.cfg'
    (source / 'config' / name).write_text(raw, encoding='utf-8')
    row = dict(filename=name, source_sha256_lf=hashlib.sha256(raw.encode()).hexdigest(),
               classification='LOAD_EVIDENCE', scenario='explicit_probe_selection', headless_class='probe_selection_missing')
    with patch.object(contract.sweep, 'generate_config', side_effect=error):
        with pytest.raises(AssertionError):
            contract.capture_raw(row, source, output)


def test_infrastructure_failure_leaves_failed_report_not_empty_success(tmp_path):
    folder = tmp_path / 'run'
    with patch.object(contract, 'verify_source_checkout', side_effect=InventoryError('wrong source')):
        result = contract.execute(tmp_path, folder)
    assert result['successful'] is False and result['results'] == []
    assert result['error'] == dict(type='InventoryError', detail='wrong source')
    saved = json.loads((folder / 'report.json').read_text(encoding='utf-8'))
    assert saved == result and saved['raw_successful'] is False
    assert 'boundary-proofs.json' in saved['evidence_sha256']


def test_existing_directory_cannot_reuse_success(tmp_path):
    with pytest.raises(FileExistsError):
        contract.execute(tmp_path, tmp_path)
