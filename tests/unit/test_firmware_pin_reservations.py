"""Reservation evidence must come from the exact embedded build dictionary."""
import hashlib
import json
from dataclasses import replace
import struct
import zlib

import pytest

from firmware.artifacts import BuildArtifact
from firmware.identity import FirmwareBuildInputs, FirmwareIdentityError, ToolchainIdentity
from firmware.pin_reservations import read_reserved_pins
from core.exceptions import GenerationError
from core.generator import generate_config
from core.pin_validator import validate_bltouch_pin_usage, PinAliasError
from core.firmware_workflow import (
    create_checkpoint, transition_checkpoint, generation_pin_reservations, FirmwareWorkflowState,
    CheckpointIncompatible,
)
from tests.unit.test_generator import _parsed, _user
from tests.unit.test_firmware_workflow import identity_reader

FINGERPRINT = "kace-b1-" + "a" * 32


def dictionary(constants=None, version=FINGERPRINT):
    return {"version": version, "config": {"MCU": "stm32f446xx", **(constants or {})}}


def wrapped(payload, fmt):
    if fmt == "BIN":
        return payload
    if fmt == "IHEX":
        lines = []
        for offset in range(0, len(payload), 16):
            data = payload[offset:offset + 16]
            record = bytes([len(data)]) + offset.to_bytes(2, "big") + b"\0" + data
            lines.append(":" + (record + bytes([-sum(record) & 255])).hex().upper())
        return ("\n".join(lines) + "\n:00000001FF\n").encode()
    blocks = []
    count = (len(payload) + 255) // 256
    for number in range(count):
        data = payload[number * 256:(number + 1) * 256]
        block = bytearray(512)
        struct.pack_into("<IIIIIIII", block, 0, 0x0A324655, 0x9E5D5157, 0,
                         0x10000000 + number * 256, len(data), number, count, 0)
        block[32:32 + len(data)] = data
        struct.pack_into("<I", block, 508, 0x0AB16F30)
        blocks.append(block)
    return b"".join(blocks)


def artifact(tmp_path, constants=None, *, fmt="BIN", payload=None):
    if payload is None:
        payload = b"prefix" + zlib.compress(json.dumps(dictionary(constants)).encode(), 9) + b"suffix"
    native = {"BIN": "klipper.bin", "IHEX": "klipper.elf.hex", "UF2": "klipper.uf2"}[fmt]
    path = tmp_path / native
    path.write_bytes(wrapped(payload, fmt))
    inputs = FirmwareBuildInputs.create(klipper_commit="b" * 40,
        canonical_config='CONFIG_MCU="stm32f446xx"\n',
        toolchain=ToolchainIdentity("make", "fixture", "gcc", "fixture"), build_id="a" * 32)
    return BuildArtifact.create(path=str(path), native_filename=native,
        size_bytes=path.stat().st_size, mcu="stm32f446xx", firmware_fingerprint=FINGERPRINT,
        mock_build=False, size_warning=False, build_identity=inputs)


@pytest.mark.parametrize("fmt", ["BIN", "UF2", "IHEX"])
def test_reads_each_container_without_guessing_transport(tmp_path, fmt):
    built = artifact(tmp_path, {"RESERVE_PINS_USB1": "PB14,PB15", "RESERVE_PINS_crystal": "PH0,PH1"}, fmt=fmt)
    assert read_reserved_pins(built.path, built.firmware_identity) == {
        "PB14": "USB1", "PB15": "USB1", "PH0": "crystal", "PH1": "crystal"}


def test_verified_dictionary_without_reservations_is_empty(tmp_path):
    built = artifact(tmp_path)
    assert read_reserved_pins(built.path, built.firmware_identity) == {}


@pytest.mark.parametrize("payload", [
    FINGERPRINT.encode(), b"no metadata", b"x\xda corrupt",
    zlib.compress(json.dumps(dictionary(version="kace-b1-" + "c" * 32)).encode()),
    zlib.compress(json.dumps(dictionary()).encode()) * 2,
    zlib.compress(json.dumps({"version": FINGERPRINT}).encode()),
    zlib.compress(json.dumps({"version": FINGERPRINT, "config": {}}).encode()),
    zlib.compress(json.dumps(dictionary()).encode())[:-2],
])
def test_missing_wrong_ambiguous_or_truncated_metadata_is_not_empty_map(tmp_path, payload):
    built = artifact(tmp_path, payload=payload)
    with pytest.raises(FirmwareIdentityError):
        read_reserved_pins(built.path, built.firmware_identity)


@pytest.mark.parametrize("constants", [
    {"RESERVE_PINS_USB": 123}, {"RESERVE_PINS_USB": ""},
    {"RESERVE_PINS_USB": "PA11,"}, {"RESERVE_PINS_USB": "PA11, PA12"},
    {"RESERVE_PINS_": "PA11"}, {"RESERVE_PINS_USB": "toolhead:PA11"},
    {"RESERVE_PINS_USB": "PA11", "RESERVE_PINS_CAN": "PA11"},
])
def test_malformed_or_conflicting_reservations_fail_closed(tmp_path, constants):
    built = artifact(tmp_path, constants)
    with pytest.raises(FirmwareIdentityError):
        read_reserved_pins(built.path, built.firmware_identity)


def test_tampered_firmware_and_identity_are_rejected(tmp_path):
    built = artifact(tmp_path)
    with open(built.path, "ab") as stream:
        stream.write(b"changed")
    with pytest.raises(FirmwareIdentityError, match="changed"):
        read_reserved_pins(built.path, built.firmware_identity)
    with pytest.raises(FirmwareIdentityError, match="identity"):
        read_reserved_pins(built.path, None)


