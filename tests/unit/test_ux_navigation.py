"""F3B regressions: real input helper and validators, only terminal IO replaced."""
import copy
import io
import os
from unittest.mock import patch

import pytest
from core import menu
from core.exceptions import WizardExit
from core.wizard.runner import WizardRunner, PHASE_MAP, _BACK
from core.wizard.steps import sensors, motion, hardware
from core.translations import get_lang, get_mode, set_lang, set_mode


@pytest.fixture(autouse=True)
def interactive(monkeypatch):
    monkeypatch.setenv("KACE_AUTO", "0")
    monkeypatch.setattr(menu, "_MOCK_PROMPTS_ACTIVE", False)


@pytest.mark.parametrize("token", ["<", "back", "volver", "voltar", "__back__", " BACK "])
@pytest.mark.parametrize("question", sensors.GUIDED_CUSTOM_PROBE_QUESTIONS)
def test_numeric_back_never_becomes_data(token, question):
    state = {"custom_probe_pin": "PA1"}
    before = copy.deepcopy(state)
    with patch("builtins.input", return_value=token) as terminal:
        assert sensors._step_guided_custom_probe_value(state, question[0]) == _BACK
    assert terminal.call_count == 1
    assert state == before


@pytest.mark.parametrize("question,bad,good", [
    ("custom_probe_z_offset", "nan", "-1.25"),
    ("custom_probe_speed", "0", "5"),
    ("custom_probe_samples", "1.5", "2"),
    ("custom_probe_samples_tolerance", "-1", "0"),
    ("custom_probe_samples_tolerance_retries", "-1", "0"),
    ("custom_probe_sample_retract_dist", "inf", "2"),
])
def test_invalid_values_still_retry(question, bad, good):
    state = {}
    with patch("builtins.input", side_effect=[bad, good]) as terminal:
        assert sensors._step_guided_custom_probe_value(state, question) == "done"
    assert state[question] == good
    assert terminal.call_count == 2


def test_optional_absence_and_default_preserved():
    state = {}
    with patch("builtins.input", return_value=""):
        sensors._step_guided_custom_probe_value(state, "custom_probe_z_offset")
        sensors._step_guided_custom_probe_value(state, "custom_probe_samples")
    assert state == {"custom_probe_z_offset": "", "custom_probe_samples": "2"}


@pytest.mark.parametrize("error", [EOFError, KeyboardInterrupt])
def test_cancel_remains_exit(error):
    with patch("builtins.input", side_effect=error), pytest.raises(WizardExit):
        sensors._step_guided_custom_probe_value({}, "custom_probe_speed")


def test_back_is_opt_in_for_plain_text():
    with patch("builtins.input", return_value="back"):
        assert menu.simple_input("Name") == "back"


def test_volume_back_uses_positive_validator_without_mutation():
    state = {"x_size": "200"}
    with patch("builtins.input", side_effect=["-1", "<"]) as terminal:
        assert motion._step_volume(state, "x_size", "x_position_max", "Volume") == _BACK
    assert terminal.call_count == 2
    assert state == {"x_size": "200"}


@pytest.mark.parametrize("axis", "xyz")
def test_axis_subquestion_backtracking_is_preserved(axis):
    state = {}
    with patch("builtins.input", side_effect=["-5", "<", "-2", "200", "0"]):
        assert getattr(motion, f"_step_{axis}_limits")(state) == "done"
    assert state[f"{axis}_position_min"] == "-2"
    assert state[f"{axis}_position_max"] == "200"
    assert state[f"{axis}_position_endstop"] == "0"


def test_manual_probe_pin_back_uses_real_collision_validator():
    state = {"board_parsed": {}, "board": ""}
    before = copy.deepcopy(state)
    with patch("builtins.input", return_value="<"):
        assert sensors._step_custom_probe_pin(state) == _BACK
    assert state == before


def test_tmc_back_discards_staged_input_and_does_not_confirm():
    from tests.unit.test_tmc_required_current import missing_user
    state = missing_user()
    before = copy.deepcopy(state)
    with patch("builtins.input", return_value="<"), patch.object(hardware, "yes_no") as confirm:
        assert hardware._step_tmc_currents(state) == _BACK
    confirm.assert_not_called()
    assert state == before


