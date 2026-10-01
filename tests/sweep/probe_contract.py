"""Guided probe scenarios, with explicit test answers and mandatory loader gate.

Run: python -m tests.sweep.probe_contract --artifacts <new-directory>
These are configuration scenarios, not physical probe or board qualification.
"""
import argparse
from collections import Counter
import contextlib
import hashlib
import io
import json
from pathlib import Path
from unittest.mock import patch

from core.custom_probe import GUIDED_PROBE_DEFAULTS
from core.exceptions import GenerationError
from core.generator import generate_config
from core.pin_validator import _read_pin_config
from core.probe_sampling import OPTIONS, sampling_value
from core import probe_offset_visualizer as offsets
from core.wizard.steps import sensors
from tests.klipper_contract import KLIPPER_REF
from tests.matrix.run_matrix import run_docker_validation
from tests.sweep import full_sweep_runner as sweep
from tests.sweep.scope_inventory import load_inventory, verify_source_checkout

SOURCE = Path(__file__).resolve().parents[2] / '.klipper-contract-source'
FLAGS = {'pin_up_touch_mode_reports_triggered', 'probe_with_touch_mode',
         'pin_up_reports_not_triggered', 'stow_on_each_sample'}


def reviewed_probes(source=SOURCE):
    receipt = verify_source_checkout(source)
    _, inventory = load_inventory()
    rows = [r for r in inventory.values() if r['scenario'] == 'explicit_probe_selection']
    assert len(rows) == 23
    assert Counter(r['classification'] for r in rows) == {'LOAD_EVIDENCE': 22, 'NEEDS_USER_INPUT': 1}
    return receipt, rows


def choose_offsets(user, original, custom):
    """Drive the real offset/confirmation UI using recorded source test answers."""
    answers = iter(original[k] for k in ('x_offset', 'y_offset'))
    def answer(*args, **kwargs):
        value = next(answers)
        assert kwargs['validate'](value) is True
        return value
    with patch.object(offsets, 'simple_input', side_effect=answer) as prompts, \
            patch.object(offsets, 'numbered_select', return_value='yes') as confirm:
        step = sensors._step_guided_custom_probe_offsets if custom else sensors._step_probe_offsets
        assert step(user) == 'done'
        assert prompts.call_count == 2 and confirm.call_count == 1


def choose_generic(parsed, user, original):
    with patch.object(sensors, 'numbered_select', return_value='custom'):
        assert sensors._step_probe(user) == 'custom'
    def manual(*args, **kwargs):
        assert '__manual__' in [c.get('value') for c in kwargs['choices'] if isinstance(c, dict)]
        return '__manual__'
    def pin(*args, **kwargs):
        assert kwargs['validate'](original['pin']) is True
        return original['pin']
    with patch.object(sensors, '_get_parsed', return_value=parsed), \
            patch.object(sensors, 'autocomplete_select', side_effect=manual), \
            patch.object(sensors, 'simple_input', side_effect=pin):
        assert sensors._step_custom_probe_pin(user) == 'done'
    for option, flag in (('pullup', '^'), ('inverted', '!')):
        with patch.object(sensors, 'yes_no', return_value=flag in original['pin'][:3]):
            assert sensors._step_custom_probe_signal_option(user, option) == 'done'


def require_missing_geometry(parsed, user, original):
    """No inferred offsets: cancel actual X entry and verify the payload retries."""
    assert not any(k in original for k in ('x_offset', 'y_offset'))
    choose_generic(parsed, user, original)
    with patch.object(offsets, 'simple_input', return_value=None) as prompt, \
            patch.object(offsets, 'numbered_select') as confirm:
        assert sensors._step_guided_custom_probe_offsets(user) == '__back__'
        assert prompt.call_count == 1
        confirm.assert_not_called()
    assert all(k not in user for k in ('custom_probe_x_offset', 'custom_probe_y_offset',
                                      'probe_x_offset', 'probe_y_offset'))
    assert sensors._step_custom_probe(user) == '__retry__'
    assert sensors._step_custom_probe_review(user) == '__retry__'
    assert 'custom_probe' not in user and 'custom_probe_settings' not in user


