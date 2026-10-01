"""Preserved custom ADC definitions must remain usable by their consumers."""
import copy
from unittest.mock import Mock

import pytest

from core.exceptions import GenerationError
from core.thermistor import validate_adc_sensor_options, validate_sensor_references
from core.configuration_review import validate_configuration_plan
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.pin_validator import _read_pin_config
from tests.unit.test_config_transaction import FakeTransport, GENERATED
from tests.unit.test_tmc_uart_review import remote_files


VOLTAGE = {"temperature1": "25", "voltage1": "1", "temperature2": "100", "voltage2": "2"}
RESISTANCE = {"temperature1": "25", "resistance1": "100", "temperature2": "100", "resistance2": "200"}
# (id, definition, consumer options, classification against upstream)
INVALID = [
    ("empty", {}, {}, "schema"),
    ("one-point", {"temperature1": "25", "voltage1": "1"}, {}, "schema"),
    ("missing-pair", {"temperature1": "25", "temperature2": "100", "voltage2": "2"}, {}, "schema"),
    ("gap", {"temperature1": "25", "voltage1": "1", "temperature3": "100", "voltage3": "2"}, {}, "schema"),
    ("mixed", {**VOLTAGE, "resistance1": "100", "resistance2": "200"}, {}, "unused"),
    ("unused", {**VOLTAGE, "gcode": "M112"}, {}, "unused"),
    ("past-limit", {**VOLTAGE, "temperature1000": "200", "voltage1000": "3"}, {}, "unused"),
    ("nan", {**VOLTAGE, "temperature1": "nan"}, {}, "finite-policy"),
    ("inf", {**RESISTANCE, "resistance1": "inf"}, {}, "finite-policy"),
    ("bad-number", {**VOLTAGE, "voltage1": "wrong"}, {}, "schema"),
    ("duplicate-voltage", {**VOLTAGE, "voltage2": "1"}, {}, "duplicate"),
    ("duplicate-resistance", {**RESISTANCE, "resistance2": "100"}, {}, "duplicate"),
    ("flat", {**VOLTAGE, "temperature2": "25"}, {}, "invertibility-policy"),
    ("turning", {**VOLTAGE, "temperature3": "50", "voltage3": "3"}, {}, "invertibility-policy"),
    ("negative-resistance", {**RESISTANCE, "resistance1": "-100"}, {}, "physical-policy"),
    ("below-absolute-zero", {**VOLTAGE, "temperature1": "-274"}, {}, "physical-policy"),
    ("slope-overflow", {**VOLTAGE, "voltage2": "1.0000000000000002", "temperature2": "1e308"}, {}, "finite-policy"),
    ("offset-overflow", {"temperature1": "1e308", "voltage1": "1", "temperature2": "0", "voltage2": "2"}, {}, "finite-policy"),
    ("no-usable-points", VOLTAGE, {"voltage_offset": "10"}, "window"),
    ("one-usable-point", VOLTAGE, {"adc_voltage": "1.5"}, "window"),
    ("collapsed-points", VOLTAGE, {"adc_voltage": "1e308", "voltage_offset": "-1e308"}, "duplicate"),
]


def sections(table, consumer=None, *, name="Curve", header=None):
    return {header or "adc_temperature " + name: dict(table),
            "temperature_sensor test": {"sensor_type": name, "sensor_pin": "PC11", **(consumer or {})}}


def text_of(items):
    return "\n".join(f"[{section}]\n" + "\n".join(f"{key}: {value}" for key, value in options.items()) + "\n"
                     for section, options in items.items())


@pytest.mark.parametrize("case,table,consumer,classification", INVALID, ids=[case[0] for case in INVALID])
def test_invalid_table_or_consumer_is_rejected(case, table, consumer, classification):
    with pytest.raises(GenerationError):
        validate_adc_sensor_options(sections(table, consumer))


@pytest.mark.parametrize("case,table,consumer,classification", INVALID, ids=[case[0] for case in INVALID])
@pytest.mark.parametrize("noop", (False, True))
def test_bad_preserved_table_blocks_transaction_before_confirmation(tmp_path, noop, case, table, consumer, classification):
    remote = remote_files(text_of(sections(table, consumer)))
    if noop:
        plan = build_managed_config_plan(GENERATED, None, remote)
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        assert not build_managed_config_plan(GENERATED, None, remote).changed_artifacts
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, GENERATED, None, activation="none", confirm=confirm,
        snapshot_root=str(tmp_path / "snapshots"), verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    confirm.assert_not_called()
    assert transport.files == remote


@pytest.mark.parametrize("table", (VOLTAGE, RESISTANCE))
@pytest.mark.parametrize("descending", (False, True))
@pytest.mark.parametrize("header", ("adc_temperature Curve", "adc_temperature\tCurve"))
def test_monotonic_tables_survive_reconciliation_without_mutation(table, descending, header):
    table = dict(table)
    if descending:
        table["temperature1"], table["temperature2"] = table["temperature2"], table["temperature1"]
    values = sections(table, header=header)
    before = copy.deepcopy(values)
    validate_adc_sensor_options(values)
    remote = remote_files(text_of(values))
    plan = build_managed_config_plan(GENERATED, None, remote)
    assert validate_configuration_plan(plan).valid
    effective = _read_pin_config(effective_hardware_text(plan))[0]
    assert effective[header] == table
    assert values == before


