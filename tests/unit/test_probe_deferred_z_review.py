"""A deferred calibration decision only needs incompatible travel reviewed."""
import copy
import os

import pytest

from core.exceptions import GenerationError
from core.firmware_workflow import persistable_wizard_data, restore_wizard_data
from core.profile_values import mark_user_override
from core.translations import get_lang, set_lang, t
from core.wizard.runner import WizardRunner
from core.wizard.steps import probe_homing, sensors
from tests.unit.test_probe_review_navigation import actual_catalog, guided_user


@pytest.fixture(autouse=True)
def interactive(monkeypatch):
    previous = get_lang()
    set_lang("English")
    monkeypatch.setenv("KACE_AUTO", "0")
    yield
    set_lang(previous)


def deferred_user(restored=False):
    user = guided_user()
    return restore_wizard_data(persistable_wizard_data(user)) if restored else user


def set_limit(user, key, value):
    user[key] = value
    mark_user_override(user, key)


@pytest.mark.parametrize("restored", [False, True])
@pytest.mark.parametrize("minimum", ["0", "-1"])
def test_compatible_deferred_range_advances_without_any_prompt(monkeypatch, restored, minimum):
    user = deferred_user(restored)
    set_limit(user, "z_position_min", minimum)
    original = copy.deepcopy(user)
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("No repeated question"))
    monkeypatch.setattr(probe_homing, "yes_no", lambda *a, **k: pytest.fail("No limit change"))
    assert probe_homing.review_probe_homing_geometry(user)
    assert user == original


@pytest.mark.parametrize("restored", [False, True])
@pytest.mark.parametrize("language", ["English", "Español", "Português"])
@pytest.mark.parametrize("width", [60, 80, 120])
def test_deferred_conflict_asks_physical_confirmation_before_edit_or_back(
        monkeypatch, capsys, restored, language, width):
    set_lang(language)
    monkeypatch.setattr("shutil.get_terminal_size", lambda **k: os.terminal_size((width, 24)))
    user = deferred_user(restored)
    original = copy.deepcopy(user)

    def cancel(prompt, choices, **kwargs):
        assert prompt == t("wizard.probe_z.minimum_prompt")
        assert kwargs["require_explicit"] is True
        assert choices == [
            {"name": t("wizard.probe_z.edit_minimum"), "value": "edit"},
            {"name": t("wizard.probe_z.back_review"), "value": "cancel"},
        ]
        return "cancel"

    monkeypatch.setattr(probe_homing, "numbered_select", cancel)
    confirmations = []
    monkeypatch.setattr(probe_homing, "yes_no", lambda prompt, **kw: confirmations.append((prompt, kw)) or False)
    assert not probe_homing.review_probe_homing_geometry(user)
    text = capsys.readouterr().out
    normalized = " ".join(text.split())
    assert " ".join(t("wizard.probe_z.deferred_context").split()) in normalized
    assert confirmations == [(t("wizard.probe_z.confirm_deferred_minimum", old="0.5", new="0"), {"default": False})]
    assert t("wizard.probe_z.deferred_title") not in normalized
    assert t("wizard.probe_z.known") not in normalized
    assert t("wizard.probe_z.later") not in normalized
    assert " ".join(t("wizard.probe_z.definition").split()) not in normalized
    assert "wizard." not in text
    assert max(map(len, text.splitlines())) <= width
    assert user == original


@pytest.mark.parametrize("restored", [False, True])
@pytest.mark.parametrize("action,value", [("prepare_zero", "0"), ("edit", "-0.25")])
def test_deferred_minimum_is_staged_and_only_changes_after_physical_confirmation(
        monkeypatch, restored, action, value):
    user = deferred_user(restored)
    original = copy.deepcopy(user)
    expected = copy.deepcopy(original)
    set_limit(expected, "z_position_min", value)
    monkeypatch.setattr(probe_homing, "numbered_select", lambda *a, **k: action)
    monkeypatch.setattr(probe_homing, "simple_input", lambda *a, **k: value)
    confirmations = []

    def confirm(prompt, default):
        assert user == original
        assert default is False
        expected_prompt = (t("wizard.probe_z.confirm_deferred_minimum", old="0.5", new="0")
                           if not confirmations else t("wizard.review_z.confirm", old="0.5", new=value))
        assert prompt == expected_prompt
        confirmations.append(prompt)
        return action == "prepare_zero" or len(confirmations) == 2

    monkeypatch.setattr(probe_homing, "yes_no", confirm)
    assert probe_homing.review_probe_homing_geometry(user)
    assert len(confirmations) == (1 if action == "prepare_zero" else 2)
    assert user == expected
    resumed = restore_wizard_data(persistable_wizard_data(user))
    assert resumed["custom_probe_settings"]["z_offset"] is None
    assert resumed["custom_probe"].config_text == original["custom_probe"].config_text
    monkeypatch.setattr(probe_homing, "numbered_select", lambda *a, **k: pytest.fail("Already compatible"))
    assert probe_homing.review_probe_homing_geometry(resumed)


