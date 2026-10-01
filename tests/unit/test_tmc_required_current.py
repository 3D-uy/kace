"""Missing motor current must be supplied explicitly, never synthesized."""
import copy
from unittest.mock import patch

import pytest

from core.exceptions import GenerationError, WizardExit
from core.generator import generate_config
from core.profile_values import resolve_generation_values, mark_user_override, tmc_run_current
from core.wizard.steps import hardware
from tests.unit.test_tmc_electrical_authority import inputs


@pytest.mark.parametrize("model", ["tmc2208", "tmc2209", "tmc2130", "tmc5160"])
@pytest.mark.parametrize("target", ["x", "y", "z", "z1", "z2", "z3", "e"])
def test_absent_current_cannot_use_a_stale_default(model, target):
    board, _, user, section = inputs(model, target)
    del board[section]["run_current"]
    user[f"run_current_{target}"] = "0.650"
    user["_value_provenance"][f"run_current_{target}"] = "SAFE_DEFAULT"
    values, provenance = resolve_generation_values(board, user)
    assert f"run_current_{target}" not in values
    assert provenance[f"run_current_{target}"] == "UNRESOLVED"


def missing_user():
    board, _, user, section = inputs()
    user["z_motors"] = "1"
    board[section].pop("run_current")
    user["_value_provenance"]["run_current_x"] = "SAFE_DEFAULT"
    return user


def test_generation_blocks_missing_current_before_writing(tmp_path):
    user = missing_user()
    output = tmp_path / "printer.cfg"
    with pytest.raises(GenerationError, match="run_current_x"):
        generate_config(user["board_parsed"], user, output_path=str(output), verbose=False)
    assert not output.exists()


def test_guided_current_is_explicit_and_generates(tmp_path):
    user = missing_user()
    with patch.object(hardware, "simple_input", return_value="0.730") as prompt, \
            patch.object(hardware, "yes_no", return_value=True):
        assert hardware._step_tmc_currents(user) == "done"
    assert prompt.call_args.kwargs["default"] == ""
    assert user["run_current_x"] == "0.730"
    assert user["_value_provenance"]["run_current_x"] == "USER_OVERRIDE"
    assert "run_current" not in user["board_parsed"]["tmc2209 stepper_x"]
    result = generate_config(user["board_parsed"], user, output_path=str(tmp_path / "p.cfg"), verbose=False)
    assert "run_current: 0.730" in result["content"]


@pytest.mark.parametrize("answer", [None, "__quit__", "__back__", "nan", "inf", "-0.1", "0", "2.001", ""])
def test_invalid_or_cancelled_input_does_not_mutate_state(answer):
    user = missing_user()
    before = copy.deepcopy(user)
    with patch.object(hardware, "simple_input", return_value=answer), \
            patch.object(hardware, "yes_no", return_value=True):
        if answer in (None, "__quit__"):
            with pytest.raises(WizardExit):
                hardware._step_tmc_currents(user)
        else:
            assert hardware._step_tmc_currents(user) in ("__back__", "__retry__")
    assert user == before


def test_declined_current_confirmation_is_atomic():
    user = missing_user()
    before = copy.deepcopy(user)
    with patch.object(hardware, "simple_input", return_value="0.730"), \
            patch.object(hardware, "yes_no", return_value=False):
        assert hardware._step_tmc_currents(user) == "__retry__"
    assert user == before


def test_auto_never_prompts_for_missing_current(monkeypatch):
    user = missing_user()
    before = copy.deepcopy(user)
    monkeypatch.setenv("KACE_AUTO", "1")
    with patch.object(hardware, "simple_input") as prompt:
        with pytest.raises(GenerationError, match="run_current_x"):
            hardware._step_tmc_currents(user)
    prompt.assert_not_called()
    assert user == before


def test_complete_current_source_skips_prompt():
    _, _, user, _ = inputs()
    user["z_motors"] = "1"
    with patch.object(hardware, "simple_input") as prompt:
        assert hardware._step_tmc_currents(user) == "done"
    prompt.assert_not_called()


def test_custom_socket_does_not_create_a_board_current():
    user = {"z_motors": "2", "z_socket_assignments": {"stepper_z1": "custom"},
            "board_parsed": {}, "board_raw_config": "# custom", "driver_type": "TMC2209", "driver_mode": "UART"}
    with patch.object(hardware, "simple_input", return_value="PC9"):
        hardware._apply_z_tmc_mappings(user)
    assert user["board_parsed"]["tmc2209 stepper_z1"] == {"uart_pin": "PC9"}


