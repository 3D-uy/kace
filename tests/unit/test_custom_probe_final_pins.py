"""Standard custom probes must pass the final, identity-bound pin gates."""
from unittest.mock import patch

import pytest

from core.custom_probe import parse_custom_probe_config, GuidedCustomProbeSettings
from core.exceptions import GenerationError
from core.generator import generate_config
from core.pin_validator import validate_probe_pin_usage, PinAliasError
from core.configuration_review import validate_configuration_plan
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.deployer import _run_config_transaction
from core.firmware_workflow import generation_pin_reservations
from core.managed_config import build_managed_config_plan
from core.workflow_outcome import WorkflowOutcome
from tests.unit.test_generator import _parsed, _user
from tests.unit.test_firmware_pin_reservations import artifact, resumed_user, FINGERPRINT
from tests.unit.test_peripheral_bus_reservations import peripheral_firmware
from tests.unit.test_reserved_pin_review import assert_untouched
from tests.unit.test_config_transaction import GENERATED, FakeTransport

STANDARD = GENERATED + b"# PROBE_CALIBRATE\n[stepper_z]\nendstop_pin: probe:z_virtual_endstop\n[probe]\npin: ^PB8\n"


def custom(pin):
    return parse_custom_probe_config(f"[probe]\npin: {pin}\nx_offset: 0\ny_offset: 0\nz_offset: 0\n")


@pytest.mark.parametrize("token", ["", "!!PB8", "!^PB8", "mcu:^PB8", "<GND>"])
def test_malformed_custom_pin_rejected(token):
    with pytest.raises(PinAliasError):
        validate_probe_pin_usage(f"[probe]\npin: {token}\n")


@pytest.mark.parametrize("pin", ["PB8", "^PB8", "~!PB8", "^mcu:PB8", "^HEADER"])
def test_custom_pin_uses_aliases_and_firmware_reservations(pin):
    cfg = f"[probe]\npin: {pin}\n[board_pins]\naliases: HEADER=PB8\n"
    with pytest.raises(PinAliasError, match="reserved by firmware for CAN"):
        validate_probe_pin_usage(cfg, firmware_reservations={"mcu": {"PB8": "CAN"}})
    validate_probe_pin_usage(cfg, firmware_reservations={"toolhead": {"PB8": "CAN"}})


@pytest.mark.parametrize("section,field", [("stepper_x", "step_pin"), ("stepper_z", "endstop_pin"),
    ("heater_bed", "heater_pin"), ("fan", "pin"), ("display", "encoder_pins")])
def test_custom_probe_is_exclusive(section, field):
    cfg = f"[probe]\npin: ^PB8\n[{section}]\n{field}: PB8\n"
    with pytest.raises(PinAliasError, match="conflicts"):
        validate_probe_pin_usage(cfg)


def test_virtual_z_and_macro_variables_do_not_claim_probe_gpio():
    validate_probe_pin_usage("[probe]\npin: ~!PB8\n[stepper_z]\nendstop_pin: probe:z_virtual_endstop\n"
                             "[gcode_macro ATTACH]\nvariable_pin: 'PB8'\ngcode:\n  G4 P1\n")


def test_probe_from_user_include_alone_requires_firmware_evidence(tmp_path):
    built = artifact(tmp_path, {"RESERVE_PINS_USB": "PB14,PB15"})
    remote = {"printer.cfg": GENERATED + b"[include user.cfg]\n",
              "user.cfg": b"[probe]\npin: PB14\nz_offset: 0\n"}
    plan = build_managed_config_plan(GENERATED, None, remote)
    result = validate_configuration_plan(plan, firmware_reservation_reader=lambda text:
        generation_pin_reservations({"firmware_artifact": built}, config=text))
    assert any(error.code == "probe-pin-conflict" and "USB" in error.message for error in result.errors)


def test_old_positive_fixture_collision_is_explicitly_rejected(tmp_path):
    output = tmp_path / "printer.cfg"
    output.write_text("previous", encoding="utf-8")
    with pytest.raises(GenerationError, match=r"conflicts with \[stepper_x\] step_pin"):
        generate_config(_parsed(), _user(probe_kind="custom", custom_probe=custom("^PA1")), str(output), verbose=False)
    assert output.read_text() == "previous"


