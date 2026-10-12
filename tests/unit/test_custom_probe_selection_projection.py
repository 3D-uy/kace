"""Probe choices use selected configuration wiring, not all discovery examples.

This is offline allocation coverage. A declared input is not proof of electrical
compatibility, successful probing, or qualification of the source board.
"""
import copy
from pathlib import Path
from unittest.mock import patch

import pytest

from core.exceptions import GenerationError
from core.pin_validator import PinAliases, PinAliasError
from core.profile_values import resolve_tmc_sections
from core.scraper import parse_config
from core.tmc_socket import REVIEWED
from core.wizard.steps import sensors
from tests.unit.test_firmware_pin_reservations import artifact, resumed_user
from tests.unit.test_tmc_socket import inputs, MODELS, FIXTURES


@pytest.mark.parametrize("name", sorted(REVIEWED))
@pytest.mark.parametrize("model", MODELS)
def test_every_reviewed_socket_profile_preserves_selected_motor_and_transport_allocations(name, model):
    board, user = inputs(name, model)
    selected = resolve_tmc_sections(board, user)
    before = copy.deepcopy(user)
    with patch.object(sensors, "_get_parsed", return_value=board):
        projected = sensors._probe_allocation_sections(user)
        check = sensors.make_pin_validator_with_collision_check(user, for_custom_probe=True)
    assert {n: options for n, options in projected.items() if n.startswith("tmc")} == selected
    assert user == before
    for target in ("stepper_x", "stepper_y", "stepper_z", "stepper_z1", "extruder"):
        for field in ("step_pin", "dir_pin", "enable_pin"):
            assert check(board[target][field].lstrip("!")) is not True, (name, model, target, field)
    for name, options in selected.items():
        for field, value in options.items():
            if field.endswith("_pin") and "virtual_endstop" not in value:
                assert check(value.lstrip("!^~")) is not True, (name, field)


def test_reported_skr_uart_accepts_replaced_z_without_foreign_spi_diag():
    name = "generic-bigtreetech-skr-v1.4.cfg"
    board = parse_config((FIXTURES/name).read_text(encoding="utf-8"), name, keep_comments=True)
    user = dict(board=name, board_parsed=board, mcu_type="lpc1769", driver_type="TMC2209", driver_mode="UART", z_motors="1")
    with patch.object(sensors, "_get_parsed", return_value=board):
        custom = sensors.make_pin_validator_with_collision_check(user, for_custom_probe=True)
        ordinary = sensors.make_pin_validator_with_collision_check(user)
        projected = sensors._probe_allocation_sections(user)
    assert custom("^P1.27") is True
    assert ordinary("^P1.27") is not True
    assert not any(name.startswith("tmc2130 ") for name in projected)
    assert custom("P1.8") is not True


@pytest.mark.parametrize("change", ["missing_mode", "wrong_mode", "unsupported_model", "missing_section", "empty_transport", "bad_count"])
def test_incomplete_or_invalid_selected_driver_cannot_free_every_pin(change):
    board = {"stepper_x": {"step_pin": "PB0"}, "tmc2209 stepper_x": {"uart_pin": "PB1"}}
    user = dict(board_parsed=board, driver_type="TMC2209", driver_mode="UART", z_motors="1")
    if change == "missing_mode":
        user.pop("driver_mode")
    elif change == "wrong_mode":
        user["driver_mode"] = "SPI"
    elif change == "unsupported_model":
        user["driver_type"] = "TMC9999"
    elif change == "missing_section":
        board.pop("tmc2209 stepper_x")
    elif change == "empty_transport":
        board["tmc2209 stepper_x"]["uart_pin"] = ""
    else:
        user["z_motors"] = "invalid"
    before = copy.deepcopy(user)
    with patch.object(sensors, "_get_parsed", return_value=board):
        with pytest.raises(GenerationError):
            sensors._probe_allocation_sections(user)
        check = sensors.make_pin_validator_with_collision_check(user, for_custom_probe=True)
    assert check("PB8") is not True
    assert user == before


