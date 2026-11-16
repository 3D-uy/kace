"""Real isolated loader for the new entry; destination/MCU remain simulated."""
import os
import pytest

from core.configuration_operation import run_configuration_operation
from core.klipper_preflight import validate_plan as real_validate_plan
from tests.unit.test_configuration_operation import setup_operation, receipt, ID


pytestmark = pytest.mark.skipif(os.environ.get("KACE_C3_DOCKER_INTEGRATION") != "1",
                                reason="requires explicitly provisioned Docker preflight")


def test_configuration_entry_uses_real_loader_before_deferred_publication(setup_operation, monkeypatch):
    source, original, digest, transport = setup_operation
    monkeypatch.setattr("core.klipper_preflight.validate_plan", real_validate_plan)
    monkeypatch.setattr("core.deployer._select_config_activation", lambda: "none")
    result = run_configuration_operation(ID, digest)
    assert result.exit_code == 41, result.detail
    assert source.read_bytes() == original
    assert receipt(source).exists()
    assert any(call[0] == "upload" for call in transport.calls)
    assert not any(call[0] in {"restart", "restart_moonraker"} for call in transport.calls)
