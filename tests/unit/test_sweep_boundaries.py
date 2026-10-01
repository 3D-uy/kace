"""Replay all reviewed negative rows by class; attack the proof harness too."""
from pathlib import Path
from unittest.mock import patch

import pytest

from core.exceptions import GenerationError
from tests.sweep import boundary_contract as contract
from tests.sweep.result_codes import SweepResult
from tests.sweep import scope_inventory


@pytest.fixture(scope='module')
def reviewed():
    source = Path(__file__).resolve().parents[2] / '.klipper-contract-source'
    receipt, rows = contract.reviewed_boundaries(source)
    assert receipt['qualified_boards'] == []
    return source, rows


@pytest.mark.parametrize('kind', contract.CLASSES)
def test_complete_reviewed_class(reviewed, tmp_path, kind):
    source, rows = reviewed
    selected = [r for r in rows if r['headless_class'] == kind]
    assert len(selected) == contract.CLASS_COUNTS[kind]
    for row in selected:
        record = contract.verify_boundary(row, source, tmp_path)
        assert record['emitted_artifacts'] == []
        assert record['raw_code'] in (SweepResult.FAILURE, SweepResult.UNSUPPORTED)
        if row['classification'] == 'SOURCE_DEPENDENCY_BLOCKED':
            assert record['artifact_check'] and record['recovery_check']


RAW = '[printer]\nkinematics: cartesian\n'


def check_generation(tmp_path):
    return contract.generation_boundary('generic-test.cfg', RAW, tmp_path,
                                        'bed_circuit_absent', 'heater_pin')


@pytest.mark.parametrize('error', [RuntimeError('heater_pin'), ValueError('heater_pin'),
                                  GenerationError('unrelated dependency')])
def test_unrelated_or_untyped_failure_is_not_boundary_evidence(tmp_path, error):
    with patch.object(contract.sweep, 'generate_config', side_effect=error):
        with pytest.raises(AssertionError):
            check_generation(tmp_path)


def test_missing_rejection_is_not_boundary_evidence(tmp_path):
    with patch.object(contract.sweep, 'generate_config', return_value=None):
        with pytest.raises(AssertionError):
            check_generation(tmp_path)


@pytest.mark.parametrize('filename', ['printer.cfg', 'printer.cfg.provenance.json', 'unexpected.txt'])
def test_partial_output_before_rejection_fails(tmp_path, filename):
    def leak(*args, **kwargs):
        (tmp_path / filename).write_text('partial', encoding='utf-8')
        raise GenerationError('heater_pin')
    with patch.object(contract.sweep, 'generate_config', side_effect=leak):
        with pytest.raises(AssertionError, match='emitted artifacts'):
            check_generation(tmp_path)


def test_same_text_from_parser_does_not_substitute_for_generator(tmp_path):
    with patch.object(contract.sweep, 'parse_config', side_effect=GenerationError('heater_pin')):
        with pytest.raises(AssertionError, match='concrete generator rejection'):
            check_generation(tmp_path)


@pytest.mark.parametrize('call', [lambda: None, lambda: (_ for _ in ()).throw(GenerationError('other'))])
def test_artifact_guard_must_reject_for_expected_reason(call):
    with pytest.raises(AssertionError):
        contract.require_rejection(call, 'heater_pin')


def test_artifact_runtime_error_is_not_swallowed():
    with pytest.raises(RuntimeError):
        contract.require_rejection(lambda: (_ for _ in ()).throw(RuntimeError('heater_pin')), 'heater_pin')


def test_source_drift_after_inventory_is_rejected(reviewed, tmp_path):
    _, rows = reviewed
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config' / rows[0]['filename']).write_text(RAW, encoding='utf-8')
    with pytest.raises(AssertionError, match='Source changed'):
        contract.verify_boundary(rows[0], tmp_path, tmp_path)


@pytest.mark.parametrize('git_results, message', [(['0' * 40], 'revision'),
    ([contract.KLIPPER_REF, ' M config/example.cfg'], 'Dirty')])
def test_unreviewed_checkout_fails_before_inventory(git_results, message, tmp_path):
    with patch.object(scope_inventory.subprocess, 'check_output', side_effect=git_results), \
            patch.object(scope_inventory, 'verify_source_inventory') as inventory:
        with pytest.raises(scope_inventory.InventoryError, match=message):
            contract.reviewed_boundaries(tmp_path)
        inventory.assert_not_called()