def test_no_driver_selection_keeps_unknown_driver_allocations_conservative():
    board = {"tmc2130 stepper_z": {"diag1_pin": "PB8"}, "stepper_z": {"endstop_pin": "PB8"}}
    with patch.object(sensors, "_get_parsed", return_value=board):
        check = sensors.make_pin_validator_with_collision_check({}, for_custom_probe=True)
    assert check("^PB8") is not True


def test_board_map_from_a_different_selected_identity_cannot_offer_or_validate_inputs():
    user = dict(board="new-board.cfg", _board_parsed_for="old-board.cfg",
                board_parsed={"probe": {"pin": "PB8"}},
                driver_type="None (Standard)", driver_mode="Standalone")
    before = copy.deepcopy(user)
    with pytest.raises(GenerationError):
        sensors._probe_allocation_sections(user)
    assert sensors._get_probe_input_candidates(user) == []
    assert sensors.make_pin_validator_with_collision_check(user, for_custom_probe=True)("PB8") is not True
    assert user == before


@pytest.mark.parametrize("changes", [
    {"driver_mode": "UART"},
    {"board_parsed": "not a pin map"},
    {"board": "new.cfg", "board_parsed": {"probe": {"pin": "PB8"},
        "_tmc_socket_source": {"profile": "old.cfg", "sha256": "0"*64}}},
])
def test_partial_selection_or_invalid_source_binding_remains_closed(changes):
    user = {"board_parsed": {"probe": {"pin": "PB8"}}}
    user.update(changes)
    with pytest.raises(GenerationError):
        sensors._probe_allocation_sections(user)
    assert sensors._get_probe_input_candidates(user) == []
    assert sensors.make_pin_validator_with_collision_check(user, for_custom_probe=True)("PB8") is not True


def test_saved_multiz_assignments_are_authoritative_over_refetched_discovery():
    raw = {"stepper_x": {"step_pin": "PB0"}}
    assigned = {**raw, "stepper_z1": {"step_pin": "PB8", "dir_pin": "PB9", "enable_pin": "!PB10"}}
    user = dict(board_parsed=assigned, z_motors="2", driver_type="None (Standard)", driver_mode="Standalone")
    with patch("core.wizard.get_current_board_parsed", return_value=raw) as reload:
        check = sensors.make_pin_validator_with_collision_check(user, for_custom_probe=True)
    reload.assert_not_called()
    assert check("PB8") is not True
    assert check("PB9") is not True
    assert check("PB10") is not True


@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize("reserved", ["RESERVE_PINS_USB", "RESERVE_PINS_CAN"])
def test_selected_probe_and_replaced_z_never_bypass_bound_firmware(tmp_path, resume, reserved):
    built = artifact(tmp_path, {reserved: "PB8,PB9"})
    user = resumed_user(built) if resume else {"firmware_artifact": built}
    board = {"probe": {"pin": "^PB8"}, "stepper_z": {"endstop_pin": "PB9"}}
    with patch.object(sensors, "_get_parsed", return_value=board):
        assert sensors._get_probe_input_candidates(user) == []
        check = sensors.make_pin_validator_with_collision_check(user, for_custom_probe=True)
    assert "reserved by firmware" in check("PB8")
    assert "reserved by firmware" in check("PB9")


_PINNED_CONFIG = Path(__file__).resolve().parents[2]/".klipper-contract-source/config"
_DECLARED_INPUT_PROFILES = sorted(path for pattern in ("generic-*.cfg", "printer-*.cfg")
                                for path in _PINNED_CONFIG.glob(pattern))


