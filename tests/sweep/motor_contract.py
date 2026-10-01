"""Guided motor/TMC class replays with official load and object-ownership gates.

Run: python -m tests.sweep.motor_contract --artifacts <new-directory>
Source settings are recorded test choices, not hardware tuning or calibration.
"""
import argparse
from collections import Counter
import contextlib
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
from unittest.mock import patch

from core.generator import generate_config
from core.pin_validator import _read_pin_config
from core.scraper import detect_driver_info
from core.wizard.steps import hardware
from tests.klipper_contract import KLIPPER_REF
from tests.matrix.run_matrix import run_docker_validation
from tests.sweep import full_sweep_runner as sweep
from tests.sweep.probe_contract import SOURCE, choose_probe, verify_preserved
from tests.sweep.scope_inventory import load_inventory, verify_source_checkout

MOTOR_FIELDS = ('step_pin', 'dir_pin', 'enable_pin', 'endstop_pin', 'microsteps',
                'full_steps_per_rotation', 'rotation_distance', 'gear_ratio', 'step_pulse_duration')
CONTROL_REASONS = {'control-lost-independent-endstop': 'Z endstop ownership',
                   'control-unknown-fan-consumer': 'steppers are unknown'}


def equivalent(a, b):
    if str(a).lower() in ('true', 'false'):
        return str(a).lower() == str(b).lower()
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return a == b


def compare_fields(source, rendered):
    comparisons = {}
    for section, fields in source.items():
        assert section in rendered, f'Missing section: {section}'
        comparisons[section] = {}
        for key, value in fields.items():
            actual = rendered[section].get(key)
            assert key in rendered[section] and equivalent(value, actual), f'Changed {section}.{key}: {value} -> {actual}'
            comparisons[section][key] = dict(source=value, rendered=actual, equivalent=True)
    return comparisons


def expected_objects(source):
    motors = sorted(k for k in source if k.startswith('stepper_') or k == 'extruder')
    z_motors = [k for k in motors if k.startswith('stepper_z')]
    virtual = source['stepper_z'].get('endstop_pin') == 'probe:z_virtual_endstop'
    ownership = {'stepper_z': [] if virtual else ['stepper_z']}
    for name in z_motors:
        if name == 'stepper_z':
            continue
        if source[name].get('endstop_pin'):
            ownership[name.removeprefix('stepper_')] = [name]
        elif not virtual:
            ownership['stepper_z'].append(name)
    def names(value):
        return sorted(x.strip() for x in value.split(',') if x.strip())
    fans = {k: dict(steppers=names(v['stepper']) if 'stepper' in v else motors,
                    heaters=names(v.get('heater', 'extruder')))
            for k, v in source.items() if k.startswith('controller_fan ')}
    return dict(z_endstops=ownership, z_steppers=z_motors, virtual_z=virtual, controller_fans=fans)


