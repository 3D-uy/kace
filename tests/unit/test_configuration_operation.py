"""Configuration-only entry exercises real generation and the shared transaction."""
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from core.configuration_operation import run_configuration_operation
from core.firmware_workflow import (
    create_checkpoint, transition_checkpoint, write_checkpoint, FirmwareWorkflowState,
)
from core.klipper_preflight import PreflightResult, plan_digest
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_firmware_workflow import artifact, identity_reader
from tests.unit.test_generator import _parsed, _user


ID = "a" * 32


@pytest.fixture
def setup_operation(tmp_path, monkeypatch):
    source = tmp_path / "firmware-workflow.json"
    monkeypatch.setenv("KACE_FIRMWARE_WORKFLOW_PATH", str(source))
    monkeypatch.delenv("KACE_AUTO", raising=False)
    user = _user(mcu_type="stm32f407", board_parsed=_parsed(), macros_generated=False)
    checkpoint = create_checkpoint(user, identity_reader=identity_reader())
    checkpoint = transition_checkpoint(checkpoint, FirmwareWorkflowState.ARTIFACT_READY,
                                       artifact=artifact(tmp_path, model="stm32f407"))
    for state in ("AWAITING_FLASH", "VERIFYING_MCU"):
        checkpoint = transition_checkpoint(checkpoint, FirmwareWorkflowState(state))
    checkpoint = transition_checkpoint(checkpoint, FirmwareWorkflowState.MCU_VERIFIED,
                                       verified_serial_path=user["mcu_path"], flash_evidence_recorded_at=1)
    for state in ("CONFIG_GENERATED", "READY_TO_DEPLOY", "DEPLOYING", "COMPLETE"):
        checkpoint = transition_checkpoint(checkpoint, FirmwareWorkflowState(state))
    write_checkpoint(checkpoint)
    original = source.read_bytes()
    transport = FakeTransport()
    transport.host, transport.port, transport.api_key = "127.0.0.1", 7125, None
    monkeypatch.setattr("core.config_transaction.configuration_transport", lambda *a: transport)
    # Hardware proof and Docker are explicit doubles, never claimed physical.
    monkeypatch.setattr("core.firmware_workflow.generation_pin_reservations", lambda *a, **k: {})
    monkeypatch.setattr("core.deployer._require_running_firmware_checkpoint", lambda *a: None)
    monkeypatch.setattr("core.klipper_preflight.validate_plan", lambda plan:
                        PreflightResult("valid", "explicit unit loader double", plan_digest(plan)))
    monkeypatch.setattr("core.deployer._interactive_configuration_review", lambda *a: True)
    monkeypatch.setattr("core.deployer._select_config_activation", lambda: "firmware")
    return source, original, hashlib.sha256(original).hexdigest(), transport


def receipt(source):
    return source.parent / "configuration-operations" / ID / "result.json"


def test_new_operation_preserves_checkpoint_and_generates_isolated_files(setup_operation):
    source, original, digest, transport = setup_operation
    result = run_configuration_operation(ID, digest)
    assert result.ok, result.detail
    assert source.read_bytes() == original
    assert not (source.parent / "printer.cfg").exists()
    saved = json.loads(receipt(source).read_text())
    assert saved["state"] == "COMPLETE"
    assert saved["operation_id"] == ID
    assert saved["source_checkpoint_sha256"] == digest
    assert saved["exit_code"] == 0
    assert (receipt(source).parent / "printer.cfg").is_file()
    evidence = list(receipt(source).parent.glob("transaction-*.json"))
    assert len(evidence) == 1
    assert json.loads(evidence[0].read_text())["plan_digest"]
    assert [call for call in transport.calls if call[0] == "restart"] == [("restart", "firmware")]


@pytest.mark.parametrize("mode", ["cancel", "defer", "invalid", "unverified"])
def test_unapproved_or_unverified_never_completes(setup_operation, monkeypatch, mode):
    source, original, digest, transport = setup_operation
    if mode == "cancel":
        monkeypatch.setattr("core.deployer._interactive_configuration_review", lambda *a: False)
    elif mode == "defer":
        monkeypatch.setattr("core.deployer._select_config_activation", lambda: "none")
    else:
        monkeypatch.setattr("core.klipper_preflight.validate_plan", lambda plan:
                            PreflightResult(mode, "blocked", plan_digest(plan)))
    result = run_configuration_operation(ID, digest)
    assert not result.ok
    assert source.read_bytes() == original
    assert json.loads(receipt(source).read_text())["state"] != "COMPLETE"
    assert not any(call[0] == "restart" for call in transport.calls)
    if mode != "defer":
        assert not any(call[0] == "upload" for call in transport.calls)


