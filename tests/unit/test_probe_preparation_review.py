"""The provisional offset has a visible, confirmed route to a compatible range."""
import copy
import pytest

from core.exceptions import GenerationError
from core.firmware_workflow import persistable_wizard_data, restore_wizard_data
from core.translations import get_lang, set_lang
from core.wizard.steps import probe_homing, sensors
from tests.unit.test_probe_homing_contract import wizard_probe_data
from tests.unit.test_probe_review_navigation import guided_user


@pytest.fixture(autouse=True)
def interactive(monkeypatch):
    old = get_lang()
    set_lang("English")
    monkeypatch.setenv("KACE_AUTO", "0")
    yield
    set_lang(old)


@pytest.mark.parametrize("source", ["guided", "imported", "resumed", "structured"])
def test_zero_preparation_preserves_offset_and_requires_confirmation(monkeypatch, source):
    user = guided_user() if source == "guided" else wizard_probe_data()
    if source == "resumed":
        user = restore_wizard_data(persistable_wizard_data(user))
    if source == "structured":
        user.update(probe="BLTouch", probe_kind="bltouch")
        user.pop("custom_probe")
    original = copy.deepcopy(user)
    answers = iter(["prepare_zero", "n", "cancel"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    assert not probe_homing.review_probe_homing_geometry(user)
    assert user == original
    answers = iter(["prepare_zero", "y"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    assert probe_homing.review_probe_homing_geometry(user)
    assert user["z_position_min"] == "0"
    assert user["_value_provenance"]["z_position_min"] == "USER_OVERRIDE"
    assert user["_profile_parsed"] == original["_profile_parsed"]
    assert user.get("custom_probe") == original.get("custom_probe")
    probe_homing.validate_wizard_probe_homing_geometry(user)


def test_manual_enter_offers_compatible_zero_instead_of_invalid_saved_minimum(monkeypatch, capsys):
    user = wizard_probe_data()
    prompts = []
    answers = iter(["edit", "", "y"])
    def enter(prompt):
        # A narrow terminal prints leading help lines before the final input line.
        prompts.append(capsys.readouterr().out + prompt)
        return next(answers)
    monkeypatch.setattr("builtins.input", enter)
    assert probe_homing.review_probe_homing_geometry(user)
    assert user["z_position_min"] == "0"
    numeric = prompts[1].split("Mechanical Z minimum", 1)[1]
    assert "position_min" in numeric
    assert "0.5" not in numeric
    assert "Enter accepts 0" in " ".join(numeric.split())


@pytest.mark.parametrize("value", ["0.5", "1", "2", "nan", "inf"])
def test_incompatible_manual_input_still_cannot_change_state(monkeypatch, value):
    user = wizard_probe_data()
    original = copy.deepcopy(user)
    actions = iter(["edit", "cancel"])
    monkeypatch.setattr(probe_homing, "numbered_select", lambda *a, **k: next(actions))
    monkeypatch.setattr(probe_homing, "simple_input", lambda *a, **k: value)
    monkeypatch.setattr(probe_homing, "yes_no", lambda *a, **k: pytest.fail("invalid range"))
    assert not probe_homing.review_probe_homing_geometry(user)
    assert user == original


def test_no_zero_proposal_when_zero_is_not_a_valid_range(monkeypatch):
    user = wizard_probe_data(minimum="0.5", offset="-1")
    def cancel(prompt, choices, **kwargs):
        assert "prepare_zero" not in [c["value"] for c in choices]
        return "cancel"
    monkeypatch.setattr(probe_homing, "numbered_select", cancel)
    assert not probe_homing.review_probe_homing_geometry(user)


def test_forced_valid_review_reports_rejected_edit_without_losing_original(monkeypatch, capsys):
    user = wizard_probe_data(minimum="0", offset="0")
    original = copy.deepcopy(user)
    answers = iter(["edit", "1", "continue"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    assert probe_homing.review_probe_homing_geometry(user, force=True)
    assert user == original
    assert "Minimum 1 is incompatible" in capsys.readouterr().out


def test_auto_never_prepares_a_range_without_consent(monkeypatch):
    user = guided_user()
    original = copy.deepcopy(user)
    monkeypatch.setenv("KACE_AUTO", "1")
    with pytest.raises(GenerationError):
        probe_homing.review_probe_homing_geometry(user)
    assert user == original


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
def test_compact_summary_keeps_comments_in_optional_details(monkeypatch, capsys, language):
    set_lang(language)
    user = guided_user()
    original = copy.deepcopy(user)
    monkeypatch.setattr("builtins.input", lambda *a: "1")
    assert sensors._step_custom_probe_review(user) == "done"
    summary = capsys.readouterr().out
    assert "# " not in summary
    assert "PROBE_CALIBRATE" in summary
    assert "-12" in summary and "7 mm/s" in summary
    assert "wizard.review" not in summary
    assert user == original
    replies = iter(["4", "1", "1"])
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))
    assert sensors._step_custom_probe_review(user) == "done"
    details = capsys.readouterr().out
    assert original["custom_probe"].config_text in details
    assert user == original


def test_imported_detail_does_not_rewrite_raw_source(monkeypatch, capsys):
    user = wizard_probe_data()
    original = copy.deepcopy(user)
    replies = iter(["2", "1", "1"])
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))
    assert sensors._step_custom_probe_review(user) == "done"
    assert user["custom_probe"].config_text in capsys.readouterr().out
    assert user == original
