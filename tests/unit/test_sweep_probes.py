"""Portable guided probe classes and fail-closed loader/result contracts."""
from collections import Counter
import copy
from pathlib import Path
from unittest.mock import patch

import pytest

from core.exceptions import GenerationError
from core.scraper import parse_config
from tests.sweep import probe_contract as contract


@pytest.fixture(scope='module')
def generated(tmp_path_factory):
    folder = tmp_path_factory.mktemp('guided-probes')
    receipt, records = contract.generate_probes(contract.SOURCE, folder)
    return folder, receipt, records


@pytest.mark.parametrize('kind,status,count', [('bltouch', 'GENERATED', 13),
    ('probe', 'GENERATED', 9), ('probe', 'NEEDS_USER_INPUT', 1)])
def test_all_reviewed_probe_classes(generated, kind, status, count):
    folder, receipt, records = generated
    assert receipt['profile_count'] == 192
    selected = [r for r in records if (r['probe_class'], r['status']) == (kind, status)]
    assert len(selected) == count
    for row in selected:
        if status == 'GENERATED':
            assert (folder / row['config_path']).is_file()
            assert (folder / (row['config_path'] + '.provenance.json')).is_file()
        else:
            assert row['missing'] == ['x_offset', 'y_offset']
            assert row['config_path'] is None
            assert not (folder / row['filename'].replace('.cfg', '.out.cfg')).exists()


@pytest.mark.parametrize('mode', ['missing', 'extra', 'invalid', 'truthy', 'infra', 'empty'])
def test_loader_failures_never_become_success(generated, mode):
    rows = copy.deepcopy(generated[2])
    results = {r['filename']: {'valid': True} for r in rows if r['status'] == 'GENERATED'}
    first = next(iter(results))
    error = None
    if mode == 'missing':
        del results[first]
    elif mode == 'extra':
        results['unknown'] = {'valid': True}
    elif mode == 'invalid':
        results[first]['valid'] = False
    elif mode == 'truthy':
        results[first]['valid'] = 'true'
    elif mode == 'infra':
        error = 'Docker unavailable'
    else:
        rows, results = [], {}
    assert contract.apply_loader_results(rows, results, error)[0] is False


def test_only_complete_official_results_award_pass(generated):
    rows = copy.deepcopy(generated[2])
    results = {r['filename']: {'valid': True} for r in rows if r['status'] == 'GENERATED'}
    assert contract.apply_loader_results(rows, results, None) == (True, None)
    assert Counter(r['status'] for r in rows) == {'PASS': 22, 'NEEDS_USER_INPUT': 1}


@pytest.mark.parametrize('error', [RuntimeError('probe'), GenerationError('unexpected probe failure')])
def test_guided_generation_failure_is_not_a_boundary_pass(generated, tmp_path, error):
    row = next(r for r in generated[2] if r['probe_class'] == 'bltouch')
    with patch.object(contract, 'generate_config', side_effect=error):
        with pytest.raises(AssertionError):
            contract.replay_probe(row, contract.SOURCE, tmp_path)


@pytest.mark.parametrize('error', [RuntimeError('no validated custom probe configuration'),
                                  GenerationError('unrelated hardware error')])
def test_missing_geometry_requires_concrete_generator_rejection(generated, tmp_path, error):
    row = next(r for r in generated[2] if r['status'] == 'NEEDS_USER_INPUT')
    with patch.object(contract, 'generate_config', side_effect=error):
        with pytest.raises(AssertionError):
            contract.replay_probe(row, contract.SOURCE, tmp_path)


@pytest.mark.parametrize('key', ['sensor_pin', 'control_pin', 'samples', 'speed', 'pin_move_time',
                                'probe_with_touch_mode', 'x_offset', 'set_output_mode'])
def test_preservation_proof_detects_missing_hardware_option(key):
    values = {'sensor_pin': '^PA1', 'control_pin': 'PA2', 'samples': '3', 'speed': '4',
              'pin_move_time': '0.5', 'probe_with_touch_mode': 'true', 'x_offset': '-30', 'set_output_mode': '5V'}
    with pytest.raises(AssertionError):
        contract.verify_preserved({key: values[key]}, {}, 'bltouch', '')


def test_preservation_proof_rejects_rewired_pin():
    with pytest.raises(AssertionError):
        contract.verify_preserved({'sensor_pin': '^PA1'}, {'sensor_pin': '^PA2'}, 'bltouch', '')


def test_new_guided_option_cannot_be_silently_dropped():
    original = dict(pin='PA1', x_offset='0', y_offset='0', z_offset='1', activate_gcode='CUSTOM')
    with pytest.raises(AssertionError, match='Unreviewed guided options'):
        contract.generic_answers(original)


def test_unequal_lift_speed_cannot_be_treated_as_default():
    original = dict(pin='PA1', x_offset='0', y_offset='0', z_offset='1', speed='3', lift_speed='5')
    with pytest.raises(AssertionError, match='Unreviewed guided options'):
        contract.generic_answers(original)


def test_changed_source_fails_before_generation(generated, tmp_path):
    row = generated[2][0]
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config' / row['filename']).write_text('# changed', encoding='utf-8')
    with pytest.raises(AssertionError, match='Source drift'):
        contract.replay_probe(row, tmp_path, tmp_path)


@pytest.mark.parametrize('answers', [[None], ['10', None]])
def test_missing_geometry_cancel_does_not_create_payload(generated, answers):
    row = next(r for r in generated[2] if r['status'] == 'NEEDS_USER_INPUT')
    raw = (contract.SOURCE / 'config' / row['filename']).read_text(encoding='utf-8')
    parsed = parse_config(raw, row['filename'])
    user = {'board': row['filename']}
    contract.choose_generic(parsed, user, row['source_probe'])
    with patch.object(contract.offsets, 'simple_input', side_effect=answers), \
            patch.object(contract.offsets, 'numbered_select') as confirm:
        assert contract.sensors._step_guided_custom_probe_offsets(user) == '__back__'
        confirm.assert_not_called()
    assert contract.sensors._step_custom_probe(user) == '__retry__'
    assert 'custom_probe' not in user


def test_existing_directory_cannot_reuse_stale_success(tmp_path):
    with pytest.raises(FileExistsError):
        contract.execute(contract.SOURCE, tmp_path)
