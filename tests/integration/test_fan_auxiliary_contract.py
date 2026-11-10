"""Auxiliary pin failures must block effective configuration publication."""
from unittest.mock import Mock
import pytest

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.exceptions import GenerationError
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.pin_validator import _read_pin_config
from tests.integration.test_heater_options_contract import destination
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_effective_xy_geometry import _generate, _context, _assert_no_destination_mutations


SECTIONS = ("fan", "fan_generic Aux", "heater_fan Aux", "controller_fan Aux", "temperature_fan Aux")


def fan_section(section):
    return "\n["+section+"]\npin: PG10\nhardware_pwm: true\n" + (
        "sensor_type: Generic 3950\nsensor_pin: PG11\nmin_temp: 0\nmax_temp: 100\ncontrol: watermark\n"
        if section.startswith("temperature_fan ") else "")


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("source", ["root", "include", "save"])
@pytest.mark.parametrize("noop", [False, True])
@pytest.mark.parametrize("option,token", [("tachometer_pin", "!PG12"), ("enable_pin", "^PG13")])
def test_invalid_auxiliary_blocks_before_confirmation_and_publication(tmp_path, section, source, noop, option, token):
    content = _generate(tmp_path); context = _context(tmp_path, content)
    remote = destination(content+fan_section(section).encode(), section, option, token, source)
    plan = build_managed_config_plan(content, None, remote, geometry_context=context)
    if noop:
        remote.update({a.remote_name:a.content for a in plan.artifacts})
        plan = build_managed_config_plan(content, None, remote, geometry_context=context)
        assert not plan.changed_artifacts
    review = validate_configuration_plan(plan)
    assert not review.valid and any(e.code=="fan-auxiliary" for e in review.errors)
    transport = FakeTransport(remote); before = dict(transport.files); confirm = Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, content, None, geometry_context=context,
        activation="none", confirm=confirm, output=lambda _:None, poll_interval=0,
        snapshot_root=str(tmp_path/"snapshots")).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    confirm.assert_not_called()
    _assert_no_destination_mutations(transport, before)


@pytest.mark.parametrize("provider,token", [
    ("[multi_pin Tach]\npins: PG12,PG14\n", "multi_pin:Tach"),
    ("[sx1509 Exp]\ni2c_address: 62\n", "sx1509_Exp:PIN_3"),
])
def test_declared_counter_provider_blocks_transaction(tmp_path, provider, token):
    content = _generate(tmp_path); context = _context(tmp_path, content)
    remote = {"printer.cfg": content+b"\n[include user.cfg]\n",
              "user.cfg": (provider+fan_section("fan_generic Aux")+"tachometer_pin: "+token+"\n").encode()}
    transport = FakeTransport(remote); before = dict(transport.files); confirm = Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, content, None, geometry_context=context,
        activation="none", confirm=confirm, output=lambda _:None, poll_interval=0,
        snapshot_root=str(tmp_path/"snapshots")).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    confirm.assert_not_called()
    _assert_no_destination_mutations(transport, before)


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("option,token", [("tachometer_pin", "!PG12"), ("enable_pin", "^PG13")])
def test_invalid_postrender_leaves_cfg_and_provenance_intact(tmp_path, monkeypatch, section, option, token):
    import core.generator as generator
    original = generator._postprocess_generated_output
    monkeypatch.setattr(generator, "_postprocess_generated_output", lambda text:
        original(text)+fan_section(section)+option+": "+token+"\n")
    cfg,sidecar = tmp_path/"printer.cfg",tmp_path/"printer.cfg.provenance.json"
    cfg.write_bytes(b"existing cfg"); sidecar.write_bytes(b"existing sidecar")
    with pytest.raises(GenerationError, match=option): _generate(tmp_path)
    assert cfg.read_bytes()==b"existing cfg" and sidecar.read_bytes()==b"existing sidecar"


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("source", ["root", "include", "save"])
def test_valid_pullup_tach_and_inverted_enable_preserved(tmp_path, section, source):
    content = _generate(tmp_path); context = _context(tmp_path, content)
    initial = content+(fan_section(section)+"enable_pin: !PG13\n").encode()
    remote = destination(initial, section, "tachometer_pin", "^PG12", source)
    transport = FakeTransport(remote)
    result = ConfigDeploymentTransaction(transport, content, None, geometry_context=context,
        activation="none", confirm=lambda _:True, output=lambda _:None, poll_interval=0,
        snapshot_root=str(tmp_path/"snapshots")).run()
    assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    plan = build_managed_config_plan(content,None,transport.files,geometry_context=context)
    actual = _read_pin_config(effective_hardware_text(plan))[0][section]
    assert actual["enable_pin"]=="!PG13" and actual["tachometer_pin"]=="^PG12"
