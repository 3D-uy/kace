"""RESTART acknowledgement may precede the old Klipper error disappearing."""
from unittest.mock import Mock, patch

import pytest

from core.config_transaction import ConfigDeploymentTransaction, MoonrakerConfigTransport, LocalMoonrakerConfigTransport
from tests.unit.test_config_transaction import FakeTransport, GENERATED


@pytest.mark.parametrize("states", [
    ["error", "startup", "ready", "ready"],
    ["shutdown", "disconnected", "startup", "ready", "ready"],
    ["ready", "startup", "ready", "ready"],
])
def test_transient_old_error_after_restart_does_not_abort_verified_transaction(tmp_path, states):
    transport = FakeTransport()
    transport.klipper_state = Mock(side_effect=states)
    firmware = Mock()
    result = ConfigDeploymentTransaction(transport, GENERATED, None, activation="firmware",
        snapshot_root=str(tmp_path), poll_interval=0, verify_firmware=firmware).run()
    assert result.ok, result.detail
    assert transport.klipper_state.call_count == len(states)
    assert ("verify_active_configuration",) in transport.calls
    assert [c for c in transport.calls if c[0] == "restart"] == [("restart", "firmware")]
    firmware.assert_called_once()


@pytest.mark.parametrize("state", ["error", "shutdown", "startup", "disconnected"])
def test_persistent_non_ready_times_out_and_keeps_diagnostic(state):
    transport = FakeTransport()
    transport.klipper_state = Mock(return_value=state)
    transport.klipper_failure_detail = Mock(return_value="Option 'pin' is not valid in section 'probe'")
    transaction = ConfigDeploymentTransaction(transport, GENERATED, None,
        activation="firmware", timeout=3, poll_interval=0)
    with patch("core.config_transaction.time.monotonic", side_effect=[0, 1, 2, 3]):
        assert transaction._wait_ready() == (False, state)
    assert transport.klipper_state.call_count == 2
    assert "Option 'pin'" in str(transaction._readiness_failure(state))


@pytest.mark.parametrize("local", [False, True])
def test_activation_diagnostic_retains_state_message_or_api_error(local, tmp_path):
    transport = (LocalMoonrakerConfigTransport(str(tmp_path)) if local
                 else MoonrakerConfigTransport("pi.local", 7125))
    for ok, detail in [(False, "state is 'error' (Unknown pin)"),
                       (False, "Moonraker /printer/info request failed: HTTP 401"),
                       (True, "ready")]:
        with patch("core.moonraker.check_klipper_ready", return_value=(ok, detail)):
            assert transport.klipper_failure_detail() == ("" if ok else detail)


def test_diagnostic_failure_cannot_hide_original_timeout():
    transport = FakeTransport()
    transport.klipper_failure_detail = Mock(side_effect=OSError("diagnostic offline"))
    transaction = ConfigDeploymentTransaction(transport, GENERATED, None, activation="firmware")
    assert str(transaction._readiness_failure("error")) == "Klipper did not become Ready (state=error)"


def test_persistent_error_never_reports_done_or_skips_loaded_verification(tmp_path):
    transport = FakeTransport()
    transport.klipper_state = Mock(return_value="error")
    transport.klipper_failure_detail = Mock(return_value="Unknown pin 'PB99'")
    firmware = Mock()
    events = []
    result = ConfigDeploymentTransaction(transport, GENERATED, None, activation="firmware",
        snapshot_root=str(tmp_path), timeout=0.02, poll_interval=0.001,
        verify_firmware=firmware, state_sink=lambda state, detail: events.append(state)).run()
    assert not result.ok and not result.pending
    assert "activation error:" in result.detail and "Unknown pin 'PB99'" in result.detail
    assert "DONE" not in events
    assert ("verify_active_configuration",) not in transport.calls
    firmware.assert_not_called()


def test_lost_api_after_one_ready_sample_is_reported_as_disconnected():
    transport = FakeTransport()
    transport.moonraker_online = Mock(side_effect=[True, False])
    transaction = ConfigDeploymentTransaction(transport, GENERATED, None,
        activation="firmware", timeout=3, poll_interval=0)
    with patch("core.config_transaction.time.monotonic", side_effect=[0, 1, 2, 3]):
        assert transaction._wait_ready() == (False, "disconnected")
