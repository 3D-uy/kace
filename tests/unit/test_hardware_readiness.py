"""Cross-stage regressions before the first physical validation."""
import copy
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from firmware.artifacts import BuildArtifact
from firmware.configuration import klipper_config, board_reference_clock, FirmwareConfigurationError
from firmware.derivation import derive_config
from firmware.identity import FirmwareBuildInputs, ToolchainIdentity
from firmware.validator import validate_config
from firmware.deployment.models import DeploymentTarget
from firmware.deployment.profiles import DeploymentProfileResolver
from core.firmware_workflow import (
    artifact_evidence, create_checkpoint, transition_checkpoint, validate_checkpoint,
    FirmwareWorkflowError, FirmwareWorkflowState as State,
)
from core.config_transaction import ConfigDeploymentTransaction, LocalConfigTransport
from core.managed_config import build_managed_config_plan, HARDWARE_REMOTE
from tests.unit.test_config_transaction import GENERATED
from tests.unit.test_firmware_workflow import base_user_data, identity_reader, artifact


def resolve_kconfig(tmp_path, model, clock=None):
    root = Path(__file__).resolve().parents[2] / ".klipper-contract-source"
    if not root.is_dir():
        pytest.skip("Pinned Klipper checkout unavailable")
    spec = importlib.util.spec_from_file_location("readiness_kconfig", root / "lib/kconfiglib/kconfiglib.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    requested = derive_config(model, "uart" if model.startswith("atmega") else "usb", **(
        {"flash_start": "0x8000"} if model.startswith("stm32f4") else {}))
    if clock:
        requested["CONFIG_CLOCK_REF_FREQ"] = clock
    cfg = tmp_path / ".config"
    cfg.write_text("".join(f"{key}={value}\n" for key, value in klipper_config(requested, model).items()))
    before = Path.cwd()
    try:
        os.chdir(root)
        resolved = module.Kconfig("src/Kconfig", warn_to_stderr=False)
        resolved.load_config(str(cfg))
        resolved.write_config(str(cfg))
    finally:
        os.chdir(before)
    assert validate_config(str(tmp_path), requested=requested, processor=model)[0]
    return resolved, cfg.read_text()


@pytest.mark.parametrize("model,expected", [("stm32f446", "12000000"), ("stm32f429", "8000000")])
def test_octopus_exact_board_clock_survives_real_kconfig(tmp_path, model, expected):
    clock = board_reference_clock("generic-bigtreetech-octopus-v1.1.cfg", model)
    assert clock == expected
    resolved, _ = resolve_kconfig(tmp_path, model, clock)
    assert resolved.syms["CLOCK_REF_FREQ"].str_value == expected


def test_stm32_cannot_silently_default_its_crystal():
    with pytest.raises(FirmwareConfigurationError, match="reference clock"):
        klipper_config(derive_config("stm32f446", "usb"), "stm32f446")
    assert board_reference_clock("another-board.cfg", "stm32f446") is None


def test_wizard_passes_octopus_reference_to_builder():
    from core.firmware_wizard import run_firmware_wizard
    from core.translations import t
    with patch("core.firmware_wizard.yes_no", return_value=True), \
         patch("core.firmware_wizard.numbered_select", return_value=t("builder.compile_now")), \
         patch("core.firmware_wizard.build_firmware_orchestrator", return_value={"status": "error", "message": "test stop"}) as build:
        run_firmware_wizard({"board": "generic-bigtreetech-octopus-v1.1.cfg",
                             "mcu_type": "stm32f446", "mcu_hint": "usb"})
    assert build.call_args.kwargs["config_dict"]["CONFIG_CLOCK_REF_FREQ"] == "12000000"


def test_auto_wizard_refuses_unknown_board_crystal(monkeypatch):
    from core.firmware_wizard import run_firmware_wizard
    monkeypatch.setenv("KACE_AUTO", "1")
    with patch("core.firmware_wizard.yes_no", return_value=True), \
         patch("core.firmware_wizard.build_firmware_orchestrator") as build:
        result = run_firmware_wizard({"board": "unknown.cfg", "mcu_type": "stm32f446", "mcu_hint": "usb"})
    assert not result.ok
    assert "reference clock" in result.detail
    build.assert_not_called()


def build_artifact(tmp_path, config='CONFIG_MCU="lpc1769"\n', model="lpc1769", filename="klipper.bin"):
    path = tmp_path / filename
    path.write_bytes(b"verified original firmware")
    inputs = FirmwareBuildInputs.create(klipper_commit="a" * 40, canonical_config=config,
        toolchain=ToolchainIdentity("make", "test", "gcc", "test"))
    return BuildArtifact.create(path=str(path), native_filename=filename, size_bytes=path.stat().st_size,
        mcu=model, firmware_fingerprint="", mock_build=False, size_warning=False, build_identity=inputs)


def test_ramps_profiles_accept_real_kconfig_and_reject_another_avr(tmp_path):
    _, config = resolve_kconfig(tmp_path, "atmega2560")
    built = build_artifact(tmp_path, config, "atmega2560", "klipper.elf.hex")
    resolver = DeploymentProfileResolver()
    target = DeploymentTarget("generic-ramps.cfg", "atmega2560")
    assert {p.method.value for p in resolver.available(target, built)} == {"USB", "MANUAL"}
    wrong = build_artifact(tmp_path, config.replace('"atmega2560"', '"atmega1284p"'), "atmega2560", "klipper.elf.hex")
    assert not resolver.available(target, wrong)


