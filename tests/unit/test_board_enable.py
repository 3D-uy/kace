"""Kobra Go PB6 is a hardware enable, not a slicer/start-macro dependency."""
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from core.board_auxiliary import selected_board_digital_outputs, selected_board_electrical_source
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.configuration_review import validate_configuration_plan
from core.custom_probe import parse_custom_probe_config
from core.exceptions import GenerationError
from core.generator import generate_config
from core.managed_config import build_managed_config_plan
from core.pin_validator import _read_pin_config
from core.scraper import parse_config
from tests.unit.test_generator import _user
from tests.unit.test_config_transaction import FakeTransport, GENERATED

PROFILE = "printer-anycubic-kobra-go-2022.cfg"
SECTION = "output_pin enable_pin"
FIXTURE = Path(__file__).resolve().parents[1]/"fixtures/board-enable"/PROFILE


def board_case():
    raw = FIXTURE.read_bytes().decode()
    board = parse_config(raw, PROFILE, keep_comments=True)
    choices = _user(board=PROFILE, x_size="220", y_size="220", z_size="250", probe="Custom Probe")
    fields = _read_pin_config(raw)[0]["probe"]
    choices["custom_probe"] = parse_custom_probe_config("[probe]\n"+"".join(f"{k}: {v}\n" for k,v in fields.items()))
    return raw, board, choices


def test_real_generation_recovery_provenance_and_repeat_publication(tmp_path):
    raw, board, choices = board_case()
    text = generate_config(board, choices, output_path=str(tmp_path/"printer.cfg"), verbose=False)["content"].encode()
    assert _read_pin_config(text.decode())[0][SECTION] == {"pin": "PB6", "value": "1"}
    proof = json.loads((tmp_path/"printer.cfg.provenance.json").read_text())
    assert proof["sources"]["auxiliary_digital_outputs"][SECTION] == {"pin":"PB6", "value":"1"}
    recovered = selected_board_electrical_source({"board":PROFILE, "board_raw_config":raw})
    dest = FakeTransport()
    for _ in range(2):
        outcome = ConfigDeploymentTransaction(dest, text, None, selected_board=recovered,
            activation="none", snapshot_root=str(tmp_path/"snapshots"), poll_interval=0).run()
        assert outcome.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION, outcome.detail


@pytest.mark.parametrize("mutation", ["source", "value", "pwm", "pin", "shutdown"])
def test_invalid_enable_never_overwrites_artifacts(tmp_path, mutation):
    _, board, choices = board_case()
    if mutation == "source": board.pop("_auxiliary_electrical_activity")
    else: board[SECTION][mutation] = {"value":".5", "pwm":"true", "pin":"^PB6", "shutdown":"nan"}[mutation]
    if mutation == "shutdown":
        board[SECTION]["shutdown_value"] = board[SECTION].pop("shutdown")
    board["_auxiliary_electrical_active_options"][SECTION] = list(board[SECTION])
    paths = [tmp_path/n for n in ("printer.cfg", "macros.cfg", "printer.cfg.provenance.json")]
    for p in paths: p.write_bytes(b"existing")
    with pytest.raises(GenerationError):
        generate_config(board, choices, output_path=str(paths[0]), include_macros=True, verbose=False)
    assert all(p.read_bytes() == b"existing" for p in paths)


@pytest.mark.parametrize("override", ["pin: PB7", "pin: !PB6", "value: 0", "shutdown_value: 1", "pwm: true"])
@pytest.mark.parametrize("noop", [False, True])
def test_late_override_rejected_before_changes(tmp_path, override, noop):
    _, board, choices = board_case()
    text = generate_config(board, choices, output_path=str(tmp_path/"printer.cfg"), verbose=False)["content"].encode()
    remote = {"printer.cfg":text+b"\n[include user.cfg]\n", "user.cfg":("["+SECTION+"]\n"+override+"\n").encode()}
    if noop:
        remote.update({a.remote_name:a.content for a in build_managed_config_plan(text,None,remote).artifacts})
        assert not build_managed_config_plan(text,None,remote).changed_artifacts
    dest, confirm = FakeTransport(remote), Mock(return_value=True)
    outcome = ConfigDeploymentTransaction(dest,text,None,selected_board=board,confirm=confirm,
        activation="firmware",snapshot_root=str(tmp_path/"snapshots")).run()
    assert outcome.state == ConfigTransactionState.PRECONDITION_FAILED
    assert all(c[0]=="read" for c in dest.calls) and dest.files==remote
    confirm.assert_not_called()


