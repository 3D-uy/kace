"""Primary probe inputs and advanced aliases remain explicit, reversible choices."""
import copy
from unittest.mock import patch

import pytest

from core.exceptions import WizardExit
from core.translations import get_lang, set_lang
from core.wizard.runner import _BACK, _QUIT
from core.wizard.steps import sensors


def context(board):
    return {"board_parsed": board, "driver_type": "None (Standard)", "driver_mode": "Standalone"}


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
def test_primary_menu_keeps_expansion_aliases_behind_localized_advanced_choice(language):
    board = {"probe": {"pin": "^PB8"}, "bltouch": {"sensor_pin": "PB9"},
             "stepper_z": {"endstop_pin": "!PB10"},
             "board_pins": {"aliases": "EXP1_1=PB11,EXP1_2=PB12"}}
    user = context(board)
    old = get_lang()
    set_lang(language)
    try:
        with patch.object(sensors, "_get_parsed", return_value=board), patch.object(
                sensors, "autocomplete_select", return_value=_BACK) as choose:
            assert sensors._step_custom_probe_pin(user) == _BACK
        choices = choose.call_args.kwargs["choices"]
        values = [choice["value"] for choice in choices]
        assert values[:3] == ["PB8", "PB9", "PB10"]
        assert "__advanced__" in values and "__manual__" in values
        assert "PB11" not in values and "PB12" not in values
        assert all("wizard." not in choice["name"] for choice in choices)
        assert "custom_probe_pin" not in user
    finally:
        set_lang(old)


@pytest.mark.parametrize("source,token,pullup,inverted", [
    ("probe", "^!PB8", True, True), ("bltouch", "!PB8", False, True),
    ("z_endstop", "^!PB8", False, False),
])
def test_input_signal_flags_come_from_selected_probe_not_replaced_endstop(source, token, pullup, inverted):
    name, field = {"probe": ("probe", "pin"), "bltouch": ("bltouch", "sensor_pin"),
                   "z_endstop": ("stepper_z", "endstop_pin")}[source]
    board = {name: {field: token}}
    user = context(board)
    with patch.object(sensors, "_get_parsed", return_value=board), patch.object(
            sensors, "autocomplete_select", return_value="PB8"):
        assert sensors._step_custom_probe_pin(user) == "done"
    assert user["custom_probe_pin"] == "PB8"
    assert user["custom_probe_pullup"] is pullup
    assert user["custom_probe_inverted"] is inverted


@pytest.mark.parametrize("pin", ["probe:z_virtual_endstop", "tmc2209_stepper_z:virtual_endstop", "TODO", "<GND>"])
def test_virtual_and_placeholder_endstops_never_become_physical_input_candidates(pin):
    board = {"stepper_z": {"endstop_pin": pin}}
    with patch.object(sensors, "_get_parsed", return_value=board):
        assert sensors._get_probe_input_candidates(context(board)) == []


def test_alias_identity_deduplicates_inputs_but_not_different_mcus():
    board = {"probe": {"pin": "^HEADER"}, "bltouch": {"sensor_pin": "PB8"},
             "stepper_z": {"endstop_pin": "!toolhead:PB8"},
             "board_pins": {"aliases": "HEADER=PB8"}}
    with patch.object(sensors, "_get_parsed", return_value=board):
        choices = sensors._get_probe_input_candidates(context(board))
    assert [choice["pin"] for choice in choices] == ["PB8", "toolhead:PB8"]
    assert choices[0]["source"] == "probe"
    assert choices[0]["pullup"] is True


@pytest.mark.parametrize("end", [_BACK, _QUIT, None])
def test_advanced_back_then_cancel_does_not_change_an_existing_selection(end):
    board = {"probe": {"pin": "PB8"}, "board_pins": {"aliases": "EXP1_1=PB10"}}
    user = context(board)
    user.update(custom_probe_pin="PB9", custom_probe_pullup=True, custom_probe_inverted=True)
    before = copy.deepcopy(user)
    with patch.object(sensors, "_get_parsed", return_value=board), patch.object(
            sensors, "autocomplete_select", side_effect=["__advanced__", _BACK, end]) as choose:
        if end == _BACK:
            assert sensors._step_custom_probe_pin(user) == _BACK
        else:
            with pytest.raises(WizardExit):
                sensors._step_custom_probe_pin(user)
    assert choose.call_count == 3
    assert user == before


