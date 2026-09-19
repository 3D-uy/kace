"""Eight-finding stabilization: real parsers/files, simulated device boundaries."""
import hashlib
import importlib.util
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from core.config_transaction import (
    ConfigDeploymentTransaction, ConfigTransactionState as Result,
    LocalConfigTransport, SftpConfigTransport, MoonrakerConfigTransport,
    ConfigConflictError, read_config_state,
)
from core.managed_config import build_managed_config_plan, effective_hardware_text, HARDWARE_REMOTE, ROOT_REMOTE
from core.configuration_review import validate_configuration_plan, _sections
from core.firmware_workflow import (
    create_checkpoint, transition_checkpoint, artifact_evidence, verify_reappeared_mcu,
    FirmwareWorkflowState as State, _same_mcu_model,
)
from firmware.deployment import FirmwareDeploymentService, DeploymentTarget, DeploymentMethodId, DeploymentExecutionContext, DeploymentStatus
from firmware.artifacts import FirmwareFormat
from tests.unit.test_config_transaction import FakeTransport, GENERATED
from tests.unit.test_firmware_deployment import artifact, write_artifact
from tests.unit.test_firmware_workflow import base_user_data, identity_reader
from tests.unit.test_hardware_readiness import resolve_kconfig, build_artifact


def transaction(transport, tmp_path, **kwargs):
    return ConfigDeploymentTransaction(transport, GENERATED, None,
        activation=kwargs.pop("activation", "firmware"), snapshot_root=str(tmp_path / "snap"),
        poll_interval=0, **kwargs).run()


def test_user_include_precedence_matches_actual_klipper(tmp_path):
    source = Path(__file__).resolve().parents[2] / ".klipper-contract-source/klippy/configfile.py"
    if not source.is_file():
        pytest.skip("Pinned Klipper parser unavailable")
    spec = importlib.util.spec_from_file_location("include_regression", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    transport = FakeTransport({"printer.cfg": b"[include user.cfg]\n",
        "user.cfg": b"[include nested/axis.cfg]\n",
        "nested/axis.cfg": b"[stepper_x]\ndir_pin: !PA2\nhoming_positive_dir: true\n"})
    generated = GENERATED + b"dir_pin: PA2\nposition_min: 0\nposition_max: 200\nposition_endstop: 200\nhoming_positive_dir: false\n"
    state = read_config_state(transport, generated)
    plan = build_managed_config_plan(generated, None, state)
    files = {**state, **{a.remote_name: a.content for a in plan.artifacts}}
    for name, content in files.items():
        if content is not None:
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    parser = module.ConfigFileReader()
    actual = parser.build_fileconfig_with_includes(files["printer.cfg"].decode(), str(tmp_path / "printer.cfg"))
    reviewed = _sections(effective_hardware_text(plan))
    assert reviewed["stepper_x"]["dir_pin"] == actual.get("stepper_x", "dir_pin") == "!PA2"
    assert reviewed["stepper_x"]["homing_positive_dir"] == actual.get("stepper_x", "homing_positive_dir") == "true"


@pytest.mark.parametrize("root", [b"[include missing.cfg]\n", b"[include *.cfg]\n", b"[include ../outside.cfg]\n", b"[include printer.cfg]\n"])
def test_unreviewable_includes_prevent_all_writes(tmp_path, root):
    transport = FakeTransport({"printer.cfg": root})
    result = transaction(transport, tmp_path)
    assert result.state is Result.PRECONDITION_FAILED
    assert not any(c[0] in {"upload", "restart"} for c in transport.calls)


def test_include_edit_during_confirmation_and_mcu_override_are_rejected(tmp_path):
    transport = FakeTransport({"printer.cfg": b"[include user.cfg]\n", "user.cfg": b"# reviewed\n"})
    def confirm(_):
        transport.files["user.cfg"] = b"[mcu]\nserial: /dev/another\n"
        return True
    result = transaction(transport, tmp_path, confirm=confirm)
    assert result.state is Result.PRECONDITION_FAILED
    assert "user.cfg" in result.detail
    plan = build_managed_config_plan(GENERATED, None, read_config_state(transport))
    assert any(e.code == "included-mcu-override" for e in validate_configuration_plan(plan).errors)


def test_pending_retry_activates_matching_files_and_honors_cancel(tmp_path):
    class Live(FakeTransport):
        active = b"old active config"
        def restart(self, mode):
            super().restart(mode)
            self.active = self.files["printer.cfg"]
        def verify_active_configuration(self, plan):
            expected = next(a.content for a in plan.artifacts if a.remote_name == ROOT_REMOTE)
            if self.active != expected:
                raise ConfigConflictError("active configuration differs; explicit restart required")
    transport = Live()
    assert transaction(transport, tmp_path, activation="none").pending
    assert transport.active == b"old active config"
    assert transaction(transport, tmp_path, review=lambda _: False).state is Result.CANCELLED
    assert transport.active == b"old active config"
    assert transaction(transport, tmp_path, activation_selector=lambda: "none").pending
    assert transport.active == b"old active config"
    result = transaction(transport, tmp_path, verify_existing_ready=True, verify_firmware=lambda: None)
    assert result.state is Result.ACTIVATION_FAILED
    assert transport.active == b"old active config"
    assert not any(call[0] == "restart" for call in transport.calls)
    result = transaction(transport, tmp_path, activation_selector=lambda: "firmware")
    assert result.ok
    assert transport.active == transport.files["printer.cfg"]
    assert transport.calls.count(("restart", "firmware")) == 1
    selector = Mock(side_effect=AssertionError("verified retry must not prompt for restart"))
    result = transaction(transport, tmp_path, verify_existing_ready=True,
                         verify_firmware=lambda: None, activation_selector=selector)
    assert result.ok
    selector.assert_not_called()
    assert transport.calls.count(("restart", "firmware")) == 1


@pytest.mark.parametrize("during", ["confirm", "runner"])
def test_usb_consumes_only_the_checked_bytes(tmp_path, during):
    original = b":0100000001FE\n:00000001FF\n"
    source = write_artifact(str(tmp_path), "klipper.elf.hex", original)
    service = FirmwareDeploymentService(output_dir=str(tmp_path), event_sink=lambda _: None)
    plan = service.plan(artifact(source, fmt=FirmwareFormat.IHEX),
        DeploymentTarget("generic-ramps.cfg", "atmega2560", "/dev/serial/by-id/usb-Arduino_ORIGINAL-if00",
                         usb_vid="2341", usb_pid="0042"), DeploymentMethodId.USB)
    prepared = service.prepare(plan)
    def mutate():
        Path(prepared.staged_path).write_bytes(original.replace(b"01FE", b"02FD"))
    def confirm(_):
        if during == "confirm":
            mutate()
        return True
    def consume(command, **kwargs):
        mutate()
        assert command[-1] == "flash:w:-:i"
        assert kwargs["input"] == original
        assert hashlib.sha256(kwargs["input"]).hexdigest() == prepared.sha256
    runner = Mock(side_effect=consume)
    with patch("firmware.deployment.usb.shutil.which", return_value="avrdude"):
        result = service.execute(prepared, DeploymentExecutionContext(confirm=confirm, command_runner=runner))
    assert result.status is (DeploymentStatus.FAILED if during == "confirm" else DeploymentStatus.FLASHED)
    assert runner.call_count == (0 if during == "confirm" else 1)


def test_atomic_creation_preserves_edit_after_final_read(tmp_path):
    root = tmp_path / "config"
    root.mkdir()
    class RacingLocal(LocalConfigTransport):
        def upload_if_unchanged(self, name, content, previous):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"external edit AFTER final read")
            return super().upload_if_unchanged(name, content, previous)
    result = transaction(RacingLocal(str(root)), tmp_path, activation="none")
    assert not result.ok
    # New installations publish hardware directly in printer.cfg (root-v1).
    assert (root / ROOT_REMOTE).read_bytes() == b"external edit AFTER final read"
    assert not (root / HARDWARE_REMOTE).exists()