def replay_motor(row, source, folder):
    name = row['filename']
    raw = (Path(source) / 'config' / name).read_text(encoding='utf-8')
    assert hashlib.sha256(raw.encode('utf-8')).hexdigest() == row['source_sha256_lf'], 'Source drift'
    active = _read_pin_config(raw)[0]
    record = dict(row, official_source=f'https://github.com/Klipper3d/klipper/blob/{KLIPPER_REF}/config/{name}')
    observed = []
    def selected_generation(board, user, **kwargs):
        info = detect_driver_info(board, name)
        user.update(board_parsed=board, board_raw_config=raw)
        record['driver_answers'] = info
        if info.get('driver_type'):
            for step, value in ((hardware._step_driver_type, info['driver_type']),
                                (hardware._step_driver_mode, info['driver_mode'])):
                def choose(*args, value=value, **kw):
                    assert value in [c.value for c in kw['choices']]
                    return value
                with patch.object(hardware, '_get_parsed', return_value=board), \
                        patch.object(hardware, 'numbered_select', side_effect=choose):
                    assert step(user) == value
        count = str(sum(k.startswith('stepper_z') for k in active))
        with patch.object(hardware, 'numbered_select', return_value=count):
            assert hardware._step_z_motors(user) == count
        record['z_motors_answer'] = count
        with patch.object(hardware, 'numbered_select', side_effect=AssertionError('Unexpected socket prompt')):
            assert hardware._step_z_socket_assignment(user) in ('done', '__skip__')
        with patch.object(hardware, 'simple_input', side_effect=AssertionError('No invented current')):
            assert hardware._step_tmc_currents(user) == 'done'
        if active['stepper_z']['endstop_pin'].strip() == 'probe:z_virtual_endstop':
            kind = 'bltouch' if 'bltouch' in active else 'probe'
            answers = choose_probe(board, user, kind, active[kind])
            record['probe_answers'] = dict(kind=kind, answers=answers)
        else:
            record['probe_answers'] = dict(kind='none', scope='Physical Z endstop; optional probing not qualified')
        observed.append(True)
        return generate_config(board, user, **kwargs)
    with contextlib.redirect_stdout(io.StringIO()), patch.object(sweep, 'generate_config', selected_generation):
        result, generated, _ = sweep._classify_config(name, raw, str(folder), without_display=True)
    assert observed == [True] and generated and result.code == 'GENERATED', result.detail
    filename = name.replace('.cfg', '.out.cfg')
    content = (folder / filename).read_text(encoding='utf-8')
    rendered = _read_pin_config(content)[0]
    tmc = {k: v for k, v in active.items() if k.startswith('tmc')}
    motors = {k: {key: value for key, value in v.items() if key in MOTOR_FIELDS}
              for k, v in active.items() if k.startswith('stepper_') or k == 'extruder'}
    fans = {k: v for k, v in active.items() if k.startswith('controller_fan ')}
    assert {k for k in rendered if k.startswith('tmc')} == set(tmc), 'Unexpected TMC inventory'
    assert {k for k in rendered if k.startswith('stepper_') or k == 'extruder'} == set(motors), 'Unexpected motor inventory'
    record['tmc_comparisons'] = compare_fields(tmc, rendered)
    record['motor_comparisons'] = compare_fields(motors, rendered)
    record['fan_comparisons'] = compare_fields(fans, rendered)
    if record['probe_answers']['kind'] != 'none':
        kind = record['probe_answers']['kind']
        verify_preserved(active[kind], rendered[kind], kind, content)
    record.update(status='GENERATED', config_path=filename, expected_objects=expected_objects(active),
                  artifact_sha256=hashlib.sha256(content.encode('utf-8')).hexdigest())
    return record


def generate_motors(source, folder):
    receipt = verify_source_checkout(source)
    _, inventory = load_inventory()
    rows = [r for r in inventory.values() if r['scenario'] == 'explicit_motor_selection']
    assert len(rows) == 6 and all(r['classification'] == 'LOAD_EVIDENCE' for r in rows)
    assert Counter(r['headless_class'] for r in rows) == {'tmc_selection_missing': 5, 'cooling_consumer_missing': 1}
    assert not list(folder.iterdir()), 'Use a fresh output directory'
    records = [replay_motor(row, source, folder) for row in rows]
    assert Counter(r['driver_answers']['driver_mode'] for r in records) == {'UART': 4, 'SPI': 1, None: 1}
    return receipt, records


def run_object_validation(folder, manifest):
    image = f'kace-klipper-matrix:{KLIPPER_REF[:12]}'
    script = Path(__file__).with_name('motor_objects.py').resolve()
    command = ['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'python',
               '--mount', f'type=bind,source={folder.resolve()},target=/matrix',
               '--mount', f'type=bind,source={script},target=/motor_objects.py,readonly',
               image, '/motor_objects.py', f'/matrix/{manifest.name}', '/matrix/motor-objects.json']
    try:
        run = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', check=False)
        if run.returncode:
            return {}, run.stderr or run.stdout or 'Object validator failed'
        payload = json.loads((folder / 'motor-objects.json').read_text(encoding='utf-8'))
        assert payload['klipper_ref'] == KLIPPER_REF
        return payload['results'], None
    except (OSError, ValueError, KeyError, AssertionError) as exc:
        return {}, f'Object validator unavailable or invalid: {exc}'


