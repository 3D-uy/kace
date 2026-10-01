"""Thermal review class, real guards and adversarial official-result checks."""
import copy
from unittest.mock import patch

import pytest

from core.exceptions import GenerationError
from tests.sweep import thermal_contract as contract


@pytest.fixture(scope='module')
def generated(tmp_path_factory):
    folder = tmp_path_factory.mktemp('reviewed-thermal')
    receipt, records = contract.generate_thermal(contract.SOURCE, folder)
    return folder, receipt, records


def test_complete_thermal_class_and_recovery_guards(generated):
    folder, receipt, records = generated
    assert receipt['profile_count'] == 192 and receipt['qualified_boards'] == []
    assert len(records) == 2
    for row in records:
        assert row['status'] == 'GENERATED' and row['checkpoint_receipt_preserved']
        assert set(row['guards']) == {'unreviewed', 'automatic', 'declined', 'changed_mcu',
                                     'artifact_policy_changed', 'artifact_circuit_changed'}
        assert all(row['guards'].values())
        assert (folder / row['config_path']).is_file()
        assert (folder / (row['config_path'] + '.provenance.json')).is_file()


def official_results(records):
    results = {r['filename']: {'valid': True} for r in records}
    results.update({n: dict(valid=valid, reason=reason or 'loaded', exception='Error' if not valid else None)
                    for n, (_, valid, reason) in contract.CONTROLS.items()})
    traces = []
    for spec in contract.trace_specs(records):
        gain = spec['gain_time']
        for scenario in ('not-heating', 'target-zero', 'at-target'):
            faulting = scenario == 'not-heating'
            faults = [0, 0, 0, 1] if faulting else [0, 0, 0, 0]
            traces.append(dict(file=spec['config_path'], scenario=scenario, gain_time=gain,
                events=[dict(time=t, faults=f) for t, f in zip([0., gain-.5, gain, gain+1.], faults)],
                faults=['not heating at expected rate'] if faulting else []))
    return results, dict(klipper_ref=contract.KLIPPER_REF, traces=traces)


def test_complete_official_evidence_is_required(generated):
    rows = copy.deepcopy(generated[2])
    results, traces = official_results(rows)
    assert contract.apply_results(rows, results, traces, None) == (True, None)
    assert all(r['status'] == 'PASS' for r in rows)


@pytest.mark.parametrize('mutation', ['missing', 'extra', 'invalid', 'truthy', 'control_accepts',
    'control_unrelated', 'control_exception', 'infra', 'empty', 'duplicate'])
def test_invalid_loader_evidence_never_passes(generated, mutation):
    rows = copy.deepcopy(generated[2])
    results, traces = official_results(rows)
    name, error = rows[0]['filename'], None
    if mutation == 'missing':
        del results[name]
    elif mutation == 'extra':
        results['unknown'] = {'valid': True}
    elif mutation == 'invalid':
        results[name]['valid'] = False
    elif mutation == 'truthy':
        results[name]['valid'] = 'true'
    elif mutation == 'control_accepts':
        results['negative-max-error']['valid'] = True
    elif mutation == 'control_unrelated':
        results['negative-max-error']['reason'] = "Option 'max_error' unexpected failure"
    elif mutation == 'control_exception':
        results['negative-max-error']['exception'] = 'RuntimeError'
    elif mutation == 'infra':
        error = 'Docker unavailable'
    elif mutation == 'empty':
        rows = []
    else:
        rows[1] = copy.deepcopy(rows[0])
    assert contract.apply_results(rows, results, traces, error)[0] is False


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'wrong_pin', 'time', 'gain',
    'missing_fault', 'unexpected_fault', 'wrong_fault', 'malformed'])
def test_incomplete_or_wrong_temperature_trace_is_rejected(generated, mutation):
    rows = copy.deepcopy(generated[2])
    results, payload = official_results(rows)
    traces = payload['traces']
    if mutation == 'missing':
        traces.pop()
    elif mutation == 'duplicate':
        traces[1] = copy.deepcopy(traces[0])
    elif mutation == 'wrong_pin':
        payload['klipper_ref'] = '0' * 40
    elif mutation == 'time':
        traces[0]['events'][-1]['time'] -= 1
    elif mutation == 'gain':
        traces[0]['gain_time'] = 1
    elif mutation == 'missing_fault':
        traces[0]['events'][-1]['faults'] = 0
    elif mutation == 'unexpected_fault':
        traces[1]['faults'] = ['not heating at expected rate']
    elif mutation == 'wrong_fault':
        traces[0]['faults'] = ['different shutdown']
    else:
        traces[0] = {}
    assert contract.apply_results(rows, results, payload, None)[0] is False


@pytest.mark.parametrize('error', [RuntimeError('explicit review'), GenerationError('unrelated failure')])
def test_unrelated_generation_exception_is_not_boundary_evidence(generated, tmp_path, error):
    with patch.object(contract, 'generate_config', side_effect=error):
        with pytest.raises(AssertionError):
            contract.replay_thermal(generated[2][0], contract.SOURCE, tmp_path)


def test_bypassed_review_cannot_produce_success(generated, tmp_path):
    with patch.object(contract, 'review_thermal_policy', return_value=None):
        with pytest.raises(AssertionError):
            contract.replay_thermal(generated[2][0], contract.SOURCE, tmp_path)


def test_wrong_recovered_artifact_guard_is_not_accepted(generated, tmp_path):
    with patch.object(contract, 'validate_board_electrical_artifact', return_value=None):
        with pytest.raises(AssertionError):
            contract.replay_thermal(generated[2][0], contract.SOURCE, tmp_path)


def test_source_drift_fails_before_review(generated, tmp_path):
    row = generated[2][0]
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config' / row['filename']).write_text('# changed', encoding='utf-8')
    with pytest.raises(AssertionError, match='Source drift'):
        contract.replay_thermal(row, tmp_path, tmp_path)


def test_control_copies_leave_generated_files_unchanged(generated, tmp_path):
    folder, _, records = generated
    for row in records:
        (tmp_path / row['config_path']).write_bytes((folder / row['config_path']).read_bytes())
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert len(contract.create_controls(records, tmp_path)) == 6
    assert all((tmp_path / k).read_bytes() == v for k, v in before.items())


def test_existing_directory_cannot_reuse_stale_results(tmp_path):
    with pytest.raises(FileExistsError):
        contract.execute(contract.SOURCE, tmp_path)
