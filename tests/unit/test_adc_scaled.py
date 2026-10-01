"""Selected scaled ADC circuits retain dependencies and physical pin identity."""
import json
from unittest.mock import Mock

import pytest

from core.exceptions import GenerationError
from core.configuration_review import validate_configuration_plan
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.managed_config import build_managed_config_plan, effective_hardware_text
from core.pin_validator import PinAliases, _read_pin_config
from tests.unit.test_adc_sensor_options import inputs, render
from tests.unit.test_config_transaction import FakeTransport, GENERATED
from tests.unit.test_tmc_uart_review import remote_files


REFERENCE = {"vref_pin": "PF1", "vssa_pin": "PF2", "smooth_time": "1.5"}


def circuit(**options):
    return {"mcu": {"serial": "/tmp/test"}, "adc_scaled Scaled": {**REFERENCE, **options},
            "temperature_sensor test": {"sensor_type": "Generic 3950", "sensor_pin": "Scaled:PF3"}}


def text_of(sections):
    return "\n".join(f"[{name}]\n" + "\n".join(f"{key}: {value}" for key, value in options.items()) + "\n"
                     for name, options in sections.items())


@pytest.mark.parametrize("section", ("extruder", "heater_bed"))
@pytest.mark.parametrize("scraped", (False, True))
def test_selected_board_dependency_survives_generation_reconciliation_and_noop(tmp_path, section, scraped):
    board, user = inputs("Generic 3950", section, sensor_pin="Scaled:PF3", pullup_resistor="2200")
    board["adc_scaled scaled" if scraped else "adc_scaled Scaled"] = dict(REFERENCE)
    board["adc_scaled unused"] = {"vref_pin": "invalid"}
    user["_profile_parsed"] = {"adc_scaled Scaled": {"vref_pin": "PA1", "vssa_pin": "PA2"}}
    content = render(tmp_path, board, user)
    sections = _read_pin_config(content)[0]
    assert sections["adc_scaled Scaled"] == REFERENCE
    assert "adc_scaled unused" not in sections
    assert list(sections).index("adc_scaled Scaled") < list(sections).index(section)
    provenance = json.loads((tmp_path / "printer.cfg.provenance.json").read_text())
    assert provenance["sources"]["adc_scaled"] == {"adc_scaled Scaled": REFERENCE}
    remote = {"printer.cfg": content.encode()}
    plan = build_managed_config_plan(content.encode(), None, remote)
    assert validate_configuration_plan(plan).valid
    assert _read_pin_config(effective_hardware_text(plan))[0]["adc_scaled Scaled"] == REFERENCE
    remote.update({a.remote_name: a.content for a in plan.artifacts})
    assert not build_managed_config_plan(content.encode(), None, remote).changed_artifacts


@pytest.mark.parametrize("changes", ({"vref_pin": ""}, {"vssa_pin": "!PF2"}, {"vref_pin": "other:PF1"},
    {"smooth_time": "0"}, {"smooth_time": "nan"}, {"smooth_time": "inf"}, {"unused": "1"},
    {"vssa_pin": "PF1"}, {"vref_pin": "Scaled:PF1"}))
def test_invalid_selected_provider_fails_before_output(tmp_path, changes):
    board, user = inputs("Generic 3950", sensor_pin="Scaled:PF3")
    board["adc_scaled Scaled"] = {**REFERENCE, **changes}
    with pytest.raises(GenerationError, match="ADC scaled"):
        render(tmp_path, board, user)
    assert not (tmp_path / "printer.cfg").exists()


@pytest.mark.parametrize("pin", ("PF1", "PF2", "PF3", "mcu:PF3", "Scaled:PF3"))
@pytest.mark.parametrize("noop", (False, True))
def test_effective_collision_blocks_publication_before_confirmation(tmp_path, pin, noop):
    extra = text_of(circuit()).replace("[mcu]\nserial: /tmp/test\n", "")
    remote = remote_files(extra + f"[output_pin conflict]\npin: {pin}\n")
    if noop:
        plan = build_managed_config_plan(GENERATED, None, remote)
        remote.update({a.remote_name: a.content for a in plan.artifacts})
    transport, confirm = FakeTransport(remote), Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, GENERATED, None, activation="none",
        confirm=confirm, snapshot_root=str(tmp_path / "snapshots"), verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "ADC scaled" in result.detail
    confirm.assert_not_called()
    assert remote == transport.files


def test_aliases_resolve_on_physical_mcu_not_virtual_chip():
    sections = circuit()
    sections["board_pins physical"] = {"aliases": "SENSOR=PF3"}
    assert PinAliases(sections).resolve("Scaled:SENSOR") == ("mcu", "PF3")


def test_scaled_pin_uses_reference_mcu_identity():
    sections = circuit(vref_pin="tool:PF1", vssa_pin="tool:PF2")
    sections["mcu tool"] = {"serial": "/tmp/tool"}
    assert PinAliases(sections).resolve("Scaled:PF3") == ("tool", "PF3")


@pytest.mark.parametrize("section,pin", (("adc_scaled Scaled", "PF1"), ("temperature_sensor test", "PF3")))
def test_bound_firmware_reservations_cover_refs_and_sensor(section, pin):
    from core.adc_scaled import validate_adc_scaled
    with pytest.raises(GenerationError, match="reserved"):
        validate_adc_scaled(circuit(), firmware_reservations={"mcu": {pin: "selected bus"}})


