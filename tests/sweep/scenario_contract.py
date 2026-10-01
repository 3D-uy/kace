"""Complete reviewed 192-scenario contract, separate from the raw sweep policy.

Run: python -m tests.sweep.scenario_contract --artifacts <new-directory>
No scenario is waived because generation failed or metadata calls it blocked.
"""
import argparse
from collections import Counter
import contextlib
import hashlib
import io
import json
from pathlib import Path
from unittest.mock import patch

from core.exceptions import GenerationError
from tests.klipper_contract import KLIPPER_REF
from tests.matrix.run_matrix import run_docker_validation
from tests.sweep import boundary_contract, full_sweep_runner as sweep
from tests.sweep import probe_contract, motor_contract, thermal_contract
from tests.sweep.scope_inventory import load_inventory, verify_source_checkout

SOURCE = Path(__file__).resolve().parents[2] / '.klipper-contract-source'
INPUT_REASONS = {
    'probe_selection_missing': '[stepper_z] probe:z_virtual_endstop requires a generated probe',
    'tmc_selection_missing': '[stepper_x]: TMC virtual_endstop has no supported driver section',
    'cooling_consumer_missing': 'requires available stepper stepper_z1',
    'thermal_policy_review_missing': 'selected-source protection requires explicit review',
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def capture_raw(row, source, folder):
    """Run the unchanged explicit-no-display fixture and retain real outcomes."""
    name = row['filename']
    raw = (source / 'config' / name).read_text(encoding='utf-8')
    assert hashlib.sha256(raw.encode('utf-8')).hexdigest() == row['source_sha256_lf'], 'Source drift'
    before = {p.name: digest(p) for p in folder.iterdir() if p.is_file()}
    original, errors = sweep.generate_config, []
    def observe(*args, **kwargs):
        try:
            return original(*args, **kwargs)
        except Exception as exc:
            errors.append(exc)
            raise
    with patch.object(sweep, 'generate_config', side_effect=observe), contextlib.redirect_stdout(io.StringIO()):
        result, generated, warnings = sweep._classify_config(name, raw, str(folder), without_display=True)
    record = dict(filename=name, source_sha256_lf=row['source_sha256_lf'], code=result.code,
                  detail=result.detail, generated=generated, warnings=warnings,
                  config_path=name.replace('.cfg', '.out.cfg') if generated else None,
                  exception_type=type(errors[0]).__name__ if errors else None)
    base = row['classification'] == 'LOAD_EVIDENCE' and row['scenario'] == 'baseline_without_display'
    if base:
        assert generated and result.code == 'GENERATED' and not errors, record
    else:
        assert not generated, f'Unreviewed raw fixture success: {name}'
        assert {p.name: digest(p) for p in folder.iterdir() if p.is_file()} == before, 'Failed raw scenario changed artifacts'
        if row['headless_class'] == 'unsupported_kinematics':
            assert result.code == 'UNSUPPORTED' and not errors, record
        else:
            assert result.code == 'FAILURE' and len(errors) == 1 and isinstance(errors[0], GenerationError), record
            if row['scenario'] != 'baseline_without_display':
                assert INPUT_REASONS[row['headless_class']] in str(errors[0]), record
    return record


def validate_raw(records, validations, error):
    expected = {r['filename'] for r in records if r['generated']}
    assert not error, error
    assert isinstance(validations, dict) and set(validations) == expected, 'Incomplete/extra baseline loader evidence'
    for row in records:
        if not row['generated']:
            continue
        actual = validations[row['filename']]
        assert isinstance(actual, dict) and actual.get('valid') is True, (row['filename'], actual)
        row.update(klipper=actual, code='PASS', detail=actual.get('reason', 'Klipper loaded config'))


def exact_rows(records, names):
    indexed = {r['filename']: r for r in records}
    assert len(indexed) == len(records) and set(indexed) == set(names), 'Duplicate, missing or extra scenario evidence'
    return indexed


def reconcile(inventory, receipt, raw_rows, boundaries, guided):
    """Require exact partition coverage and existing concrete class proofs."""
    assert len(inventory) == 192 and receipt['profile_count'] == 192
    raw = exact_rows(raw_rows, inventory)
    blocked_names = {n for n, r in inventory.items() if r['headless_class'] in boundary_contract.CLASSES}
    blocked = exact_rows(boundaries, blocked_names)
    assert len(blocked) == 47
    by_scenario = {}
    for scenario in ('explicit_probe_selection', 'explicit_motor_selection', 'explicit_thermal_review'):
        report = guided[scenario]
        assert report['successful'] is True and report['infrastructure_error'] is None, scenario
        assert report['klipper_ref'] == KLIPPER_REF and report['source_inventory'] == receipt
        assert report['qualified_boards'] == []
        names = {n for n, r in inventory.items() if r['scenario'] == scenario}
        by_scenario[scenario] = exact_rows(report['profiles'], names)
    results = []
    for name, row in inventory.items():
        baseline = raw[name]
        assert baseline['source_sha256_lf'] == row['source_sha256_lf'], name
        proof = None
        if name in blocked:
            proof = blocked[name]
            assert proof['raw_code'] == baseline['code'] and proof['raw_detail'] == baseline['detail'], name
            assert proof['emitted_artifacts'] == [] and proof['active_dependencies'], name
            if row['classification'] == 'SOURCE_DEPENDENCY_BLOCKED':
                assert proof['artifact_check'] and proof['recovery_check'], name
            else:
                assert proof['boundary_check'], name
            result = 'BOUNDARY_VERIFIED'
        elif row['scenario'] == 'baseline_without_display':
            assert row['classification'] == 'LOAD_EVIDENCE'
            assert baseline['code'] == 'PASS' and baseline['generated'] is True
            assert baseline['klipper']['valid'] is True
            result = 'LOAD_VERIFIED'
        else:
            proof = by_scenario[row['scenario']][name]
            if row['classification'] == 'NEEDS_USER_INPUT':
                assert proof['status'] == 'NEEDS_USER_INPUT' and proof['missing'] == ['x_offset', 'y_offset']
                assert proof['config_path'] is None
                assert 'no validated custom probe configuration' in proof['generation_rejection']
                result = 'INPUT_REQUIRED_VERIFIED'
            else:
                assert proof['status'] == 'PASS' and proof['klipper']['valid'] is True
                result = 'LOAD_VERIFIED'
        if proof is not None:
            assert all(proof[k] == row[k] for k in row), f'Scenario identity drift: {name}'
        results.append(dict(row, contract_result=result, raw_code=baseline['code'], raw_detail=baseline['detail']))
    assert Counter(r['contract_result'] for r in results) == {
        'LOAD_VERIFIED': 144, 'BOUNDARY_VERIFIED': 47, 'INPUT_REQUIRED_VERIFIED': 1}
    assert Counter(r['code'] for r in raw_rows) == {'PASS': 114, 'FAILURE': 68, 'UNSUPPORTED': 10}
    return results


def execute(source, folder):
    folder.mkdir(parents=True, exist_ok=False)
    report = dict(klipper_ref=KLIPPER_REF, qualified_boards=[], successful=False,
                  contract='reviewed-initial-installation-scenarios', error=None, results=[])
    raw_rows, boundaries, guided = [], [], {}
    try:
        receipt = verify_source_checkout(source)
        _, inventory = load_inventory()
        report['source_inventory'] = receipt
        raw_folder = folder / 'raw-headless'
        raw_folder.mkdir()
        for row in inventory.values():
            raw_rows.append(capture_raw(row, source, raw_folder))
        write_json(raw_folder / 'generation.json', raw_rows)
        cases = [dict(id=r['filename'], config_path=r['config_path'], generation={'status': 'generated'})
                 for r in raw_rows if r['generated']]
        assert len(cases) == 114, 'Incomplete baseline generation coverage'
        manifest = raw_folder / 'manifest.json'
        write_json(manifest, dict(klipper_ref=KLIPPER_REF, qualified_boards=[], scope_inventory=receipt, cases=cases))
        print('Validating 114 baseline configurations with pinned Klipper...', flush=True)
        validations, error = run_docker_validation(raw_folder, manifest)
        validate_raw(raw_rows, validations, error)
        boundary_folder = folder / 'boundaries'
        boundary_folder.mkdir()
        checked_receipt, blocked = boundary_contract.reviewed_boundaries(source)
        assert checked_receipt == receipt
        for row in blocked:
            boundaries.append(boundary_contract.verify_boundary(row, source, boundary_folder))
        assert not list(boundary_folder.iterdir())
        for scenario, module, directory in (
                ('explicit_probe_selection', probe_contract, 'probes'),
                ('explicit_motor_selection', motor_contract, 'motors'),
                ('explicit_thermal_review', thermal_contract, 'thermal')):
            print(f'Running concrete class contract: {scenario}', flush=True)
            guided[scenario] = module.execute(source, folder / directory)
        assert verify_source_checkout(source) == receipt, 'Source changed during execution'
        report['results'] = reconcile(inventory, receipt, raw_rows, boundaries, guided)
        report['successful'] = True
    except Exception as exc:
        report['error'] = dict(type=type(exc).__name__, detail=str(exc))
    finally:
        # Keep partial observations on failure. A failed class never disappears
        # into an accepted empty run or an expected-failure regex allowlist.
        write_json(folder / 'raw-headless-results.json', dict(successful=False,
            scope='Unchanged no-probe/one-Z/standalone fixture; raw sweep policy retained',
            results=raw_rows, summary=dict(Counter(r['code'] for r in raw_rows))))
        write_json(folder / 'boundary-proofs.json', boundaries)
        report['summary'] = dict(Counter(r['contract_result'] for r in report['results']))
        report['class_reports'] = {k: dict(successful=v['successful'], infrastructure_error=v['infrastructure_error'])
                                   for k, v in guided.items()}
        report['raw_successful'] = False
        report['evidence_sha256'] = {p.relative_to(folder).as_posix(): digest(p)
            for p in folder.rglob('*') if p.is_file() and p != folder / 'report.json'}
        write_json(folder / 'report.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path, required=True)
    args = parser.parse_args()
    report = execute(SOURCE, args.artifacts)
    print(json.dumps(dict(successful=report['successful'], error=report['error'], summary=report['summary'])))
    raise SystemExit(0 if report['successful'] else 1)
