"""Effective watermark options reject before confirmation and artifact writes."""
from unittest.mock import Mock

import pytest

from core.configuration_review import validate_configuration_plan
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.exceptions import GenerationError
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.pin_validator import _read_pin_config
from tests.integration.test_heater_options_contract import destination
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_effective_xy_geometry import (
    _assert_no_destination_mutations, _context, _generate,
)


SECTION = "heater_generic chamber"
WATERMARK = (
    "\n[heater_generic chamber]\nheater_pin: PG12\nsensor_pin: PG11\n"
    "sensor_type: EPCOS 100K B57560G104F\ncontrol: watermark\n"
    "min_temp: 0\nmax_temp: 150\n"
)


def _plan(tmp_path, source, value, noop):
    content = _generate(tmp_path)
    context = _context(tmp_path, content)
    existing = content + WATERMARK.encode()
    remote = ({"printer.cfg": existing} if value is None
              else destination(existing, SECTION, "max_delta", value, source))
    plan = build_managed_config_plan(content, None, remote, geometry_context=context)
    if noop:
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        plan = build_managed_config_plan(content, None, remote, geometry_context=context)
        assert not plan.changed_artifacts
    assert _read_pin_config(effective_hardware_text(plan))[0][SECTION].get("max_delta") == value
    return content, context, remote, plan


@pytest.mark.parametrize("source", ["root", "include", "save"])
@pytest.mark.parametrize("noop", [False, True])
@pytest.mark.parametrize("value", ["0", "-0.25", "nan", "inf"])
def test_invalid_delta_blocks_before_confirmation_and_writes(tmp_path, source, noop, value):
    content, context, remote, plan = _plan(tmp_path, source, value, noop)
    review = validate_configuration_plan(plan)
    assert not review.valid and any(
        e.code == "heater-options" and "max_delta" in e.message for e in review.errors)
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


@pytest.mark.parametrize("source", ["root", "include", "save"])
@pytest.mark.parametrize("noop", [False, True])
@pytest.mark.parametrize("value", ["0.25", "1000000"])
def test_positive_delta_survives_effective_publication(tmp_path, source, noop, value):
    content, context, remote, plan = _plan(tmp_path, source, value, noop)
    review = validate_configuration_plan(plan)
    assert review.valid, review.errors
    transport = FakeTransport(remote)
    result = ConfigDeploymentTransaction(
        transport, content, None, geometry_context=context, activation="none",
        confirm=lambda _: True, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path / "snapshots"),
    ).run()
    assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    actual = build_managed_config_plan(content, None, transport.files, geometry_context=context)
    assert _read_pin_config(effective_hardware_text(actual))[0][SECTION]["max_delta"] == value
    if noop:
        assert not any(call[0] in ("upload", "delete", "restart") for call in transport.calls)


def test_omitted_delta_does_not_materialize_upstream_default(tmp_path):
    _, _, _, plan = _plan(tmp_path, "root", None, False)
    assert validate_configuration_plan(plan).valid
    assert "max_delta" not in _read_pin_config(effective_hardware_text(plan))[0][SECTION]


@pytest.mark.parametrize("value", ["0", "-0.25", "nan", "inf"])
def test_postrender_invalid_delta_preserves_both_existing_artifacts(tmp_path, monkeypatch, value):
    import core.generator as generator
    original = generator._postprocess_generated_output
    monkeypatch.setattr(generator, "_postprocess_generated_output",
                        lambda text: original(text) + WATERMARK + f"max_delta: {value}\n")
    target = tmp_path / "printer.cfg"
    sidecar = tmp_path / "printer.cfg.provenance.json"
    target.write_bytes(b"existing cfg")
    sidecar.write_bytes(b"existing sidecar")
    with pytest.raises(GenerationError, match="max_delta"):
        _generate(tmp_path)
    assert target.read_bytes() == b"existing cfg"
    assert sidecar.read_bytes() == b"existing sidecar"