def test_alias_collision_and_duplicate_override_do_not_bypass_exclusive_adc():
    from core.adc_scaled import validate_adc_scaled
    sections = circuit()
    sections["board_pins physical"] = {"aliases": "SENSOR=PF3"}
    sections["duplicate_pin_override"] = {"pins": "PF3"}
    sections["fan"] = {"pin": "SENSOR"}
    with pytest.raises(GenerationError, match="conflicts"):
        validate_adc_scaled(sections)


def test_different_mcus_with_same_pin_spelling_do_not_collide():
    from core.adc_scaled import validate_adc_scaled
    sections = circuit()
    sections["mcu tool"] = {"serial": "/tmp/tool"}
    sections["fan"] = {"pin": "tool:PF3"}
    validate_adc_scaled(sections)


def test_provider_must_precede_consumers():
    from core.adc_scaled import validate_adc_scaled
    sections = circuit()
    values = sections.pop("adc_scaled Scaled")
    sections["adc_scaled Scaled"] = values
    with pytest.raises(GenerationError, match="before"):
        validate_adc_scaled(sections)


def test_non_adc_use_of_virtual_chip_is_rejected():
    from core.adc_scaled import validate_adc_scaled
    sections = circuit()
    sections["fan"] = {"pin": "Scaled:PF4"}
    with pytest.raises(GenerationError, match="only ADC"):
        validate_adc_scaled(sections)


def test_provider_cannot_shadow_mcu():
    from core.adc_scaled import validate_adc_scaled
    sections = circuit()
    sections["mcu Scaled"] = {"serial": "/tmp/tool"}
    with pytest.raises(GenerationError, match="duplicate"):
        validate_adc_scaled(sections)


@pytest.mark.parametrize("pin", ("PF1", "PF2", "PF3"))
def test_effective_review_reads_bound_firmware_reservations_without_a_probe(pin):
    text = GENERATED + text_of({name: options for name, options in circuit().items() if name != "mcu"}).encode()
    plan = build_managed_config_plan(text, None, {"printer.cfg": text})
    reader = Mock(return_value={"mcu": {pin: "SPI bus from bound firmware"}})
    result = validate_configuration_plan(plan, firmware_reservation_reader=reader)
    reader.assert_called_once()
    assert any(error.code == "adc-scaled" and "reserved" in error.message for error in result.errors)


def test_generation_reads_bound_reservations_for_scaler_without_a_probe(tmp_path, monkeypatch):
    board, user = inputs("Generic 3950", sensor_pin="Scaled:PF3")
    board["adc_scaled Scaled"] = REFERENCE
    reader = Mock(return_value={"mcu": {"PF3": "firmware bus"}})
    monkeypatch.setattr("core.firmware_workflow.generation_pin_reservations", reader)
    with pytest.raises(GenerationError, match="reserved"):
        render(tmp_path, board, user)
    reader.assert_called_once()
    assert not (tmp_path / "printer.cfg").exists()


def test_printer_profile_cannot_supply_a_missing_board_scaler(tmp_path):
    board, user = inputs("Generic 3950", sensor_pin="Scaled:PF3")
    user["_profile_parsed"] = {"adc_scaled Scaled": REFERENCE}
    with pytest.raises(GenerationError, match="ADC pin chip"):
        render(tmp_path, board, user)


def test_conflicting_scraped_definitions_fail_instead_of_guessing(tmp_path):
    board, user = inputs("Generic 3950", sensor_pin="Scaled:PF3")
    board["adc_scaled Scaled"] = REFERENCE
    board["adc_scaled scaled"] = {**REFERENCE, "vref_pin": "PF4"}
    with pytest.raises(GenerationError, match="conflicting board definition"):
        render(tmp_path, board, user)


def test_reference_mcus_must_agree_even_when_both_declared():
    from core.adc_scaled import validate_adc_scaled
    sections = circuit(vssa_pin="tool:PF2")
    sections["mcu tool"] = {"serial": "/tmp/tool"}
    with pytest.raises(GenerationError, match="same MCU"):
        validate_adc_scaled(sections)


def test_probe_checker_sees_the_scaled_sensor_physical_pin():
    from core.pin_validator import validate_probe_pin_usage, PinAliasError
    sections = circuit()
    sections["probe"] = {"pin": "PF3", "z_offset": "0"}
    with pytest.raises(PinAliasError, match="conflicts"):
        validate_probe_pin_usage(text_of(sections))


def test_tab_separated_scaler_still_requests_firmware_evidence():
    text = GENERATED + text_of({name: options for name, options in circuit().items() if name != "mcu"}).replace(
        "[adc_scaled Scaled]", "[adc_scaled\tScaled]").encode()
    reader = Mock(return_value={"mcu": {"PF3": "firmware bus"}})
    result = validate_configuration_plan(build_managed_config_plan(text, None, {"printer.cfg": text}),
                                         firmware_reservation_reader=reader)
    reader.assert_called_once()
    assert any(error.code == "adc-scaled" and "reserved" in error.message for error in result.errors)