@pytest.mark.parametrize("model,maximum", [("tmc2208", 2), ("tmc2209", 2), ("tmc2225", 2), ("tmc2130", 2), ("tmc5160", 10)])
@pytest.mark.parametrize("value", ["0", "-0.1", "nan", "inf", "", "over", "maximum", "0.580"])
def test_numeric_contract(model, maximum, value):
    value = str(maximum + 0.001) if value == "over" else str(maximum) if value == "maximum" else value
    if value in (str(maximum), "0.580"):
        assert tmc_run_current(model, value) == value
    else:
        with pytest.raises(GenerationError):
            tmc_run_current(model, value)


@pytest.mark.parametrize("owner", ["PROFILE", "USER_OVERRIDE", "SAFE_DEFAULT"])
def test_invalid_current_blocks_generation_from_every_source(tmp_path, owner):
    board, _, user, section = inputs()
    user["z_motors"] = "1"
    board[section]["run_current"] = "2.001"
    user["run_current_x"] = "2.001"
    user["_value_provenance"]["run_current_x"] = owner
    with pytest.raises(GenerationError, match="run_current_x"):
        generate_config(board, user, output_path=str(tmp_path / "p.cfg"), verbose=False)
    assert not (tmp_path / "p.cfg").exists()


def test_configuration_change_during_confirmation_is_not_overwritten():
    user = missing_user()
    def confirm(*args, **kwargs):
        user["board"] = "other.cfg"
        return True
    with patch.object(hardware, "simple_input", return_value="0.730"), \
            patch.object(hardware, "yes_no", side_effect=confirm):
        assert hardware._step_tmc_currents(user) == "__retry__"
    assert user["board"] == "other.cfg"
    assert user["_value_provenance"]["run_current_x"] == "SAFE_DEFAULT"


def test_auto_preserves_explicit_current_on_resume(monkeypatch):
    user = missing_user()
    user["run_current_x"] = "0.730"
    mark_user_override(user, "run_current_x")
    monkeypatch.setenv("KACE_AUTO", "1")
    with patch.object(hardware, "simple_input") as prompt:
        assert hardware._step_tmc_currents(user) == "done"
    prompt.assert_not_called()
    assert user["run_current_x"] == "0.730"


@pytest.mark.parametrize("target", ["x", "y", "z", "z1", "z2", "z3", "e"])
def test_every_motor_can_receive_an_individual_current(target):
    board, _, user, section = inputs(target=target)
    del board[section]["run_current"]
    with patch.object(hardware, "simple_input", return_value="0.730") as prompt, \
            patch.object(hardware, "yes_no", return_value=True):
        assert hardware._step_tmc_currents(user) == "done"
    assert prompt.call_count == 1
    assert user[f"run_current_{target}"] == "0.730"


def test_custom_socket_and_current_are_accepted_together():
    user = missing_user()
    user.update(z_motors="2", z_socket_assignments={"stepper_z1": "custom"}, board_raw_config="# custom")
    with patch.object(hardware, "simple_input", side_effect=["PC9", "0.730", "0.510"]), \
            patch.object(hardware, "yes_no", return_value=True):
        assert hardware._step_tmc_currents(user) == "done"
    assert user["board_parsed"]["tmc2209 stepper_z1"] == {"uart_pin": "PC9"}
    assert user["run_current_x"] == "0.730" and user["run_current_z1"] == "0.510"


def test_auto_missing_custom_pin_never_prompts(monkeypatch):
    user = missing_user()
    user.update(z_motors="2", z_socket_assignments={"stepper_z1": "custom"}, board_raw_config="# custom")
    monkeypatch.setenv("KACE_AUTO", "1")
    with patch.object(hardware, "simple_input") as prompt:
        with pytest.raises(GenerationError, match="uart_pin"):
            hardware._step_tmc_currents(user)
    prompt.assert_not_called()


def test_runner_back_discards_current_before_a_new_selection():
    from core.wizard.runner import WizardRunner
    user = missing_user()
    visits = []
    def next_step(state):
        visits.append(state["run_current_x"])
        return "__back__" if len(visits) == 1 else "done"
    runner = WizardRunner({"tmc_currents": {"prompt": hardware._step_tmc_currents},
                           "probe": {"prompt": next_step}}, ["tmc_currents", "probe"], user)
    with patch.object(hardware, "simple_input", side_effect=["0.730", "0.610"]), \
            patch.object(hardware, "yes_no", return_value=True):
        result = runner.run("tmc_currents")
    assert visits == ["0.730", "0.610"]
    assert result["run_current_x"] == "0.610"


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
def test_current_step_has_translated_header_and_help(language):
    from core.translations._strings import UI_STRINGS
    for key in ("wizard.step.tmc_currents.header", "wizard.step.tmc_currents.hint",
                "wizard.tmc_current.title", "wizard.tmc_current.help", "wizard.tmc_current.input",
                "wizard.tmc_current.invalid", "wizard.tmc_current.confirm", "wizard.tmc_current.changed"):
        assert UI_STRINGS[key][language]