@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize("guided", [False, True])
def test_raw_guided_and_resumed_generation_reject_reservations(tmp_path, resume, guided):
    built = artifact(tmp_path, {"RESERVE_PINS_CAN": "PB8,PB9"})
    user = resumed_user(built) if resume else _user(firmware_artifact=built)
    payload = GuidedCustomProbeSettings(pin="^PB8", x_offset=0, y_offset=0).to_config() if guided else custom("^PB8")
    user.update(probe_kind="custom", custom_probe=payload)
    with pytest.raises(GenerationError, match="reserved by firmware for CAN"):
        generate_config(_parsed(), user, str(tmp_path / "printer.cfg"), verbose=False)
    assert not (tmp_path / "printer.cfg").exists()
    assert not (tmp_path / "printer.cfg.provenance.json").exists()


def test_raw_pull_down_and_macros_are_preserved_when_not_reserved(tmp_path):
    payload = custom("~!PB8")
    result = generate_config(_parsed(), _user(probe_kind="custom", custom_probe=payload),
                             str(tmp_path / "printer.cfg"), verbose=False)
    assert payload.config_text in result["content"]


def test_inductive_generation_reads_bound_reservations(tmp_path):
    built = artifact(tmp_path, {"RESERVE_PINS_CAN": "PB8,PB9"})
    with pytest.raises(GenerationError, match="reserved"):
        generate_config(_parsed(probe={"pin": "^PB8"}), _user(probe="Inductive", firmware_artifact=built),
                         str(tmp_path / "printer.cfg"), verbose=False)


@pytest.mark.parametrize("extra,expected", [
    (b"[probe]\npin: PB14\n", False),
    (b"[probe]\npin: toolhead:PB14\n", True),
])
def test_live_adapter_rejects_reserved_custom_include_with_mcu_scope(tmp_path, extra, expected):
    built = artifact(tmp_path, {"RESERVE_PINS_USB1": "PB14,PB15"})
    original = {"printer.cfg": GENERATED + b"[include user.cfg]\n", "user.cfg": b"[include pin.cfg]\n",
                "pin.cfg": extra}
    transport = FakeTransport(original)
    with patch("core.deployer._preflight_check", return_value=True), patch(
        "core.deployer._interactive_configuration_review", return_value=True):
        result = _run_config_transaction(transport, {"firmware_artifact": built}, "none",
                                         generated=(str(tmp_path / "source.cfg"), STANDARD, None))
    if expected:
        assert result.outcome == WorkflowOutcome.DEPLOYED_PENDING_ACTIVATION
    else:
        assert result.outcome == WorkflowOutcome.PRECONDITION_FAILED
        assert "USB1" in result.detail
        assert_untouched(transport, original)


def test_noop_cannot_skip_custom_i2c_bus_review(tmp_path):
    built = peripheral_firmware(tmp_path)
    config = STANDARD + b"[temperature_sensor t]\nsensor_type: BME280\n"
    plan = build_managed_config_plan(config, None, {})
    original = {item.remote_name: item.content for item in plan.artifacts}
    assert not build_managed_config_plan(config, None, original).changed_artifacts
    transport = FakeTransport(original)
    result = ConfigDeploymentTransaction(transport, config, None, activation="none", verify_existing_ready=True,
        snapshot_root=str(tmp_path / "snapshots"), firmware_reservation_reader=lambda text:
        generation_pin_reservations({"firmware_artifact": built}, config=text)).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "i2c1" in result.detail
    assert_untouched(transport, original)


def test_missing_metadata_fails_for_standard_probe(tmp_path):
    built = artifact(tmp_path, payload=FINGERPRINT.encode())
    plan = build_managed_config_plan(STANDARD, None, {})
    result = validate_configuration_plan(plan, firmware_reservation_reader=lambda text:
        generation_pin_reservations({"firmware_artifact": built}, config=text))
    assert any(error.code == "firmware-pin-evidence" for error in result.errors)


def test_custom_firmware_rechecked_after_confirmation(tmp_path):
    built = artifact(tmp_path)
    original = {"printer.cfg": GENERATED}
    transport = FakeTransport(original)
    def confirm(_):
        with open(built.path, "ab") as stream:
            stream.write(b"changed")
        return True
    result = ConfigDeploymentTransaction(transport, STANDARD, None, activation="none", confirm=confirm,
        snapshot_root=str(tmp_path / "snapshots"), firmware_reservation_reader=lambda text:
        generation_pin_reservations({"firmware_artifact": built}, config=text)).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert_untouched(transport, original)
