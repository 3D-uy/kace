"""Exercise nested Back with actual terminal helpers and staged hardware data."""
import copy

import pytest

from core import menu
from core.exceptions import WizardExit
from core.translations import get_lang, set_lang
from core.wizard.runner import WizardRunner, _BACK
from core.wizard.steps import hardware, sensors, software


@pytest.fixture(autouse=True)
def interactive(monkeypatch):
    old = get_lang()
    set_lang("English")
    monkeypatch.setenv("KACE_AUTO", "0")
    monkeypatch.setattr(menu, "_MOCK_PROMPTS_ACTIVE", False)
    yield
    set_lang(old)


def enter(monkeypatch, answers):
    responses = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt: next(responses))


@pytest.mark.parametrize("answers", [
    ["<"],
    ["custom", "<"],
    ["default", "<"],
    ["default", "custom", "<"],
])
def test_fan_nested_back_never_commits_half_of_assignment(monkeypatch, answers):
    state = {"board": "fixture.cfg", "board_raw_config": "[fan]\npin: PA1\n",
             "fan_part_cooling_pin": "old_part", "fan_hotend_pin": "old_hotend"}
    before = copy.deepcopy(state)
    enter(monkeypatch, answers)
    assert hardware._step_fan_assignment(state) == _BACK
    assert state == before


def test_custom_z_socket_back_reopens_previous_motor(monkeypatch):
    state = {"z_motors": "3", "board": "fixture.cfg", "board_raw_config": "# custom\n",
             "board_parsed": {}}
    prompts = []

    def select(prompt, *args, **kwargs):
        prompts.append(prompt)
        return menu.numbered_select(prompt, *args, **kwargs)

    monkeypatch.setattr(hardware, "numbered_select", select)
    enter(monkeypatch, ["custom", "PA1", "PA2", "PA3", "back", "quit"])
    with pytest.raises(WizardExit):
        hardware._step_z_socket_assignment(state)
    assert len(prompts) == 3
    assert prompts[0] != prompts[1]
    assert prompts[2] == prompts[0]


def test_z_socket_back_skips_board_owned_motor_without_deleting_it(monkeypatch):
    state = {"z_motors": "3", "board": "fixture.cfg", "board_raw_config": "# custom\n",
             "board_parsed": {"stepper_z1": {"step_pin": "PA1", "dir_pin": "PA2", "enable_pin": "PA3"}}}
    before = copy.deepcopy(state)
    enter(monkeypatch, ["back"])
    assert hardware._step_z_socket_assignment(state) == _BACK
    assert state == before


def test_z_socket_reassignment_restores_reusable_source_and_discards_old_mapping(monkeypatch):
    source = {"step_pin": "PB1", "dir_pin": "PB2", "enable_pin": "PB3",
              "step_pulse_duration": "0.000002"}
    state = {"z_motors": "3", "board": "fixture.cfg", "board_raw_config": "[extruder1]\n",
             "board_parsed": {"extruder1": copy.deepcopy(source)}}
    enter(monkeypatch, ["extruder1", "back", "custom", "PA1", "PA2", "PA3", "extruder1"])
    assert hardware._step_z_socket_assignment(state) == "done"
    assert state["z_socket_assignments"] == {"stepper_z1": "custom", "stepper_z2": "extruder1"}
    assert state["board_parsed"]["stepper_z1"]["step_pin"] == "PA1"
    assert state["board_parsed"]["stepper_z2"] == source
    assert "extruder1" not in state["board_parsed"]


@pytest.mark.parametrize("answers", [
    ["__manual__", "<", "<"],
    ["cat:basic_lcd", "__manual__", "<", "<", "<"],
])
def test_display_manual_back_retraces_parent_menus_without_committing(monkeypatch, answers):
    from core import display_wizard

    state = {"board": "fixture.cfg", "board_parsed": {},
             "display_choice": "existing", "display_section": "existing_section"}
    before = copy.deepcopy(state)
    monkeypatch.setattr(display_wizard, "run_manual_selection_analysis",
                        lambda *a, **k: pytest.fail("Back must not analyze or accept a display"))
    enter(monkeypatch, answers)
    assert software._step_display(state) == _BACK
    assert state == before


def test_bltouch_back_from_control_pin_restores_probe_selection_snapshot(monkeypatch):
    state = {"board": "fixture.cfg", "board_parsed": {}, "preserved": {"value": 1}}
    monkeypatch.setattr(sensors, "_get_parsed", lambda data: {})
    config = {
        "probe": {"prompt": sensors._step_probe,
                  "next": lambda answer, data: None if answer == "none" else "bltouch_pins"},
        "bltouch_pins": {"prompt": sensors._step_bltouch_pins},
    }
    for step in config.values():
        step["track_interaction"] = True
    enter(monkeypatch, ["bltouch", "PA1", "<", "none"])
    result = WizardRunner(config, list(config), state).run("probe")
    assert result["probe"] == "None"
    assert result["preserved"] == {"value": 1}
    assert "bltouch_sensor_pin" not in result
    assert "bltouch_control_pin" not in result


@pytest.mark.parametrize("probe", ["BLTouch", "CR-Touch", "Inductive"])
def test_structured_probe_back_from_y_offset_keeps_previous_offset_pair(monkeypatch, probe):
    state = {"probe": probe, "probe_x_offset": "-20", "probe_y_offset": "5"}
    before = copy.deepcopy(state)
    enter(monkeypatch, ["-35", "<"])
    assert sensors._step_probe_offsets(state) == _BACK
    assert state == before