@pytest.mark.parametrize("mutation", ["replace", "remove", "prepared_digest"])
def test_evidence_never_rebases_the_immutable_build_hash(tmp_path, mutation):
    built = build_artifact(tmp_path)
    data = {"firmware_artifact": built, "firmware_path": built.path}
    assert artifact_evidence(data)["sha256"] == built.sha256
    if mutation == "replace":
        Path(built.path).write_bytes(b"different firmware")
    elif mutation == "remove":
        Path(built.path).unlink()
    else:
        data["prepared_firmware_deployment"] = SimpleNamespace(sha256="b" * 64)
    with pytest.raises(FirmwareWorkflowError):
        artifact_evidence(data)


def test_resume_rejects_checkpoint_whose_outer_digest_was_rebased(tmp_path):
    built = build_artifact(tmp_path)
    evidence = artifact_evidence({"firmware_artifact": built, "firmware_path": built.path})
    cp = create_checkpoint(base_user_data(), identity_reader=identity_reader())
    evidence["sha256"] = "b" * 64
    with pytest.raises(FirmwareWorkflowError, match="immutable build"):
        validate_checkpoint(transition_checkpoint(cp, State.ARTIFACT_READY, artifact=evidence))


@pytest.mark.parametrize("original_exists", [True, False])
@pytest.mark.parametrize("remote_name", ["printer.cfg", HARDWARE_REMOTE])
def test_rollback_preserves_post_read_external_edit_on_real_files(tmp_path, original_exists, remote_name):
    from core.snapshot import create_snapshot
    root = tmp_path / "config"
    (root / "kace").mkdir(parents=True)
    original = b"# KACE layout: root-v1\n# original hardware\n" if original_exists else None
    # Existing user roots retain managed includes; fresh/root-v1 installations
    # publish hardware in printer.cfg. Exercise rollback ownership in both.
    remote = {"printer.cfg": b"# existing user root\n", remote_name: original}
    plan = build_managed_config_plan(GENERATED, None, remote)
    published = next(a.content for a in plan.artifacts if a.remote_name == remote_name)
    (root / remote_name).write_bytes(published)
    class Transport(LocalConfigTransport):
        reads = 0
        def read_files(self, names):
            result = super().read_files(names)
            self.reads += 1
            if self.reads == 1:
                (root / remote_name).write_bytes(b"external edit AFTER ownership read")
            return result
    transaction = ConfigDeploymentTransaction(Transport(str(root)), GENERATED, None,
        activation="none", snapshot_root=str(tmp_path / "snap"))
    transaction.plan = plan
    transaction.snapshot = create_snapshot({remote_name: original}, persist_root=str(tmp_path / "snap"))
    transaction._written_names = {remote_name}
    restored, detail = transaction._rollback()
    assert restored is False
    assert "manual recovery" in detail
    assert (root / remote_name).read_bytes() == b"external edit AFTER ownership read"
    assert Path(transaction.snapshot.storage_path).is_dir()


@pytest.mark.parametrize("state", [State.CONFIG_GENERATED, State.READY_TO_DEPLOY, State.DEPLOYING])
def test_resume_regenerates_missing_config_without_recompiling(tmp_path, monkeypatch, state):
    import kace
    from tests.regression.test_main_integration import _WIZARD_USER_DATA_WITH_PARSED
    data = copy.deepcopy(_WIZARD_USER_DATA_WITH_PARSED)
    serial = "/dev/serial/by-id/usb-Klipper_lpc1769_ORIGINAL-if00"
    data.update(mcu_type="lpc1769", mcu_hint="usb", mcu_path=serial, probe="None", display_choice="none",
                macros_generated=False)
    cp = create_checkpoint(data, identity_reader=identity_reader())
    cp = transition_checkpoint(cp, State.ARTIFACT_READY, artifact=artifact(tmp_path))
    cp = transition_checkpoint(cp, State.VERIFYING_MCU)
    cp = transition_checkpoint(cp, State.MCU_VERIFIED, verified_serial_path=serial, flash_evidence_recorded_at=1)
    for step in (State.CONFIG_GENERATED, State.READY_TO_DEPLOY, State.DEPLOYING):
        cp = transition_checkpoint(cp, step)
        if step is state:
            break
    cfg = tmp_path / "printer.cfg"
    expand = os.path.expanduser
    monkeypatch.setenv("KACE_AUTO", "1")
    monkeypatch.setenv("KACE_FIRMWARE_WORKFLOW_PATH", str(tmp_path / "workflow.json"))
    monkeypatch.setattr(kace, "_resume_firmware_workflow", lambda: (cp, "continue"))
    monkeypatch.setattr(kace, "_persist_workflow", lambda *_a, **_k: None)
    monkeypatch.setattr(kace.os.path, "expanduser", lambda p: str(cfg) if p == "~/kace/printer.cfg" else expand(p))
    generator = Mock(side_effect=lambda *_a, **_k: cfg.write_text(f"[mcu]\nserial: {serial}\n"))
    monkeypatch.setattr(kace, "generate_config", generator)
    with patch("kace.yes_no", return_value=True), patch("kace.numbered_select", return_value="none"), \
         patch("kace.print_summary"), patch("kace.time.sleep"), patch("builtins.print"), \
         patch("core.firmware_wizard.run_firmware_wizard") as compile_firmware:
        with pytest.raises(SystemExit) as exit_result:
            kace.main()
    assert exit_result.value.code == 0
    generator.assert_called_once()
    assert generator.call_args.kwargs["include_macros"] is False
    compile_firmware.assert_not_called()
