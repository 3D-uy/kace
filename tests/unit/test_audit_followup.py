"""Regressions for the twelve cross-stage findings; no hardware or compilation."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch
import zlib

import pytest

from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.managed_config import build_managed_config_plan, ROOT_REMOTE, HARDWARE_REMOTE
from firmware.configuration import klipper_config
from firmware.derivation import derive_config
from firmware.identity import firmware_version_matches, fingerprint_makefile, _compiler_for_config
from firmware.validator import validate_config
from tests.unit.test_config_transaction import FakeTransport, GENERATED

ROOT = Path(__file__).resolve().parents[2]
KLIPPER = ROOT / ".klipper-contract-source"


@pytest.mark.parametrize("model,comm,address,resolved", [
    ("stm32f446", "usb", 0x8008000, "stm32f446xx"),
    ("stm32g0b1", "usb", 0x8002000, "stm32g0b1xx"),
    ("stm32f103", "uart", 0x8007000, "stm32f103xe"),
    ("lpc1769", "usb", 0x4000, "lpc1769"),
    ("atmega2560", "uart", None, "atmega2560"),
    ("atmega1284p", "uart", None, "atmega1284p"),
    ("rp2040", "usb", 0x10000100, "rp2040"),
])
def test_actual_kconfig_preserves_requested_target(tmp_path, model, comm, address, resolved):
    source = KLIPPER / "lib/kconfiglib/kconfiglib.py"
    if not source.exists():
        pytest.skip("Pinned Klipper checkout unavailable")
    spec = importlib.util.spec_from_file_location("audit_kconfiglib", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    requested = derive_config(model, comm)
    if model.startswith("stm32"):
        requested["CONFIG_CLOCK_REF_FREQ"] = "12000000" if model == "stm32f446" else "8000000"
    choices = klipper_config(requested, model)
    config = tmp_path / ".config"
    config.write_text("".join(f"{key}={value}\n" for key, value in choices.items()))
    previous = Path.cwd()
    try:
        os.chdir(KLIPPER)
        kconf = module.Kconfig("src/Kconfig", warn_to_stderr=False)
        kconf.load_config(str(config))
        kconf.write_config(str(config))
    finally:
        os.chdir(previous)
    assert kconf.syms["MCU"].str_value == resolved
    if address is not None:
        assert int(kconf.syms["FLASH_APPLICATION_ADDRESS"].str_value, 16) == address
    assert validate_config(str(tmp_path), requested=requested, processor=model)[0]
    assert _compiler_for_config(config.read_text()) == ("avr-gcc" if model.startswith("atmega") else "arm-none-eabi-gcc")
    config.write_text(config.read_text().replace(f'CONFIG_MACH_{model.upper()}=y', ""))
    if model.startswith(("stm32", "lpc", "rp")):
        assert not validate_config(str(tmp_path), requested=requested, processor=model)[0]


def test_real_buildcommands_version_and_embedded_metadata(tmp_path):
    from firmware.boards.kconfig import artifact_contains_firmware_fingerprint
    script = KLIPPER / "scripts/buildcommands.py"
    if not script.exists():
        pytest.skip("Pinned Klipper checkout unavailable")
    marker = "kace-b1-" + "2" * 32
    request = tmp_path / "requests.txt"
    request.write_text("DECL_COMMAND_FLAGS command_identify 0 identify offset=%u count=%c\n")
    dictionary = tmp_path / "dict.json"
    subprocess.run([sys.executable, "-B", str(script), "--extra=-" + marker,
                    "-d", str(dictionary), str(request), str(tmp_path / "generated.c")],
                   cwd=KLIPPER, check=True, capture_output=True)
    version = json.loads(dictionary.read_text())["version"]
    assert firmware_version_matches(version, marker)
    assert artifact_contains_firmware_fingerprint(zlib.compress(dictionary.read_bytes()), marker)
    assert "--extra=-" + marker in fingerprint_makefile((KLIPPER / "Makefile").read_text(), marker)
    assert not firmware_version_matches(version + "0", marker)
    assert not firmware_version_matches(version + "-" + marker, marker)
    assert not firmware_version_matches(version, "kace-b1-" + "3" * 32)
    compressed = zlib.compress(dictionary.read_bytes())
    records = []
    for offset in range(0, len(compressed), 16):
        chunk = compressed[offset:offset + 16]
        record = bytes([len(chunk)]) + offset.to_bytes(2, "big") + b"\0" + chunk
        records.append(b":" + (record + bytes([-sum(record) % 256])).hex().encode())
    ihex = b"\n".join(records + [b":00000001FF"])
    assert artifact_contains_firmware_fingerprint(ihex, marker)


@pytest.mark.parametrize("changed", [True, False])
def test_unchanged_root_is_verified_after_activation(tmp_path, changed):
    plan = build_managed_config_plan(GENERATED, None, {})
    transport = FakeTransport({a.remote_name: a.content for a in plan.artifacts})
    def external_edit(*_args):
        transport.files[ROOT_REMOTE] = b"# external edit\n"
    transport.restart = external_edit
    kwargs = {} if changed else {"verify_firmware": external_edit}
    result = ConfigDeploymentTransaction(
        transport, GENERATED.replace(b"PA1", b"PA2") if changed else GENERATED, None,
        activation="firmware", snapshot_root=str(tmp_path), poll_interval=0, **kwargs).run()
    assert result.state is not ConfigTransactionState.COMMITTED
    assert transport.files[ROOT_REMOTE] == b"# external edit\n"


@pytest.mark.parametrize("active_in_include", [False, True])
def test_actual_klipper_active_calibration_wins_over_older_autosave(tmp_path, active_in_include):
    source = KLIPPER / "klippy/configfile.py"
    if not source.exists():
        pytest.skip("Pinned Klipper checkout unavailable")
    spec = importlib.util.spec_from_file_location("audit_configfile", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    active = b"[probe]\npin: PA1\nz_offset: 1.5\n"
    saved = (module.AUTOSAVE_HEADER + "#*# [probe]\n#*# z_offset = 2.375\n").encode()
    files = {ROOT_REMOTE: saved if active_in_include else active + saved}
    if active_in_include:
        files[HARDWARE_REMOTE] = active
    plan = build_managed_config_plan(b"[probe]\npin: PA1\nz_offset: 0\n", None, files)
    for item in plan.artifacts:
        path = tmp_path / item.remote_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(item.content)
    printer = Mock()
    printer.get_start_args.return_value = {"config_file": str(tmp_path / ROOT_REMOTE)}
    printer.command_error = RuntimeError
    autosave = module.ConfigAutoSave(printer)
    effective, _ = autosave.load_main_config()
    assert effective.getfloat("probe", "z_offset") == 1.5
    autosave.set("probe", "z_offset", "3")
    autosave.cmd_SAVE_CONFIG(Mock(error=RuntimeError))
    assert autosave.load_main_config()[0].getfloat("probe", "z_offset") == 3


@pytest.mark.parametrize("fail_at", [1, 2, 3])
def test_installer_preserves_original_on_failed_rename(tmp_path, fail_at):
    bash = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
    if not Path(bash).exists():
        pytest.skip("Bash unavailable")
    install, stage, backup = [tmp_path / name for name in ("install", ".kace-install.test", ".kace-backup.test")]
    for path in (install, stage, backup):
        path.mkdir()
    (install / "core").write_text("ORIGINAL")
    (stage / "core").write_text("NEW")
    source = (ROOT / "install.sh").read_text(encoding="utf-8")
    functions = source[source.index("_safe_remove_transaction_dir() {"):source.index("trap _cleanup_installer EXIT")]
    script = f'''export PATH=/usr/bin:/bin:$PATH
INSTALL_PARENT='{tmp_path.as_posix()}'
INSTALL_DIR='{install.as_posix()}'
STAGING_DIR='{stage.as_posix()}'
BACKUP_DIR='{backup.as_posix()}'
PUBLICATION_ACTIVE=1
PUBLISHED_PATHS=' core'
{functions}
count=0
mv() {{ count=$((count+1)); [ "$count" -ne {fail_at} ] || return 1; command mv "$@"; }}
mv -- "$INSTALL_DIR/core" "$BACKUP_DIR/core" && mv -- "$STAGING_DIR/core" "$INSTALL_DIR/core"
false
_cleanup_installer
'''
    result = subprocess.run([bash, "-c", script], capture_output=True, text=True)
    assert result.returncode == 1
    copies = [p for base in (install, stage, backup) for p in base.rglob("*") if p.is_file() and p.read_text() == "ORIGINAL"]
    assert copies
    if fail_at < 3:
        assert (install / "core").read_text() == "ORIGINAL"
    else:
        assert "preserved runtime copies" in result.stderr


@pytest.mark.parametrize("hint", ["usb", "manual"])
def test_initial_stock_mcu_uses_exact_contract_before_checkpoint(hint):
    from core.firmware_wizard import resolve_initial_mcu
    from core.firmware_workflow import create_checkpoint
    data = {"board": "generic-creality-v4.2.7.cfg", "mcu_hint": hint,
            "mcu_path": "/dev/serial/by-id/usb-CH340-original"}
    assert resolve_initial_mcu(data) == "stm32f103"
    checkpoint = create_checkpoint(data, identity_reader=SimpleNamespace(read=lambda _: None))
    assert checkpoint["hardware"]["mcu"] == "stm32f103"


def test_multi_variant_contract_is_not_guessed():
    from core.firmware_wizard import resolve_initial_mcu
    from firmware.boards.runtime import BoardContractRuntimeError
    with pytest.raises(BoardContractRuntimeError, match="exact variant"):
        resolve_initial_mcu({"board": "generic-bigtreetech-skr-v1.4.cfg", "mcu_hint": "manual"})


@pytest.mark.parametrize("same", [True, False])
def test_creality_uart_bridge_requires_original_physical_adapter(tmp_path, same):
    from core.mcu_monitor import McuIdentity
    from core.firmware_workflow import create_checkpoint, transition_checkpoint, verify_reappeared_mcu, CheckpointIncompatible, FirmwareWorkflowState as State
    from tests.unit.test_firmware_workflow import artifact
    path = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
    baseline = McuIdentity(path, "/dev/ttyUSB0", physical_port="usb-1", vendor_id="1a86", model_id="7523", serial="original")
    data = {"board": "generic-creality-v4.2.7.cfg", "mcu_type": "stm32f103", "mcu_path": path}
    checkpoint = create_checkpoint(data, identity_reader=SimpleNamespace(read=lambda _: baseline))
    checkpoint = transition_checkpoint(checkpoint, State.ARTIFACT_READY, artifact=artifact(tmp_path, model=data["mcu_type"]))
    checkpoint = transition_checkpoint(checkpoint, State.AWAITING_FLASH)
    candidate = baseline if same else McuIdentity(path, "/dev/ttyUSB1", physical_port="usb-2", vendor_id="1a86", model_id="7523", serial="other")
    with patch("core.firmware_workflow.os.path.exists", return_value=True):
        verify = lambda: verify_reappeared_mcu(checkpoint, detector=lambda: {"mcu_path": path}, flash_evidence=True,
                            identity_reader=SimpleNamespace(read=lambda _: candidate), ambiguity_resolver=lambda _: True)
        if same:
            assert verify()[0]["state"] == State.MCU_VERIFIED.value
        else:
            with pytest.raises(CheckpointIncompatible):
                verify()


@pytest.mark.parametrize("hint", ["usb", "manual"])
def test_cli_does_not_skip_first_install_firmware_without_detected_model(tmp_path, monkeypatch, hint):
    import copy
    import kace
    from core.workflow_outcome import pending_activation
    from tests.regression.test_main_integration import _WIZARD_USER_DATA_WITH_PARSED
    data = copy.deepcopy(_WIZARD_USER_DATA_WITH_PARSED)
    data.update(board="generic-creality-v4.2.7.cfg", mcu_type=None, mcu_hint=hint, probe="None", display_choice="none")
    monkeypatch.setenv("KACE_AUTO", "1")
    monkeypatch.setenv("KACE_FIRMWARE_WORKFLOW_PATH", str(tmp_path / "workflow.json"))
    with patch("kace.run_wizard", return_value=data), patch("kace.has_todo_pins", return_value=[]), \
         patch("kace.generate_config") as generate, patch("kace.time.sleep"), patch("builtins.print"), \
         patch("core.firmware_workflow.McuIdentityReader", return_value=SimpleNamespace(read=lambda _: None)), \
         patch("core.firmware_wizard.run_firmware_wizard", return_value=pending_activation("compile required")) as firmware:
        with pytest.raises(SystemExit) as result:
            kace.main()
    assert result.value.code == 41
    firmware.assert_called_once_with(data)
    generate.assert_not_called()
    assert json.loads((tmp_path / "workflow.json").read_text())["hardware"]["mcu"] == "stm32f103"


def test_contract_model_alias_is_exact_and_board_specific():
    from core.firmware_workflow import _same_mcu_model
    assert _same_mcu_model("generic-creality-v4.2.7.cfg", "stm32f103", "stm32f103xe")
    assert not _same_mcu_model("generic-creality-v4.2.7.cfg", "stm32f103", "stm32f446xx")
    assert not _same_mcu_model("unknown.cfg", "stm32f103", "stm32f103xe")


def test_legacy_build_rejects_missing_embedded_identity(tmp_path, monkeypatch):
    from firmware import builder
    from firmware.identity import FirmwareBuildInputs, ToolchainIdentity
    (tmp_path / "Makefile").write_text("$(PYTHON) ./scripts/buildcommands.py -d $(OUT)klipper.dict")
    inputs = FirmwareBuildInputs.create(klipper_commit="1" * 40, canonical_config='CONFIG_MCU="stm32f446xx"\n',
        toolchain=ToolchainIdentity("make", "make", "gcc", "gcc"))
    monkeypatch.setattr(builder, "generate_firmware_config", lambda *a, **kw: (True, ""))
    monkeypatch.setattr(builder, "validate_config", lambda *a, **kw: (True, ""))
    monkeypatch.setattr(builder, "create_build_inputs", lambda **kw: inputs)
    monkeypatch.setattr(builder, "is_mock_build", lambda _: False)
    def make(command, **kw):
        if "-f" in command:
            (tmp_path / "out").mkdir()
            (tmp_path / "out/klipper.bin").write_bytes(b"firmware without identity" * 1024)
        return Mock()
    monkeypatch.setattr(builder.subprocess, "run", make)
    result = builder.build_firmware_orchestrator(derived_mcu="stm32f446", hint="usb",
        klipper_path=str(tmp_path), output_dir=str(tmp_path / "published"), build_context=builder.BuildContext(concurrency=1))
    assert result["status"] == "error"
    assert "does not contain" in result["message"]
    assert not (tmp_path / "published/klipper.bin").exists()