def generic_answers(original):
    assert all(k in original for k in ('pin', 'x_offset', 'y_offset', 'z_offset'))
    extra = set(original) - {'pin', 'x_offset', 'y_offset', 'z_offset', *GUIDED_PROBE_DEFAULTS}
    equivalent_lift = extra == {'lift_speed'} and float(original['lift_speed']) == float(original.get('speed', GUIDED_PROBE_DEFAULTS['speed']))
    assert not extra or equivalent_lift, f'Unreviewed guided options: {extra}'
    return {**{k: str(v) for k, v in GUIDED_PROBE_DEFAULTS.items()}, **original}


def verify_preserved(original, rendered, kind, content):
    """Every explicit source option is checked; calibration Z is named separately."""
    for key, value in original.items():
        if kind == 'bltouch' and key == 'z_offset':
            assert float(rendered[key]) == 0 and 'PROBE_CALIBRATE' in content
        elif key == 'lift_speed' and kind == 'probe':
            assert float(rendered.get(key, rendered['speed'])) == float(value)
        else:
            assert key in rendered, f'Missing {kind}.{key}'
            if key in OPTIONS:
                assert sampling_value(key, rendered[key]) == sampling_value(key, value), key
            elif key in ('x_offset', 'y_offset', 'z_offset', 'pin_move_time'):
                assert float(rendered[key]) == float(value), key
            elif key in FLAGS:
                assert rendered[key].lower() == value.lower(), key
            else:
                assert rendered[key] == value, key


def choose_probe(parsed, user, kind, original):
    """Shared guided choices for probe and motor scenarios; no guessed geometry."""
    answers = generic_answers(original) if kind == 'probe' else original
    if kind == 'bltouch':
        with patch.object(sensors, 'numbered_select', return_value='bltouch'):
            assert sensors._step_probe(user) == 'bltouch'
        choose_offsets(user, original, custom=False)
        with patch.object(sensors, '_get_parsed', return_value=parsed):
            assert not sensors._needs_bltouch_pins(user)
    else:
        choose_generic(parsed, user, original)
        choose_offsets(user, original, custom=True)
        for key, *_ in sensors.GUIDED_CUSTOM_PROBE_QUESTIONS:
            value = answers[key.removeprefix('custom_probe_')]
            def answer(*args, value=value, **kwargs):
                assert kwargs['validate'](value) is True
                return value
            with patch.object(sensors, 'simple_input', side_effect=answer):
                assert sensors._step_guided_custom_probe_value(user, key) == 'done'
        with patch.object(sensors, 'numbered_select', return_value=answers['samples_result']):
            assert sensors._step_custom_probe_samples_result(user) == 'done'
        assert sensors._step_custom_probe(user) == 'done'
        assert sensors._step_custom_probe_review(user) == 'done'
    return answers


