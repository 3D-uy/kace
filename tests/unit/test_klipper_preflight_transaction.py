"""The publication transaction must fail closed on preflight uncertainty."""
from dataclasses import replace
from unittest.mock import patch

import pytest

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.klipper_preflight import PreflightResult, plan_digest
from tests.unit.test_config_transaction import FakeTransport, GENERATED


@pytest.mark.parametrize("status", ["invalid", "unverified", "unexpected"])
def test_preflight_failure_precedes_review_and_writes(tmp_path, status):
    transport = FakeTransport({"printer.cfg": b"# original\n"})
    reviews = []
    transaction = ConfigDeploymentTransaction(
        transport, GENERATED, None, activation="none", snapshot_root=str(tmp_path),
        review=lambda item: reviews.append(item) or True,
    )
    with patch("core.klipper_preflight.validate_plan", return_value=PreflightResult(status, "test")):
        result = transaction.run()
    assert result.state is ConfigTransactionState.PRECONDITION_FAILED
    assert status in result.detail
    assert not reviews
    assert not any(call[0] == "upload" for call in transport.calls)


def test_preflight_digest_mismatch_precedes_review_and_writes(tmp_path):
    transport = FakeTransport({"printer.cfg": b"# original\n"})
    reviews = []
    transaction = ConfigDeploymentTransaction(
        transport, GENERATED, None, activation="none", snapshot_root=str(tmp_path),
        review=lambda item: reviews.append(item) or True,
    )
    with patch("core.klipper_preflight.validate_plan", return_value=PreflightResult("valid", "test", "wrong")):
        result = transaction.run()
    assert result.state is ConfigTransactionState.PRECONDITION_FAILED
    assert not reviews
    assert not any(call[0] == "upload" for call in transport.calls)


def test_review_cannot_replace_the_preflighted_plan(tmp_path):
    transport = FakeTransport({"printer.cfg": b"# original\n"})
    transaction = ConfigDeploymentTransaction(
        transport, GENERATED, None, activation="none", snapshot_root=str(tmp_path),
    )

    def review(_item):
        artifact = transaction.plan.artifacts[0]
        transaction.plan = replace(transaction.plan, artifacts=(
            replace(artifact, content=artifact.content + b"# changed\n"),
            *transaction.plan.artifacts[1:],
        ))
        return True

    transaction.review = review
    with patch("core.klipper_preflight.validate_plan", side_effect=lambda plan: PreflightResult("valid", "test", plan_digest(plan))):
        result = transaction.run()
    assert result.state is ConfigTransactionState.PRECONDITION_FAILED
    assert "changed after Klipper preflight" in result.detail
    assert not any(call[0] == "upload" for call in transport.calls)


def test_unreadable_plan_after_review_fails_closed(tmp_path):
    transport = FakeTransport({"printer.cfg": b"# original\n"})
    transaction = ConfigDeploymentTransaction(
        transport, GENERATED, None, activation="none", snapshot_root=str(tmp_path),
    )
    count = 0

    def digest(plan):
        nonlocal count
        count += 1
        if count > 1:
            raise ValueError("include no longer reviewable")
        return plan_digest(plan)

    with patch("core.klipper_preflight.validate_plan", side_effect=lambda plan: PreflightResult("valid", "test", plan_digest(plan))), \
         patch("core.klipper_preflight.plan_digest", side_effect=digest):
        result = transaction.run()
    assert result.state is ConfigTransactionState.PRECONDITION_FAILED
    assert "could not be revalidated" in result.detail
    assert not any(call[0] == "upload" for call in transport.calls)


def test_valid_preflight_allows_existing_transaction_flow(tmp_path):
    transport = FakeTransport({"printer.cfg": b"# original\n"})
    transaction = ConfigDeploymentTransaction(
        transport, GENERATED, None, activation="none", snapshot_root=str(tmp_path),
    )
    with patch("core.klipper_preflight.validate_plan", side_effect=lambda plan: PreflightResult("valid", "test", plan_digest(plan))):
        result = transaction.run()
    assert result.state is ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    assert any(call[0] == "upload" for call in transport.calls)
