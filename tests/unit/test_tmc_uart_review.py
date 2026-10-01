"""Preserved destination files cannot bypass TMC UART review."""
from unittest.mock import Mock, patch

import pytest

from core.configuration_review import validate_configuration_plan
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.managed_config import build_managed_config_plan
from core.deployer import _copy_artifacts
from tests.unit.test_config_transaction import FakeTransport, GENERATED


UART = GENERATED + b"[tmc2209 stepper_x]\nuart_pin: PC11\nrun_current: 0.580\n"


CASES = [
    ("mixed-model-valid", "[tmc2208 stepper_y]\nuart_pin: PC12\n", True),
    ("mixed-model-duplicate", "[tmc2208 stepper_y]\nuart_pin: mcu:PC11\n", False),
    ("additional-target", "[tmc2209 stepper_z3]\nuart_pin: PC11\n", False),
    ("second-address", "[tmc2209 stepper_y]\nuart_pin: PC11\nuart_address: 1\n", True),
    ("invalid-2208-address", "[tmc2208 stepper_y]\nuart_pin: PC12\nuart_address: 1\n", False),
    ("invalid-address", "[tmc2209 stepper_y]\nuart_pin: PC12\nuart_address: bad\n", False),
    ("missing-rx", "[tmc2209 stepper_y]\nrun_current: 0.580\n", False),
    ("fan-conflict", "[fan]\npin: !PC11\n", False),
    ("stepper-conflict", "[stepper_y]\nstep_pin: PC11\n", False),
    ("diag-conflict", "[tmc2209 stepper_x]\ndiag_pin: ^PC11\n", False),
    ("independent-mcu", "[mcu tool]\nserial: /dev/serial/tool\n[fan]\npin: tool:PC11\n", True),
    ("case-sensitive-mcu", "[mcu Tool]\nserial: /dev/serial/tool\n[tmc2208 stepper_y]\nuart_pin: Tool:PC11\n", True),
    ("multiline-alias", "[board_pins custom]\naliases:\n  HEADER=PC11,\n  NEXT=HEADER\n[fan]\npin: NEXT\n", False),
    ("override-does-not-bypass", "[duplicate_pin_override]\npins: PC11\n[fan]\npin: PC11\n", False),
    ("macro-not-hardware", "[gcode_macro TEST]\nvariable_pin: PC11\ngcode:\n  M118 test\n", True),
]


def remote_files(extra):
    return {"printer.cfg": GENERATED + b"[include user.cfg]\n",
            "user.cfg": b"[include wiring.cfg]\n", "wiring.cfg": extra.encode()}


@pytest.mark.parametrize("name,extra,valid", CASES, ids=[c[0] for c in CASES])
def test_review_expands_preserved_includes(name, extra, valid):
    plan = build_managed_config_plan(UART, None, remote_files(extra))
    result = validate_configuration_plan(plan)
    uart_errors = [e for e in result.errors if e.code == "tmc-uart-conflict"]
    assert bool(uart_errors) is not valid, result


@pytest.mark.parametrize("noop", [False, True])
def test_transaction_rejects_before_confirmation_writes_and_restart(tmp_path, noop):
    remote = remote_files("[tmc2208 stepper_y]\nuart_pin: PC11\n")
    if noop:
        initial = build_managed_config_plan(UART, None, remote)
        remote.update({a.remote_name: a.content for a in initial.artifacts})
        assert not build_managed_config_plan(UART, None, remote).changed_artifacts
    transport = FakeTransport(remote)
    confirm = Mock(return_value=True)
    result = ConfigDeploymentTransaction(transport, UART, None, activation="none", confirm=confirm,
        snapshot_root=str(tmp_path / "snapshots"), verify_existing_ready=noop).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "UART" in result.detail
    confirm.assert_not_called()
    assert transport.files == remote
    assert not any(c[0] in ("upload", "delete", "restart") for c in transport.calls)


def test_valid_mixed_models_can_publish_without_restart(tmp_path):
    transport = FakeTransport(remote_files("[tmc2208 stepper_y]\nuart_pin: PC12\nrun_current: 0.580\n"))
    result = ConfigDeploymentTransaction(transport, UART, None, activation="none",
        snapshot_root=str(tmp_path / "snapshots")).run()
    assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    assert any(c[0] == "upload" for c in transport.calls)


def test_local_export_rejects_preserved_uart_conflict(tmp_path, capsys):
    before = remote_files("[fan]\npin: PC11\n")
    transport = FakeTransport(before)
    with patch("core.deployer._generated_config_bytes", return_value=("source.cfg", UART, None)), \
            patch("core.config_transaction.LocalConfigTransport", return_value=transport), \
            patch("core.deployer._review_configuration_export", return_value=True):
        assert not _copy_artifacts({}, str(tmp_path), "config")
    assert "TMC UART" in capsys.readouterr().out
    assert transport.files == before
    assert not any(c[0] == "upload" for c in transport.calls)


def test_include_edit_after_confirmation_cannot_be_published(tmp_path):
    transport = FakeTransport(remote_files("[fan]\npin: PC12\n"))
    def edit_include(_):
        transport.files["wiring.cfg"] = b"[fan]\npin: PC11\n"
        return True
    result = ConfigDeploymentTransaction(transport, UART, None, activation="none", confirm=edit_include,
        snapshot_root=str(tmp_path / "snapshots")).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert not any(c[0] in ("upload", "delete", "restart") for c in transport.calls)
    assert transport.files["wiring.cfg"] == b"[fan]\npin: PC11\n"


def test_generated_uart_cannot_reuse_motor_step_pin(tmp_path):
    from core.generator import generate_config
    from core.exceptions import GenerationError
    from tests.unit.test_generator import _parsed, _user
    board = _parsed()
    board["tmc2208 stepper_x"] = {"run_current": "0.580", "uart_pin": "PC11", "select_pins": "PD1"}
    output = tmp_path / "printer.cfg"
    with pytest.raises(GenerationError, match="TMC UART.*stepper_z"):
        generate_config(board, _user(driver_type="TMC2208", driver_mode="UART"), output_path=str(output))
    assert not output.exists()
