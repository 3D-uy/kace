import json
import unittest

from core.workflow_outcome import (
    WorkflowOutcome,
    WorkflowResult,
    cancelled,
    failed,
    success,
)


class TestWorkflowOutcomeContract(unittest.TestCase):
    def test_only_success_has_zero_exit_code(self):
        self.assertEqual(WorkflowOutcome.SUCCESS.exit_code, 0)
        for outcome in WorkflowOutcome:
            if outcome is not WorkflowOutcome.SUCCESS:
                self.assertNotEqual(outcome.exit_code, 0)

    def test_exit_codes_are_stable_and_distinct(self):
        self.assertEqual(
            {outcome.name: outcome.exit_code for outcome in WorkflowOutcome},
            {
                "SUCCESS": 0,
                "CANCELLED": 2,
                "PRECONDITION_FAILED": 10,
                "GENERATION_FAILED": 20,
                "FIRMWARE_FAILED": 30,
                "DEPLOYMENT_FAILED": 40,
            },
        )

    def test_marker_is_versioned_machine_readable_json(self):
        result = WorkflowResult(WorkflowOutcome.DEPLOYMENT_FAILED, "upload failed")
        marker = result.marker()
        self.assertTrue(marker.startswith("=== KACE_RESULT: "))
        payload = json.loads(marker.removeprefix("=== KACE_RESULT: ").removesuffix(" ==="))
        self.assertEqual(payload["protocol"], "kace-outcome/v1")
        self.assertEqual(payload["outcome"], "DEPLOYMENT_FAILED")
        self.assertEqual(payload["exit_code"], 40)
        self.assertEqual(payload["detail"], "upload failed")

    def test_constructors_preserve_typed_semantics(self):
        self.assertTrue(success("done").ok)
        self.assertEqual(cancelled("stop").outcome, WorkflowOutcome.CANCELLED)
        self.assertEqual(
            failed(WorkflowOutcome.GENERATION_FAILED, "bad config").exit_code,
            20,
        )

    def test_failed_rejects_non_failure_outcomes(self):
        for outcome in (WorkflowOutcome.SUCCESS, WorkflowOutcome.CANCELLED):
            with self.assertRaises(ValueError):
                failed(outcome, "invalid")


if __name__ == "__main__":
    unittest.main()
