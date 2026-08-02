"""Self-tests for the Docker-backed KACE configuration matrix."""

from __future__ import annotations

import itertools
from pathlib import Path
import tempfile
import unittest

from tests.matrix import run_matrix as matrix


class TestPairwiseSelection(unittest.TestCase):
    def test_every_factor_pair_is_covered(self):
        pools = list(matrix.FACTOR_VALUES.values())
        rows = matrix.pairwise_rows(pools)
        covered = set().union(*(matrix._pair_tokens(row) for row in rows))
        expected = set()
        for left in range(len(pools)):
            for right in range(left + 1, len(pools)):
                expected.update(
                    (left, lv, right, rv)
                    for lv, rv in itertools.product(pools[left], pools[right])
                )
        self.assertEqual(covered, expected)
        self.assertLess(len(rows), len(list(itertools.product(*pools))))

    def test_selection_and_ids_are_reproducible(self):
        first = matrix.build_cases("full")
        second = matrix.build_cases("full")
        self.assertEqual(first, second)
        self.assertEqual([case.case_id for case in first], [case.case_id for case in second])
        self.assertEqual(len({case.case_id for case in first}), len(first))


class TestCoverage(unittest.TestCase):
    def test_full_profile_covers_every_board_contract(self):
        expected = set(matrix.supported_boards())
        actual = {(case.mcu, case.board) for case in matrix.build_cases("full")}
        self.assertTrue(expected <= actual)

    def test_full_profile_covers_declared_factors(self):
        cases = matrix.build_cases("full")
        for factor, values in matrix.FACTOR_VALUES.items():
            self.assertEqual({getattr(case, factor) for case in cases} & set(values), set(values))

    def test_quick_profile_is_reduced_but_covers_all_probe_kinds(self):
        quick = matrix.build_cases("quick")
        full = matrix.build_cases("full")
        self.assertLess(len(quick), len(full))
        self.assertEqual({case.probe for case in quick}, set(matrix.FACTOR_VALUES["probe"]))
        self.assertEqual({case.display for case in quick}, set(matrix.FACTOR_VALUES["display"]))


class TestClassificationAndContracts(unittest.TestCase):
    def test_safe_rejection_is_never_pass(self):
        result, reason = matrix.classify(
            {"status": "expected_reject", "reason": "invalid geometry"}, None, None
        )
        self.assertEqual(result, matrix.FINAL_EXPECTED_REJECT)
        self.assertNotEqual(result, matrix.FINAL_PASS)
        self.assertEqual(reason, "invalid geometry")

    def test_generated_case_without_docker_is_infrastructure_error(self):
        result, _ = matrix.classify(
            {"status": "generated", "reason": "ok"}, None, "daemon unavailable"
        )
        self.assertEqual(result, matrix.FINAL_INFRA_ERROR)

    def test_docker_contract_is_immutable_and_offline_at_validation(self):
        dockerfile = (matrix.PROJECT_ROOT / "tests/matrix/Dockerfile").read_text(encoding="utf-8")
        source = Path(matrix.__file__).read_text(encoding="utf-8")
        self.assertIn(matrix.KLIPPER_REF, dockerfile)
        self.assertIn('test "$(git -C /opt/klipper rev-parse HEAD)" = "${KLIPPER_REF}"', dockerfile)
        self.assertIn('"--network", "none"', source)

    def test_markdown_report_contains_machine_result(self):
        fake_case = {
            "id": "case-id",
            "spec": {
                "board": "board", "mcu": "mcu", "kinematics": "cartesian",
                "bed": "standard", "homing": "origin_min", "probe": "none",
                "display": "none", "complexity": "minimal", "expected": "valid",
            },
            "config_path": "configs/case-id.cfg",
            "generation": {"status": "generated", "reason": "ok"},
            "klipper": {"valid": True, "reason": "loaded"},
            "result": matrix.FINAL_PASS,
            "reason": "loaded",
        }
        payload = {
            "schema_version": 1, "profile": "quick", "klipper_ref": matrix.KLIPPER_REF,
            "cases": [fake_case], "summary": {
                "total": 1, "generated": 1, matrix.FINAL_PASS: 1,
                matrix.FINAL_EXPECTED_REJECT: 0, matrix.FINAL_KACE_ERROR: 0,
                matrix.FINAL_KLIPPER_ERROR: 0, matrix.FINAL_INFRA_ERROR: 0,
            },
            "coverage": {"boards": ["board"], "mcus": ["mcu"],
                         "kinematics": ["cartesian"], "probes": ["none"]},
            "duration_seconds": 0.1,
        }
        report = matrix._report(payload)
        self.assertIn("**PASS**", report)
        self.assertIn(matrix.KLIPPER_REF, report)


class TestGenerationFlow(unittest.TestCase):
    def test_expected_invalid_cases_are_rejected_by_kace(self):
        rejects = [case for case in matrix.build_cases("quick") if case.expected == "reject"]
        with tempfile.TemporaryDirectory() as temp_dir:
            results = [matrix.generate_case(case, Path(temp_dir)) for case in rejects]
        self.assertTrue(results)
        self.assertTrue(all(result["status"] == "expected_reject" for result in results), results)


if __name__ == "__main__":
    unittest.main()