def test_existing_local_update_is_rejected_before_partial_publication(tmp_path):
    root = tmp_path / "config"
    root.mkdir()
    (root / "printer.cfg").write_bytes(b"user data")
    result = transaction(LocalConfigTransport(str(root)), tmp_path, activation="none")
    assert result.state is Result.PRECONDITION_FAILED
    assert list(root.iterdir()) == [root / "printer.cfg"]
    assert (root / "printer.cfg").read_bytes() == b"user data"
    assert "proposal" in result.detail


@pytest.mark.parametrize("model,clock", [("stm32f446", "12000000"), ("stm32f429", "8000000")])
def test_legacy_octopus_resolved_model_keeps_physical_identity(tmp_path, model, clock):
    resolved, config = resolve_kconfig(tmp_path, model, clock)
    actual_model = resolved.syms["MCU"].str_value
    built = build_artifact(tmp_path, config, model)
    data = {**base_user_data(), "board": "generic-bigtreetech-octopus-v1.1.cfg", "mcu_type": model}
    cp = create_checkpoint(data, identity_reader=identity_reader())
    cp = transition_checkpoint(cp, State.ARTIFACT_READY,
        artifact=artifact_evidence({"firmware_artifact": built, "firmware_path": built.path}))
    cp = transition_checkpoint(cp, State.AWAITING_FLASH)
    path = f"/dev/serial/by-id/usb-Klipper_{actual_model}_ORIGINAL-if00"
    with patch("core.firmware_workflow.os.path.exists", return_value=True):
        verified, _ = verify_reappeared_mcu(cp, flash_evidence=True, identity_reader=identity_reader(),
            detector=lambda: {"derived_mcu": actual_model, "mcu_path": path})
    assert verified["state"] == State.MCU_VERIFIED.value
    assert not _same_mcu_model(data["board"], model, "stm32f407xx")
    assert not _same_mcu_model("another-board.cfg", model, actual_model)