@pytest.mark.parametrize("fmt", ["UF2", "IHEX"])
def test_corrupt_container_cannot_fall_back_to_scanning_raw_bytes(tmp_path, fmt):
    built = artifact(tmp_path, fmt=fmt)
    path = tmp_path / built.native_filename
    path.write_bytes(b"bad" + path.read_bytes())
    identity = replace(built.firmware_identity, artifact_size=path.stat().st_size,
                       artifact_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    with pytest.raises(FirmwareIdentityError, match="container"):
        read_reserved_pins(path, identity)


@pytest.mark.parametrize("token,blocked", [
    ("^PB8", True), ("^mcu:PB8", True), ("^HEADER", True),
    ("^toolhead:PB8", False), ("^toolhead:HEADER", False),
])
def test_reservations_follow_aliases_in_their_mcu(token, blocked):
    content = f"[bltouch]\nsensor_pin: {token}\ncontrol_pin: PB9\n"
    content += "[board_pins]\nmcu: mcu,toolhead\naliases: HEADER=PB8\n"
    if blocked:
        with pytest.raises(PinAliasError, match="reserved by firmware for CAN"):
            validate_bltouch_pin_usage(content, firmware_reservations={"mcu": {"PB8": "CAN"}})
    else:
        validate_bltouch_pin_usage(content, firmware_reservations={"mcu": {"PB8": "CAN"}})


def resumed_user(built):
    user = _user(probe="BLTouch", mcu_type="stm32f446xx", board="custom.cfg")
    checkpoint = create_checkpoint(user, identity_reader=identity_reader())
    checkpoint = transition_checkpoint(checkpoint, FirmwareWorkflowState.ARTIFACT_READY,
        artifact={"path": built.path, "sha256": built.sha256, "size_bytes": built.size_bytes,
                  "build": built.to_dict()})
    checkpoint = transition_checkpoint(checkpoint, FirmwareWorkflowState.AWAITING_FLASH)
    checkpoint = transition_checkpoint(checkpoint, FirmwareWorkflowState.VERIFYING_MCU)
    checkpoint = transition_checkpoint(checkpoint, FirmwareWorkflowState.MCU_VERIFIED,
        verified_serial_path="/dev/serial/by-id/test", flash_evidence_recorded_at=1)
    user["mcu_path"] = "/dev/serial/by-id/test"
    user["workflow_checkpoint"] = checkpoint
    return user


@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize("probe", ["BLTouch", "CR-Touch"])
def test_generation_rejects_reserved_manual_pin_before_writing(tmp_path, resume, probe):
    built = artifact(tmp_path, {"RESERVE_PINS_USB1": "PB14,PB15"})
    user = resumed_user(built) if resume else _user(firmware_artifact=built)
    user.update(probe=probe, bltouch_control_pin="PB14")
    output = tmp_path / "printer.cfg"
    output.write_bytes(b"previous configuration")
    with pytest.raises(GenerationError, match="reserved by firmware for USB1"):
        generate_config(_parsed(bltouch={"sensor_pin": "^PB8", "control_pin": "PB9"}),
                        user, str(output), verbose=False)
    assert output.read_bytes() == b"previous configuration"
    assert not (tmp_path / "printer.cfg.provenance.json").exists()


def test_generation_accepts_same_pin_with_different_compiled_usb_mapping(tmp_path):
    built = artifact(tmp_path, {"RESERVE_PINS_USB": "PA11,PA12"})
    result = generate_config(_parsed(bltouch={"sensor_pin": "^PB8", "control_pin": "PB14"}),
        _user(probe="BLTouch", firmware_artifact=built), str(tmp_path / "printer.cfg"), verbose=False)
    assert "control_pin: PB14" in result["content"]


def test_missing_metadata_is_not_ignored_during_generation(tmp_path):
    built = artifact(tmp_path, payload=FINGERPRINT.encode())
    with pytest.raises(GenerationError, match="identify dictionary"):
        generate_config(_parsed(bltouch={"sensor_pin": "^PB8", "control_pin": "PB9"}),
            _user(probe="BLTouch", firmware_artifact=built), str(tmp_path / "printer.cfg"), verbose=False)
    assert not (tmp_path / "printer.cfg").exists()


def test_unbound_path_and_runtime_checkpoint_mismatch_are_rejected(tmp_path):
    built = artifact(tmp_path)
    with pytest.raises(FirmwareIdentityError, match="bound build"):
        generation_pin_reservations({"firmware_path": built.path})
    user = resumed_user(built)
    user["firmware_artifact"] = replace(built, firmware_identity=replace(
        built.firmware_identity, reported_version="kace-b1-" + "c" * 32))
    with pytest.raises(FirmwareIdentityError, match="differs"):
        generation_pin_reservations(user)


def test_config_only_has_no_firmware_evidence():
    assert generation_pin_reservations({}) == {}


def test_resumed_reservations_cannot_be_used_for_another_board(tmp_path):
    user = resumed_user(artifact(tmp_path))
    user["board"] = "other.cfg"
    with pytest.raises(CheckpointIncompatible, match="board"):
        generation_pin_reservations(user)


def test_resumed_reservations_cannot_be_used_for_another_serial_path(tmp_path):
    user = resumed_user(artifact(tmp_path))
    user["mcu_path"] = "/dev/serial/by-id/other"
    with pytest.raises(CheckpointIncompatible, match="serial path"):
        generation_pin_reservations(user)


def test_oversized_dictionary_cannot_supply_reservations(tmp_path):
    value = dictionary({"RESERVE_PINS_USB": "PA11,PA12"})
    value["padding"] = "0" * (2 * 1024 * 1024)
    built = artifact(tmp_path, payload=zlib.compress(json.dumps(value).encode()))
    with pytest.raises(FirmwareIdentityError, match="identify dictionary"):
        read_reserved_pins(built.path, built.firmware_identity)
