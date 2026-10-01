"""Scope metadata cannot silently hide added, missing, or changed sources."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tests.sweep.scope_inventory import InventoryError, load_inventory, verify_source_inventory
from tests.klipper_contract import KLIPPER_REF


class ScopeInventoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = self.root / 'config'
        self.config.mkdir()
        self.inventory = self.root / 'inventory.json'
        self.raw = '[printer]\nkinematics: cartesian\n'
        (self.config / 'generic-example.cfg').write_text(self.raw, encoding='utf-8')
        self.data = {
            'schema_version': 1, 'klipper_ref': KLIPPER_REF, 'scope': 'Synthetic contract test.',
            'profiles': [{'filename': 'generic-example.cfg',
                          'source_sha256_lf': hashlib.sha256(self.raw.encode()).hexdigest(),
                          'classification': 'LOAD_EVIDENCE', 'scenario': 'baseline_without_display',
                          'headless_class': 'loaded_generated_configuration'}],
        }

    def verify(self):
        self.inventory.write_text(json.dumps(self.data), encoding='utf-8')
        return verify_source_inventory(self.config, self.inventory)

    def test_valid_inventory_is_not_board_qualification(self):
        result = self.verify()
        self.assertEqual(result['profile_count'], 1)
        self.assertEqual(result['qualification'], 'source-inventory-only')
        self.assertEqual(result['qualified_boards'], [])
        self.assertEqual(result['inventory_sha256'], hashlib.sha256(self.inventory.read_bytes()).hexdigest())

    def test_added_profile_cannot_be_ignored(self):
        (self.config / 'printer-added.cfg').write_text(self.raw, encoding='utf-8')
        with self.assertRaisesRegex(InventoryError, 'added=.*printer-added'):
            self.verify()

    def test_missing_profile_cannot_reduce_coverage(self):
        (self.config / 'generic-example.cfg').unlink()
        with self.assertRaisesRegex(InventoryError, 'missing=.*generic-example'):
            self.verify()

    def test_same_cardinality_does_not_allow_substitution(self):
        (self.config / 'generic-example.cfg').rename(self.config / 'printer-replacement.cfg')
        with self.assertRaisesRegex(InventoryError, 'Source inventory changed'):
            self.verify()

    def test_semantic_source_change_requires_review(self):
        (self.config / 'generic-example.cfg').write_text(self.raw.replace('cartesian', 'corexy'), encoding='utf-8')
        with self.assertRaisesRegex(InventoryError, 'Reviewed source bytes changed'):
            self.verify()

    def test_only_newline_representation_is_normalized(self):
        (self.config / 'generic-example.cfg').write_bytes(self.raw.replace('\n', '\r\n').encode())
        self.assertEqual(self.verify()['profile_count'], 1)
        (self.config / 'generic-example.cfg').write_text(self.raw + '# additional source text\n', encoding='utf-8')
        with self.assertRaises(InventoryError):
            self.verify()

    def test_non_profile_upstream_files_are_outside_enumeration(self):
        (self.config / 'sample-macros.cfg').write_text('# unrelated sample', encoding='utf-8')
        self.assertEqual(self.verify()['profile_count'], 1)

    def test_duplicate_profile_cannot_hide_a_missing_one(self):
        self.data['profiles'].append(dict(self.data['profiles'][0]))
        with self.assertRaisesRegex(InventoryError, 'duplicate profile'):
            self.verify()

    def test_duplicate_json_keys_are_rejected(self):
        self.inventory.write_text('{"schema_version": 1, "schema_version": 1}', encoding='utf-8')
        with self.assertRaisesRegex(InventoryError, 'Duplicate inventory key'):
            load_inventory(self.inventory)

    def test_wrong_revision_is_not_accepted(self):
        self.data['klipper_ref'] = '0' * 40
        with self.assertRaisesRegex(InventoryError, 'pinned Klipper revision'):
            self.verify()

    def test_empty_inventory_is_not_a_success(self):
        self.data['profiles'] = []
        with self.assertRaisesRegex(InventoryError, 'Empty or invalid'):
            self.verify()

    def test_unknown_schema_or_fields_require_review(self):
        for mutation in ({'schema_version': True}, {'schema_version': 2}, {'waive_failures': True}):
            with self.subTest(mutation=mutation):
                original = dict(self.data)
                self.data.update(mutation)
                with self.assertRaises(InventoryError):
                    self.verify()
                self.data = original

    def test_invalid_row_contracts_are_rejected(self):
        for mutation in ({'filename': '../generic-example.cfg'}, {'filename': 'sample-example.cfg'},
                         {'source_sha256_lf': 'invalid'}, {'classification': 'ALLOW_ANY_FAILURE'},
                         {'scenario': 'guess_hardware'}, {'headless_class': 'bed_circuit_absent'},
                         {'scenario': None}, {'ignore_loader': True}):
            with self.subTest(mutation=mutation):
                original = dict(self.data['profiles'][0])
                self.data['profiles'][0].update(mutation)
                with self.assertRaises(InventoryError):
                    self.verify()
                self.data['profiles'][0] = original

    def test_blocked_source_is_only_a_disposition_not_a_pass(self):
        self.data['profiles'][0].update(classification='SOURCE_DEPENDENCY_BLOCKED',
                                       headless_class='electrical_dependency_blocked')
        result = self.verify()
        self.assertEqual(result['disposition_counts'], {'SOURCE_DEPENDENCY_BLOCKED': 1})
        self.assertEqual(result['qualified_boards'], [])
        self.assertNotIn('successful', result)

    def test_packaged_inventory_contains_all_reviewed_scenarios(self):
        data, rows = load_inventory()
        self.assertEqual(len(rows), 192)
        self.assertEqual(data['klipper_ref'], KLIPPER_REF)
        self.assertEqual({row['scenario'] for row in rows.values()}, {
            'baseline_without_display', 'explicit_probe_selection',
            'explicit_motor_selection', 'explicit_thermal_review'})


if __name__ == '__main__':
    unittest.main()