def test_declined_then_resume_reuses_generation_and_reapproves(setup_operation, monkeypatch):
    source, original, digest, transport = setup_operation
    monkeypatch.setattr("core.deployer._interactive_configuration_review", lambda *a: False)
    assert not run_configuration_operation(ID, digest).ok
    result_hash = hashlib.sha256(receipt(source).read_bytes()).hexdigest()
    generated = (receipt(source).parent / "printer.cfg").read_bytes()
    generate = Mock(side_effect=AssertionError("resume must not regenerate"))
    monkeypatch.setattr("core.generator.generate_config", generate)
    review = Mock(return_value=True)
    monkeypatch.setattr("core.deployer._interactive_configuration_review", review)
    result = run_configuration_operation(ID, digest, resume=True, result_sha256=result_hash)
    assert result.ok, result.detail
    review.assert_called_once()
    generate.assert_not_called()
    assert (receipt(source).parent / "printer.cfg").read_bytes() == generated
    assert source.read_bytes() == original


def test_duplicate_id_does_not_replace_complete_receipt(setup_operation):
    source, original, digest, transport = setup_operation
    assert run_configuration_operation(ID, digest).ok
    previous = receipt(source).read_bytes()
    transport.calls.clear()
    assert not run_configuration_operation(ID, digest).ok
    assert not run_configuration_operation(ID, digest, resume=True,
               result_sha256=hashlib.sha256(previous).hexdigest()).ok
    assert receipt(source).read_bytes() == previous
    assert source.read_bytes() == original
    assert not transport.calls


def test_source_hash_mismatch_rejects_before_generation(setup_operation):
    source, original, digest, transport = setup_operation
    result = run_configuration_operation(ID, "0" * 64)
    assert not result.ok
    assert not receipt(source).exists()
    assert source.read_bytes() == original
    assert not transport.calls


def test_source_changes_during_review_stops_before_upload(setup_operation, monkeypatch):
    source, original, digest, transport = setup_operation
    def review(*args):
        # Simulates an external non-cooperating editor, not a KACE write.
        source.write_bytes(original + b"\n")
        return True
    monkeypatch.setattr("core.deployer._interactive_configuration_review", review)
    result = run_configuration_operation(ID, digest)
    assert not result.ok
    assert not any(call[0] in {"upload", "restart"} for call in transport.calls)


def test_resume_rejects_changed_generated_bytes(setup_operation, monkeypatch):
    source, original, digest, transport = setup_operation
    monkeypatch.setattr("core.deployer._interactive_configuration_review", lambda *a: False)
    assert not run_configuration_operation(ID, digest).ok
    result_hash = hashlib.sha256(receipt(source).read_bytes()).hexdigest()
    (receipt(source).parent / "printer.cfg").write_text("changed")
    transport.calls.clear()
    result = run_configuration_operation(ID, digest, resume=True, result_sha256=result_hash)
    assert not result.ok
    assert "changed" in result.detail
    assert not transport.calls
    assert source.read_bytes() == original


def test_resume_deferred_publication_activates_existing_bytes_only_after_choice(setup_operation, monkeypatch):
    source, original, digest, transport = setup_operation
    monkeypatch.setattr("core.deployer._select_config_activation", lambda: "none")
    first = run_configuration_operation(ID, digest)
    assert not first.ok
    assert json.loads(receipt(source).read_text())["state"] == "PENDING_ACTIVATION"
    result_hash = hashlib.sha256(receipt(source).read_bytes()).hexdigest()
    files = dict(transport.files)
    transport.calls.clear()
    activation = Mock(return_value="firmware")
    monkeypatch.setattr("core.deployer._select_config_activation", activation)
    second = run_configuration_operation(ID, digest, resume=True, result_sha256=result_hash)
    assert second.ok, second.detail
    activation.assert_called_once()
    assert transport.files == files
    assert not any(call[0] == "upload" for call in transport.calls)
    assert [call for call in transport.calls if call[0] == "restart"] == [("restart", "firmware")]
    assert source.read_bytes() == original


def test_generated_serial_mismatch_blocks_before_transport(setup_operation, monkeypatch):
    source, original, digest, transport = setup_operation
    from core.generator import generate_config
    def wrong_serial(*args, **kwargs):
        result = generate_config(*args, **kwargs)
        path = Path(kwargs["output_path"])
        path.write_text(path.read_text().replace("usb-test-if00", "usb-wrong-if00"))
        return result
    monkeypatch.setattr("core.generator.generate_config", wrong_serial)
    result = run_configuration_operation(ID, digest)
    assert not result.ok
    assert "serial" in result.detail
    assert not transport.calls
    assert source.read_bytes() == original


def test_recovery_after_remote_activation_verifies_without_second_restart(setup_operation, monkeypatch):
    source, original, digest, transport = setup_operation
    monkeypatch.setattr("core.deployer._select_config_activation", lambda: "none")
    assert not run_configuration_operation(ID, digest).ok
    result_hash = hashlib.sha256(receipt(source).read_bytes()).hexdigest()
    # Models activation completing remotely before the client lost its result.
    transport.active_files = dict(transport.files)
    transport.calls.clear()
    activation = Mock(side_effect=AssertionError("already active must not ask for a second restart"))
    monkeypatch.setattr("core.deployer._select_config_activation", activation)
    result = run_configuration_operation(ID, digest, resume=True, result_sha256=result_hash)
    assert result.ok, result.detail
    assert "already installed" in result.detail
    activation.assert_not_called()
    assert not any(call[0] in {"upload", "restart"} for call in transport.calls)
    assert source.read_bytes() == original