def test_calibration_window_is_evaluated_for_each_consumer():
    values = sections(VOLTAGE)
    values["temperature_sensor second"] = {"sensor_type": "Curve", "adc_voltage": "1.5"}
    with pytest.raises(GenerationError, match="second"):
        validate_adc_sensor_options(values)


def test_discarded_voltage_samples_do_not_poison_valid_window():
    values = sections({**VOLTAGE, "temperature3": "50", "voltage3": "10"})
    # Upstream ignores the third point for this consumer. Only the usable curve
    # must be invertible; do not reject an unused out-of-window turning point.
    validate_adc_sensor_options(values)


def test_definition_schema_is_checked_even_without_consumer():
    with pytest.raises(GenerationError):
        validate_adc_sensor_options({"adc_temperature unused": {"temperature1": "25", "voltage1": "1"}})


def test_official_999_pair_limit_is_accepted():
    table = {}
    for index in range(1, 1000):
        table[f"temperature{index}"] = str(index)
        table[f"voltage{index}"] = str(index / 1000)
    validate_adc_sensor_options(sections(table))


def test_default_adc_loader_is_not_an_unnamed_custom_sensor():
    validate_sensor_references({"adc_temperature": {}, "temperature_sensor test": {"sensor_type": "PT1000"}})


def test_tab_delimited_custom_thermistor_cannot_bypass_numeric_schema():
    from core.thermistor import validate_custom_thermistors
    with pytest.raises(GenerationError, match="beta"):
        validate_custom_thermistors({"thermistor\tCurve": {"temperature1": "25", "resistance1": "100000", "beta": "0"}})


@pytest.mark.parametrize("invalid", (False, True))
def test_case_distinct_thermistor_definitions_are_validated_individually(invalid):
    definitions = {
        "thermistor Curve": {"temperature1": "25", "resistance1": "100000", "beta": "0" if invalid else "3950"},
        "thermistor curve": {"temperature1": "20", "resistance1": "140000", "temperature2": "195",
                             "resistance2": "593", "temperature3": "255", "resistance3": "189"},
        "temperature_sensor test": {"sensor_type": "Curve", "sensor_pin": "PC11"},
    }
    review = validate_configuration_plan(build_managed_config_plan(GENERATED, None, remote_files(text_of(definitions))))
    assert review.valid == (not invalid)


def test_later_case_distinct_valid_beta_cannot_hide_an_invalid_definition():
    beta = {"temperature1": "25", "resistance1": "100000", "beta": "3950"}
    remote = remote_files(text_of({"thermistor Curve": {**beta, "beta": "0"}, "thermistor curve": beta}))
    review = validate_configuration_plan(build_managed_config_plan(GENERATED, None, remote))
    assert any(error.code == "custom-thermistor" for error in review.errors)


def test_later_include_overrides_are_checked_as_effective_values():
    remote = remote_files(text_of(sections(VOLTAGE)))
    remote["wiring.cfg"] += b"\n[include later.cfg]\n"
    remote["later.cfg"] = b"[adc_temperature Curve]\nvoltage2: 1\n"
    result = validate_configuration_plan(build_managed_config_plan(GENERATED, None, remote))
    assert any(error.code == "adc-sensor-options" for error in result.errors)


@pytest.mark.parametrize("kind,table", (("thermistor", {"temperature1": "25", "resistance1": "100000", "beta": "3950"}), ("adc_temperature", VOLTAGE)))
@pytest.mark.parametrize("consumer", ("extruder", "heater_bed", "temperature_sensor test", "temperature_fan test"))
def test_custom_definition_must_precede_its_first_use(kind, table, consumer):
    values = {consumer: {"sensor_type": "Curve"}, kind + " Curve": table}
    with pytest.raises(GenerationError, match="before"):
        validate_sensor_references(values)
    validate_sensor_references(dict(reversed(list(values.items()))))


@pytest.mark.parametrize("noop", (False, True))
def test_forward_reference_in_separate_include_blocks_publication(tmp_path, noop):
    remote = remote_files(text_of({"temperature_sensor test": {"sensor_type": "Curve", "sensor_pin": "PC11"}})
                          + "\n[include curve.cfg]\n")
    remote["curve.cfg"] = text_of({"adc_temperature Curve": VOLTAGE}).encode()
    if noop:
        plan = build_managed_config_plan(GENERATED, None, remote)
        remote.update({a.remote_name: a.content for a in plan.artifacts})
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, GENERATED, None, activation="none", confirm=confirm,
        snapshot_root=str(tmp_path / "snapshots"), verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "before" in result.detail
    confirm.assert_not_called()
    assert transport.files == remote
