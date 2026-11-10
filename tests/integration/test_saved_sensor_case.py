"""Saved sensor fields reach review without changing the saved bytes."""
from unittest.mock import Mock

import pytest

from core.configuration_review import validate_configuration_plan
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.pin_validator import _read_pin_config
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_effective_xy_geometry import _assert_no_destination_mutations, _context, _generate
from tests.unit.test_saved_sensor_case import CURVES, block, saved


def prepare(tmp_path, kind, source, noop, value="100000"):
    content = _generate(tmp_path)
    context = _context(tmp_path, content)
    section = f"{kind} Curve"
    partial = {k: v for k, v in CURVES[kind].items() if k != "resistance1"}
    definitions = (block(section, partial)
                   + "\n[temperature_sensor chamber]\nsensor_type: Curve\nsensor_pin: PG11\n")
    autosave = saved(section, {"resistance1": value}).encode()
    if source == "include":
        remote = {"printer.cfg": content + b"\n[include user.cfg]\n" + autosave,
                  "user.cfg": b"[include nested.cfg]\n", "nested.cfg": definitions.encode()}
    else:
        remote = {"printer.cfg": content + definitions.encode() + autosave}
    plan = build_managed_config_plan(content, None, remote, geometry_context=context)
    if noop:
        remote.update({artifact.remote_name: artifact.content for artifact in plan.artifacts})
        plan = build_managed_config_plan(content, None, remote, geometry_context=context)
        assert not plan.changed_artifacts
    return content, context, remote, plan, autosave


@pytest.mark.parametrize("kind", CURVES)
@pytest.mark.parametrize("source", ["root", "include"])
@pytest.mark.parametrize("noop", [False, True])
def test_valid_mixed_case_saved_curve_is_reviewed_and_published_unchanged(tmp_path, kind, source, noop):
    content, context, remote, plan, autosave = prepare(tmp_path, kind, source, noop)
    review = validate_configuration_plan(plan)
    assert review.valid, review.errors
    assert _read_pin_config(effective_hardware_text(plan))[0][f"{kind} Curve"] == CURVES[kind]
    transport = FakeTransport(remote)
    result = ConfigDeploymentTransaction(
        transport, content, None, geometry_context=context, activation="none",
        confirm=lambda _: True, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path / "snapshots"),
    ).run()
    assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    assert transport.files["printer.cfg"].endswith(autosave)
    if source == "include":
        assert transport.files["nested.cfg"] == remote["nested.cfg"]
    if noop:
        assert not any(call[0] in ("upload", "delete", "restart") for call in transport.calls)


@pytest.mark.parametrize("kind", CURVES)
@pytest.mark.parametrize("source", ["root", "include"])
@pytest.mark.parametrize("noop", [False, True])
def test_invalid_saved_curve_still_blocks_before_confirmation_or_writes(tmp_path, kind, source, noop):
    content, context, remote, plan, _ = prepare(tmp_path, kind, source, noop, value="-1")
    review = validate_configuration_plan(plan)
    assert not review.valid
    transport = FakeTransport(remote)
    before = dict(transport.files)
    confirm = Mock(return_value=True)
    result = ConfigDeploymentTransaction(
        transport, content, None, geometry_context=context, activation="none",
        confirm=confirm, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path / "snapshots"),
    ).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    confirm.assert_not_called()
    _assert_no_destination_mutations(transport, before)


@pytest.mark.parametrize("kind", CURVES)
def test_generated_curve_does_not_replace_or_import_a_case_distinct_user_curve(tmp_path, kind):
    base = _generate(tmp_path)
    first = CURVES[kind]
    second = {**first, "resistance1": "110000"}
    generated = base + block(f"{kind} Curve", first).encode()
    remote = {"printer.cfg": base + block(f"{kind} curve", second).encode()}
    # This exercises the pure ownership plan, not review or geometry provenance.
    plan = build_managed_config_plan(generated, None, remote)
    actual = _read_pin_config(effective_hardware_text(plan))[0]
    assert actual[f"{kind} Curve"] == first
    assert actual[f"{kind} curve"] == second
