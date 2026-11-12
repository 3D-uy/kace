"""Complete deferred calibration and any travel confirmation at the Z question."""
import copy

import pytest

from core.firmware_workflow import persistable_wizard_data, restore_wizard_data
from core.menu import _plain_label
from core.profile_values import mark_user_override
from core.translations import get_lang, get_mode, set_lang, set_mode, t
from core.wizard.runner import WizardRunner, _BACK
from core.wizard.steps import probe_homing, sensors
from tests.unit.test_probe_homing_contract import wizard_probe_data
from tests.unit.test_probe_review_navigation import actual_catalog


@pytest.fixture(autouse=True)
def interactive(monkeypatch):
    language, mode = get_lang(), get_mode()
    set_lang("English")
    monkeypatch.setenv("KACE_AUTO", "0")
    yield
    set_lang(language)
    set_mode(mode)


def z_question(minimum="0.5"):
    user = wizard_probe_data(minimum)
    user.pop("custom_probe")
    user.update(custom_probe_pin="PB8", custom_probe_pullup=True,
                custom_probe_x_offset="-12", custom_probe_y_offset="4",
                custom_probe_z_offset="2")
    return user


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
@pytest.mark.parametrize("mode", ["Beginner", "Advanced"])
def test_later_and_physical_clearance_complete_at_z_question_without_publishing_future_fields(
        monkeypatch, capsys, language, mode):
    set_lang(language)
    set_mode(mode)
    user = z_question()
    original = copy.deepcopy(user)
    expected = copy.deepcopy(user)
    expected.update(custom_probe_z_offset="", z_position_min="0")
    mark_user_override(expected, "z_position_min")
    answers = iter(["2", "y"])
    prompts = []
    screens = []

    def enter(prompt):
        # Even the first decision stays staged until physical clearance is
        # explicitly accepted. No typed/default sampling payload leaks early.
        assert user == original
        screens.append(capsys.readouterr().out)
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr("builtins.input", enter)
    assert sensors._step_guided_custom_probe_value(user, "custom_probe_z_offset") == "done"
    assert len(prompts) == 2
    assert user == expected
    assert "custom_probe" not in user and "custom_probe_settings" not in user
    for key, *_ in sensors.GUIDED_CUSTOM_PROBE_QUESTIONS:
        if key != "custom_probe_z_offset":
            assert key not in user
    text = " ".join(_plain_label("".join(screens) + capsys.readouterr().out).split())
    assert t("wizard.probe_z.minimum_prompt") not in text
    assert t("wizard.probe_z.back_review") not in text
    assert t("wizard.probe_z.deferred_title") not in text
    rendered = _plain_label(screens[-1] + prompts[-1])
    assert " ".join(t("wizard.probe_z.confirm_deferred_minimum", old="0.5", new="0").split()) in " ".join(rendered.split())


@pytest.mark.parametrize("minimum", ["0", "-1"])
def test_compatible_later_choice_only_asks_the_offset_decision(monkeypatch, minimum):
    user = z_question(minimum)
    expected = copy.deepcopy(user)
    expected["custom_probe_z_offset"] = ""
    answers = iter(["2"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    monkeypatch.setattr(probe_homing, "yes_no", lambda *a, **k: pytest.fail("No minimum edit"))
    assert sensors._step_guided_custom_probe_value(user, "custom_probe_z_offset") == "done"
    assert user == expected
    assert sensors._step_custom_probe(user) == "done"
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("No second question"))
    assert probe_homing.review_probe_homing_geometry(user)


@pytest.mark.parametrize("answers", [
    ["later", "n", "cancel", "<"],
    ["later", "", "cancel", "<"],
    ["later", "n", "edit", "<", "<"],
])
def test_back_or_default_no_preserves_offset_minimum_and_nested_draft(monkeypatch, answers):
    user = z_question()
    original = copy.deepcopy(user)
    responses = iter(answers)
    monkeypatch.setattr("builtins.input", lambda *a: next(responses))
    assert sensors._step_guided_custom_probe_value(user, "custom_probe_z_offset") == _BACK
    assert user == original
    with pytest.raises(StopIteration):
        next(responses)


@pytest.mark.parametrize("value", ["0.5", "2", "nan", "inf"])
def test_rejected_minimum_in_z_question_cannot_commit_any_part_of_decision(monkeypatch, value):
    user = z_question()
    original = copy.deepcopy(user)
    answers = iter(["later", "<"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    actions = iter(["edit", "cancel"])
    monkeypatch.setattr(probe_homing, "numbered_select", lambda *a, **k: next(actions))
    monkeypatch.setattr(probe_homing, "simple_input", lambda *a, **k: value)
    confirmations = []
    def decline_proposal(prompt, **kwargs):
        assert not confirmations, "An invalid manual range must not reach confirmation"
        confirmations.append(prompt)
        return False
    monkeypatch.setattr(probe_homing, "yes_no", decline_proposal)
    assert sensors._step_guided_custom_probe_value(user, "custom_probe_z_offset") == _BACK
    assert user == original


@pytest.mark.parametrize("restored", [False, True])
def test_confirmed_minimum_survives_editing_an_existing_probe_review(monkeypatch, restored):
    user = z_question()
    user["custom_probe_z_offset"] = "1"
    assert sensors._step_custom_probe(user) == "done"
    if restored:
        user = restore_wizard_data(persistable_wizard_data(user))
    original = copy.deepcopy(user)
    original_raw = user["custom_probe"].config_text
    responses = iter(["offset", "later", "y", "continue"])
    monkeypatch.setattr("builtins.input", lambda *a: next(responses))
    assert sensors._step_custom_probe_review(user) == "done"
    assert user["z_position_min"] == "0"
    assert user["_value_provenance"]["z_position_min"] == "USER_OVERRIDE"
    assert user["_profile_parsed"] == original["_profile_parsed"]
    expected_raw = original_raw.replace("z_offset: 1", "z_offset: 0")
    if not restored:
        # Live guided comments reflect the new provisional state. Restored raw
        # blocks keep their existing comments under the saved ownership rules.
        expected_raw = expected_raw.replace(t("wizard.probe_comment.z_offset"),
                                            t("wizard.probe_comment.uncalibrated"))
    assert user["custom_probe"].config_text == expected_raw
    saved = restore_wizard_data(persistable_wizard_data(user))
    assert saved["custom_probe_settings"]["z_offset"] is None
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("Already confirmed"))
    assert probe_homing.review_probe_homing_geometry(saved)


def test_restored_raw_review_does_not_require_duplicate_guided_input_fields(monkeypatch):
    user = z_question()
    user["custom_probe_z_offset"] = "1"
    assert sensors._step_custom_probe(user) == "done"
    user = restore_wizard_data(persistable_wizard_data(user))
    for key in list(user):
        if key.startswith("custom_probe_") and key != "custom_probe_settings":
            user.pop(key)
    original_raw = user["custom_probe"].config_text
    replies = iter(["offset", "later", "y", "continue"])
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))
    assert sensors._step_custom_probe_review(user) == "done"
    assert user["z_position_min"] == "0"
    assert user["custom_probe_settings"]["z_offset"] is None
    assert user["custom_probe"].config_text == original_raw.replace("z_offset: 1", "z_offset: 0")