@pytest.mark.parametrize("destination,active,allowed", [
    ("/other-config", "/printer_data/config/printer.cfg", False),
    ("/config-link", "/printer_data/config/printer.cfg", True),
    ("/printer_data/config", "/printer_data/config/alternate.cfg", False),
])
def test_sftp_target_is_bound_to_active_config(destination, active, allowed):
    sftp = Mock()
    sftp.normalize.side_effect = lambda path: path.replace("/config-link", "/printer_data/config")
    transport = SftpConfigTransport(sftp, destination, "test", 7125)
    with patch("core.moonraker._get", return_value=(True, "OK", {"result": {"config_file": active}})):
        if allowed:
            transport.validate_activation_target()
        else:
            with pytest.raises(ConfigConflictError, match="does not match"):
                transport.validate_activation_target()
    sftp.put.assert_not_called()


def test_moonraker_cannot_claim_conditional_writes():
    transport = MoonrakerConfigTransport("test", 7125)
    for previous in (None, b"original"):
        assert not transport.supports_conditional_write(previous)
        with pytest.raises(ConfigConflictError):
            transport.upload_if_unchanged("printer.cfg", b"new", previous)


def test_sftp_creation_uses_no_replace_and_preserves_racing_edit():
    sftp = Mock()
    sftp.rename.side_effect = FileExistsError("external edit appeared")
    transport = SftpConfigTransport(sftp, "/config", "test", 7125)
    with pytest.raises(FileExistsError):
        transport.upload_if_unchanged("printer.cfg", b"proposed", None)
    sftp.posix_rename.assert_not_called()
    sftp.rename.assert_called_once()
    assert sftp.rename.call_args.args[1] == "/config/printer.cfg"
    assert sftp.remove.call_args.args[0] != "/config/printer.cfg"
    with pytest.raises(ConfigConflictError):
        transport.upload_if_unchanged("printer.cfg", b"proposed", b"original")


def test_model_edit_cannot_reuse_original_hardware_checkpoint(tmp_path):
    from core.firmware_workflow import validate_checkpoint, CheckpointIncompatible
    built = build_artifact(tmp_path, model="stm32f446")
    cp = transition_checkpoint(create_checkpoint(base_user_data(), identity_reader=identity_reader()),
        State.ARTIFACT_READY, artifact=artifact_evidence({"firmware_artifact": built, "firmware_path": built.path}))
    with pytest.raises(CheckpointIncompatible, match="compiled MCU"):
        validate_checkpoint(cp)


def test_moonraker_activation_path_is_checked_even_without_writes(tmp_path):
    transport = MoonrakerConfigTransport("test", 7125)
    with patch("core.moonraker._get", side_effect=[
        (True, "OK", {"result": {"config_file": "/other/printer.cfg"}}),
        (True, "OK", {"result": [{"name": "config", "path": "/config"}]}),
    ]), patch.object(transport, "read_files") as read:
        result = transaction(transport, tmp_path)
    assert result.state is Result.PRECONDITION_FAILED
    read.assert_not_called()


@pytest.mark.parametrize("original_exists", [True, False])
def test_bootstrap_rollback_preserves_both_external_edits(tmp_path, original_exists):
    from tests.regression.test_bootstrap_config_defaults import TestBootstrapConfigDefaults, _find_bash
    if not _find_bash():
        pytest.skip("Bash unavailable")
    TestBootstrapConfigDefaults.setUpClass()
    config, state = tmp_path / "moonraker.conf", tmp_path / "power.json"
    if original_exists:
        config.write_bytes(b"original config\r\n")
        state.write_bytes(b"original state\r\n")
    result = TestBootstrapConfigDefaults()._run_bootstrap_library('''
systemctl() { echo 'unexpected service action'; return 99; }
begin_power_reconciliation "$1" "$2"
printf '%s' 'external config' > "$1"
printf '%s' 'external state' > "$2"
rollback_power_reconciliation
''', config, state)
    assert result.returncode != 0
    assert "manual recovery" in result.stderr
    assert "moonraker.conf" in result.stderr and "power.json" in result.stderr
    assert "unexpected service action" not in result.stdout
    assert config.read_bytes() == b"external config"
    assert state.read_bytes() == b"external state"
    if original_exists:
        assert next(tmp_path.glob("moonraker.conf.kace-power-backup.*")).read_bytes() == b"original config\r\n"
        assert next(tmp_path.glob("power.json.kace-power-backup.*")).read_bytes() == b"original state\r\n"
    else:
        assert "__ABSENT__" in result.stderr


def test_real_physical_client_is_blocked_before_firmware(tmp_path):
    from core.deployer import _MoonrakerClient
    from core.moonraker_deployer import Deployer, DeploymentManifest, McuTarget, DeployState
    from core.snapshot import create_snapshot
    cfg = tmp_path / "printer.cfg"
    cfg.write_bytes(b"proposed")
    flash = Mock()
    client = _MoonrakerClient("never-connect", 7125)
    snapshot = create_snapshot({"printer.cfg": b"original"}, persist_root=str(tmp_path / "snap"))
    with patch("core.moonraker._get", side_effect=AssertionError("No network expected")):
        result = Deployer(client, DeploymentManifest([McuTarget("mcu", "test")], str(cfg)),
            snapshot=snapshot, firmware_copy=flash, event_sink=lambda _: None).run()
    assert result.state is DeployState.FAILED_PRECONDITION
    flash.assert_not_called()
