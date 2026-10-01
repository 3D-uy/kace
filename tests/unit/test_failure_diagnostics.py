"""Observed deployment failures must not become diagnoses of the Linux host."""
from unittest.mock import Mock, patch

import pytest

from core.deployer import _preflight_check, deploy_moonraker
from core.moonraker import check_klipper_ready
from core.workflow_outcome import WorkflowOutcome


def test_structural_rejection_reports_local_evidence_without_host_cause(tmp_path, capsys):
    target = tmp_path / "printer.cfg"
    target.write_text("[gcode_macro CANCEL_PRINT]\ngcode: M112\n", encoding="utf-8")
    consent = Mock(return_value=True)
    with patch("core.firmware_workflow.enforce_deployment_invariants"), \
         patch("core.pin_validator.validate_pins_for_mcu") as pins:
        assert _preflight_check(str(target), {}, consent) is False
    output = capsys.readouterr().out
    assert "Pre-flight check FAILED" in output
    assert "missing required section [mcu]" in output
    assert "missing required section [printer]" in output
    assert "not uploaded" in output
    assert "host status" in output
    assert not any(term in output.lower() for term in ("oom", "restart-loop", "lock up", "low-memory"))
    pins.assert_not_called()
    consent.assert_not_called()


@pytest.mark.parametrize("detail", ["HTTP 401: Unauthorized", "HTTP 503: Service unavailable", "Connection refused"])
def test_moonraker_probe_failure_retains_api_detail_without_declaring_host_offline(detail):
    with patch("core.config_transaction.local_moonraker_available", return_value=False), \
         patch("core.menu.simple_input", side_effect=["pi.local", "7125", ""]), \
         patch("core.menu.yes_no", return_value=False), \
         patch("core.moonraker.check_moonraker", return_value=(False, detail)), \
         patch("core.deployer._run_config_transaction") as deploy:
        result = deploy_moonraker({})
    assert result.outcome is WorkflowOutcome.DEPLOYMENT_FAILED
    assert result.detail == f"Moonraker check failed: {detail}"
    deploy.assert_not_called()


@pytest.mark.parametrize("detail", ["HTTP 401: Unauthorized", "HTTP 503: Service unavailable", "Connection refused"])
def test_readiness_request_failure_is_not_a_klipper_or_host_state(detail):
    with patch("core.moonraker._get", return_value=(False, detail, {})):
        ok, message = check_klipper_ready("pi.local", 7125)
    assert not ok
    assert message == f"Moonraker /printer/info request failed: {detail}"


@pytest.mark.parametrize("state", ["error", "shutdown", "startup", "disconnected"])
def test_reported_klipper_state_and_message_remain_distinct_from_api_failure(state):
    with patch("core.moonraker._get", return_value=(True, "OK", {
        "result": {"state": state, "state_message": "Observed Klipper detail"},
    })):
        ok, message = check_klipper_ready("pi.local", 7125)
    assert not ok
    assert message == f"state is '{state}' (Observed Klipper detail)"


def test_only_ready_is_a_positive_readiness_result():
    with patch("core.moonraker._get", return_value=(True, "OK", {"result": {"state": "ready"}})):
        assert check_klipper_ready("pi.local", 7125) == (True, "ready")
