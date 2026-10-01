"""ADC options must follow the selected Klipper sensor factory."""
import json
from unittest.mock import Mock

import pytest

from core.exceptions import GenerationError
from core.generator import generate_config
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.firmware_workflow import persistable_wizard_data
from core.scraper import parse_config
from data.profiles import THERMISTOR_PRESETS
from tests.unit.test_generator import _parsed, _user
from tests.unit.test_config_transaction import FakeTransport, GENERATED
from tests.unit.test_tmc_uart_review import remote_files


VALUES = {"pullup_resistor": "2200", "inline_resistor": "0", "adc_voltage": "3.3", "voltage_offset": "0.1"}


def accepted(sensor, option):
    if sensor == "PT100 INA826":
        return option in ("adc_voltage", "voltage_offset")
    if sensor == "PT1000":
        return option == "pullup_resistor"
    return option in ("pullup_resistor", "inline_resistor")


def inputs(sensor, section="extruder", **options):
    board, user = _parsed(), _user()
    board[section].update(options)
    user["hotend_thermistor" if section == "extruder" else "bed_thermistor"] = sensor
    return board, user


def render(tmp_path, board, user):
    return generate_config(board, user, output_path=str(tmp_path / "printer.cfg"), verbose=False)["content"]


@pytest.mark.parametrize("section", ("extruder", "heater_bed"))
@pytest.mark.parametrize("sensor", THERMISTOR_PRESETS)
@pytest.mark.parametrize("option,value", VALUES.items())
def test_preset_option_matrix(tmp_path, section, sensor, option, value):
    board, user = inputs(sensor, section, **{option: value})
    if not accepted(sensor, option):
        with pytest.raises(GenerationError, match=option):
            render(tmp_path, board, user)
        assert not (tmp_path / "printer.cfg").exists()
    else:
        text = render(tmp_path, board, user)
        assert parse_config(text)[section][option] == value
        plan = build_managed_config_plan(text.encode(), None, {"printer.cfg": text.encode()})
        assert validate_configuration_plan(plan).valid
        assert parse_config(effective_hardware_text(plan))[section][option] == value


@pytest.mark.parametrize("option,bad", [("adc_voltage", x) for x in ("0", "-1", "nan", "inf", "", None, True, "bad")]
                         + [("voltage_offset", x) for x in ("nan", "inf", "", None, True, "bad")])
def test_invalid_amplifier_numbers_fail_before_writing(tmp_path, option, bad):
    board, user = inputs("PT100 INA826", **{option: bad})
    with pytest.raises(GenerationError, match=option):
        render(tmp_path, board, user)
    assert not (tmp_path / "printer.cfg").exists()


@pytest.mark.parametrize("resume", (False, True))
def test_board_owns_amplifier_values_despite_printer_profile(tmp_path, resume):
    board, user = inputs("PT100 INA826", adc_voltage="3.3", voltage_offset="-0.1")
    user["_profile_parsed"] = {"extruder": {"adc_voltage": "5", "voltage_offset": "0.2"}}
    if resume:
        user = json.loads(json.dumps(persistable_wizard_data(user)))
    result = parse_config(render(tmp_path, board, user))["extruder"]
    assert result["adc_voltage"] == "3.3"
    assert result["voltage_offset"] == "-0.1"


@pytest.mark.parametrize("sensor,option", [("PT1000", "inline_resistor"), ("PT100 INA826", "pullup_resistor"), ("Generic 3950", "adc_voltage")])
@pytest.mark.parametrize("noop", (False, True))
def test_incompatible_preserved_sensor_blocks_transaction(tmp_path, sensor, option, noop):
    remote = remote_files(f"[temperature_sensor test]\nsensor_type: {sensor}\nsensor_pin: PC11\n{option}: {VALUES[option]}\n")
    if noop:
        plan = build_managed_config_plan(GENERATED, None, remote)
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        assert not build_managed_config_plan(GENERATED, None, remote).changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, GENERATED, None, activation="none", confirm=confirm,
        snapshot_root=str(tmp_path / "snapshots"), verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert option in result.detail
    confirm.assert_not_called()
    assert transport.files == remote


def test_custom_thermistor_uses_thermistor_options_in_effective_includes():
    remote = remote_files("[thermistor MyCurve]\ntemperature1: 25\nresistance1: 100000\nbeta: 3950\n"
                         "[temperature_sensor test]\nsensor_type: MyCurve\nsensor_pin: PC11\nadc_voltage: 3.3\n")
    result = validate_configuration_plan(build_managed_config_plan(GENERATED, None, remote))
    assert any(error.code == "adc-sensor-options" for error in result.errors)


@pytest.mark.parametrize("options", ({"adc_voltage": "0.001"}, {"voltage_offset": "100"}, {"adc_voltage": "1e-300"}))
def test_valid_numbers_cannot_remove_all_calibration_points(tmp_path, options):
    board, user = inputs("PT100 INA826", **options)
    with pytest.raises(GenerationError, match="fewer than two calibration samples"):
        render(tmp_path, board, user)
    remote = remote_files("[temperature_sensor test]\nsensor_type: PT100 INA826\nsensor_pin: PC11\n"
                         + "\n".join(f"{key}: {value}" for key, value in options.items()))
    assert not validate_configuration_plan(build_managed_config_plan(GENERATED, None, remote)).valid


def test_finite_extreme_values_cannot_collapse_calibration_points(tmp_path):
    board, user = inputs("PT100 INA826", adc_voltage="1e308", voltage_offset="-1e308")
    with pytest.raises(GenerationError, match="collapse calibration samples"):
        render(tmp_path, board, user)


@pytest.mark.parametrize("kind", ("voltage", "resistance"))
@pytest.mark.parametrize("option,value", VALUES.items())
def test_preserved_custom_adc_dispatch_uses_resistance1_presence(kind, option, value):
    from core.thermistor import validate_adc_sensor_options
    definition = {"temperature1": "25", "temperature2": "100", kind + "1": "1", kind + "2": "2"}
    sections = {"adc_temperature Custom": definition,
                "temperature_sensor test": {"sensor_type": "Custom", option: value}}
    supported = option == "pullup_resistor" if kind == "resistance" else option in ("adc_voltage", "voltage_offset")
    if supported:
        validate_adc_sensor_options(sections)
    else:
        with pytest.raises(GenerationError, match=option):
            validate_adc_sensor_options(sections)


@pytest.mark.parametrize("sections", (
    {"thermistor Generic 3950": {}},
    {"thermistor Custom": {}, "adc_temperature Custom": {}},
))
def test_ambiguous_factory_names_are_not_silently_resolved(sections):
    from core.thermistor import validate_adc_sensor_options
    with pytest.raises(GenerationError, match="ambiguous sensor factory name"):
        validate_adc_sensor_options(sections)
