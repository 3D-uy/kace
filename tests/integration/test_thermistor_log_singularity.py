"""Singular curves become review failures, not unhandled arithmetic errors."""
from unittest.mock import Mock

import pytest

from core.configuration_review import validate_configuration_plan
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.exceptions import GenerationError
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.pin_validator import _read_pin_config
from tests.integration.test_heater_options_contract import destination
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_custom_thermistor_dependencies import inputs, render
from tests.unit.test_effective_xy_geometry import (
    _assert_no_destination_mutations, _context, _generate,
)
from tests.unit.test_thermistor_log_singularity import COLLAPSED, curve


SECTION = "thermistor collapsed"


def _definition(fields):
    return f"\n[{SECTION}]\n" + "".join(f"{key}: {value}\n" for key, value in fields.items())


def _plan(tmp_path, source, noop):
    content = _generate(tmp_path)
    context = _context(tmp_path, content)
    fields = curve(("100000", "100001", "100002"))
    if source == "save":
        # SAVE_CONFIG supplies the effective value, without an active override.
        del fields["resistance3"]
    existing = content + (_definition(fields)
        + "\n[temperature_sensor chamber]\nsensor_type: collapsed\nsensor_pin: PG11\n").encode()
    remote = destination(existing, SECTION, "resistance3", COLLAPSED[2], source)
    plan = build_managed_config_plan(content, None, remote, geometry_context=context)
    if noop:
        remote.update({artifact.remote_name: artifact.content for artifact in plan.artifacts})
        plan = build_managed_config_plan(content, None, remote, geometry_context=context)
        assert not plan.changed_artifacts
    assert _read_pin_config(effective_hardware_text(plan))[0][SECTION] == curve()
    return content, context, remote, plan


@pytest.mark.parametrize("source", ["root", "include", "save"])
@pytest.mark.parametrize("noop", [False, True])
def test_effective_singular_curve_returns_review_error(tmp_path, source, noop):
    _, _, _, plan = _plan(tmp_path, source, noop)
    review = validate_configuration_plan(plan)
    assert not review.valid
    assert any(error.code == "custom-thermistor" and "singular" in error.message
               for error in review.errors)


@pytest.mark.parametrize("source", ["root", "include", "save"])
@pytest.mark.parametrize("noop", [False, True])
def test_transaction_reports_precondition_before_confirmation_or_writes(tmp_path, source, noop):
    content, context, remote, _ = _plan(tmp_path, source, noop)
    transport = FakeTransport(remote)
    before = dict(transport.files)
    confirm = Mock(return_value=True)
    result = ConfigDeploymentTransaction(
        transport, content, None, geometry_context=context, activation="none",
        confirm=confirm, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path / "snapshots"),
    ).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "singular" in result.detail
    confirm.assert_not_called()
    _assert_no_destination_mutations(transport, before)


@pytest.mark.parametrize("source", ["board", "profile", "postrender"])
def test_generation_reports_structured_error_and_preserves_artifacts(tmp_path, monkeypatch, source):
    board, user = inputs(definition=curve())
    if source == "profile":
        user["_profile_parsed"] = {"thermistor g2": board.pop("thermistor g2")}
    elif source == "postrender":
        import core.generator as generator
        original = generator._postprocess_generated_output
        monkeypatch.setattr(generator, "_postprocess_generated_output",
                            lambda text: original(text) + _definition(curve()))
    target, sidecar = tmp_path / "printer.cfg", tmp_path / "printer.cfg.provenance.json"
    target.write_bytes(b"existing cfg")
    sidecar.write_bytes(b"existing sidecar")
    with pytest.raises(GenerationError, match="singular"):
        if source == "postrender":
            _generate(tmp_path)
        else:
            render(tmp_path, board, user)
    assert target.read_bytes() == b"existing cfg"
    assert sidecar.read_bytes() == b"existing sidecar"
