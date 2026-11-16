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
    # Explicit simulated operator consent; retain the actual fixed-geometry step.
    monkeypatch.setattr("core.wizard.steps.printable_area.numbered_select", lambda *a, **kw: "confirm")
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


def test_legacy_geometry_requires_specific_confirmation_before_publication(setup_operation, monkeypatch):
    source, original, digest, transport = setup_operation
    assert "_printable_xy_confirmation" not in json.loads(original)["wizard_data"]
    decision = Mock(return_value="__back__")
    monkeypatch.setattr("core.wizard.steps.printable_area.numbered_select", decision)
    result = run_configuration_operation(ID, digest)
    assert not result.ok
    decision.assert_called_once()
    assert source.read_bytes() == original
    assert not any(call[0] in {"upload", "restart", "restart_moonraker"} for call in transport.calls)


def test_resume_confirms_frozen_artifact_geometry_not_restored_proposals(setup_operation, monkeypatch):
    source, original, digest, transport = setup_operation
    monkeypatch.setattr("core.deployer._select_config_activation", lambda: "none")
    assert not run_configuration_operation(ID, digest).ok
    directory = receipt(source).parent
    frozen = {name: (directory / name).read_bytes() for name in (
        "printer.cfg", "printer.cfg.provenance.json", "generated.json")}
    expected = json.loads(frozen["printer.cfg.provenance.json"])["geometry"]
    result_hash = hashlib.sha256(receipt(source).read_bytes()).hexdigest()
    from core.configuration_operation import restore_wizard_data as restore
    def changed_proposal(saved):
        restored = restore(saved)
        restored.update(printable_x_max=120, x_position_max=150, x_size=120)
        return restored
    monkeypatch.setattr("core.configuration_operation.restore_wizard_data", changed_proposal)
    monkeypatch.setattr("core.generator.generate_config", Mock(side_effect=AssertionError("resume must not regenerate")))
    from core.wizard.steps.printable_area import _step_printable_area as review
    seen = []
    def capture_geometry(data, *, allow_edit):
        seen.append(dict(data))
        assert allow_edit is False
        return review(data, allow_edit=allow_edit)
    monkeypatch.setattr("core.wizard.steps.printable_area._step_printable_area", capture_geometry)
    monkeypatch.setattr("core.deployer._select_config_activation", lambda: "firmware")
    result = run_configuration_operation(ID, digest, resume=True, result_sha256=result_hash)
    assert result.ok, result.detail
    assert len(seen) == 1
    assert seen[0]["printable_x_max"] == expected["printable_x_max"]
    assert float(seen[0]["x_position_max"]) == 235
    assert {name: (directory / name).read_bytes() for name in frozen} == frozen
    assert source.read_bytes() == original


def test_saved_confirmation_does_not_skip_operation_review(setup_operation, monkeypatch):
    source, original, digest, transport = setup_operation
    from core.firmware_workflow import _with_integrity, restore_wizard_data, persistable_wizard_data
    from core.motion_model import printable_xy_confirmation_matches
    from core.wizard.steps.printable_area import _step_printable_area
    checkpoint = json.loads(original)
    decisions = restore_wizard_data(checkpoint["wizard_data"])
    decisions.update(x_position_min=0, x_position_max=235, y_position_min=0, y_position_max=235)
    assert _step_printable_area(decisions) == "confirmed"
    checkpoint["wizard_data"] = persistable_wizard_data(decisions)
    write_checkpoint(_with_integrity(checkpoint), str(source), expected_revision=(str(source), digest))
    before = source.read_bytes()
    assert printable_xy_confirmation_matches(restore_wizard_data(json.loads(before)["wizard_data"]))
    decision = Mock(return_value="confirm")
    monkeypatch.setattr("core.wizard.steps.printable_area.numbered_select", decision)
    result = run_configuration_operation(ID, hashlib.sha256(before).hexdigest())
    assert result.ok, result.detail
    decision.assert_called_once()
    assert decision.call_args.kwargs["require_explicit"] is True
    assert source.read_bytes() == before


def test_resume_cancelled_geometry_never_republishes_or_regenerates(setup_operation, monkeypatch):
    source, original, digest, transport = setup_operation
    monkeypatch.setattr("core.deployer._select_config_activation", lambda: "none")
    assert not run_configuration_operation(ID, digest).ok
    directory = receipt(source).parent
    frozen = {name: (directory / name).read_bytes() for name in (
        "printer.cfg", "printer.cfg.provenance.json", "generated.json")}
    result_hash = hashlib.sha256(receipt(source).read_bytes()).hexdigest()
    monkeypatch.setattr("core.generator.generate_config", Mock(side_effect=AssertionError("resume must not regenerate")))
    monkeypatch.setattr("core.wizard.steps.printable_area.numbered_select", lambda *a, **kw: "__back__")
    transport.calls.clear()
    result = run_configuration_operation(ID, digest, resume=True, result_sha256=result_hash)
    assert not result.ok
    assert json.loads(receipt(source).read_bytes())["state"] == "CANCELLED"
    assert source.read_bytes() == original
    assert {name: (directory / name).read_bytes() for name in frozen} == frozen
    assert not transport.calls


