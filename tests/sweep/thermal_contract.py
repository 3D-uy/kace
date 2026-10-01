"""Portable explicit thermal-review scenarios; no automatic consent or heater IO.

Run: python -m tests.sweep.thermal_contract --artifacts <new-directory>
"""
import argparse
from collections import Counter
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
from unittest.mock import patch

from core.board_auxiliary import selected_board_electrical_source, validate_board_electrical_artifact
from core.firmware_workflow import persistable_wizard_data
from core.generator import generate_config
from core.heater_verification import _settings
from core.pin_validator import _read_pin_config
from core.thermal_review import RECEIPT
from core.wizard.steps.thermal import review_thermal_policy
from tests.klipper_contract import KLIPPER_REF
from tests.matrix.run_matrix import run_docker_validation
from tests.sweep import full_sweep_runner as sweep
from tests.sweep.boundary_contract import require_rejection as reject
from tests.sweep.scope_inventory import load_inventory, verify_source_checkout

SOURCE = Path(__file__).resolve().parents[2] / '.klipper-contract-source'
CONTROLS = {
    'defaults': ('', True, None),
    'lower-bounds': ('max_error: 0\nhysteresis: 0\nheating_gain: .1\ncheck_gain_time: 1', True, None),
    'negative-max-error': ('max_error: -1', False, "Option 'max_error' in section 'verify_heater heater_bed' must have minimum of 0.0"),
    'negative-hysteresis': ('hysteresis: -1', False, "Option 'hysteresis' in section 'verify_heater heater_bed' must have minimum of 0.0"),
    'zero-heating-gain': ('heating_gain: 0', False, "Option 'heating_gain' in section 'verify_heater heater_bed' must be above 0.0"),
    'short-gain-time': ('check_gain_time: .99', False, "Option 'check_gain_time' in section 'verify_heater heater_bed' must have minimum of 1.0"),
}


