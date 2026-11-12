"""Opt-in real Klipper preflight across the configuration transaction boundary.

Set KACE_C3_DOCKER_INTEGRATION=1 and provision the receipt before running.
Only Klipper loading and KACE planning/publication logic are real: the destination
is FakeTransport, activation is deferred, and no printer is contacted.
"""
import os
from unittest.mock import Mock

import pytest

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.managed_config import build_managed_config_plan
from tests.integration.test_controller_fan_references import EXTRA, SECTION
from tests.integration.test_heater_options_contract import destination
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_effective_xy_geometry import _context, _generate


pytestmark = pytest.mark.skipif(os.environ.get("KACE_C3_DOCKER_INTEGRATION") != "1",
                                reason="requires explicitly provisioned Docker preflight")


@pytest.mark.parametrize("source", ["root", "include", "save"])
@pytest.mark.parametrize("noop", [False, True], ids=["changed", "noop"])
@pytest.mark.parametrize("value,valid", [("Missing", False), ("extruder, heater_bed", True)],
                         ids=["missing-reference", "valid-references"])
def test_real_loader_config_publication(tmp_path, source, noop, value, valid):
    base = _generate(tmp_path)
    geometry = _context(tmp_path, base)
    remote = destination(base + EXTRA.encode(), SECTION, "heater", value, source)
    plan = build_managed_config_plan(base, None, remote, geometry_context=geometry)
    if noop:
        remote.update({artifact.remote_name: artifact.content for artifact in plan.artifacts})
        plan = build_managed_config_plan(base, None, remote, geometry_context=geometry)
    assert bool(plan.changed_artifacts) is not noop

    transport = FakeTransport(remote)
    original = dict(transport.files)
    original_active = dict(transport.active_files)
    review = Mock(return_value=True)
    select_activation = Mock(return_value="none")
    transaction = ConfigDeploymentTransaction(
        transport, base, None, activation="none", geometry_context=geometry,
        snapshot_root=str(tmp_path / "snapshots"), review=review,
        activation_selector=select_activation,
    )
    result = transaction.run()
    writes = [call[1] for call in transport.calls if call[0] == "upload"]
    assert not any(call[0] in {"restart", "restart_moonraker"} for call in transport.calls)
    assert transport.active_files == original_active

    if valid:
        assert result.state is ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION, result.detail
        review.assert_called_once()
        select_activation.assert_called_once()
        assert sorted(writes) == sorted(artifact.remote_name for artifact in plan.changed_artifacts)
        assert transport.files == {
            **original, **{artifact.remote_name: artifact.content for artifact in plan.artifacts},
        }
        if noop:
            assert transport.files == original
            assert result.snapshot is None
        else:
            assert result.snapshot is not None
    else:
        assert result.state is ConfigTransactionState.PRECONDITION_FAILED, result.detail
        assert "Klipper preflight invalid" in result.detail
        review.assert_not_called()
        select_activation.assert_not_called()
        assert not any(call[0] in {"upload", "delete"} for call in transport.calls)
        assert transport.files == original
        assert result.snapshot is None