def test_actual_wizard_route_reaches_thermal_without_second_range_panel(monkeypatch):
    user = z_question()
    catalog = actual_catalog()
    catalog["hotend_therm"] = {"prompt": lambda state: "done", "next": lambda a, u: None}
    # The real catalog visits all remaining sample questions and builds the
    # authoritative raw probe only after the Z decision has been completed.
    replies = iter(["later", "y", "", "", "1", "", "", "", "continue"])
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))
    headers = []
    monkeypatch.setattr("core.wizard.ui._print_step_header", lambda step, *a, **k: headers.append(step))
    order = ["custom_probe_z_offset", "custom_probe_speed", "custom_probe_samples",
             "custom_probe_samples_result", "custom_probe_samples_tolerance",
             "custom_probe_samples_tolerance_retries", "custom_probe_sample_retract_dist",
             "custom_probe", "custom_probe_review", "probe_homing", "hotend_therm"]
    runner = WizardRunner(catalog, order, user)
    result = runner.run("custom_probe_z_offset")
    assert result["z_position_min"] == "0"
    assert result["custom_probe_settings"].z_offset is None
    assert "probe_homing" in runner.history_stack
    assert "probe_homing" not in headers
    assert "hotend_therm" in runner.history_stack
    with pytest.raises(StopIteration):
        next(replies)


def test_later_boundary_change_reopens_the_same_validator(monkeypatch):
    user = z_question()
    replies = iter(["later", "y"])
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))
    assert sensors._step_guided_custom_probe_value(user, "custom_probe_z_offset") == "done"
    assert sensors._step_custom_probe(user) == "done"
    assert not probe_homing.probe_homing_review_required(user)
    user["z_position_min"] = "0.5"
    mark_user_override(user, "z_position_min")
    original = copy.deepcopy(user)
    assert probe_homing.probe_homing_review_required(user)
    monkeypatch.setattr(probe_homing, "numbered_select", lambda *a, **k: "cancel")
    monkeypatch.setattr(probe_homing, "yes_no", lambda *a, **k: False)
    assert not probe_homing.review_probe_homing_geometry(user)
    assert user == original


def test_incomplete_probe_cannot_commit_deferred_decision(monkeypatch):
    user = {"custom_probe_z_offset": "2"}
    original = copy.deepcopy(user)
    monkeypatch.setattr("builtins.input", lambda *a: "later")
    assert sensors._step_guided_custom_probe_value(user, "custom_probe_z_offset") == _BACK
    assert user == original


@pytest.mark.parametrize("key", ["z_position_min", "z_position_max"])
def test_unresolved_range_returns_without_publishing_decision(monkeypatch, capsys, key):
    user = z_question()
    user["_value_provenance"][key] = "UNRESOLVED"
    original = copy.deepcopy(user)
    monkeypatch.setattr("builtins.input", lambda *a: "later")
    assert sensors._step_guided_custom_probe_value(user, "custom_probe_z_offset") == _BACK
    assert user == original
    assert " ".join(t("wizard.probe_z.range_unresolved").split()) in " ".join(capsys.readouterr().out.split())
