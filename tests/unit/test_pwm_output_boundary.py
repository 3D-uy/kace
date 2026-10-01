"""Unimplemented selected-board PWM must not disappear from deployable artifacts."""
from unittest.mock import Mock, patch

import pytest

from core.board_auxiliary import (SOURCE_ACTIVITY, SOURCE_OPTIONS, unresolved_pwm_outputs,
    selected_board_electrical_source, validate_board_electrical_artifact)
from core.config_transaction import ConfigDeploymentTransaction, ConfigTransactionState
from core.exceptions import GenerationError
from core.generator import generate_config
from core.scraper import parse_config
from tests.unit.test_generator import _parsed, _user
from tests.unit.test_config_transaction import FakeTransport, GENERATED

RAW = "[output_pin beeper]\npin: PG1\npwm: True\ncycle_time: .001\n"


@pytest.mark.parametrize("section", ["output_pin beeper", "output_pin stepper_xy_current",
    "output_pin heater_enable", "output_pin fan3", "output_pin auto_poweroff"])
@pytest.mark.parametrize("old", [False, True])
def test_selected_pwm_never_replaces_any_generated_artifact(tmp_path, section, old):
    source = parse_config(RAW.replace("output_pin beeper", section))
    if old:
        source.pop(SOURCE_ACTIVITY)
        source.pop(SOURCE_OPTIONS)
    board = {**_parsed(), **source}
    paths = [tmp_path / n for n in ("printer.cfg", "printer.cfg.provenance.json", "macros.cfg")]
    for path in paths:
        path.write_bytes(b"existing")
    with pytest.raises(GenerationError, match="unsupported electrical dependencies") as error:
        generate_config(board, _user(), output_path=str(paths[0]), include_macros=True, verbose=False)
    assert section in str(error.value)
    assert all(path.read_bytes() == b"existing" for path in paths)


@pytest.mark.parametrize("pwm", ["True", "yes", "on", "1", "invalid", "", None])
def test_true_or_unresolved_pwm_is_not_silently_ignored(pwm):
    assert unresolved_pwm_outputs({"output_pin beeper": {"pin": "PG1", "pwm": pwm}}) == ["output_pin beeper"]


@pytest.mark.parametrize("comments", [False, True])
@pytest.mark.parametrize("raw", ["#[output_pin beeper]\n#pin: PG1\n#pwm: True\n",
    "[output_pin beeper]\npin: PG1\n#pwm: True\n",
    "[output_pin beeper]\npin: PG1\npwm: False\n#pwm: True\n"])
def test_proven_commented_pwm_is_not_activated_or_blocked(comments, raw):
    assert unresolved_pwm_outputs(parse_config(raw, keep_comments=comments)) == []


@pytest.mark.parametrize("metadata", [None, [], {}, {"output_pin beeper": "False"}])
def test_malformed_activity_cannot_hide_pwm(metadata):
    source = {"output_pin beeper": {"pin": "PG1", "pwm": "True"}, SOURCE_ACTIVITY: metadata}
    assert unresolved_pwm_outputs(source) == ["output_pin beeper"]


def test_commented_repeat_does_not_disable_active_pwm():
    source = parse_config(RAW+"#[output_pin beeper]\n#pwm: False\n", keep_comments=True)
    assert unresolved_pwm_outputs(source) == ["output_pin beeper"]


@pytest.mark.parametrize("with_pwm", [False, True])
def test_saved_artifact_even_with_copied_pwm_cannot_bypass_pending_contract(tmp_path, with_pwm):
    artifact = GENERATED+(RAW.encode() if with_pwm else b"")
    source = selected_board_electrical_source({"workflow_checkpoint": {"wizard_data": {
        "board": "selected.cfg", "board_raw_config": RAW}}})
    dest, confirm = FakeTransport({"printer.cfg": artifact}), Mock(return_value=True)
    result = ConfigDeploymentTransaction(dest, artifact, None, selected_board=source, activation="firmware",
        confirm=confirm, snapshot_root=str(tmp_path), poll_interval=0).run()
    assert result.state == ConfigTransactionState.PRECONDITION_FAILED
    assert "output_pin beeper" in result.detail
    assert not dest.calls and dest.files == {"printer.cfg": artifact}
    confirm.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_foreign_mechanical_profile_is_not_selected_pwm_authority(tmp_path):
    result = generate_config(_parsed(), _user(_profile_parsed=parse_config(RAW)),
        output_path=str(tmp_path / "printer.cfg"), verbose=False)
    assert "[output_pin beeper]" not in result["content"]


def test_unrelated_user_pwm_include_remains_allowed(tmp_path):
    remote = {"printer.cfg": GENERATED+b"[include user.cfg]\n", "user.cfg": RAW.encode()}
    dest = FakeTransport(remote)
    result = ConfigDeploymentTransaction(dest, GENERATED, None, selected_board=parse_config(GENERATED.decode()),
        activation="none", snapshot_root=str(tmp_path), poll_interval=0).run()
    assert result.state == ConfigTransactionState.DEPLOYED_PENDING_ACTIVATION
    assert dest.files["user.cfg"] == RAW.encode()


def test_live_export_and_integrated_firmware_stop_before_effects(tmp_path):
    from core.deployer import _run_config_transaction, _copy_artifacts, deploy_firmware_installation
    from core.workflow_outcome import WorkflowOutcome
    from core.moonraker_deployer import DeployState
    from tests.unit.test_deployer import FirmwareInstallationPreconditionTests
    user = FirmwareInstallationPreconditionTests()._user()
    user.update(board="selected.cfg", board_raw_config=RAW)
    dest = FakeTransport()
    with patch("core.deployer._generated_config_bytes", return_value=("unused", GENERATED, None)), \
         patch("core.config_transaction.configuration_transport", return_value=dest), \
         patch("core.deployer.shutil.copy2") as copy:
        assert _run_config_transaction(dest, user, "none", generated=("unused", GENERATED, None)).outcome == WorkflowOutcome.PRECONDITION_FAILED
        assert not _copy_artifacts(user, str(tmp_path), "all")
        assert deploy_firmware_installation(user).state == DeployState.FAILED_PRECONDITION
    assert not dest.calls
    copy.assert_not_called()
    user["firmware_deployment_service"].execute.assert_not_called()