def test_advanced_selection_is_revalidated_against_new_consumer():
    board = {"probe": {"pin": "PB8"}, "board_pins": {"aliases": "EXP1_1=PB10"}}
    user = context(board)
    before = copy.deepcopy(user)
    count = 0
    def choose(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 1:
            return "__advanced__"
        assert "PB10" in [choice["value"] for choice in kwargs["choices"]]
        board["fan"] = {"pin": "PB10"}
        return "PB10"
    with patch.object(sensors, "_get_parsed", return_value=board), patch.object(
            sensors, "autocomplete_select", side_effect=choose):
        assert sensors._step_custom_probe_pin(user) == "__retry__"
    assert "custom_probe_pin" not in user
    assert "custom_probe_pullup" not in user
    assert "custom_probe_inverted" not in user
    # The simulated external board change is not a stored probe choice.
    assert {k: v for k, v in user.items() if k != "board_parsed"} == {k: v for k, v in before.items() if k != "board_parsed"}


@pytest.mark.parametrize("new_aliases", ["", "EXP1_1=PB11", "RENAMED=PB10"])
def test_advanced_declaration_change_retries_even_when_original_gpio_remains_free(new_aliases, capsys):
    board = {"probe": {"pin": "PB8"}, "board_pins": {"aliases": "EXP1_1=PB10"}}
    user = context(board)
    user.update(custom_probe_pin="PB9", custom_probe_pullup=True, custom_probe_inverted=True)
    previous_selection = {key: value for key, value in user.items() if key != "board_parsed"}
    count = 0
    def choose(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 1:
            return "__advanced__"
        assert any(choice["value"] == "PB10" and "EXP1_1" in choice["name"]
                   for choice in kwargs["choices"])
        board["board_pins"]["aliases"] = new_aliases
        # Allocation alone cannot detect removal/remapping of a menu declaration.
        assert sensors.make_pin_validator_with_collision_check(user, for_custom_probe=True)("PB10") is True
        return "PB10"
    with patch.object(sensors, "autocomplete_select", side_effect=choose):
        assert sensors._step_custom_probe_pin(user) == "__retry__"
    assert {key: value for key, value in user.items() if key != "board_parsed"} == previous_selection
    from core.translations import t
    assert t("wizard.custom_probe_input_changed") in capsys.readouterr().out


def test_advanced_unchanged_declaration_can_be_selected():
    board = {"probe": {"pin": "PB8"}, "board_pins": {"aliases": "EXP1_1=PB10"}}
    user = context(board)
    with patch.object(sensors, "autocomplete_select", side_effect=["__advanced__", "PB10"]):
        assert sensors._step_custom_probe_pin(user) == "done"
    assert user["custom_probe_pin"] == "PB10"
    assert user["custom_probe_pullup"] is False
    assert user["custom_probe_inverted"] is False


def test_manual_selection_after_compact_menu_uses_custom_transition_and_explicit_modifiers():
    board = {"stepper_z": {"endstop_pin": "!PB8"}}
    user = context(board)
    with patch.object(sensors, "_get_parsed", return_value=board), patch.object(
            sensors, "autocomplete_select", return_value="__manual__"), patch.object(
            sensors, "simple_input", return_value="^!PB8") as prompt:
        assert sensors._step_custom_probe_pin(user) == "done"
    assert prompt.call_args.kwargs["validate"]("^!PB8") is True
    assert user["custom_probe_pin"] == "PB8"
    assert user["custom_probe_pullup"] is True
    assert user["custom_probe_inverted"] is True


@pytest.mark.parametrize("answer,expected", [("^!PB8", (True, True)), ("PB8", (False, False))])
def test_manual_same_gpio_explicit_flags_override_old_flags_but_bare_input_preserves_them(answer, expected):
    board = {"probe": {"pin": "PB8"}}
    user = context(board)
    user.update(custom_probe_pin="PB8", custom_probe_pullup=False, custom_probe_inverted=False)
    with patch.object(sensors, "_get_parsed", return_value=board), patch.object(
            sensors, "autocomplete_select", return_value="__manual__"), patch.object(
            sensors, "simple_input", return_value=answer):
        assert sensors._step_custom_probe_pin(user) == "done"
    assert (user["custom_probe_pullup"], user["custom_probe_inverted"]) == expected