@pytest.mark.skipif(not _DECLARED_INPUT_PROFILES, reason="Pinned Klipper source inventory unavailable")
@pytest.mark.parametrize("path", _DECLARED_INPUT_PROFILES, ids=lambda p: p.name)
def test_all_available_pinned_board_and_printer_profiles_offer_only_valid_declared_input_identities(path):
    board = parse_config(path.read_text(encoding="utf-8"), path.name, keep_comments=True)
    user = dict(board=path.name, board_parsed=board, driver_type="None (Standard)", driver_mode="Standalone", z_motors="1")
    try:
        resolver = PinAliases({name: fields for name, fields in board.items() if isinstance(fields, dict)})
    except PinAliasError:
        # Discovery may expose malformed/unsupported aliases. A source boundary
        # cannot become an empty allocation map that accepts arbitrary GPIOs.
        with patch.object(sensors, "_get_parsed", return_value=board):
            assert sensors._get_probe_input_candidates(user) == []
            check = sensors.make_pin_validator_with_collision_check(user, for_custom_probe=True)
        assert check("PB8") is not True
        return
    declared = set()
    for name, field in (("probe", "pin"), ("bltouch", "sensor_pin"), ("stepper_z", "endstop_pin")):
        token = board.get(name, {}).get(field)
        if token and "virtual_endstop" not in token and "TODO" not in token.upper():
            try:
                declared.add(resolver.resolve(token))
            except ValueError:
                pass
    before = copy.deepcopy(board)
    with patch.object(sensors, "_get_parsed", return_value=board):
        candidates = sensors._get_probe_input_candidates(user)
        validator = sensors.make_pin_validator_with_collision_check(user, for_custom_probe=True)
    identities = [resolver.resolve(candidate["pin"]) for candidate in candidates]
    assert len(identities) == len(set(identities))
    assert set(identities) <= declared
    for candidate in candidates:
        assert candidate["source"] in ("probe", "bltouch", "z_endstop")
        assert validator(candidate["pin"]) is True
        if candidate["source"] == "z_endstop":
            assert candidate["pullup"] is False and candidate["inverted"] is False
    assert board == before


def test_reported_selection_generates_a_probe_transition_and_effective_includes_remain_authoritative(tmp_path):
    import importlib.util
    from core.configuration_review import validate_configuration_plan
    from core.custom_probe import GuidedCustomProbeSettings
    from core.generator import generate_config
    from core.managed_config import build_managed_config_plan
    from tests.unit.test_tmc_socket import confirm_currents
    board, user = inputs()
    confirm_currents(board, user)
    user.update(probe_kind="custom", probe="Custom Probe",
                custom_probe=GuidedCustomProbeSettings(pin="^P1.27", x_offset=0, y_offset=0).to_config())
    result = generate_config(board, user, str(tmp_path/"printer.cfg"), verbose=False)
    actual = parse_config(result["content"])
    assert actual["probe"]["pin"] == "^P1.27"
    assert actual["stepper_z"]["endstop_pin"] == "probe:z_virtual_endstop"
    assert "position_endstop" not in actual["stepper_z"]
    assert not any(name.startswith("tmc2130 ") for name in actual)
    generated = result["content"].encode()
    fresh = build_managed_config_plan(generated, None, {})
    assert validate_configuration_plan(fresh).valid
    pinned_parser = _PINNED_CONFIG.parent/"klippy/configfile.py"
    assert pinned_parser.is_file(), "Pinned Klipper parser is required for this integration regression"
    spec = importlib.util.spec_from_file_location("probe_selection_klipper_config", pinned_parser)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    files = {item.remote_name: item.content for item in fresh.artifacts}
    for name, content in files.items():
        path = tmp_path/"managed"/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    actual = module.ConfigFileReader().build_fileconfig_with_includes(
        files["printer.cfg"].decode(), str(tmp_path/"managed/printer.cfg"))
    assert actual.get("probe", "pin") == "^P1.27"
    assert actual.get("stepper_z", "endstop_pin") == "probe:z_virtual_endstop"
    assert not actual.has_option("stepper_z", "position_endstop")
    assert not any(name.startswith("tmc2130 ") for name in actual.sections())
    # A later user include can still own a conflicting consumer. It must not be
    # bypassed merely because the compact menu accepted the declared Z input.
    existing = {"printer.cfg": b"[include user.cfg]\n", "user.cfg": b"[fan]\npin: P1.27\n"}
    plan = build_managed_config_plan(generated, None, existing)
    review = validate_configuration_plan(plan)
    assert not review.valid
    assert any(error.code == "probe-pin-conflict" for error in review.errors)