def test_z_mechanics_back_discards_staging_and_does_not_confirm():
    from tests.unit.test_z_mechanics_wizard import data
    state = data()
    before = copy.deepcopy(state)
    with patch.object(motion, "numbered_select", return_value="individual"), \
            patch("builtins.input", return_value="<"), patch.object(motion, "yes_no") as confirm:
        assert motion._step_z_mechanics(state) == _BACK
    confirm.assert_not_called()
    assert state == before


def test_runner_back_retry_branch_and_receipt_rollback():
    answers = iter(["custom", "none"])
    states = []
    def choose(state):
        states.append(copy.deepcopy(state))
        answer = next(answers)
        state["probe"] = answer
        state["receipt"] = answer
        return answer
    config = {
        "probe": {"prompt": choose, "next": lambda a, ud: "custom_probe_speed" if a == "custom" else "bed_therm"},
        "custom_probe_speed": {"prompt": lambda ud: sensors._step_guided_custom_probe_value(ud, "custom_probe_speed")},
        "bed_therm": {"prompt": lambda ud: "done"},
    }
    runner = WizardRunner(config, list(config), {})
    with patch("builtins.input", return_value="<"), patch("core.wizard.ui._print_step_header") as header:
        result = runner.run("probe")
    assert states == [{}, {}]
    assert result == {"probe": "none", "receipt": "none"}
    assert runner.history_stack == ["probe", "bed_therm"]
    assert header.call_args.kwargs["active_steps"] == ["probe", "bed_therm"]
    assert "custom_probe_speed" not in runner.snapshots


def test_retry_does_not_increase_step_number_or_keep_draft():
    count = 0
    def prompt(state):
        nonlocal count
        count += 1
        assert "draft" not in state
        state["draft"] = count
        return "__retry__" if count == 1 else "done"
    runner = WizardRunner({"probe": {"prompt": prompt}}, ["probe"], {})
    with patch("core.wizard.ui._print_step_header") as header:
        runner.run("probe")
    assert [call.kwargs["active_steps"] for call in header.call_args_list] == [["probe"], ["probe"]]


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
@pytest.mark.parametrize("step", [key for key in PHASE_MAP if key.startswith("custom_probe_")] + ["homing_directions"])
def test_custom_probe_headers_localized_and_internal_step_not_counted(language, step):
    from core.wizard.ui import _print_step_header
    old_lang, old_mode = get_lang(), get_mode()
    try:
        set_lang(language); set_mode("Beginner")
        with patch("core.wizard.ui._SUPPRESS_HEADERS", False), patch.dict(os.environ, {"KACE_QUIET": "0"}), patch("sys.stdout", new_callable=io.StringIO) as output:
            _print_step_header(step, {}, active_steps=["previous", step])
        assert "wizard." not in output.getvalue()
        assert "2" in output.getvalue()
        from core.translations import t
        assert t("wizard.custom_probe_intro") not in output.getvalue()
        if step.startswith("custom_probe_") and not step.endswith(("preview", "offsets")):
            title = t(f"wizard.step.{step}.header")
            assert title in output.getvalue()  # Full title must fit, never be clipped.
            assert t("wizard.custom_probe_guided_hint").split()[0] in output.getvalue()
    finally:
        set_lang(old_lang); set_mode(old_mode)


def test_internal_steps_run_without_header_or_count():
    calls = []
    config = {"probe": {"prompt": lambda ud: calls.append("probe")},
              "custom_probe": {"prompt": lambda ud: calls.append("assemble"), "visible": lambda ud: False},
              "custom_probe_review": {"prompt": lambda ud: calls.append("review")}}
    with patch("core.wizard.ui._print_step_header") as header:
        WizardRunner(config, list(config), {}).run("probe")
    assert calls == ["probe", "assemble", "review"]
    assert header.call_args.kwargs["active_steps"] == ["probe", "custom_probe_review"]


