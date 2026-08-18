import json
import os
from io import StringIO
import unittest
from unittest.mock import patch

from core.outcome_renderer import print_workflow_result, render_workflow_result
from core.translations import get_lang, set_lang
from core.workflow_outcome import (
    WorkflowOutcome,
    WorkflowResult,
    cancelled,
    failed,
    pending_activation,
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
                "DEPLOYED_PENDING_ACTIVATION": 41,
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
        for outcome in (
            WorkflowOutcome.SUCCESS,
            WorkflowOutcome.CANCELLED,
            WorkflowOutcome.DEPLOYED_PENDING_ACTIVATION,
        ):
            with self.assertRaises(ValueError):
                failed(outcome, "invalid")

    def test_cancelled_has_friendly_localized_human_output_without_protocol(self):
        previous = get_lang()
        try:
            set_lang("Español")
            rendered = render_workflow_result(cancelled("internal detail"), color=False)
        finally:
            set_lang(previous)
        self.assertIn("⚠ Instalación cancelada", rendered)
        self.assertIn("No se aplicaron cambios en la configuración.", rendered)
        self.assertIn("KACE finalizó de forma segura.", rendered)
        self.assertNotIn("internal detail", rendered)
        self.assertNotIn("KACE_RESULT", rendered)

    def test_pending_activation_is_a_warning_not_a_failure(self):
        rendered = render_workflow_result(pending_activation("restart needed"), color=False)
        self.assertIn("⚠ Installation pending activation", rendered)
        self.assertNotIn("failed", rendered.casefold())

    def test_real_failure_has_human_error_without_machine_protocol(self):
        rendered = render_workflow_result(
            failed(WorkflowOutcome.DEPLOYMENT_FAILED, "upload verification failed"),
            color=False,
        )
        self.assertIn("✖ Installation failed", rendered)
        self.assertIn("upload verification failed", rendered)
        self.assertNotIn("KACE_RESULT", rendered)

    def test_machine_marker_is_opt_in_and_contract_is_unchanged(self):
        result = cancelled("deployment cancelled after dry-run diff")
        with patch.dict(os.environ, {}, clear=True):
            human = StringIO()
            print_workflow_result(result, stream=human)
            self.assertNotIn("KACE_RESULT", human.getvalue())

        with patch.dict(os.environ, {"KACE_MACHINE_OUTPUT": "1"}, clear=True):
            diagnostic = StringIO()
            print_workflow_result(result, stream=diagnostic)
        self.assertIn(result.marker(), diagnostic.getvalue())


if __name__ == "__main__":
    unittest.main()
