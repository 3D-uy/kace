"""Optional real Docker preflight across the firmware orchestration boundary.

Set KACE_C3_DOCKER_INTEGRATION=1 and a provisioned receipt to run. No device
or firmware service is contacted; only the loader and KACE plan are real.
"""
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from core import config_transaction, deployer
from core.moonraker_deployer import DeployResult, DeployState
from tests.integration.test_controller_fan_references import SECTION, EXTRA
from tests.integration.test_heater_options_contract import destination
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_effective_xy_geometry import _generate
from tests.unit.test_effective_xy_deployment import _firmware_user

pytestmark = pytest.mark.skipif(os.environ.get("KACE_C3_DOCKER_INTEGRATION") != "1",
                                reason="requires explicitly provisioned Docker preflight")


@pytest.mark.parametrize("value,valid,selected", [
    pytest.param("Missing", False, True, id="selected-missing-reference"),
    pytest.param("extruder, heater_bed", True, True, id="selected-valid-references"),
    pytest.param("Missing", True, False, id="unselected-old-reference"),
])
def test_real_loader_firmware_boundary(tmp_path, value, valid, selected):
    source = tmp_path / "source"
    source.mkdir()
    base = _generate(source)
    source_path = source / "printer.cfg"
    user, _artifact = _firmware_user(tmp_path)
    remote = destination(base + EXTRA.encode(), SECTION, "heater", value, "include")
    if selected:
        # Fresh installation loads only dependencies selected by the NEW tree.
        # Keep the invalid-reference case before every physical boundary.
        base += EXTRA.encode() + b"\n[include user.cfg]\n"
        source_path.write_bytes(base)
        sidecar = Path(str(source_path) + ".provenance.json")
        provenance = json.loads(sidecar.read_text(encoding="utf-8"))
        provenance["geometry"]["source_sha256"] = hashlib.sha256(base).hexdigest()
        sidecar.write_text(json.dumps(provenance), encoding="utf-8")
    transport = FakeTransport(remote)
    original = dict(transport.files)
    from core.snapshot import create_snapshot
    def stop_at_boundary():
        physical.call_args.kwargs["before_config_upload"]()
        return DeployResult(DeployState.ABORTED, "simulated firmware boundary")
    with patch.object(config_transaction, "configuration_transport", return_value=transport), \
         patch.object(deployer, "_generated_config_bytes", return_value=(str(source_path), base, None)), \
         patch.object(deployer, "_preflight_check", return_value=True), \
         patch.object(deployer, "_interactive_configuration_review", return_value=True) as review, \
         patch("core.snapshot.create_snapshot", side_effect=lambda originals, **kwargs:
               create_snapshot(originals, persist_root=str(tmp_path / "snapshots"), **kwargs)), \
         patch("core.power_controller.configured_power_controller", return_value=None) as power, \
         patch("core.mcu_monitor.McuPresenceMonitor"), \
         patch("core.moonraker_deployer.Deployer") as physical:
        physical.return_value.run.side_effect = stop_at_boundary
        result = deployer.deploy_firmware_installation(user)
    if valid:
        assert result.state == DeployState.ABORTED, result.detail
        assert result.detail == "simulated firmware boundary"
        review.assert_called_once()
        power.assert_called_once()
        physical.assert_called_once()
    else:
        assert result.state == DeployState.FAILED_PRECONDITION
        assert "isolated Klipper preflight invalid" in result.detail, result.detail
        review.assert_not_called()
        power.assert_not_called()
        physical.assert_not_called()
    user["firmware_deployment_service"].execute.assert_not_called()
    assert transport.files == original
