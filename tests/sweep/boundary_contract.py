"""Concrete negative scenario proofs; never a waiver for the raw sweep.

Run through test_sweep_boundaries.py. These seven classes cover only the
reviewed rejection scenarios, not positive loads or physical board support.
"""
from collections import Counter
import contextlib
import hashlib
import io
import json
from pathlib import Path
from unittest.mock import patch

from core.board_auxiliary import (selected_board_electrical_source,
    validate_board_electrical_artifact, unresolved_electrical_dependencies)
from core.capabilities import NUMERIC_RULES, finite_number, validate_kinematics
from core.config_sections import section_identity
from core.exceptions import GenerationError
from core.pin_validator import _read_pin_config
from core.scraper import parse_config
from core.thermistor import validate_bed_circuit
from tests.klipper_contract import KLIPPER_REF
from tests.sweep import full_sweep_runner as sweep
from tests.sweep.result_codes import SweepResult
from tests.sweep.scope_inventory import load_inventory, verify_source_checkout

CLASSES = {
    'electrical_dependency_blocked': ('SOURCE_DEPENDENCY_BLOCKED', 'electrical dependencies'),
    'homing_dependency_blocked': ('SOURCE_DEPENDENCY_BLOCKED', 'homing_override'),
    'cooling_class_blocked': ('SOURCE_DEPENDENCY_BLOCKED', 'cooling'),
    'fan_options_unreviewed': ('SOURCE_DEPENDENCY_BLOCKED', 'tachometer_pin'),
    'bed_circuit_absent': ('GENERATION_INPUT_INCOMPLETE', 'heater_pin'),
    'unsupported_kinematics': ('KACE_CAPABILITY_LIMIT', 'kinematics'),
    'motion_policy_limit': ('KACE_CAPABILITY_LIMIT', 'max_velocity'),
}
CLASS_COUNTS = dict(zip(CLASSES, (21, 4, 2, 2, 6, 10, 2)))


def reviewed_boundaries(source):
    """Require a clean pinned checkout and the complete 192-source inventory."""
    receipt = verify_source_checkout(source)
    _, inventory = load_inventory()
    rows = [r for r in inventory.values() if r['classification'] in {
        'SOURCE_DEPENDENCY_BLOCKED', 'GENERATION_INPUT_INCOMPLETE', 'KACE_CAPABILITY_LIMIT'}]
    assert Counter(r['headless_class'] for r in rows) == CLASS_COUNTS, 'Boundary coverage changed'
    assert receipt['profile_count'] == 192
    return receipt, rows


def require_rejection(call, fragment):
    try:
        call()
    except GenerationError as exc:
        assert fragment.lower() in str(exc).lower(), str(exc)
        return str(exc)
    raise AssertionError('Boundary unexpectedly accepted: ' + fragment)


def generation_boundary(name, raw, folder, kind, fragment):
    """Observe the actual generator exception before the raw runner formats it."""
    assert not list(folder.iterdir()), 'Output directory must be empty'
    original = sweep.generate_config
    exceptions = []
    calls = []
    def observe(*args, **kwargs):
        calls.append(True)
        try:
            return original(*args, **kwargs)
        except Exception as exc:
            exceptions.append(exc)
            raise
    with patch.object(sweep, 'generate_config', side_effect=observe), contextlib.redirect_stdout(io.StringIO()):
        result, generated, _ = sweep._classify_config(name, raw, str(folder), without_display=True)
    assert not list(folder.iterdir()), 'Rejected scenario emitted artifacts'
    assert not generated
    assert fragment.lower() in result.detail.lower(), result.detail
    if kind == 'unsupported_kinematics':
        assert result.code == SweepResult.UNSUPPORTED and not calls
    else:
        assert result.code == SweepResult.FAILURE
        assert len(calls) == len(exceptions) == 1, 'No concrete generator rejection'
        assert isinstance(exceptions[0], GenerationError), repr(exceptions[0])
        assert fragment.lower() in str(exceptions[0]).lower()
    return dict(raw_code=result.code, raw_detail=result.detail, emitted_artifacts=[])


def verify_boundary(row, source, folder):
    """Check active source, real generation and applicable artifact/resume guards."""
    kind = row['headless_class']
    classification, fragment = CLASSES[kind]
    assert row['classification'] == classification
    name = row['filename']
    raw = (Path(source) / 'config' / name).read_text(encoding='utf-8')
    assert hashlib.sha256(raw.encode('utf-8')).hexdigest() == row['source_sha256_lf'], 'Source changed after inventory check'
    parsed = parse_config(raw, name)
    active = _read_pin_config(raw)[0]
    record = dict(row, official_source=f'https://github.com/Klipper3d/klipper/blob/{KLIPPER_REF}/config/{name}')
    record.update(generation_boundary(name, raw, folder, kind, fragment))
    if kind == 'electrical_dependency_blocked':
        dependencies = unresolved_electrical_dependencies(parsed)
        assert dependencies
        indexed = {section_identity(k): k for k in active}
        assert len(indexed) == len(active)
        record['active_dependencies'] = {indexed[k]: active[indexed[k]] for k in dependencies}
    elif kind == 'homing_dependency_blocked':
        assert 'homing_override' in active
        record['active_dependencies'] = {'homing_override': active['homing_override']}
    elif kind in ('cooling_class_blocked', 'fan_options_unreviewed'):
        fans = {k: v for k, v in active.items() if 'fan' in k.split()[0]}
        assert fans
        record['active_dependencies'] = fans
        if kind == 'fan_options_unreviewed':
            assert any(k.startswith('heater_fan ') and 'tachometer_pin' in v for k, v in fans.items())
    elif kind == 'bed_circuit_absent':
        assert not active.get('heater_bed', {}).get('heater_pin')
        record['active_dependencies'] = {'heater_bed': active.get('heater_bed')}
        record['boundary_check'] = require_rejection(lambda: validate_bed_circuit(active, required=True), fragment)
    elif kind == 'unsupported_kinematics':
        kinematics = active['printer']['kinematics']
        assert kinematics == 'delta'
        record['active_dependencies'] = {'printer': active['printer']}
        record['boundary_check'] = require_rejection(lambda: validate_kinematics(kinematics), fragment)
    else:
        velocity = active['printer']['max_velocity']
        maximum = NUMERIC_RULES['max_velocity'].maximum
        assert float(velocity) > maximum == 2000.
        record['active_dependencies'] = {'printer': active['printer']}
        record['boundary_check'] = require_rejection(lambda: finite_number('max_velocity', velocity, maximum=maximum), fragment)
    if classification == 'SOURCE_DEPENDENCY_BLOCKED':
        artifact_fragment = 'Replicape' if 'replicape' in parsed else fragment
        record['artifact_check'] = require_rejection(
            lambda: validate_board_electrical_artifact(parsed, raw), artifact_fragment)
        saved = {'workflow_checkpoint': {'wizard_data': {'board': name, 'board_raw_config': raw}}}
        def recovered_check():
            selected = selected_board_electrical_source(json.loads(json.dumps(saved)))
            validate_board_electrical_artifact(selected, raw)
        record['recovery_check'] = require_rejection(recovered_check, artifact_fragment)
    assert not list(folder.iterdir()), 'Boundary validation emitted artifacts'
    return record
