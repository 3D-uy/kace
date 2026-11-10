"""Preserved common fan options reject before confirmation or destination writes."""
from unittest.mock import Mock
import pytest
from core.configuration_review import validate_configuration_plan
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.pin_validator import _read_pin_config
from core.exceptions import GenerationError
from tests.unit.test_effective_xy_geometry import _generate, _context, _assert_no_destination_mutations
from tests.unit.test_config_transaction import FakeTransport
from tests.integration.test_heater_options_contract import destination

SECTIONS = ("fan", "fan_generic Aux", "heater_fan Aux", "controller_fan Aux", "temperature_fan Aux")


def fan_fixture(content, section):
    extra = ""
    if section.startswith("temperature_fan "):
        extra = "sensor_type: Generic 3950\nsensor_pin: PG11\ncontrol: watermark\nmin_temp: 0\nmax_temp: 100\n"
    return content + (f"\n[{section}]\npin: PG10\nhardware_pwm: true\n"
                      "tachometer_pin: ^PG12\n" + extra).encode()


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("source", ["root", "include", "save"])
@pytest.mark.parametrize("noop", [False, True])
@pytest.mark.parametrize("option,value", [("max_power", "0"), ("tachometer_poll_interval", "nan")])
def test_invalid_common_options_block_before_confirmation_and_writes(tmp_path, section, source, noop, option, value):
    content = _generate(tmp_path)
    context = _context(tmp_path, content)
    remote = destination(fan_fixture(content, section), section, option, value, source)
    plan = build_managed_config_plan(content, None, remote, geometry_context=context)
    if noop:
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        plan = build_managed_config_plan(content, None, remote, geometry_context=context)
        assert not plan.changed_artifacts
    assert _read_pin_config(effective_hardware_text(plan))[0][section][option] == value
    review = validate_configuration_plan(plan)
    assert not review.valid and any(e.code == "part-fan-options" for e in review.errors)
    transport = FakeTransport(remote)
    before = dict(transport.files)
    confirm = Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, content, None, geometry_context=context,
        activation="none", confirm=confirm, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path/"snapshots")).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    confirm.assert_not_called()
    _assert_no_destination_mutations(transport, before)


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("option,value", [("cycle_time", "0"), ("tachometer_ppr", "1.5")])
def test_postrender_invalid_common_options_preserve_existing_artifacts(tmp_path, monkeypatch, section, option, value):
    import core.generator as generator
    original = generator._postprocess_generated_output
    monkeypatch.setattr(generator, "_postprocess_generated_output", lambda text:
        fan_fixture(original(text).encode(), section).decode()+f"\n[{section}]\n{option}: {value}\n")
    target, sidecar = tmp_path/"printer.cfg", tmp_path/"printer.cfg.provenance.json"
    target.write_bytes(b"existing cfg")
    sidecar.write_bytes(b"existing sidecar")
    with pytest.raises(GenerationError, match=option):
        _generate(tmp_path)
    assert target.read_bytes() == b"existing cfg"
    assert sidecar.read_bytes() == b"existing sidecar"


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("option,value", [("tachometer_ppr", "2"), ("tachometer_poll_interval", ".0015")])
def test_unconsumed_tachometer_options_block_before_confirmation_and_writes(tmp_path, section, option, value):
    content = _generate(tmp_path)
    context = _context(tmp_path, content)
    remote = destination(fan_fixture(content, section).replace(b"tachometer_pin: ^PG12\n", b""),
                         section, option, value, "include")
    transport = FakeTransport(remote)
    before = dict(transport.files)
    confirm = Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, content, None, geometry_context=context,
        activation="none", confirm=confirm, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path/"snapshots")).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    confirm.assert_not_called()
    _assert_no_destination_mutations(transport, before)


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("source", ["root", "include", "save"])
def test_explicit_zero_and_tachometer_are_preserved_through_deployment(tmp_path, section, source):
    content = _generate(tmp_path)
    context = _context(tmp_path, content)
    remote = destination(fan_fixture(content, section), section, "kick_start_time", "0", source)
    transport = FakeTransport(remote)
    result = ConfigDeploymentTransaction(transport, content, None, geometry_context=context,
        activation="none", confirm=lambda _: True, output=lambda _: None, poll_interval=0,
        snapshot_root=str(tmp_path/"snapshots")).run()
    assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    actual = effective_hardware_text(build_managed_config_plan(content, None, transport.files, geometry_context=context))
    fields = _read_pin_config(actual)[0][section]
    assert fields["kick_start_time"] == "0"
    assert fields["tachometer_pin"] == "^PG12"