def object_controls(records, folder):
    """Two semantic class controls; neither modifies a generated scenario file."""
    independent = [r for r in records if 'z1' in r['expected_objects']['z_endstops']]
    explicit_fan = [r for r in records if any('stepper' in fields
                    for fields in r['fan_comparisons'].values())]
    assert len(independent) == len(explicit_fan) == 1
    specs = [('control-lost-independent-endstop', independent[0], 'stepper_z1', 'endstop_pin', ''),
             ('control-unknown-fan-consumer', explicit_fan[0],
              next(k for k, v in explicit_fan[0]['fan_comparisons'].items() if 'stepper' in v),
              'stepper', 'stepper: stepper_nonexistent')]
    controls = []
    for name, row, section, field, replacement in specs:
        text = (folder / row['config_path']).read_text(encoding='utf-8')
        pattern = r'(?ms)(^\[' + re.escape(section) + r'\][^\n]*\n)(.*?)(?=^\[|\Z)'
        section_match = re.search(pattern, text)
        assert section_match is not None
        body, count = re.subn(r'(?m)^' + re.escape(field) + r'\s*:.*$', replacement, section_match[2])
        assert count == 1
        altered = text[:section_match.start(2)] + body + text[section_match.end(2):]
        filename = name + '.cfg'
        (folder / filename).write_text(altered, encoding='utf-8')
        controls.append(dict(id=name, config_path=filename, expected_objects=row['expected_objects']))
    return controls


def valid_controls(results):
    return set(results) == set(CONTROL_REASONS) and all(
        isinstance(results[name], dict) and results[name].get('valid') is False
        and reason in results[name].get('reason', '') for name, reason in CONTROL_REASONS.items())


def apply_results(records, loaded, objects, error):
    expected = {r['filename'] for r in records}
    if len(records) != len(expected) or len(expected) != 6 or any(r['status'] != 'GENERATED' for r in records):
        return False, 'Incomplete motor generation coverage'
    if error or set(loaded) != expected or set(objects) != expected:
        return False, error or 'Missing or extra official results'
    for row in records:
        row['klipper'] = loaded[row['filename']]
        row['objects'] = objects[row['filename']]
        correct = row['klipper'].get('valid') is True and row['objects'].get('valid') is True
        correct = correct and all(row['objects'].get(k) == v for k, v in row['expected_objects'].items())
        row['status'] = 'PASS' if correct else 'FAILURE'
    return all(r['status'] == 'PASS' for r in records), None


def execute(source, folder):
    folder.mkdir(parents=True, exist_ok=False)
    receipt, records = generate_motors(source, folder)
    cases = [dict(id=r['filename'], config_path=r['config_path'], generation={'status': 'generated'},
                  expected_objects=r['expected_objects']) for r in records]
    controls = object_controls(records, folder)
    manifest = folder / 'manifest.json'
    manifest.write_text(json.dumps(dict(klipper_ref=KLIPPER_REF, qualified_boards=[], cases=cases,
                                       scope_inventory=receipt, object_controls=controls), indent=2), encoding='utf-8')
    loaded, error = run_docker_validation(folder, manifest)
    objects, object_error = ({}, None) if error else run_object_validation(folder, manifest)
    control_results = {name: objects.get(name) for name in CONTROL_REASONS}
    if not error and not object_error and not valid_controls(control_results):
        object_error = 'Official semantic controls failed or were not executed'
    objects = {k: v for k, v in objects.items() if k not in CONTROL_REASONS}
    successful, error = apply_results(records, loaded, objects, error or object_error)
    report = dict(klipper_ref=KLIPPER_REF, source_inventory=receipt, profiles=records,
                  qualified_boards=[], successful=successful, infrastructure_error=error,
                  object_controls=control_results,
                  scope='Motor/TMC guided scenarios; source choices, no physical tuning or MCU connection')
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