def test_enable_reservations_collisions_and_missing_artifact(tmp_path):
    _, board, choices = board_case()
    text = generate_config(board, choices, output_path=str(tmp_path/"good.cfg"), verbose=False)["content"].encode()
    with patch("core.firmware_workflow.generation_pin_reservations",return_value={"mcu":{"PB6":"reserved bus"}}):
        with pytest.raises(GenerationError, match="reserved bus"):
            generate_config(board, choices,output_path=str(tmp_path/"bad.cfg"),verbose=False)
    review = validate_configuration_plan(build_managed_config_plan(text,None,{}),selected_board=board,
        firmware_reservation_reader=lambda _: {"mcu":{"PB6":"reserved bus"}})
    assert not review.valid and any("reserved bus" in e.message for e in review.errors)
    board[SECTION]["pin"] = board["fan"]["pin"]
    with pytest.raises(GenerationError, match="conflicts"):
        generate_config(board,choices,output_path=str(tmp_path/"bad.cfg"),verbose=False)
    _, board, _ = board_case()
    missing = text.replace(b"[output_pin enable_pin]\npin: PB6\nvalue: 1\n",b"")
    assert missing != text
    dest = FakeTransport()
    outcome = ConfigDeploymentTransaction(dest,missing,None,selected_board=board,activation="firmware",
        snapshot_root=str(tmp_path/"snapshots")).run()
    assert outcome.state == ConfigTransactionState.PRECONDITION_FAILED and not dest.calls


def test_commented_or_unrelated_user_output_does_not_activate_contract(tmp_path):
    source = parse_config("#[output_pin enable_pin]\n#pin: PB6\n#value: 1\n",keep_comments=True)
    assert selected_board_digital_outputs(source) == {}
    remote = {"printer.cfg":GENERATED+b"\n[include user.cfg]\n",
        "user.cfg":b"[output_pin enable_pin]\npin: PG1\npwm: True\ncycle_time: .001\n"}
    reader = Mock(side_effect=AssertionError("unselected user output must not acquire firmware requirements"))
    review = validate_configuration_plan(build_managed_config_plan(GENERATED,None,remote),selected_board=source,
        firmware_reservation_reader=reader)
    assert review.valid
    reader.assert_not_called()


def test_enable_cannot_come_from_mechanical_profile(tmp_path):
    from tests.unit.test_generator import _parsed
    _, foreign, _ = board_case()
    text = generate_config(_parsed(),_user(_profile_parsed=foreign, x_size="220", y_size="220"),
        output_path=str(tmp_path/"printer.cfg"),verbose=False)["content"]
    assert SECTION not in _read_pin_config(text)[0]


def test_missing_enable_blocks_live_export_and_firmware_adapters(tmp_path):
    from core.deployer import _run_config_transaction, _copy_artifacts, deploy_firmware_installation
    from core.workflow_outcome import WorkflowOutcome
    from core.moonraker_deployer import DeployState
    from tests.unit.test_deployer import FirmwareInstallationPreconditionTests
    raw, board, choices = board_case()
    text = generate_config(board,choices,output_path=str(tmp_path/"good.cfg"),verbose=False)["content"].encode()
    missing = text.replace(b"[output_pin enable_pin]\npin: PB6\nvalue: 1\n",b"")
    assert missing != text
    user = FirmwareInstallationPreconditionTests()._user()
    user.update(board=PROFILE,board_raw_config=raw)
    dest = FakeTransport()
    with patch("core.deployer._generated_config_bytes",return_value=("unused",missing,None)), \
         patch("core.config_transaction.configuration_transport",return_value=dest), \
         patch("core.deployer.shutil.copy2") as copy:
        result = _run_config_transaction(dest,user,"none",generated=("unused",missing,None))
        assert result.outcome == WorkflowOutcome.PRECONDITION_FAILED and SECTION in result.detail
        assert not _copy_artifacts(user,str(tmp_path),"all")
        assert deploy_firmware_installation(user).state == DeployState.FAILED_PRECONDITION
    assert not dest.calls
    copy.assert_not_called()
    user["firmware_deployment_service"].execute.assert_not_called()
