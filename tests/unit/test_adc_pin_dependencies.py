"""ADC chip presence is a dependency check, not peripheral certification."""
from unittest.mock import Mock

import pytest

from core.exceptions import GenerationError
from core.configuration_review import validate_configuration_plan
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.managed_config import build_managed_config_plan
from tests.unit.test_adc_sensor_options import inputs, render
from tests.unit.test_config_transaction import FakeTransport, GENERATED
from tests.unit.test_tmc_uart_review import remote_files


@pytest.mark.parametrize("section,pin", (
    ("extruder", "vref_scaled:PB0"), ("heater_bed", "vref_scaled:PA20"),
    ("extruder", "vref_scaled:PC0"), ("heater_bed", "vref_scaled:PC15"),
    ("extruder", "vref_scaled:PC1"), ("heater_bed", "vref_scaled:PC0"),
))
def test_generator_rejects_missing_adc_provider_before_writing(tmp_path, section, pin):
    board, user = inputs("Generic 3950", section, sensor_pin=pin, pullup_resistor="2200")
    with pytest.raises(GenerationError, match="ADC pin chip.*vref_scaled"):
        render(tmp_path, board, user)
    assert not (tmp_path / "printer.cfg").exists()


@pytest.mark.parametrize("section,pin", (("extruder", "host:analog5"), ("heater_bed", "host:analog4")))
def test_missing_cramps_host_adc_dependency_blocks_generation(tmp_path, section, pin):
    board, user = inputs("EPCOS 100K B57560G104F", section, sensor_pin=pin, pullup_resistor="2000")
    with pytest.raises(GenerationError, match="ADC pin chip.*host"):
        render(tmp_path, board, user)
    assert not (tmp_path / "printer.cfg").exists()


@pytest.mark.parametrize("noop", (False, True))
@pytest.mark.parametrize("pin", ("vref_scaled:PC0", "missing:PA0", "Vref_scaled:PC0"))
def test_missing_provider_in_nested_include_blocks_transaction(tmp_path, noop, pin):
    remote = remote_files(f"[temperature_sensor chamber]\nsensor_type: Generic 3950\nsensor_pin: {pin}\n")
    if noop:
        plan = build_managed_config_plan(GENERATED, None, remote)
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        assert not build_managed_config_plan(GENERATED, None, remote).changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, GENERATED, None, activation="none",
        confirm=confirm, snapshot_root=str(tmp_path / "snapshots"), verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "ADC pin chip" in result.detail
    confirm.assert_not_called()
    assert transport.files == remote


@pytest.mark.parametrize("definition,pin", (
    ("", "mcu:PA0"), ("[mcu tool]\nserial: /tmp/tool\n", "tool:PA0"),
    ("[adc_scaled Scaled]\nvref_pin: PA1\nvssa_pin: PA2\n", " Scaled : PA0 "),
    ("[ads1x1x external]\nchip: ADS1115\n", "external:AIN0"),
    ("[ads1x1x unused external]\nchip: ADS1115\n", "external:AIN0"),
    ("[adc_scaled Scaled unused]\nvref_pin: PA1\nvssa_pin: PA2\n", "Scaled:PA0"),
))
def test_effective_provider_presence_is_recognized_without_schema_certification(definition, pin):
    remote = remote_files(definition + f"[temperature_sensor chamber]\nsensor_type: Generic 3950\nsensor_pin: {pin}\n")
    review = validate_configuration_plan(build_managed_config_plan(GENERATED, None, remote))
    assert not [error for error in review.errors if error.code == "adc-pin-dependency"]


@pytest.mark.parametrize("section", ("extruder", "extruder1", "heater_bed", "heater_generic chamber",
    "temperature_sensor chamber", "temperature_fan chamber", "temperature_probe coil", "z_thermal_adjust"))
def test_all_thermal_adc_consumers_require_a_declared_chip(section):
    from core.thermistor import validate_adc_pin_dependencies
    with pytest.raises(GenerationError, match="ADC pin chip"):
        validate_adc_pin_dependencies({section: {"sensor_type": "PT1000", "sensor_pin": "missing:PA0"}})


@pytest.mark.parametrize("definition", ("thermistor MyCurve", "adc_temperature MyCurve"))
def test_custom_adc_consumers_check_pin_dependencies(definition):
    from core.thermistor import validate_adc_pin_dependencies
    with pytest.raises(GenerationError, match="ADC pin chip"):
        validate_adc_pin_dependencies({definition: {}, "temperature_sensor test": {
            "sensor_type": "MyCurve", "sensor_pin": "missing:PA0"}})


@pytest.mark.parametrize("section,sensor", (("load_cell", "Generic 3950"),
    ("probe_eddy_current test", "Generic 3950"), ("temperature_sensor test", "MAX31865")))
def test_other_registries_and_non_adc_factories_are_outside_this_check(section, sensor):
    from core.thermistor import validate_adc_pin_dependencies
    validate_adc_pin_dependencies({section: {"sensor_type": sensor, "sensor_pin": "unrelated:PA0"}})


@pytest.mark.parametrize("provider", ("multi_pin invalid", "sx1509 invalid", "probe", "gcode_macro invalid"))
def test_non_adc_provider_does_not_satisfy_sensor_dependency(provider):
    from core.thermistor import validate_adc_pin_dependencies
    with pytest.raises(GenerationError, match="ADC pin chip"):
        validate_adc_pin_dependencies({provider: {}, "temperature_sensor test": {
            "sensor_type": "Generic 3950", "sensor_pin": "invalid:PA0"}})


def test_provider_names_remain_case_sensitive():
    from core.thermistor import validate_adc_pin_dependencies
    with pytest.raises(GenerationError, match="ADC pin chip"):
        validate_adc_pin_dependencies({"adc_scaled Scaled": {}, "temperature_sensor test": {
            "sensor_type": "Generic 3950", "sensor_pin": "scaled:PA0"}})