@pytest.mark.parametrize("restored", [False, True])
def test_declining_clearance_retains_deferred_choice_and_all_limits(monkeypatch, restored):
    user = deferred_user(restored)
    original = copy.deepcopy(user)
    actions = iter(["cancel"])
    monkeypatch.setattr(probe_homing, "numbered_select", lambda *a, **k: next(actions))
    confirmations = []

    def refuse(prompt, default):
        assert default is False
        confirmations.append(prompt)
        return False

    monkeypatch.setattr(probe_homing, "yes_no", refuse)
    assert not probe_homing.review_probe_homing_geometry(user)
    assert len(confirmations) == 1
    assert user == original


@pytest.mark.parametrize("value", ["0.5", "2", "350", "nan", "inf", "-inf"])
def test_invalid_deferred_minimum_never_reaches_confirmation(monkeypatch, value):
    user = deferred_user()
    original = copy.deepcopy(user)
    actions = iter(["edit", "cancel"])
    monkeypatch.setattr(probe_homing, "numbered_select", lambda *a, **k: next(actions))
    monkeypatch.setattr(probe_homing, "simple_input", lambda *a, **k: value)
    confirmations = []
    def decline_proposal(prompt, **kwargs):
        assert not confirmations, "An invalid manual range must not reach confirmation"
        confirmations.append(prompt)
        return False
    monkeypatch.setattr(probe_homing, "yes_no", decline_proposal)
    assert not probe_homing.review_probe_homing_geometry(user)
    assert user == original


def test_deferred_invalid_maximum_does_not_offer_a_zero_fix(monkeypatch, capsys):
    user = deferred_user()
    set_limit(user, "z_position_max", "-1")
    original = copy.deepcopy(user)

    def cancel(prompt, choices, **kwargs):
        assert [c["value"] for c in choices] == ["edit", "cancel"]
        return "cancel"

    monkeypatch.setattr(probe_homing, "numbered_select", cancel)
    assert not probe_homing.review_probe_homing_geometry(user)
    normalized = " ".join(capsys.readouterr().out.split())
    assert " ".join(t("wizard.probe_z.deferred_range", minimum="0.5", maximum="-1").split()) in normalized
    assert user == original


def test_explicit_manual_review_of_compatible_deferred_range_remains_available(monkeypatch):
    user = deferred_user()
    set_limit(user, "z_position_min", "0")
    original = copy.deepcopy(user)

    def unchanged(prompt, choices, **kwargs):
        assert [c["value"] for c in choices] == ["continue", "edit", "cancel"]
        return "continue"

    monkeypatch.setattr(probe_homing, "numbered_select", unchanged)
    assert probe_homing.review_probe_homing_geometry(user, force=True)
    assert user == original


def test_rejected_manual_edit_does_not_label_accepted_deferred_range_incompatible(monkeypatch, capsys):
    user = deferred_user()
    set_limit(user, "z_position_min", "0")
    original = copy.deepcopy(user)
    answers = iter(["edit", "1", "continue"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    monkeypatch.setattr(probe_homing, "yes_no", lambda *a, **k: pytest.fail("Invalid proposed range"))
    assert probe_homing.review_probe_homing_geometry(user, force=True)
    normalized = " ".join(capsys.readouterr().out.split())
    assert t("wizard.review_z.rejected", value="1") in normalized
    assert " ".join(t("wizard.probe_z.deferred_range", minimum="0", maximum="350").split()) not in normalized
    assert user == original


@pytest.mark.parametrize("settings", [None, {}, {"z_offset": 0}])
def test_zero_without_explicit_deferred_setting_retains_known_offset_editor(monkeypatch, settings):
    user = deferred_user()
    user["custom_probe_settings"] = settings
    original = copy.deepcopy(user)

    def cancel(prompt, choices, **kwargs):
        assert "offset" in [c["value"] for c in choices]
        assert prompt == t("wizard.profile_review_prompt")
        return "cancel"

    monkeypatch.setattr(probe_homing, "numbered_select", cancel)
    assert not probe_homing.review_probe_homing_geometry(user)
    assert user == original


def test_auto_mode_cannot_accept_a_deferred_minimum_change(monkeypatch):
    user = deferred_user()
    original = copy.deepcopy(user)
    monkeypatch.setenv("KACE_AUTO", "1")
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("No automatic consent"))
    with pytest.raises(GenerationError):
        probe_homing.review_probe_homing_geometry(user)
    assert user == original


@pytest.mark.parametrize("minimum", ["0", "0.5"])
def test_real_offset_decision_then_review_keeps_calibration_deferred(monkeypatch, minimum):
    user = guided_user()
    set_limit(user, "z_position_min", minimum)
    answers = iter(["2"] + (["y"] if minimum == "0.5" else []))
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    assert sensors._step_guided_custom_probe_value(user, "custom_probe_z_offset") == "done"
    assert sensors._step_custom_probe(user) == "done"
    original_probe = user["custom_probe"]
    # The minimum was already confirmed in the Z decision, not at the gate.
    assert user["z_position_min"] == "0"
    answers = iter(["continue"])
    catalog = actual_catalog()
    catalog["hotend_therm"] = {"prompt": lambda state: "done", "next": lambda a, u: None}
    runner = WizardRunner(catalog, ["custom_probe_review", "probe_homing", "hotend_therm"], user)
    result = runner.run("custom_probe_review")
    assert "hotend_therm" in runner.history_stack
    assert result["custom_probe_settings"].z_offset is None
    assert result["custom_probe"] == original_probe
    assert result["z_position_min"] == "0"
    with pytest.raises(StopIteration):
        next(answers)
