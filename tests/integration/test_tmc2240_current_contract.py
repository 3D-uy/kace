"""Current preflight applies to effective includes/SAVE_CONFIG before writes."""
from unittest.mock import Mock

import pytest

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.exceptions import GenerationError
from core.managed_config import build_managed_config_plan, effective_hardware_text
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_effective_xy_geometry import _generate, _context, _assert_no_destination_mutations


def driver(transport, options):
    bus = "uart_pin: PG13\n" if transport == "UART" else "cs_pin: PG13\n"
    return ("[tmc2240 stepper_x]\n" + bus + "".join(f"{k}: {v}\n" for k, v in options.items())).encode()


def destination(base, transport, source, option, value):
    valid = driver(transport, {"run_current": ".4"})
    override = f"[tmc2240 stepper_x]\n{option}: {value}\n".encode()
    if source == "include":
        return {"printer.cfg": base + b"\n[include user.cfg]\n", "user.cfg": valid + b"\n[include nested.cfg]\n", "nested.cfg": override}
    if source == "save":
        return {"printer.cfg": base + b"\n" + valid + (
            "\n#*# <---------------------- SAVE_CONFIG ---------------------->\n"
            "#*# DO NOT EDIT THIS BLOCK OR BELOW. The contents are auto-generated.\n#*#\n"
            f"#*# [tmc2240 stepper_x]\n#*# {option} = {value}\n").encode()}
    return {"printer.cfg": base + b"\n" + valid + b"\n" + override}


@pytest.mark.parametrize("transport", ["UART", "SPI"])
@pytest.mark.parametrize("source", ["root", "include", "save"])
@pytest.mark.parametrize("option,value", [("hold_current", "0"), ("rref", "nan")])
@pytest.mark.parametrize("noop", [False, True])
def test_invalid_current_contract_blocks_before_confirmation_or_writes(tmp_path, transport, source, option, value, noop):
    base = _generate(tmp_path)
    context = _context(tmp_path, base)
    remote = destination(base, transport, source, option, value)
    plan = build_managed_config_plan(base, None, remote, geometry_context=context)
    if noop:
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        plan = build_managed_config_plan(base, None, remote, geometry_context=context)
        assert not plan.changed_artifacts
    review = validate_configuration_plan(plan)
    assert not review.valid
    assert any(option in error.message and "tmc2240" in error.message for error in review.errors)
    transport_obj = FakeTransport(remote)
    before = dict(transport_obj.files)
    confirm = Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport_obj, base, None, geometry_context=context,
        activation="none", confirm=confirm, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path / "snapshots")).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    confirm.assert_not_called()
    _assert_no_destination_mutations(transport_obj, before)


@pytest.mark.parametrize("transport", ["UART", "SPI"])
@pytest.mark.parametrize("options", [{"run_current": "2.1"}, {"run_current": ".4", "rref": "60000"}])
def test_valid_preserved_currents_can_publish_unchanged(tmp_path, transport, options):
    base = _generate(tmp_path)
    context = _context(tmp_path, base)
    remote = {"printer.cfg": base + b"\n[include user.cfg]\n", "user.cfg": driver(transport, options)}
    plan = build_managed_config_plan(base, None, remote, geometry_context=context)
    assert validate_configuration_plan(plan).valid
    for key, value in options.items():
        assert f"{key}: {value}" in effective_hardware_text(plan)
    device = FakeTransport(remote)
    result = ConfigDeploymentTransaction(device, base, None, geometry_context=context,
        activation="none", confirm=lambda _: True, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path / "snapshots")).run()
    assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    assert device.files["user.cfg"] == remote["user.cfg"]


@pytest.mark.parametrize("transport", ["UART", "SPI"])
def test_postrender_injection_rejects_before_cfg_or_sidecar_write(tmp_path, monkeypatch, transport):
    import core.generator as generator
    original = generator._postprocess_generated_output
    monkeypatch.setattr(generator, "_postprocess_generated_output",
        lambda text: original(text) + "\n" + driver(transport, {"run_current": "0"}).decode())
    output = tmp_path / "printer.cfg"
    sidecar = tmp_path / "printer.cfg.provenance.json"
    output.write_bytes(b"existing cfg")
    sidecar.write_bytes(b"existing sidecar")
    with pytest.raises(GenerationError, match="run_current"):
        _generate(tmp_path)
    assert output.read_bytes() == b"existing cfg"
    assert sidecar.read_bytes() == b"existing sidecar"