def test_firmware_mismatch_never_offers_an_extra_restart(setup_operation, monkeypatch):
    source, original, digest, transport = setup_operation
    monkeypatch.setattr("core.deployer._select_config_activation", lambda: "none")
    assert not run_configuration_operation(ID, digest).ok
    result_hash = hashlib.sha256(receipt(source).read_bytes()).hexdigest()
    transport.active_files = dict(transport.files)
    transport.calls.clear()
    activation = Mock(return_value="firmware")
    monkeypatch.setattr("core.deployer._select_config_activation", activation)
    monkeypatch.setattr("core.deployer._require_running_firmware_checkpoint", Mock(side_effect=RuntimeError("wrong MCU firmware")))
    result = run_configuration_operation(ID, digest, resume=True, result_sha256=result_hash)
    assert not result.ok
    assert "wrong MCU firmware" in result.detail
    activation.assert_not_called()
    assert not any(call[0] in {"upload", "restart"} for call in transport.calls)


def test_stale_resume_receipt_is_never_replaced(setup_operation, monkeypatch):
    source, original, digest, transport = setup_operation
    monkeypatch.setattr("core.deployer._interactive_configuration_review", lambda *a: False)
    assert not run_configuration_operation(ID, digest).ok
    before = receipt(source).read_bytes()
    transport.calls.clear()
    result = run_configuration_operation(ID, digest, resume=True, result_sha256="0" * 64)
    assert not result.ok
    assert "result changed" in result.detail
    assert receipt(source).read_bytes() == before
    assert not transport.calls


def test_service_configuration_change_is_rejected_before_review_and_writes(setup_operation, monkeypatch):
    source, original, digest, transport = setup_operation
    transport.files["moonraker.conf"] = b"[server]\nhost: 0.0.0.0\n"
    from core.reconciler import reconcile_moonraker_conf_content
    assert reconcile_moonraker_conf_content(transport.files["moonraker.conf"].decode())[1]
    before = dict(transport.files)
    review = Mock(return_value=True)
    monkeypatch.setattr("core.deployer._interactive_configuration_review", review)
    result = run_configuration_operation(ID, digest)
    assert not result.ok
    assert "cannot change moonraker.conf" in result.detail
    review.assert_not_called()
    assert transport.files == before
    assert not any(call[0] in {"upload", "restart", "restart_moonraker"} for call in transport.calls)
    assert source.read_bytes() == original


def test_concurrent_configuration_operation_cannot_publish(setup_operation):
    source, original, digest, transport = setup_operation
    from core.workspace import exclusive_file_lock
    with exclusive_file_lock(str(source) + ".lock", timeout_seconds=1):
        result = run_configuration_operation(ID, digest)
    assert not result.ok
    assert not receipt(source).exists()
    assert not transport.calls
    assert source.read_bytes() == original


def test_resume_binds_manifest_to_previous_receipt_not_just_modified_files(setup_operation, monkeypatch):
    source, original, digest, transport = setup_operation
    monkeypatch.setattr("core.deployer._interactive_configuration_review", lambda *a: False)
    assert not run_configuration_operation(ID, digest).ok
    previous_receipt = receipt(source).read_bytes()
    result_hash = hashlib.sha256(previous_receipt).hexdigest()
    directory = receipt(source).parent
    (directory / "printer.cfg").write_text("tampered")
    manifest_path = directory / "generated.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["printer.cfg"] = hashlib.sha256((directory / "printer.cfg").read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    transport.calls.clear()
    result = run_configuration_operation(ID, digest, resume=True, result_sha256=result_hash)
    assert not result.ok
    assert "manifest changed" in result.detail
    assert receipt(source).read_bytes() == previous_receipt
    assert not transport.calls
    assert source.read_bytes() == original


@pytest.mark.parametrize("argv", [
    ["--new-configuration", ID],
    ["--new-configuration", ID, "--configuration-checkpoint-sha256", "b" * 64, "--auto"],
    ["--resume-configuration", ID, "--configuration-checkpoint-sha256", "b" * 64],
    ["--configuration-result-sha256", "b" * 64],
    ["--new-configuration", ID, "--configuration-checkpoint-sha256", "b" * 64, "--power", "on"],
])
def test_cli_rejects_ambiguous_or_unbound_launch_before_any_work(argv):
    import subprocess
    import sys
    cli = Path(__file__).resolve().parents[2] / "kace.py"
    result = subprocess.run([sys.executable, str(cli), *argv], capture_output=True, text=True)
    assert result.returncode == 2
    assert "error:" in result.stderr
