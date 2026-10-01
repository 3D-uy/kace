"""Thermal factory names must resolve without certifying non-ADC peripherals."""
from unittest.mock import Mock

import pytest

from core.exceptions import GenerationError
from core.configuration_review import validate_configuration_plan
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.managed_config import build_managed_config_plan
from tests.unit.test_adc_sensor_options import inputs, render
from tests.unit.test_custom_thermistor_dependencies import BETA
from tests.unit.test_config_transaction import FakeTransport, GENERATED
from tests.unit.test_tmc_uart_review import remote_files


UNKNOWN = ("NTC 100K beta 3950", "generic 3950", "MissingCurve", "", "Generic 3950 extra")
NON_ADC = ("BME280", "DS18B20", "SI7013", "SI7020", "SI7021", "SHT21", "HTU21D",
           "SHT3X", "AHT10", "AHT1X", "AHT2X", "AHT3X", "LM75", "MAX6675",
           "MAX31855", "MAX31856", "MAX31865", "temperature_host", "temperature_mcu",
           "temperature_combined")


@pytest.mark.parametrize("section", ("extruder", "heater_bed"))
@pytest.mark.parametrize("sensor", tuple(name for name in UNKNOWN if name))
def test_unknown_selected_sensor_fails_before_writing(tmp_path, section, sensor):
    board, user = inputs(sensor, section)
    with pytest.raises(GenerationError, match="sensor"):
        render(tmp_path, board, user)
    assert not (tmp_path / "printer.cfg").exists()


@pytest.mark.parametrize("section", ("extruder", "heater_bed"))
def test_empty_selection_keeps_existing_resolved_default(tmp_path, section):
    from core.scraper import parse_config
    board, user = inputs("", section)
    assert parse_config(render(tmp_path, board, user))[section]["sensor_type"] == "EPCOS 100K B57560G104F"


@pytest.mark.parametrize("sensor", NON_ADC)
def test_generator_does_not_pretend_to_support_non_adc_heaters(tmp_path, sensor):
    board, user = inputs(sensor)
    with pytest.raises(GenerationError, match="not supported for generated heaters"):
        render(tmp_path, board, user)
    assert not (tmp_path / "printer.cfg").exists()


@pytest.mark.parametrize("noop", (False, True))
@pytest.mark.parametrize("sensor", UNKNOWN)
def test_unresolved_preserved_reference_blocks_transaction(tmp_path, sensor, noop):
    remote = remote_files(f"[temperature_sensor chamber]\nsensor_type: {sensor}\nsensor_pin: PC11\n")
    if noop:
        plan = build_managed_config_plan(GENERATED, None, remote)
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        assert not build_managed_config_plan(GENERATED, None, remote).changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, GENERATED, None, activation="none",
        confirm=confirm, snapshot_root=str(tmp_path / "snapshots"), verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "sensor" in result.detail
    confirm.assert_not_called()
    assert transport.files == remote


@pytest.mark.parametrize("section", ("extruder", "extruder1", "heater_bed", "heater_generic chamber",
                                    "temperature_sensor chamber", "temperature_fan chamber",
                                    "temperature_probe coil", "z_thermal_adjust"))
def test_thermal_consumers_check_references(section):
    from core.thermistor import validate_sensor_references
    with pytest.raises(GenerationError, match="Unknown.*sensor"):
        validate_sensor_references({section: {"sensor_type": "MissingCurve"}})


@pytest.mark.parametrize("sensor", NON_ADC)
def test_preserved_builtin_peripheral_name_is_recognized_without_certification(sensor):
    from core.thermistor import validate_sensor_references
    validate_sensor_references({"temperature_sensor chamber": {"sensor_type": sensor}})


@pytest.mark.parametrize("section", ("load_cell", "load_cell_probe", "probe_eddy_current probe"))
def test_other_sensor_namespaces_are_not_thermal_factories(section):
    from core.thermistor import validate_sensor_references
    validate_sensor_references({section: {"sensor_type": "NotAThermalFactory"}})


@pytest.mark.parametrize("kind", ("thermistor", "adc_temperature"))
@pytest.mark.parametrize("reference,valid", (("MyCurve", True), ("mycurve", False), ("MissingCurve", False)))
def test_custom_reference_uses_exact_case_in_effective_includes(kind, reference, valid):
    options = BETA if kind == "thermistor" else {"temperature1": "25", "voltage1": "1", "temperature2": "100", "voltage2": "2"}
    definition = f"[{kind} MyCurve]\n" + "\n".join(f"{key}: {value}" for key, value in options.items()) + "\n"
    remote = remote_files(definition + f"[temperature_sensor test]\nsensor_type: {reference}\nsensor_pin: PC11\n")
    result = validate_configuration_plan(build_managed_config_plan(GENERATED, None, remote))
    assert (not any(error.code == "sensor-reference" for error in result.errors)) == valid


def test_official_custom_name_whitespace_normalization():
    from core.thermistor import validate_sensor_references
    validate_sensor_references({"thermistor My   Curve": BETA,
                                "temperature_sensor test": {"sensor_type": "My Curve"}})


@pytest.mark.parametrize("section", ("thermistor MAX31865", "adc_temperature temperature_mcu",
                                    "thermistor Generic 3950"))
def test_custom_factory_cannot_shadow_builtin(section):
    from core.thermistor import validate_sensor_references
    with pytest.raises(GenerationError, match="ambiguous sensor factory"):
        validate_sensor_references({section: BETA})


def test_custom_factories_cannot_collide_after_name_normalization():
    from core.thermistor import validate_sensor_references
    with pytest.raises(GenerationError, match="ambiguous sensor factory"):
        validate_sensor_references({"thermistor My  Curve": BETA, "adc_temperature My Curve": {}})
