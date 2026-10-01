"""Host ADC MCU dependencies retain their own endpoint through deployment."""
import json
from unittest.mock import Mock

import pytest

from core.exceptions import GenerationError
from core.configuration_review import validate_configuration_plan
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.pin_validator import PinAliases, _read_pin_config
from tests.unit.test_adc_sensor_options import inputs, render


HOST = {"serial": "/tmp/klipper_host_mcu"}


@pytest.mark.parametrize("section,pin", (("extruder", "host:analog5"), ("heater_bed", "host:analog4")))
def test_original_host_dependency_survives_generation_and_noop(tmp_path, section, pin):
    board, user = inputs("EPCOS 100K B57560G104F", section, sensor_pin=pin, pullup_resistor="2000")
    board["mcu host"] = HOST
    board["mcu unused"] = {"serial": "/tmp/klipper_host_unused"}
    user["_profile_parsed"] = {"mcu host": {"serial": "/tmp/klipper_host_wrong"}}
    text = render(tmp_path, board, user)
    sections = _read_pin_config(text)[0]
    assert sections["mcu host"] == HOST
    assert sections["mcu"]["serial"] == user["mcu_path"]
    assert "mcu unused" not in sections
    assert sections[section]["sensor_pin"] == pin
    assert sections[section]["pullup_resistor"] == "2000"
    provenance = json.loads((tmp_path / "printer.cfg.provenance.json").read_text())
    assert provenance["sources"]["host_adc_mcus"] == {"mcu host": HOST}
    plan = build_managed_config_plan(text.encode(), None, {"printer.cfg": text.encode()})
    assert validate_configuration_plan(plan).valid
    assert _read_pin_config(effective_hardware_text(plan))[0]["mcu host"] == HOST
    remote = {"printer.cfg": text.encode(), **{a.remote_name: a.content for a in plan.artifacts}}
    assert not build_managed_config_plan(text.encode(), None, remote).changed_artifacts


@pytest.mark.parametrize("options", ({}, {"serial": ""}, {"serial": "/dev/ttyACM1"},
    {"canbus_uuid": "aabbccddeeff"}, {**HOST, "baud": "250000"},
    {**HOST, "restart_method": "command"}, {**HOST, "unused": "1"},
    {"serial": "/tmp/klipper_host_"}, {"serial": "/tmp/klipper_host_mcu\n[fan]"}))
def test_invalid_or_unreviewed_generated_transport_leaves_output_untouched(tmp_path, options):
    board, user = inputs("Generic 3950", sensor_pin="host:analog5")
    board["mcu host"] = options
    path = tmp_path / "printer.cfg"
    path.write_text("unchanged")
    with pytest.raises(GenerationError, match="Host ADC MCU"):
        render(tmp_path, board, user)
    assert path.read_text() == "unchanged"
    assert not (tmp_path / "printer.cfg.provenance.json").exists()


def test_profile_cannot_supply_missing_board_host_dependency(tmp_path):
    board, user = inputs("Generic 3950", sensor_pin="host:analog5")
    user["_profile_parsed"] = {"mcu host": HOST}
    with pytest.raises(GenerationError, match="ADC pin chip"):
        render(tmp_path, board, user)


def test_scraped_name_restores_exact_pin_namespace(tmp_path):
    board, user = inputs("Generic 3950", sensor_pin="Host:analog5")
    board["mcu host"] = HOST
    sections = _read_pin_config(render(tmp_path, board, user))[0]
    assert sections["mcu Host"] == HOST
    assert PinAliases(sections).resolve("Host:analog5") == ("Host", "analog5")
    assert PinAliases(sections).resolve("analog5") == ("mcu", "analog5")


def test_host_cannot_reuse_primary_endpoint(tmp_path):
    board, user = inputs("Generic 3950", sensor_pin="host:analog5")
    board["mcu host"] = HOST
    user["mcu_path"] = HOST["serial"]
    with pytest.raises(GenerationError, match="same endpoint"):
        render(tmp_path, board, user)


@pytest.mark.parametrize("noop", (False, True))
@pytest.mark.parametrize("override", ("serial: /tmp/klipper_host_other", "serial: /dev/ttyACM1",
    "baud: 250000", "restart_method: command", "canbus_uuid: aabbccddeeff"))
def test_nested_override_blocks_transaction_before_confirmation(tmp_path, noop, override):
    from tests.unit.test_config_transaction import FakeTransport
    board, user = inputs("Generic 3950", sensor_pin="host:analog5")
    board["mcu host"] = HOST
    content = render(tmp_path, board, user).encode()
    remote = {"printer.cfg": content + b"\n[include user.cfg]\n", "user.cfg": b"[include wiring.cfg]\n",
              "wiring.cfg": f"[mcu host]\n{override}\n".encode()}
    if noop:
        plan = build_managed_config_plan(content, None, remote)
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        assert not build_managed_config_plan(content, None, remote).changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, content, None, activation="none", confirm=confirm,
        snapshot_root=str(tmp_path / "snapshots"), verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "Host ADC MCU" in result.detail
    confirm.assert_not_called()
    assert transport.files == remote


def test_existing_root_cannot_smuggle_unconsumed_host_options(tmp_path):
    board, user = inputs("Generic 3950", sensor_pin="host:analog5")
    board["mcu host"] = HOST
    content = render(tmp_path, board, user).encode()
    remote = {"printer.cfg": content.replace(b"[mcu host]", b"[mcu host]\nbaud: 250000")}
    result = validate_configuration_plan(build_managed_config_plan(content, None, remote))
    assert any(error.code == "host-adc-mcu" for error in result.errors)


def test_unrelated_preserved_mcus_are_not_newly_certified_or_rejected():
    from core.host_mcu import validate_host_adc_mcus
    validate_host_adc_mcus({"mcu tool": {"canbus_uuid": "aabbccddeeff"}})


def test_ambiguous_board_namespace_fails(tmp_path):
    board, user = inputs("Generic 3950", sensor_pin="Host:analog5")
    board["mcu host"] = HOST
    board["mcu Host"] = {"serial": "/tmp/klipper_host_other"}
    with pytest.raises(GenerationError, match="conflicting"):
        render(tmp_path, board, user)


def test_both_primary_sensors_share_one_host_definition(tmp_path):
    board, user = inputs("EPCOS 100K B57560G104F", sensor_pin="host:analog5", pullup_resistor="2000")
    board["heater_bed"].update(sensor_pin="host:analog4", pullup_resistor="2000")
    board["mcu host"] = HOST
    text = render(tmp_path, board, user)
    assert text.count("[mcu host]") == 1
    sections = _read_pin_config(text)[0]
    assert sections["extruder"]["sensor_pin"] == "host:analog5"
    assert sections["heater_bed"]["sensor_pin"] == "host:analog4"
    assert validate_configuration_plan(build_managed_config_plan(text.encode(), None, {"printer.cfg": text.encode()})).valid


def test_secondary_endpoints_cannot_duplicate_each_other():
    from core.host_mcu import validate_host_adc_mcus
    with pytest.raises(GenerationError, match="same endpoint"):
        validate_host_adc_mcus({"mcu host": HOST, "mcu second": HOST})