def replay_probe(row, source, folder):
    name = row['filename']
    raw = (Path(source) / 'config' / name).read_text(encoding='utf-8')
    assert hashlib.sha256(raw.encode('utf-8')).hexdigest() == row['source_sha256_lf'], 'Source drift'
    active = _read_pin_config(raw)[0]
    assert ('probe' in active) != ('bltouch' in active)
    kind = 'bltouch' if 'bltouch' in active else 'probe'
    original = active[kind]
    record = dict(row, probe_class=kind, source_probe=original,
                  official_source=f'https://github.com/Klipper3d/klipper/blob/{KLIPPER_REF}/config/{name}')
    missing = [k for k in ('x_offset', 'y_offset') if k not in original]
    observed = []
    if missing:
        assert row['classification'] == 'NEEDS_USER_INPUT' and kind == 'probe'
        # Exercise both the unfinished wizard and an attempted direct generation.
        # The latter must reject the absent validated payload before writing.
        def incomplete(parsed, user, **kwargs):
            require_missing_geometry(parsed, user, original)
            try:
                return generate_config(parsed, user, **kwargs)
            except GenerationError as exc:
                observed.append(str(exc))
                raise
        before = set(folder.iterdir())
        with patch.object(sweep, 'generate_config', side_effect=incomplete), contextlib.redirect_stdout(io.StringIO()):
            result, generated, _ = sweep._classify_config(name, raw, str(folder), without_display=True)
        assert len(observed) == 1 and not generated and result.code == 'FAILURE', result.detail
        assert 'no validated custom probe configuration' in observed[0], observed
        assert set(folder.iterdir()) == before
        return dict(record, status='NEEDS_USER_INPUT', missing=missing, config_path=None,
                    generation_rejection=observed[0])

    assert row['classification'] == 'LOAD_EVIDENCE'
    answers = generic_answers(original) if kind == 'probe' else original
    def selected_generation(parsed, user, **kwargs):
        choose_probe(parsed, user, kind, original)
        observed.append(True)
        return generate_config(parsed, user, **kwargs)
    with patch.object(sweep, 'generate_config', side_effect=selected_generation), contextlib.redirect_stdout(io.StringIO()):
        result, generated, _ = sweep._classify_config(name, raw, str(folder), without_display=True)
    assert observed == [True] and generated and result.code == 'GENERATED', result.detail
    filename = name.replace('.cfg', '.out.cfg')
    content = (folder / filename).read_text(encoding='utf-8')
    sections = _read_pin_config(content)[0]
    assert sections['stepper_z']['endstop_pin'] == 'probe:z_virtual_endstop'
    assert ('probe' in sections) != ('bltouch' in sections)
    rendered = sections[kind]
    verify_preserved(original, rendered, kind, content)
    if kind == 'probe':
        for key in GUIDED_PROBE_DEFAULTS:
            assert sampling_value(key, rendered[key]) == sampling_value(key, answers[key])
    return dict(record, status='GENERATED', config_path=filename, rendered_probe=rendered,
                guided_answers=answers, artifact_sha256=hashlib.sha256(content.encode('utf-8')).hexdigest(),
                calibration='BLTouch Z requires PROBE_CALIBRATE; zero is not a measurement' if kind == 'bltouch'
                else 'Recorded source geometry is a test answer, not a physical measurement')


def generate_probes(source, folder):
    receipt, rows = reviewed_probes(source)
    assert not list(folder.iterdir()), 'Use a fresh output directory'
    records = [replay_probe(row, source, folder) for row in rows]
    assert Counter((r['probe_class'], r['status']) for r in records) == {
        ('bltouch', 'GENERATED'): 13, ('probe', 'GENERATED'): 9, ('probe', 'NEEDS_USER_INPUT'): 1}
    return receipt, records


def apply_loader_results(records, results, error):
    if Counter(r['status'] for r in records) != {'GENERATED': 22, 'NEEDS_USER_INPUT': 1}:
        return False, 'Incomplete guided probe generation coverage'
    expected = {r['filename'] for r in records if r['status'] == 'GENERATED'}
    if error or set(results) != expected:
        return False, error or 'Missing or extra official loader results'
    for row in records:
        if row['status'] == 'GENERATED':
            row['klipper'] = results[row['filename']]
            row['status'] = 'PASS' if row['klipper'].get('valid') is True else 'FAILURE'
    return all(r['status'] in ('PASS', 'NEEDS_USER_INPUT') for r in records), None


def execute(source, folder):
    folder.mkdir(parents=True, exist_ok=False)
    receipt, records = generate_probes(source, folder)
    cases = [{'id': r['filename'], 'config_path': r['config_path'], 'generation': {'status': 'generated'}}
             for r in records if r['status'] == 'GENERATED']
    manifest = folder / 'manifest.json'
    manifest.write_text(json.dumps(dict(klipper_ref=KLIPPER_REF, qualified_boards=[], cases=cases,
                                       scope_inventory=receipt), indent=2), encoding='utf-8')
    results, error = run_docker_validation(folder, manifest)
    successful, error = apply_loader_results(records, results, error)
    report = dict(klipper_ref=KLIPPER_REF, source_inventory=receipt, profiles=records,
                  qualified_boards=[], successful=successful, infrastructure_error=error,
                  scope='Guided probe scenarios only; explicit test answers, no physical qualification')
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
