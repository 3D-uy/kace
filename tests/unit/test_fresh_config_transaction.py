"""Fresh publication backs up old bytes without importing their include graph."""
from pathlib import Path

import pytest

from core import config_transaction, klipper_preflight
from core.managed_config import build_fresh_config_plan, effective_hardware_text
from tests.unit.test_config_transaction import FakeTransport
from tests.unit.test_initial_macros_layout import MACROS
from tests.unit.test_root_include_placement import generated


OLD_ROOT = (b"[include old/*.cfg]\n[include macros.cfg]\n"
            b"#*# <---------------------- SAVE_CONFIG ---------------------->\n"
            b"#*# [heater_bed]\n#*# pid_kp = 999\n")
OLD_MACROS = b"[gcode_macro OLD]\ngcode: M117 old\n"


@pytest.fixture
def fresh_destination(tmp_path, monkeypatch):
    transport = FakeTransport({"printer.cfg": OLD_ROOT, "macros.cfg": OLD_MACROS,
                               "mainsail.cfg": b"", "unrelated.cfg": b"untouched\n"})
    monkeypatch.setattr(klipper_preflight, "validate_plan", lambda plan:
        klipper_preflight.PreflightResult("valid", "explicit unit loader double", klipper_preflight.plan_digest(plan)))
    def run(macros=MACROS, **kwargs):
        return config_transaction.ConfigDeploymentTransaction(
            transport, generated("English", "\n"), macros, fresh_install=True,
            activation="none", output=lambda _: None,
            snapshot_root=str(tmp_path / "snapshots"), poll_interval=0, **kwargs,
        ).run()
    return transport, run


def test_omitted_macros_are_reviewed_and_retired_without_file_deletion():
    files = {"printer.cfg": OLD_ROOT, "macros.cfg": OLD_MACROS, "mainsail.cfg": b""}
    plan = build_fresh_config_plan(generated("English", "\n"), None, files)
    artifacts = {item.remote_name: item for item in plan.artifacts}
    assert artifacts["macros.cfg"].previous == OLD_MACROS
    assert not any(line.strip() and not line.lstrip().startswith(b"#")
                   for line in artifacts["macros.cfg"].content.splitlines())
    assert b"[include macros.cfg]" not in artifacts["printer.cfg"].content
    assert "OLD" not in effective_hardware_text(plan)
    assert any("macros.cfg" in warning and "retir" in warning for warning in plan.warnings)


@pytest.mark.parametrize("macros", [None, MACROS])
def test_fresh_publication_backs_up_before_replacing_old_root_and_macros(fresh_destination, tmp_path, macros):
    transport, run = fresh_destination
    reviews = []
    def confirm(diff):
        reviews.append(diff)
        assert transport.files["printer.cfg"] == OLD_ROOT
        assert transport.files["macros.cfg"] == OLD_MACROS
        assert not any(call[0] == "upload" for call in transport.calls)
        return True
    result = run(macros, confirm=confirm)
    assert result.pending, result.detail
    assert reviews and "OLD" in reviews[0] and "SAVE_CONFIG" in reviews[0]
    assert result.snapshot.config_files == {"printer.cfg": OLD_ROOT, "macros.cfg": OLD_MACROS}
    backup = Path(result.snapshot.storage_path)
    assert backup.is_relative_to(tmp_path / "snapshots")
    assert (backup / "printer.cfg").read_bytes() == OLD_ROOT
    assert (backup / "macros.cfg").read_bytes() == OLD_MACROS
    assert b"SAVE_CONFIG ---------------------->" not in transport.files["printer.cfg"]
    assert b"old/*.cfg" not in transport.files["printer.cfg"]
    assert b"gcode_macro OLD" not in transport.files["macros.cfg"]
    assert transport.files["unrelated.cfg"] == b"untouched\n"
    assert not any(call[0] in {"restart", "delete"} for call in transport.calls)
    assert not any("old/*.cfg" in call[1] for call in transport.calls if call[0] == "read")
    again = run(macros, confirm=lambda _: True)
    assert again.pending, again.detail
    assert again.snapshot is None