def replay_thermal(previous, source, folder):
    name = previous['filename']
    raw = (source / 'config' / name).read_text(encoding='utf-8')
    assert hashlib.sha256(raw.encode('utf-8')).hexdigest() == previous['source_sha256_lf'], 'Source drift'
    active = _read_pin_config(raw)[0]
    row = dict(previous, official_source=f'https://github.com/Klipper3d/klipper/blob/{KLIPPER_REF}/config/{name}')
    row['source_policy'] = active['verify_heater heater_bed']
    selected = {}
    original_files = {p.name: p.read_bytes() for p in folder.iterdir()}

    def reviewed_generation(board, user, **kwargs):
        user.update(board_parsed=board, board_raw_config=raw)
        original = copy.deepcopy(user)
        row['guards'] = {}
        target = Path(kwargs['output_path'])
        row['guards']['unreviewed'] = reject(lambda: generate_config(board, user, **kwargs), 'explicit review')
        assert not target.exists() and not Path(str(target) + '.provenance.json').exists()
        with patch.dict('os.environ', {'KACE_AUTO': '1'}), \
             patch('core.wizard.steps.thermal.yes_no', side_effect=AssertionError('Auto cannot ask or consent')):
            row['guards']['automatic'] = reject(lambda: review_thermal_policy(board, user), 'automatic mode')
        with patch.dict('os.environ', {'KACE_AUTO': '0'}), \
             patch('core.wizard.steps.thermal.yes_no', return_value=False) as declined:
            row['guards']['declined'] = reject(lambda: review_thermal_policy(board, user), 'Thermal')
            declined.assert_called_once()
        assert user == original and not target.exists()
        # Simulated test answer only. The actual UI still asks the user.
        with patch.dict('os.environ', {'KACE_AUTO': '0'}), \
             patch('core.wizard.steps.thermal.yes_no', return_value=True) as accepted, \
             patch('core.reconciler.write_text_atomically', side_effect=AssertionError('Preview must not write')):
            review_thermal_policy(board, user)
        accepted.assert_called_once()
        assert accepted.call_args.kwargs['default'] is False
        assert not target.exists()
        row['confirmation'] = copy.deepcopy(user[RECEIPT])
        with patch('core.wizard.steps.thermal.yes_no', side_effect=AssertionError('Unchanged receipt reused')):
            review_thermal_policy(board, user)
        changed = copy.deepcopy(user)
        changed['mcu_path'] = '/dev/serial/by-id/changed-test-fixture'
        row['guards']['changed_mcu'] = reject(lambda: generate_config(board, changed, **kwargs), 'explicit review')
        assert not target.exists()
        assert {p.name: p.read_bytes() for p in folder.iterdir()} == original_files
        result = generate_config(board, user, **kwargs)
        selected.update(copy.deepcopy(user))
        return result

    with contextlib.redirect_stdout(io.StringIO()), patch.object(sweep, 'generate_config', reviewed_generation):
        result, generated, warnings = sweep._classify_config(name, raw, str(folder), without_display=True)
    row.update(status=result.code, detail=result.detail, warnings=warnings)
    assert generated, row
    filename = name.replace('.cfg', '.out.cfg')
    text = (folder / filename).read_text(encoding='utf-8')
    rendered = _read_pin_config(text)[0]
    assert rendered['verify_heater heater_bed'] == row['source_policy']
    row['effective_policy'] = _settings('verify_heater heater_bed', rendered['verify_heater heater_bed'])
    saved = json.loads(json.dumps(persistable_wizard_data(selected)))
    context = selected_board_electrical_source({'workflow_checkpoint': {'wizard_data': saved}})
    validate_board_electrical_artifact(context, text)
    row['checkpoint_receipt_preserved'] = saved[RECEIPT] == row['confirmation']
    assert row['checkpoint_receipt_preserved']
    original_time = row['source_policy']['check_gain_time']
    row['guards']['artifact_policy_changed'] = reject(
        lambda: validate_board_electrical_artifact(context, text.replace('check_gain_time: ' + original_time, 'check_gain_time: 60')),
        'protection')
    heater_pin = rendered['heater_bed']['heater_pin']
    row['guards']['artifact_circuit_changed'] = reject(
        lambda: validate_board_electrical_artifact(context, text.replace('heater_pin: ' + heater_pin, 'heater_pin: PC99')),
        'Reviewed thermal hardware')
    row.update(config_path=filename, artifact_sha256=hashlib.sha256(text.encode('utf-8')).hexdigest())
    return row


def generate_thermal(source, folder):
    receipt = verify_source_checkout(source)
    _, inventory = load_inventory()
    rows = [r for r in inventory.values() if r['scenario'] == 'explicit_thermal_review']
    assert len(rows) == 2 and all(r['classification'] == 'LOAD_EVIDENCE' for r in rows)
    assert all(r['headless_class'] == 'thermal_policy_review_missing' for r in rows)
    assert not list(folder.iterdir()), 'Use a fresh output directory'
    records = [replay_thermal(r, source, folder) for r in rows]
    assert sorted(r['effective_policy']['check_gain_time'] for r in records) == [240., 600.]
    return receipt, records


def create_controls(records, folder):
    row = records[0]
    base = (folder / row['config_path']).read_text(encoding='utf-8')
    original = 'check_gain_time: ' + row['source_policy']['check_gain_time']
    assert base.count(original) == 1
    base = base.replace(original, '')
    cases = []
    for name, (options, _, _) in CONTROLS.items():
        filename = name + '.cfg'
        (folder / filename).write_text(base.replace('[verify_heater heater_bed]', '[verify_heater heater_bed]\n' + options), encoding='utf-8')
        cases.append(dict(id=name, config_path=filename, generation={'status': 'generated'}))
    return cases


def trace_specs(records):
    return [dict(config_path='defaults.cfg', gain_time=60.)] + [
        dict(config_path=r['config_path'], gain_time=r['effective_policy']['check_gain_time']) for r in records]


def valid_traces(payload, specs):
    try:
        return _valid_traces(payload, specs)
    except (AttributeError, KeyError, TypeError):
        return False


