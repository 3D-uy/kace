"""Self-tests for the Docker-backed KACE configuration matrix."""

from __future__ import annotations

import itertools
from pathlib import Path
from unittest.mock import patch
from dataclasses import replace

from core.exceptions import GenerationError
from tests.matrix import cases as case_module
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
    def test_full_profile_enumerates_every_catalog_label(self):
        expected = set(matrix.supported_boards())
        actual = {(case.mcu, case.board) for case in matrix.build_cases("full")}
        self.assertTrue(expected <= actual)

    def test_every_catalog_label_has_a_positive_synthetic_case(self):
        expected = set(matrix.supported_boards())
        actual = {
            (case.mcu, case.board)
            for case in matrix.build_cases("full")
            if case.expected == "valid"
        }
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
        self.assertNotIn(matrix.KLIPPER_REF, dockerfile)
        self.assertIn("ARG KLIPPER_REF", dockerfile)
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
        self.assertIn("no physical board or MCU qualification", report)
        self.assertIn(matrix.KLIPPER_REF, report)


class TestGenerationFlow(unittest.TestCase):
    def test_expected_invalid_cases_are_rejected_by_kace(self):
        rejects = [case for case in matrix.build_cases("quick") if case.expected == "reject"]
        with tempfile.TemporaryDirectory() as temp_dir:
            results = [matrix.generate_case(case, Path(temp_dir)) for case in rejects]
        self.assertTrue(results)
        self.assertTrue(all(result["status"] == "expected_reject" for result in results), results)


class TestSyntheticSourceBoundary(unittest.TestCase):
    def test_fixture_identities_do_not_claim_reviewed_sources(self):
        from core.board_cooling import REVIEWED
        for case in matrix.build_cases("full"):
            name = case_module.synthetic_profile(case)
            self.assertTrue(name.startswith("kace-synthetic-factors-"))
            self.assertNotIn(name, REVIEWED)
            self.assertEqual(case_module._user_data(case)["board"], name)
            self.assertEqual(case_module._user_data(case)["printer_profile"], name)

    def test_counterfeit_reviewed_source_still_fails_before_writing(self):
        # Regression for the former fixture: synthetic pins under an official
        # cooling identity must fail, including in an otherwise negative row.
        cases = [case for case in matrix.build_cases("full") if case.board == "duet3-mini"]
        self.assertEqual({case.expected for case in cases}, {"valid", "reject"})
        for case in cases:
            with self.subTest(case=case.case_id), tempfile.TemporaryDirectory() as folder:
                with patch.object(case_module, "synthetic_profile", return_value="generic-duet3-mini.cfg"):
                    result = matrix.generate_case(case, Path(folder))
                self.assertEqual(result["status"], "kace_error", result)
                self.assertIn("cooling source changed", result["reason"])
                self.assertEqual(list(Path(folder).iterdir()), [])


class TestExpectedRejectionEvidence(unittest.TestCase):
    def display_case(self):
        return case_module.CaseSpec("skr-v1.4", "lpc1769", "cartesian",
            "standard", "origin_min", "none", "st7920", "minimal", "reject")

    def test_display_rows_reject_but_other_factors_still_generate(self):
        for profile in ("quick", "full"):
            cases = matrix.build_cases(profile)
            for case in cases:
                if case.display != "st7920":
                    continue
                self.assertEqual(case.expected, "reject")
                if case.probe != "dockable":
                    self.assertIn(replace(case, display="none", expected="valid"), cases)

    def test_unrelated_exception_is_not_a_safe_rejection(self):
        for error in (OSError("disk failure"), GenerationError("unrelated validation failure"),
                      RuntimeError("Unknown display hardware compatibility: test")):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as folder:
                with patch.object(case_module, "generate_config", side_effect=error):
                    result = matrix.generate_case(self.display_case(), Path(folder))
                self.assertEqual(result["status"], "kace_error", result)

    def test_expected_display_rejection_has_no_artifact(self):
        with tempfile.TemporaryDirectory() as folder:
            result = matrix.generate_case(self.display_case(), Path(folder))
            self.assertEqual(result["status"], "expected_reject", result)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_partial_publication_is_an_error_and_evidence_is_preserved(self):
        for suffix in ("", ".provenance.json"):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as folder:
                case = self.display_case()
                artifact = Path(folder) / (case.case_id + ".cfg" + suffix)
                def failing(*args, **kwargs):
                    artifact.write_text("partial output")
                    raise GenerationError("Unknown display hardware compatibility: test")
                with patch.object(case_module, "generate_config", side_effect=failing):
                    result = matrix.generate_case(case, Path(folder))
                self.assertEqual(result["status"], "kace_error", result)
                self.assertEqual(artifact.read_text(), "partial output")

    def test_unexpected_generation_remains_an_error(self):
        case = replace(self.display_case(), display="none")
        with tempfile.TemporaryDirectory() as folder:
            result = matrix.generate_case(case, Path(folder))
            self.assertEqual(result["status"], "unexpected_generation", result)


if __name__ == "__main__":
    unittest.main()