@pytest.mark.parametrize("failure", ["declined", "missing-new-include", "snapshot", "external-edit"])
def test_fresh_prepublication_failure_preserves_every_existing_byte(fresh_destination, monkeypatch, failure):
    transport, run = fresh_destination
    if failure == "missing-new-include":
        transport.files.pop("mainsail.cfg")
    if failure == "snapshot":
        monkeypatch.setattr(config_transaction, "create_snapshot", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    def confirm(_):
        if failure == "external-edit":
            transport.files["printer.cfg"] = b"# concurrent edit\n"
        return failure != "declined"
    previous = dict(transport.files)
    result = run(confirm=confirm)
    assert not result.ok and not result.pending
    if failure == "external-edit":
        previous["printer.cfg"] = b"# concurrent edit\n"
    assert transport.files == previous
    assert not any(call[0] in {"upload", "restart", "delete"} for call in transport.calls)


def test_fresh_partial_failure_keeps_backup_and_requires_explicit_recovery(fresh_destination):
    transport, run = fresh_destination
    transport.fail_upload = "printer.cfg"
    result = run(None, confirm=lambda _: True)
    assert result.state is config_transaction.ConfigTransactionState.ROLLBACK_FAILED
    assert result.rollback_succeeded is False
    assert result.snapshot.config_files["macros.cfg"] == OLD_MACROS
    assert transport.files["printer.cfg"] == OLD_ROOT
    assert b"gcode_macro OLD" not in transport.files["macros.cfg"]
    assert "manual recovery" in result.detail
    assert not any(call[0] in {"restart", "delete"} for call in transport.calls)


def test_fresh_reader_only_follows_new_relative_macro_dependencies():
    transport = FakeTransport({"printer.cfg": OLD_ROOT, "macros.cfg": OLD_MACROS,
                               "mainsail.cfg": b"", "extra.cfg": b"[respond]\n"})
    macros = b"[include extra.cfg]\n" + MACROS
    state = config_transaction.read_config_state(
        transport, generated("English", "\n"), macros, fresh_install=True,
    )
    assert state["extra.cfg"] == b"[respond]\n"
    assert state["printer.cfg"] == OLD_ROOT
    assert "old/*.cfg" not in state
    plan = build_fresh_config_plan(generated("English", "\n"), macros, state)
    assert "[respond]" in effective_hardware_text(plan)


@pytest.mark.parametrize("mode", ["Beginner", "Advanced"])
def test_review_describes_real_replacements_and_old_calibration(fresh_destination, monkeypatch, mode):
    from core.configuration_review import render_configuration_review
    transport, run = fresh_destination
    monkeypatch.setattr("core.translations.get_mode", lambda: mode)
    def decline(review):
        message = render_configuration_review(review, color=False)
        assert "999" in message and "pid_kp" in message and "SAVE_CONFIG" in message
        assert "[include old/*.cfg]" in message
        assert "macros will be replaced with a comment" in message
        assert "preserving unmanaged sections" not in message
        assert "Backup before replacement:" in message and "snapshots" in message
        return False
    assert run(None, review=decline).state is config_transaction.ConfigTransactionState.CANCELLED
    assert transport.files["printer.cfg"] == OLD_ROOT
    assert transport.files["macros.cfg"] == OLD_MACROS


@pytest.mark.parametrize("interruption", ["wizard", "eof", "keyboard"])
@pytest.mark.parametrize("prompt", ["review", "activation_selector"])
def test_prepublication_interruptions_report_cancellation(fresh_destination, prompt, interruption):
    from core.deployer import _config_result_to_workflow
    from core.exceptions import WizardExit
    transport, run = fresh_destination
    def interrupt(*args):
        raise {"wizard": WizardExit, "eof": EOFError, "keyboard": KeyboardInterrupt}[interruption]()
    result = run(None, **{prompt: interrupt})
    outcome = _config_result_to_workflow(result)
    assert outcome.exit_code == 2 and "CANCELLED" in outcome.marker()
    assert not any(action[0] in {"upload", "restart", "delete"} for action in transport.calls)


def test_fresh_macro_dependency_is_validated_at_actual_root_destination(fresh_destination):
    transport, run = fresh_destination
    transport.files["extra.cfg"] = b"[respond]\n"
    result = run(b"[include extra.cfg]\n" + MACROS, confirm=lambda _: True)
    assert result.pending, result.detail
    assert b"[include extra.cfg]" in transport.files["macros.cfg"]
    assert "kace/extra.cfg" not in transport.files


def test_export_without_exclusive_publication_rejects_before_backup_or_write(tmp_path, monkeypatch):
    transport = config_transaction.LocalConfigTransport(tmp_path)
    plan = build_fresh_config_plan(generated("English", "\n"), None, {})
    def reject(*args):
        raise OSError("filesystem has no exclusive atomic publication")
    monkeypatch.setattr(transport, "_publish_new", reject)
    monkeypatch.setattr(config_transaction, "create_snapshot", lambda *a, **kw: pytest.fail("unexpected snapshot"))
    with pytest.raises(config_transaction.ConfigConflictError, match="select another filesystem"):
        config_transaction.require_conditional_writes(transport, plan)
    assert list(tmp_path.iterdir()) == []


def test_exclusive_export_preserves_concurrent_winner_and_failed_copy(tmp_path, monkeypatch):
    transport = config_transaction.LocalConfigTransport(tmp_path)
    target = tmp_path / "printer.cfg"
    target.write_bytes(b"concurrent winner")
    with pytest.raises((FileExistsError, config_transaction.ConfigConflictError)):
        transport.upload_if_unchanged("printer.cfg", b"proposal", None)
    assert target.read_bytes() == b"concurrent winner"
    def interrupted(fd):
        raise OSError("transfer interrupted")
    monkeypatch.setattr("os.fsync", interrupted)
    with pytest.raises(OSError, match="transfer interrupted"):
        transport.upload_if_unchanged("other.cfg", b"proposal", None)
    assert list(tmp_path.iterdir()) == [target]


def test_interrupted_initial_installation_resumes_only_approved_remaining_files(fresh_destination, tmp_path, monkeypatch):
    from core.firmware_workflow import (
        FirmwareWorkflowState as State, create_checkpoint, transition_checkpoint, write_checkpoint, load_checkpoint,
    )
    from tests.unit.test_firmware_workflow import artifact, identity_reader
    from tests.unit.test_generator import _user
    user = _user(mcu_type="stm32f407")
    monkeypatch.setenv("KACE_FIRMWARE_WORKFLOW_PATH", str(tmp_path / "checkpoint.json"))
    checkpoint = create_checkpoint(user, identity_reader=identity_reader())
    checkpoint = transition_checkpoint(checkpoint, State.ARTIFACT_READY, artifact=artifact(tmp_path, model="stm32f407"))
    checkpoint = transition_checkpoint(checkpoint, State.VERIFYING_MCU)
    checkpoint = transition_checkpoint(checkpoint, State.MCU_VERIFIED, verified_serial_path=user["mcu_path"],
                                       flash_evidence_recorded_at=1)
    for state in (State.CONFIG_GENERATED, State.READY_TO_DEPLOY, State.DEPLOYING):
        checkpoint = transition_checkpoint(checkpoint, state)
    write_checkpoint(checkpoint)
    transport, run = fresh_destination
    publish = transport.upload_if_unchanged
    def lose_process(name, content, previous):
        publish(name, content, previous)
        raise SystemExit(9)
    with monkeypatch.context() as change:
        change.setattr(transport, "upload_if_unchanged", lose_process)
        with pytest.raises(SystemExit):
            run(installation_checkpoint=checkpoint)
    assert transport.files["printer.cfg"] == OLD_ROOT
    assert transport.files["macros.cfg"] != OLD_MACROS
    saved = load_checkpoint()
    record = saved["installation_publication"]
    backup = Path(record["snapshot"])
    assert (backup / "printer.cfg").read_bytes() == OLD_ROOT
    assert (backup / "macros.cfg").read_bytes() == OLD_MACROS
    transport.calls.clear()
    changed_macros = MACROS + b"\n# Different generation\n"
    assert run(changed_macros, installation_checkpoint=saved).state is config_transaction.ConfigTransactionState.PRECONDITION_FAILED
    assert not any(call[0] == "upload" for call in transport.calls)
    assert run(installation_checkpoint=saved).pending
    assert [call for call in transport.calls if call[0] == "upload"] == [("upload", "printer.cfg")]
    assert load_checkpoint()["installation_publication"] == record