def _valid_traces(payload, specs):
    if payload.get('klipper_ref') != KLIPPER_REF:
        return False
    rows = payload.get('traces', [])
    expected = {(s['config_path'], scenario): s['gain_time'] for s in specs
                for scenario in ('not-heating', 'target-zero', 'at-target')}
    if len(expected) != 9 or len(rows) != 9 or {(r['file'], r['scenario']) for r in rows} != set(expected):
        return False
    for row in rows:
        gain = expected[(row['file'], row['scenario'])]
        if row['gain_time'] != gain or [e['time'] for e in row['events']] != [0., gain-.5, gain, gain+1.]:
            return False
        faulting = row['scenario'] == 'not-heating'
        if [e['faults'] for e in row['events']] != ([0, 0, 0, 1] if faulting else [0, 0, 0, 0]):
            return False
        if faulting:
            if len(row['faults']) != 1 or 'not heating at expected rate' not in row['faults'][0]:
                return False
        elif row['faults']:
            return False
    return True


def run_traces(folder, manifest):
    script = Path(__file__).with_name('thermal_traces.py').resolve()
    command = ['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'python',
        '--mount', f'type=bind,source={folder.resolve()},target=/matrix',
        '--mount', f'type=bind,source={script},target=/thermal_traces.py,readonly',
        f'kace-klipper-matrix:{KLIPPER_REF[:12]}', '/thermal_traces.py',
        f'/matrix/{manifest.name}', '/matrix/thermal-traces.json']
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', check=False)
        if result.returncode:
            return {}, result.stderr or result.stdout or 'Thermal traces failed'
        return json.loads((folder / 'thermal-traces.json').read_text(encoding='utf-8')), None
    except (OSError, ValueError) as exc:
        return {}, f'Thermal traces unavailable or invalid: {exc}'


def apply_results(records, results, traces, error):
    names = {r['filename'] for r in records}
    if len(records) != 2 or len(names) != 2 or any(r['status'] != 'GENERATED' for r in records):
        return False, 'Incomplete thermal generation coverage'
    if error or set(results) != names | set(CONTROLS):
        return False, error or 'Missing or extra official loader results'
    for name, (_, expected, reason) in CONTROLS.items():
        result = results[name]
        if result.get('valid') is not expected or (reason and (
                reason not in result.get('reason', '') or result.get('exception') != 'Error')):
            return False, f'Official numeric control failed: {name}'
    if not valid_traces(traces, trace_specs(records)):
        return False, 'Incomplete or incorrect official HeaterCheck traces'
    for row in records:
        row['klipper'] = results[row['filename']]
        row['status'] = 'PASS' if row['klipper'].get('valid') is True else 'FAILURE'
    return all(r['status'] == 'PASS' for r in records), None


def execute(source, folder):
    folder.mkdir(parents=True, exist_ok=False)
    receipt, records = generate_thermal(source, folder)
    cases = [dict(id=r['filename'], config_path=r['config_path'], generation={'status': 'generated'}) for r in records]
    cases += create_controls(records, folder)
    manifest = folder / 'manifest.json'
    manifest.write_text(json.dumps(dict(klipper_ref=KLIPPER_REF, qualified_boards=[], cases=cases,
        scope_inventory=receipt, thermal_traces=trace_specs(records)), indent=2), encoding='utf-8')
    results, error = run_docker_validation(folder, manifest)
    traces, trace_error = ({}, None) if error else run_traces(folder, manifest)
    successful, error = apply_results(records, results, traces, error or trace_error)
    report = dict(klipper_ref=KLIPPER_REF, source_inventory=receipt, profiles=records,
        qualified_boards=[], successful=successful, infrastructure_error=error,
        controls={n: results.get(n) for n in CONTROLS}, traces=traces,
        scope='Explicit test consent and synthetic HeaterCheck traces; no physical thermal qualification')
    (folder / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path, required=True)
    args = parser.parse_args()
    report = execute(SOURCE, args.artifacts)
    print(json.dumps(dict(successful=report['successful'], infrastructure_error=report['infrastructure_error'],
        counts=dict(Counter(r['status'] for r in report['profiles'])))))
    raise SystemExit(0 if report['successful'] else 1)

