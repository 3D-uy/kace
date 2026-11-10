"""Validation may create files, but must not mutate its source artifacts."""
import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from tests.matrix import run_matrix as matrix
from tests.unit.test_klipper_fan_registry_validation import harness


@pytest.fixture
def artifacts(tmp_path):
    (tmp_path/'configs').mkdir()
    (tmp_path/'configs/printer.cfg').write_text('original cfg', encoding='utf-8')
    manifest = tmp_path/'manifest.generated.json'
    manifest.write_text('{}', encoding='utf-8')
    return tmp_path, manifest


def docker_result(monkeypatch, effect):
    monkeypatch.setattr(matrix.shutil, 'which', lambda _: 'docker')
    def run(command, cwd):
        if command[1] == 'run':
            mount = next(arg for arg in command if arg.startswith('type=bind,source='))
            staged = Path(mount.split('source=', 1)[1].split(',target=', 1)[0])
            effect(staged)
        return CompletedProcess(command, 0, '', '')
    monkeypatch.setattr(matrix, '_run', run)


def write_result(folder):
    payload = {'klipper_ref': matrix.KLIPPER_REF, 'results': {'sample': {'valid': True}}}
    (folder/'klipper-results.json').write_text(json.dumps(payload), encoding='utf-8')


def test_constructor_created_file_stays_outside_original_artifacts(artifacts, monkeypatch):
    folder, manifest = artifacts
    def effect(staged):
        (staged/'created-by-constructor.cfg').write_text('side effect', encoding='utf-8')
        write_result(staged)
    docker_result(monkeypatch, effect)
    results, error = matrix.run_docker_validation(folder, manifest)
    assert error is None and results['sample']['valid']
    assert not (folder/'created-by-constructor.cfg').exists()
    assert (folder/'configs/printer.cfg').read_text() == 'original cfg'
    assert json.loads((folder/'klipper-results.json').read_text())['results'] == results


@pytest.mark.parametrize('operation', ['overwrite', 'delete'])
def test_altered_staged_input_is_unverified_and_original_is_preserved(artifacts, monkeypatch, operation):
    folder, manifest = artifacts
    def effect(staged):
        target = staged/'configs/printer.cfg'
        if operation == 'overwrite':
            target.write_text('changed by constructor', encoding='utf-8')
        else:
            target.unlink()
        write_result(staged)
    docker_result(monkeypatch, effect)
    results, error = matrix.run_docker_validation(folder, manifest)
    assert results == {} and 'changed an input' in error
    assert (folder/'configs/printer.cfg').read_text() == 'original cfg'


def test_previous_result_cannot_satisfy_a_run_that_produced_none(artifacts, monkeypatch):
    folder, manifest = artifacts
    write_result(folder)
    before = (folder/'klipper-results.json').read_bytes()
    docker_result(monkeypatch, lambda _: None)
    results, error = matrix.run_docker_validation(folder, manifest)
    assert results == {} and 'Invalid Docker result' in error
    assert (folder/'klipper-results.json').read_bytes() == before


def test_unavailable_loader_capability_is_not_a_klipper_rejection():
    result, reason = matrix.classify({'status': 'generated'},
        {'valid': False, 'infrastructure_error': 'requires an active reactor', 'reason': 'wrapped error'}, None)
    assert result == matrix.FINAL_INFRA_ERROR
    assert reason == 'requires an active reactor'


def test_constructor_requiring_reactor_is_unverified_even_when_error_is_wrapped(harness, tmp_path):
    def constructor():
        try:
            harness.reactor.pause(1e16)
        except Exception:
            raise ValueError('Unable to parse existing variable file')
    harness.printer._read_config.side_effect = constructor
    result = harness.module.validate_config(tmp_path/'printer.cfg')
    assert not result['valid'] and result['stage'] == 'object_load'
    assert result['checks'] == []
    assert 'reactor' in result['infrastructure_error']
    harness.reactor.run.assert_not_called()
    harness.printer.send_event.assert_called_once_with('klippy:disconnect')


def test_real_configuration_error_keeps_its_existing_classification(harness, tmp_path):
    harness.printer._read_config.side_effect = ValueError('unused option')
    result = harness.module.validate_config(tmp_path/'printer.cfg')
    assert not result['valid'] and 'infrastructure_error' not in result
    assert result['reason'] == 'unused option'


def test_swallowed_pause_failure_cannot_be_reported_as_valid(harness, tmp_path):
    def constructor():
        try:
            harness.reactor.pause(1e16)
        except RuntimeError:
            pass
    harness.printer._read_config.side_effect = constructor
    result = harness.module.validate_config(tmp_path/'printer.cfg')
    assert not result['valid'] and result['stage'] == 'object_load'
    assert result['checks'] == [] and result['infrastructure_error']
