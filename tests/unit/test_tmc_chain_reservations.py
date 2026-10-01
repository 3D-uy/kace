"""Reserve the chain's actual transport, never a follower's imaginary default."""
from unittest.mock import Mock, patch

import pytest

from core.bus_pins import tmc_bus_requests
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.firmware_workflow import generation_pin_reservations
from core.generator import generate_config
from core.managed_config import build_managed_config_plan
from core.pin_validator import PinAliasError
from core.profile_values import resolve_tmc_sections
from core.wizard.steps.sensors import make_pin_validator_with_collision_check
from tests.unit.test_config_transaction import FakeTransport, GENERATED
from tests.unit.test_firmware_pin_reservations import resumed_user
from tests.unit.test_generator import _parsed, _user
from tests.unit.test_reserved_pin_review import PROBE, assert_untouched
from tests.unit.test_tmc_bus_reservations import built_bus
from tests.unit.test_tmc_spi_chain import case_sections, config_text


SOFTWARE = {"spi_software_sclk_pin": "PB13", "spi_software_mosi_pin": "PB15", "spi_software_miso_pin": "PB14"}


def chain(model="tmc2130", mode="spi2", chip="mcu"):
    options = dict(SOFTWARE) if mode == "software" else ({"spi_bus": mode} if mode else {})
    if chip != "mcu":
        options = {key: f"{chip}:{value}" if key.endswith("_pin") else value for key, value in options.items()}
    return case_sections({"first": {"cs_pin": f"{chip}:PC11", **options},
                          "second": {"cs_pin": f"{chip}:PC11"},
                          "extra": {} if chip == "mcu" else {f"mcu {chip}": {"serial": "/dev/tool"}}}, model)


@pytest.mark.parametrize("model", ("tmc2130", "tmc5160"))
@pytest.mark.parametrize("mode", ("spi2", "software", None))
@pytest.mark.parametrize("chip", ("mcu", "Tool"))
def test_projection_has_only_owner_transport(model, mode, chip):
    expected = {} if mode == "software" else {chip: [("spi_bus", mode)]}
    assert tmc_bus_requests(chain(model, mode, chip)) == expected


@pytest.mark.parametrize("resume", (False, True))
@pytest.mark.parametrize("mode", ("spi2", "software"))
def test_runtime_and_resume_reserve_no_follower_default(tmp_path, resume, mode):
    built = built_bus(tmp_path)
    user = resumed_user(built) if resume else {"firmware_artifact": built}
    expected = {} if mode == "software" else {"PB12": "spi2", "PB13": "spi2", "PB14": "spi2"}
    assert generation_pin_reservations(user, config=config_text(chain(mode=mode))) == {"mcu": expected}


@pytest.mark.parametrize("mode", ("spi2", "software"))
def test_valid_chain_does_not_block_unrelated_probe_in_include(tmp_path, mode):
    built = built_bus(tmp_path)
    remote = {"printer.cfg": GENERATED + b"[include user.cfg]\n", "user.cfg": b"[include drivers.cfg]\n",
              "drivers.cfg": config_text(chain(mode=mode)).encode()}
    plan = build_managed_config_plan(PROBE, None, remote)
    result = validate_configuration_plan(plan, firmware_reservation_reader=lambda text:
        generation_pin_reservations({"firmware_artifact": built}, config=text))
    assert result.valid, result.errors


@pytest.mark.parametrize("model", ("tmc2130", "tmc5160"))
def test_generation_and_wizard_agree_on_shared_bus(tmp_path, model):
    built = built_bus(tmp_path)
    board = _parsed(**chain(model))
    user = _user(probe="BLTouch", driver_type=model.upper(), driver_mode="SPI", firmware_artifact=built)
    with patch("core.wizard.steps.sensors._get_parsed", return_value=board):
        validator = make_pin_validator_with_collision_check(user)
        assert validator("PB8") is True
        assert "spi2" in validator("PB14")
    board["bltouch"] = {"sensor_pin": "^PB8", "control_pin": "PB9"}
    generate_config(board, user, output_path=str(tmp_path / "printer.cfg"), verbose=False)


@pytest.mark.parametrize("noop", (False, True))
def test_real_owner_conflict_still_blocks_without_writes(tmp_path, noop):
    built = built_bus(tmp_path)
    generated = PROBE.replace(b"^PB8", b"^PB14")
    remote = {"printer.cfg": GENERATED + b"[include drivers.cfg]\n", "drivers.cfg": config_text(chain()).encode()}
    if noop:
        plan = build_managed_config_plan(generated, None, remote)
        remote.update({a.remote_name: a.content for a in plan.artifacts})
        assert not build_managed_config_plan(generated, None, remote).changed_artifacts
    transport = FakeTransport(remote)
    confirm = Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, generated, None, activation="none", confirm=confirm,
        snapshot_root=str(tmp_path / "snapshots"), verify_existing_ready=noop,
        firmware_reservation_reader=lambda text: generation_pin_reservations({"firmware_artifact": built}, config=text)).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "spi2" in result.detail
    confirm.assert_not_called()
    assert_untouched(transport, remote)


@pytest.mark.parametrize("changes", ({"second": {"chain_position": "1"}},
                                    {"second": {"spi_bus": "spi2"}},
                                    {"second": {"chain_length": "3"}}))
def test_projection_cannot_hide_invalid_chain(changes):
    with pytest.raises(PinAliasError, match="SPI"):
        tmc_bus_requests(case_sections(changes))


def test_independent_device_still_reserves_its_default():
    sections = chain()
    sections["tmc2130 stepper_z"] = {"cs_pin": "PC12", "run_current": "0.580"}
    assert tmc_bus_requests(sections) == {"mcu": [("spi_bus", "spi2"), ("spi_bus", None)]}


def test_alias_and_mixed_model_follow_same_owner():
    sections = chain()
    second = sections.pop("tmc2130 stepper_y")
    sections["tmc5160 stepper_y"] = second
    sections["board_pins custom"] = {"aliases": "CS=PC11"}
    for name in ("tmc2130 stepper_x", "tmc5160 stepper_y"):
        sections[name]["cs_pin"] = "CS"
    assert tmc_bus_requests(sections) == {"mcu": [("spi_bus", "spi2")]}


def test_literal_none_does_not_merge_transports():
    sections = chain()
    for options in sections.values():
        options["cs_pin"] = "None"
    assert tmc_bus_requests(sections) == {"mcu": [("spi_bus", "spi2"), ("spi_bus", None)]}


def test_projection_order_matches_generated_z_before_extruder():
    board = {"tmc2130 extruder": {"cs_pin": "PC11", "run_current": "0.580", "chain_length": "2", "chain_position": "2"},
             "tmc2130 stepper_z1": {"cs_pin": "PC11", "run_current": "0.580", "chain_length": "2", "chain_position": "1", "spi_bus": "spi2"}}
    selected = resolve_tmc_sections(board, _user(driver_type="TMC2130", driver_mode="SPI", z_motors="2"))
    assert list(selected) == ["tmc2130 stepper_z1", "tmc2130 extruder"]
    assert tmc_bus_requests(selected) == {"mcu": [("spi_bus", "spi2")]}