@pytest.mark.parametrize("answers,key", [(["<"], "probe_x_offset"), (["-38", "<"], "probe_y_offset")])
def test_probe_offset_preview_back_does_not_reach_confirmation(answers, key):
    from core import probe_offset_visualizer as preview
    with patch("builtins.input", side_effect=answers), patch.object(preview, "numbered_select") as confirm:
        result = preview.run_probe_offset_step({"probe": "Custom Probe"})
    assert result[key] == _BACK
    confirm.assert_not_called()


def test_uart_pin_back_propagates_through_staged_tmc_step():
    state = {"z_motors": "2", "z_socket_assignments": {"stepper_z1": "custom"},
             "board_parsed": {}, "board_raw_config": "# custom", "driver_type": "TMC2209", "driver_mode": "UART"}
    before = copy.deepcopy(state)
    with patch("builtins.input", return_value="<"), patch.object(hardware, "yes_no") as confirm:
        assert hardware._step_tmc_currents(state) == _BACK
    assert state == before
    confirm.assert_not_called()


@pytest.fixture(params=["English", "Español", "Português"])
def ui_language(request):
    old = get_lang()
    set_lang(request.param)
    yield request.param
    set_lang(old)


def test_search_localized_without_changing_selection(ui_language, capsys):
    from core.translations import t
    choices = [(f"PB{i}", i) for i in range(20)] + [(t("choice.back"), _BACK)]
    with patch("builtins.input", side_effect=["missing", "PB", "missing", t("choice.back")]) as terminal:
        assert menu.autocomplete_select("Pin", choices) == _BACK
    output = capsys.readouterr().out
    assert t("menu.search_help", count=21) in output
    assert t("menu.search_no_matches", query="missing") in output
    assert t("menu.search_matches", query="PB") in output
    assert t("menu.search_retry", query="missing") in output
    prompts = [call.args[0] for call in terminal.call_args_list]
    assert t("menu.search_prompt", value="PB0") in prompts[0]
    assert t("menu.search_select", count=20) in prompts[2]
    with patch("builtins.input", side_effect=["PB", "3"]):
        assert menu.autocomplete_select("Pin", choices) == 2
    with patch("builtins.input", return_value=""):
        assert menu.autocomplete_select("Pin", choices, default=7) == 7
    for error in (KeyboardInterrupt, EOFError):
        with patch("builtins.input", side_effect=error), pytest.raises(WizardExit):
            menu.autocomplete_select("Pin", choices)


def test_localized_probe_and_driver_labels_keep_internal_values(ui_language, capsys):
    from core.translations import t
    state = {}
    with patch("builtins.input", return_value="3"):
        assert sensors._step_probe(state) == sensors.PROBE_KIND_INDUCTIVE
    assert state["probe"] == "Inductive"
    output = capsys.readouterr().out
    assert t("wizard.probe_none") in output
    assert t("wizard.probe_inductive") in output
    with patch.object(hardware, "_get_parsed", return_value={}), patch.object(
        hardware, "detect_driver_info", return_value={"is_socketed": True}
    ), patch("builtins.input", return_value="1"):
        assert hardware._step_driver_type(state) == "None (Standard)"
    assert state["driver_type"] == "None (Standard)"
    expected_label = {
        "English": "Other STEP/DIR driver (no UART/SPI)",
        "Español": "Otro driver STEP/DIR (sin UART/SPI)",
        "Português": "Outro driver STEP/DIR (sem UART/SPI)",
    }[ui_language]
    output = capsys.readouterr().out
    assert expected_label in output
    assert "None (Standard)" not in output
    from core.terminal import INPUT
    assert INPUT not in output


def test_mcu_auto_detection_uses_selected_language(ui_language, capsys):
    from firmware.detector import discover_mcu_hardware
    from core.translations import t
    port = "/dev/serial/by-id/usb-Klipper_stm32f446xx_Octopus-v1.1-if00"
    with patch("glob.glob", return_value=[port]):
        assert discover_mcu_hardware()["mcu_path"] == port
    assert t("mcu.auto_detected") in capsys.readouterr().out
