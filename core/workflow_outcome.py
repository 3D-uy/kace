"""Typed terminal outcomes for the top-level KACE workflow.

The CLI, installer, and bootstrap share the numeric exit-code contract below.
Only ``SUCCESS`` maps to zero; cancellation is intentionally non-success so an
installer cannot mistake an incomplete interactive workflow for provisioning.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum


class WorkflowOutcome(Enum):
    SUCCESS = 0
    CANCELLED = 2
    PRECONDITION_FAILED = 10
    GENERATION_FAILED = 20
    FIRMWARE_FAILED = 30
    DEPLOYMENT_FAILED = 40

    @property
    def exit_code(self) -> int:
        return int(self.value)


@dataclass(frozen=True)
class WorkflowResult:
    outcome: WorkflowOutcome
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome is WorkflowOutcome.SUCCESS

    @property
    def exit_code(self) -> int:
        return self.outcome.exit_code

    def marker(self) -> str:
        payload = {
            "protocol": "kace-outcome/v1",
            "outcome": self.outcome.name,
            "exit_code": self.exit_code,
            "detail": self.detail,
        }
        return f"=== KACE_RESULT: {json.dumps(payload, separators=(',', ':'))} ==="


def success(detail: str = "") -> WorkflowResult:
    return WorkflowResult(WorkflowOutcome.SUCCESS, detail)


def cancelled(detail: str = "") -> WorkflowResult:
    return WorkflowResult(WorkflowOutcome.CANCELLED, detail)


def failed(outcome: WorkflowOutcome, detail: str) -> WorkflowResult:
    if outcome in (WorkflowOutcome.SUCCESS, WorkflowOutcome.CANCELLED):
        raise ValueError("failed() requires a failure outcome")
    return WorkflowResult(outcome, detail)