@pytest.mark.parametrize("phase", ["geometry", "effective"])
def test_review_cannot_authorize_changed_generated_bytes(setup_operation, monkeypatch, phase):
    source, original, digest, transport = setup_operation
    def edit_artifact(*args, **kwargs):
        path = receipt(source).parent / "printer.cfg"
        path.write_bytes(path.read_bytes() + b"\n# concurrent edit\n")
        return "confirm" if phase == "geometry" else True
    target = ("core.wizard.steps.printable_area.numbered_select" if phase == "geometry"
              else "core.deployer._interactive_configuration_review")
    monkeypatch.setattr(target, edit_artifact)
    result = run_configuration_operation(ID, digest)
    assert not result.ok
    assert "changed after review" in result.detail
    assert source.read_bytes() == original
    assert not any(call[0] in {"upload", "restart", "restart_moonraker"} for call in transport.calls)


@pytest.mark.parametrize("invalid", ["missing", "wrong-source", "outside-travel"])
def test_resume_rejects_unusable_frozen_geometry_before_confirmation(setup_operation, monkeypatch, invalid):
    source, original, digest, transport = setup_operation
    monkeypatch.setattr("core.deployer._select_config_activation", lambda: "none")
    assert not run_configuration_operation(ID, digest).ok
    directory = receipt(source).parent
    sidecar = directory / "printer.cfg.provenance.json"
    payload = json.loads(sidecar.read_bytes())
    if invalid == "missing":
        payload.pop("geometry")
    elif invalid == "wrong-source":
        payload["geometry"]["source_sha256"] = "0" * 64
    else:
        payload["geometry"]["printable_x_min"] = -10
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    manifest_path = directory / "generated.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest[sidecar.name] = hashlib.sha256(sidecar.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    saved = json.loads(receipt(source).read_bytes())
    saved["generated_manifest_sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    receipt(source).write_text(json.dumps(saved), encoding="utf-8")
    result_hash = hashlib.sha256(receipt(source).read_bytes()).hexdigest()
    decision = Mock(side_effect=AssertionError("unusable geometry cannot be confirmed"))
    monkeypatch.setattr("core.wizard.steps.printable_area.numbered_select", decision)
    transport.calls.clear()
    result = run_configuration_operation(ID, digest, resume=True, result_sha256=result_hash)
    assert not result.ok
    decision.assert_not_called()
    assert source.read_bytes() == original
    assert not transport.calls


def test_configuration_entry_replaces_old_tree_and_recovers_partial_fresh_publication(setup_operation, monkeypatch):
    source, original, digest, transport = setup_operation
    old_root = b"[include missing-old/*.cfg]\n#*# <---------------------- SAVE_CONFIG ---------------------->\n"
    old_macros = b"[gcode_macro OLD]\ngcode: M117 old\n"
    transport.files.update({"printer.cfg": old_root, "macros.cfg": old_macros})
    transport.fail_upload = "printer.cfg"
    result = run_configuration_operation(ID, digest)
    assert not result.ok
    records = list(receipt(source).parent.glob("transaction-*.json"))
    assert len(records) == 1
    evidence = json.loads(records[0].read_text())
    assert evidence["state"] == "ROLLBACK_FAILED"
    assert evidence["rollback_succeeded"] is False
    backup = Path(evidence["snapshot_path"])
    assert backup.is_relative_to(receipt(source).parent / "snapshots")
    assert (backup / "printer.cfg").read_bytes() == old_root
    assert (backup / "macros.cfg").read_bytes() == old_macros
    assert transport.files["printer.cfg"] == old_root
    assert b"gcode_macro OLD" not in transport.files["macros.cfg"]
    assert not any(call[0] == "restart" for call in transport.calls)
    result_hash = hashlib.sha256(receipt(source).read_bytes()).hexdigest()
    transport.fail_upload = None
    monkeypatch.setattr("core.generator.generate_config", Mock(side_effect=AssertionError("recovery must not regenerate")))
    result = run_configuration_operation(ID, digest, resume=True, result_sha256=result_hash)
    assert result.ok, result.detail
    assert source.read_bytes() == original
    assert (backup / "printer.cfg").read_bytes() == old_root
    assert (backup / "macros.cfg").read_bytes() == old_macros
    assert b"missing-old" not in transport.files["printer.cfg"]
    assert b"SAVE_CONFIG ---------------------->" not in transport.files["printer.cfg"]
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


def test_complete_receipt_sync_failure_reports_failure_without_complete_event(setup_operation, monkeypatch):
    source, original, digest, transport = setup_operation
    emitted = []
    from core import reconciler
    sync_directory = reconciler.fsync_directory

    def fail_complete_barrier(directory):
        saved = receipt(source)
        if Path(directory) == saved.parent and saved.exists():
            if json.loads(saved.read_text())["state"] == "COMPLETE":
                raise OSError("synthetic COMPLETE directory sync failure")
        sync_directory(directory)

    monkeypatch.setattr(reconciler, "fsync_directory", fail_complete_barrier)
    monkeypatch.setattr("core.moonraker_deployer.JsonEventSink", lambda: emitted.append)
    result = run_configuration_operation(ID, digest)
    assert not result.ok
    assert "durability is not confirmed" in result.detail
    assert json.loads(receipt(source).read_text())["state"] == "FAILED"
    assert not any(event["state"] == "COMPLETE" for event in emitted)
    assert source.read_bytes() == original
    assert [call for call in transport.calls if call[0] == "restart"] == [("restart", "firmware")]


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
