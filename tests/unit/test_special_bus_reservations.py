"""Special sensors and unavailable host evidence cannot bypass pin review."""
import pytest

from core.bus_pins import hardware_bus_requests
from core.pin_validator import PinAliasError
from core.firmware_workflow import generation_pin_reservations
from firmware.identity import FirmwareIdentityError
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.managed_config import build_managed_config_plan
from tests.unit.test_config_transaction import FakeTransport, GENERATED
from tests.unit.test_reserved_pin_review import PROBE, assert_untouched
from tests.unit.test_peripheral_bus_reservations import peripheral_firmware
from tests.unit.test_firmware_pin_reservations import resumed_user


@pytest.mark.parametrize("section", ["load_cell", "load_cell scale", "load_cell_probe"])
@pytest.mark.parametrize("sensor", ["ads1220", "ads131m02", "ads131m04"])
def test_load_cell_dispatch_and_cs_mcu(section, sensor):
    assert hardware_bus_requests({section: {"sensor_type": sensor, "cs_pin": "toolhead:PC8"}}) == {
        "toolhead": [("spi_bus", None)]}


@pytest.mark.parametrize("sensor", ["hx711", "hx717"])
def test_hx_interfaces_do_not_activate_spi(sensor):
    assert hardware_bus_requests({"load_cell_probe": {"sensor_type": sensor, "spi_bus": "spi1"}}) == {}


@pytest.mark.parametrize("section,sensor", [("load_cell", "ADS1220"), ("load_cell", "future"),
    ("load_cell_probe", None), ("probe_eddy_current p", "future"), ("probe_eddy_current p", None)])
def test_unknown_dispatch_fails_instead_of_claiming_no_bus(section, sensor):
    with pytest.raises(PinAliasError, match="sensor_type"):
        hardware_bus_requests({section: {"sensor_type": sensor}})


def test_eddy_default_and_software_bus_use_standard_i2c_rules():
    opts = {"sensor_type": "ldc1612", "i2c_mcu": "toolhead", "i2c_bus": "i2c2"}
    assert hardware_bus_requests({"probe_eddy_current p": opts}) == {"toolhead": [("i2c_bus", "i2c2")]}
    opts.update(i2c_software_scl_pin="toolhead:PC8", i2c_software_sda_pin="toolhead:PC9")
    assert hardware_bus_requests({"probe_eddy_current p": opts}) == {}


def test_load_cell_software_spi_has_no_implicit_hardware_reservation():
    assert hardware_bus_requests({"load_cell_probe": {"sensor_type": "ads1220", "cs_pin": "PC8",
        "spi_software_sclk_pin": "PC9", "spi_software_miso_pin": "PC10", "spi_software_mosi_pin": "PC11"}}) == {}


@pytest.mark.parametrize("host", ["mcu", "host", "toolhead"])
def test_replicape_never_guesses_host_bus_or_pru_reservations(host):
    with pytest.raises(PinAliasError, match="host-specific SPI/PWM and PRU evidence"):
        hardware_bus_requests({"replicape": {"host_mcu": host, "revision": "B3"}})


@pytest.mark.parametrize("extra,reason", [
    ("[load_cell scale]\nsensor_type: ads1220\ncs_pin: PC8\n", "spi1"),
    ("[probe_eddy_current p]\nsensor_type: ldc1612\n", "i2c1"),
    ("[replicape]\nhost_mcu: host\nrevision: B3\n", "host-specific"),
])
@pytest.mark.parametrize("resume", [False, True])
def test_nested_include_and_noop_resume_are_rejected_before_writes(tmp_path, extra, reason, resume):
    built = peripheral_firmware(tmp_path)
    user = resumed_user(built) if resume else {"firmware_artifact": built}
    remote = {"printer.cfg": GENERATED + b"[include user.cfg]\n", "user.cfg": b"[include special.cfg]\n",
              "special.cfg": extra.encode()}
    plan = build_managed_config_plan(PROBE, None, remote)
    remote.update({item.remote_name: item.content for item in plan.artifacts})
    assert not build_managed_config_plan(PROBE, None, remote).changed_artifacts
    transport = FakeTransport(remote)
    result = ConfigDeploymentTransaction(transport, PROBE, None, activation="none",
        snapshot_root=str(tmp_path / "snapshots"), verify_existing_ready=True,
        firmware_reservation_reader=lambda hardware: generation_pin_reservations(user, config=hardware)).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert reason in result.detail
    assert_untouched(transport, remote)


def test_configuration_only_does_not_claim_host_evidence():
    assert generation_pin_reservations({}, config="[replicape]\nhost_mcu: host\n") == {}


def test_bound_artifact_does_not_substitute_for_replicape_host_evidence(tmp_path):
    built = peripheral_firmware(tmp_path)
    with pytest.raises(FirmwareIdentityError, match="host-specific"):
        generation_pin_reservations({"firmware_artifact": built}, config="[replicape]\nhost_mcu: host\n")
