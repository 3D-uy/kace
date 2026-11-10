"""Drive the real probe menus and wizard routing through a rejected Z range."""
import copy
from unittest.mock import patch

import pytest

import core.wizard as wizard
from core.custom_probe import GuidedCustomProbeSettings, parse_custom_probe_config
from core.translations import get_lang, set_lang
from core.wizard.runner import WizardRunner, _BACK
from core.wizard.steps import sensors, motion
from tests.unit.test_probe_homing_contract import wizard_probe_data
from tests.unit.test_homing_direction_wizard import travel


@pytest.fixture
def interactive(monkeypatch):
    old = get_lang()
    set_lang("English")
    monkeypatch.setenv("KACE_AUTO", "0")
    monkeypatch.setattr("core.wizard.ui._print_step_header", lambda *a, **k: None)
    yield
    set_lang(old)


def actual_catalog():
    captured = {}
    def capture(self, start):
        captured.update(self.steps_config)
        return {}
    with patch.object(WizardRunner, "run", capture), \
            patch.object(wizard, "discover_mcu", return_value={}), \
            patch.object(wizard, "fetch_config_list", return_value=[]):
        wizard.run_wizard()
    return captured


def guided_user():
    user = wizard_probe_data()
    user.update(custom_probe_pin="PB8", custom_probe_pullup=True,
                custom_probe_x_offset="-12", custom_probe_y_offset="4",
                custom_probe_z_offset="", custom_probe_speed="7")
    assert sensors._step_custom_probe(user) == "done"
    return user


@pytest.mark.parametrize("answers,minimum,offset", [
    (["continue", "n", "cancel", "offset", "known", "1", "continue"], "0.5", 1),
    (["continue", "n", "edit", "0", "y"], "0", 0),
    (["continue", "y"], "0", 0),
])
def test_rejected_geometry_returns_to_editable_review_and_can_finish(
        interactive, monkeypatch, answers, minimum, offset):
    config = actual_catalog()
    user = guided_user()
    inputs = iter(answers)
    monkeypatch.setattr("builtins.input", lambda *a: next(inputs))
    config["hotend_therm"] = {"prompt": lambda ud: "done", "next": lambda a, u: None}
    runner = WizardRunner(config, ["custom_probe_review", "probe_homing", "hotend_therm"], user)
    result = runner.run("custom_probe_review")
    assert result["z_position_min"] == minimum
    assert result["custom_probe"].z_offset == offset
    assert result["custom_probe_settings"].speed == 7
    assert result["custom_probe"].x_offset == -12
    assert result["custom_probe_pin"] == "PB8"
    assert "hotend_therm" in runner.history_stack
    with pytest.raises(StopIteration):
        next(inputs)


def test_review_cancelled_edit_preserves_every_guided_value(interactive, monkeypatch):
    user = guided_user()
    original = copy.deepcopy(user)
    inputs = iter(["2", "<", "1"])
    monkeypatch.setattr("builtins.input", lambda *a: next(inputs))
    assert sensors._step_custom_probe_review(user) == "done"
    assert user == original


def test_back_from_gate_preserves_previous_review_edit(interactive, monkeypatch):
    config = actual_catalog()
    user = guided_user()
    inputs = iter(["offset", "known", "0.25", "continue", "cancel",
                   "offset", "known", "1", "continue"])
    prompts = []
    def enter(prompt):
        prompts.append(prompt)
        return next(inputs)
    monkeypatch.setattr("builtins.input", enter)
    config["hotend_therm"] = {"prompt": lambda ud: "done", "next": lambda a, u: None}
    runner = WizardRunner(config, ["custom_probe_review", "probe_homing", "hotend_therm"], user)
    runner.run("custom_probe_review")
    assert any("0.25" in prompt for prompt in prompts)
    assert user["custom_probe"].z_offset == 1


def test_unknown_polarity_survives_raw_checkpoint_restore(interactive, monkeypatch):
    from core.firmware_workflow import persistable_wizard_data, restore_wizard_data
    user = guided_user()
    monkeypatch.setattr("builtins.input", lambda *a: "3")
    assert sensors._step_custom_probe_signal_option(user, "inverted") == "done"
    assert sensors._step_custom_probe(user) == "done"
    raw = user["custom_probe"].config_text
    assert "Polarity is unverified" in raw
    restored = restore_wizard_data(persistable_wizard_data(user))
    assert restored["custom_probe"].config_text == raw


def test_unknown_signal_is_explicitly_provisional_and_back_does_not_mutate(interactive, monkeypatch, capsys):
    user = {"custom_probe_inverted": True}
    inputs = iter(["4", "3"])
    monkeypatch.setattr("builtins.input", lambda *a: next(inputs))
    assert sensors._step_custom_probe_signal_option(user, "inverted") == _BACK
    assert user == {"custom_probe_inverted": True}
    assert sensors._step_custom_probe_signal_option(user, "inverted") == "done"
    assert user["custom_probe_inverted"] is False
    assert user["custom_probe_polarity_unverified"] is True
    output = capsys.readouterr().out
    assert "QUERY_PROBE" in output and "before any homing" in output


def test_pullup_can_go_back_without_changing_the_selected_signal(interactive, monkeypatch):
    user = {"custom_probe_pullup": True}
    monkeypatch.setattr("builtins.input", lambda *a: "3")
    assert sensors._step_custom_probe_signal_option(user, "pullup") == _BACK
    assert user == {"custom_probe_pullup": True}


def test_switching_probe_type_clears_unknown_polarity(interactive, monkeypatch):
    user = guided_user()
    user["custom_probe_polarity_unverified"] = True
    monkeypatch.setattr("builtins.input", lambda *a: "1")
    assert sensors._step_probe(user) == "none"
    assert "custom_probe_polarity_unverified" not in user


def test_missing_guided_payload_goes_back_instead_of_retrying_without_input():
    assert sensors._step_custom_probe({}) == _BACK
    assert sensors._step_custom_probe_review({}) == _BACK


@pytest.mark.parametrize("language,marker", [
    ("English", "UNCALIBRATED"), ("Español", "SIN CALIBRAR"),
    ("Português", "NÃO CALIBRADO"),
])
def test_guided_comments_are_localized_and_raw_imports_are_preserved(language, marker):
    block = GuidedCustomProbeSettings("PB8", -12, 4).to_config(language=language)
    assert marker in block.config_text
    assert "QUERY_PROBE" in block.config_text and "PROBE_CALIBRATE" in block.config_text
    assert block.z_offset == 0
    original = "# own comment\n[probe]\npin: PB8\nz_offset: 1\n"
    assert parse_custom_probe_config(original).config_text == original


def test_reviewed_profile_reuses_directions_without_repeating_choices(interactive):
    user = travel(x_position_endstop="320")
    with patch.object(motion, "numbered_select", side_effect=AssertionError("duplicate homing prompt")):
        assert motion._step_homing_directions(user, reviewed=True) == "done"
    assert user["homing_positive_dir_x"] == "True"
    assert user["homing_positive_dir_y"] == "False"
    assert actual_catalog()["profile_review"]["next"]("confirm", user) == "z_mechanics"


def test_reviewed_profile_still_resolves_ambiguous_homing(interactive):
    user = travel(x_position_endstop="160")
    with patch.object(motion, "numbered_select", return_value="True") as select:
        assert motion._step_homing_directions(user, reviewed=True) == "done"
    assert select.call_count == 1
    assert user["homing_positive_dir_x"] == "True"
