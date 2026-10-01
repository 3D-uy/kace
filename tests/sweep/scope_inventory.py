"""Require the complete reviewed source inventory before a raw config sweep.

Dispositions describe reviewed scenarios, not acceptable runtime outcomes.
In particular, no entry here turns a generation/loader failure into success.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess

from tests.klipper_contract import KLIPPER_REF

INVENTORY_PATH = Path(__file__).with_name('support_inventory.json')
_HEX = re.compile(r'[0-9a-f]{64}')
_ROUTES = {
    ('LOAD_EVIDENCE', 'baseline_without_display'): {'loaded_generated_configuration'},
    ('LOAD_EVIDENCE', 'explicit_probe_selection'): {'probe_selection_missing'},
    ('LOAD_EVIDENCE', 'explicit_motor_selection'): {'tmc_selection_missing', 'cooling_consumer_missing'},
    ('LOAD_EVIDENCE', 'explicit_thermal_review'): {'thermal_policy_review_missing'},
    ('NEEDS_USER_INPUT', 'explicit_probe_selection'): {'probe_selection_missing'},
    ('SOURCE_DEPENDENCY_BLOCKED', 'baseline_without_display'): {
        'electrical_dependency_blocked', 'homing_dependency_blocked',
        'cooling_class_blocked', 'fan_options_unreviewed'},
    ('GENERATION_INPUT_INCOMPLETE', 'baseline_without_display'): {'bed_circuit_absent'},
    ('KACE_CAPABILITY_LIMIT', 'baseline_without_display'): {'unsupported_kinematics', 'motion_policy_limit'},
}


class InventoryError(ValueError):
    """The source or review scope changed and needs explicit reconciliation."""


def verify_source_checkout(source):
    """Shared prerequisite for portable scenario proofs against official sources."""
    source = Path(source)
    def git(*args):
        return subprocess.check_output(['git', '-C', str(source), *args], text=True).strip()
    if git('rev-parse', 'HEAD') != KLIPPER_REF:
        raise InventoryError('Wrong Klipper revision')
    if git('status', '--porcelain'):
        raise InventoryError('Dirty Klipper source')
    return verify_source_inventory(source / 'config')


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InventoryError(f'Duplicate inventory key: {key}')
        result[key] = value
    return result


def load_inventory(path=INVENTORY_PATH):
    """Read a strict, revision-bound contract; reject unknown dispositions."""
    data = json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=_unique_object)
    if not isinstance(data, dict) or set(data) != {'schema_version', 'klipper_ref', 'scope', 'profiles'}:
        raise InventoryError('Invalid inventory document fields')
    if type(data['schema_version']) is not int or data['schema_version'] != 1:
        raise InventoryError('Unsupported inventory schema')
    if data['klipper_ref'] != KLIPPER_REF:
        raise InventoryError('Inventory does not match the pinned Klipper revision')
    if not isinstance(data['scope'], str) or not data['scope'].strip():
        raise InventoryError('Missing inventory scope')
    if not isinstance(data['profiles'], list) or not data['profiles']:
        raise InventoryError('Empty or invalid inventory')
    records = {}
    fields = {'filename', 'source_sha256_lf', 'classification', 'scenario', 'headless_class'}
    for row in data['profiles']:
        if not isinstance(row, dict) or set(row) != fields or not all(isinstance(v, str) for v in row.values()):
            raise InventoryError('Invalid inventory profile fields')
        name = row['filename']
        if not re.fullmatch(r'(?:generic|printer)-[A-Za-z0-9_.-]+\.cfg', name) or name in records:
            raise InventoryError(f'Invalid or duplicate profile: {name}')
        if not _HEX.fullmatch(row['source_sha256_lf']):
            raise InventoryError(f'Invalid source hash: {name}')
        route = (row['classification'], row['scenario'])
        if row['headless_class'] not in _ROUTES.get(route, set()):
            raise InventoryError(f'Unreviewed scenario/class: {name}')
        records[name] = dict(row)
    return data, records


def verify_source_inventory(config_dir, inventory_path=INVENTORY_PATH):
    """Check exact membership and normalized bytes, not merely total count."""
    data, records = load_inventory(inventory_path)
    paths = {p.name: p for p in Path(config_dir).glob('*.cfg')
             if p.name.startswith(('generic-', 'printer-'))}
    missing, added = sorted(records.keys() - paths.keys()), sorted(paths.keys() - records.keys())
    if missing or added:
        raise InventoryError(f'Source inventory changed: missing={missing}, added={added}')
    for name, row in records.items():
        raw = paths[name].read_text(encoding='utf-8')
        digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()
        if digest != row['source_sha256_lf']:
            raise InventoryError(f'Reviewed source bytes changed: {name}')
    return {
        'klipper_ref': data['klipper_ref'],
        'inventory_sha256': hashlib.sha256(Path(inventory_path).read_bytes()).hexdigest(),
        'profile_count': len(records),
        'source_sha256_lf': {name: row['source_sha256_lf'] for name, row in records.items()},
        'disposition_counts': dict(Counter(r['classification'] for r in records.values())),
        'reviewed_scenarios': dict(Counter(r['scenario'] for r in records.values())),
        'qualification': 'source-inventory-only',
        'qualified_boards': [],
    }
