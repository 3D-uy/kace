"""Explicit known/deferred Z decisions preserve geometry and accepted drafts."""
import copy
import os

import pytest

from core.firmware_workflow import persistable_wizard_data, restore_wizard_data
from core.menu import _plain_label
from core.translations import get_lang, set_lang, t
from core.wizard.runner import _BACK
from core.wizard.steps import sensors, probe_homing
from tests.unit.test_probe_review_navigation import guided_user
from tests.unit.test_probe_homing_contract import wizard_probe_data


@pytest.fixture(autouse=True)
def interactive(monkeypatch):
    previous = get_lang()
    set_lang("English")
    monkeypatch.setenv("KACE_AUTO", "0")
    yield
    set_lang(previous)


@pytest.mark.parametrize("value", ["2", "0", "0.5000001"])
def test_known_choice_preserves_supplied_value_and_never_changes_minimum(monkeypatch, value):
    user = guided_user()
    original = copy.deepcopy(user)
    answers = iter(["1", value])
    monkeypatch.setattr("builtins.input", lambda *args: next(answers))
    assert sensors._step_guided_custom_probe_value(user, "custom_probe_z_offset") == "done"
    assert sensors._step_custom_probe(user) == "done"
    assert user["custom_probe_settings"].z_offset == float(value)
    assert user["custom_probe"].z_offset == float(value)
    assert user["z_position_min"] == original["z_position_min"]
    if value != "0":
        monkeypatch.setattr(probe_homing, "numbered_select", lambda *a, **k: pytest.fail("valid offset"))
        assert probe_homing.review_probe_homing_geometry(user)


@pytest.mark.parametrize("accept", [True, False])
def test_unknown_choice_then_confirmed_preparation_uses_zero_without_calibrating(monkeypatch, accept):
    user = guided_user()
    original = copy.deepcopy(user)
    answers = iter(["2", "y"] if accept else
                   ["2", "n", "cancel", "<"])
    monkeypatch.setattr("builtins.input", lambda *args: next(answers))
    result = sensors._step_guided_custom_probe_value(user, "custom_probe_z_offset")
    assert result == ("done" if accept else _BACK)
    if accept:
        assert sensors._step_custom_probe(user) == "done"
        monkeypatch.setattr(probe_homing, "numbered_select", lambda *a, **k: pytest.fail("Already reviewed in Z decision"))
        assert probe_homing.review_probe_homing_geometry(user)
        assert user["z_position_min"] == "0"
        assert user["custom_probe_settings"].z_offset is None
        assert user["custom_probe"].z_offset == 0
        assert user["custom_probe"].config_text == original["custom_probe"].config_text
    else:
        assert user == original


@pytest.mark.parametrize("answers", [["<"], ["known", "<", "<"]])
def test_back_preserves_previous_known_value(monkeypatch, answers):
    user = {"custom_probe_z_offset": "2"}
    before = copy.deepcopy(user)
    responses = iter(answers)
    monkeypatch.setattr("builtins.input", lambda *args: next(responses))
    assert sensors._step_guided_custom_probe_value(user, "custom_probe_z_offset") == _BACK
    assert user == before


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
@pytest.mark.parametrize("width", [40, 60, 80, 120])
def test_review_groups_and_state_survive_checkpoint_without_rewriting_raw(monkeypatch, capsys, language, width):
    set_lang(language)
    monkeypatch.setattr("shutil.get_terminal_size", lambda **kw: os.terminal_size((width, 24)))
    user = restore_wizard_data(persistable_wizard_data(guided_user()))
    original = copy.deepcopy(user)
    monkeypatch.setattr(sensors, "numbered_select", lambda *a, **k: "continue")
    assert sensors._step_custom_probe_review(user) == "done"
    text = _plain_label(capsys.readouterr().out)
    normalized = " ".join(text.split())
    for group in ("connection", "offsets", "measurements"):
        assert t("wizard.probe_review.group_" + group) in normalized
    assert normalized.count(" ".join(t("wizard.review_probe.provisional").split())) == 1
    assert "# " not in text
    assert max(map(len, text.splitlines())) <= width
    assert user == original


def test_resumed_known_zero_is_not_reported_as_provisional(monkeypatch, capsys):
    user = guided_user()
    user["custom_probe_z_offset"] = "0"
    sensors._step_custom_probe(user)
    user = restore_wizard_data(persistable_wizard_data(user))
    monkeypatch.setattr(sensors, "numbered_select", lambda *a, **k: "continue")
    assert sensors._step_custom_probe_review(user) == "done"
    normalized = " ".join(_plain_label(capsys.readouterr().out).split())
    assert " ".join(t("wizard.review_probe.provisional").split()) not in normalized
    assert " ".join(t("wizard.review_probe.supplied").split()) in normalized


@pytest.mark.parametrize("choice,expected", [("known", 2.0), ("later", None)])
def test_resumed_review_edits_z_while_preserving_other_raw_bytes(monkeypatch, choice, expected):
    user = guided_user()
    user["custom_probe_z_offset"] = "1"
    sensors._step_custom_probe(user)
    user = restore_wizard_data(persistable_wizard_data(user))
    raw = user["custom_probe"].config_text
    answers = iter(["offset", choice] + (["2"] if choice == "known" else ["y"]) + ["continue"])
    monkeypatch.setattr("builtins.input", lambda *args: next(answers))
    assert sensors._step_custom_probe_review(user) == "done"
    assert user["custom_probe_settings"]["z_offset"] == expected
    assert user["custom_probe"].config_text == raw.replace("z_offset: 1", "z_offset: 2" if expected else "z_offset: 0")
    assert user["z_position_min"] == ("0.5" if choice == "known" else "0")


def test_imported_zero_is_not_assumed_to_be_an_unknown_measurement(monkeypatch):
    user = wizard_probe_data()
    original = copy.deepcopy(user)
    def cancel(prompt, choices, **kwargs):
        assert t("wizard.probe_z.prepare_later") not in [choice["name"] for choice in choices]
        return "cancel"
    monkeypatch.setattr(probe_homing, "numbered_select", cancel)
    assert not probe_homing.review_probe_homing_geometry(user)
    assert user == original
