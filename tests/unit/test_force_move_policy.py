"""FORCE_MOVE requires a reviewed bool; profile defaults are not consent."""
import copy

import pytest

from core.exceptions import GenerationError, WizardExit
from core.generator import _native_feature_sections
from core.reconciler import reconcile_printer_cfg_content
from tests.unit.test_generator import _generate, _parsed, _user


@pytest.mark.parametrize("inherited", [None, "True", "False", "true", "1"])
def test_generation_never_treats_inherited_force_move_as_consent(inherited):
    parsed = {} if inherited is None else {"force_move": {"enable_force_move": inherited}}
    assert _native_feature_sections(parsed)["force_move"]["enable_force_move"] == "False"


@pytest.mark.parametrize("decision", [False, True])
def test_explicit_reviewed_choice_survives_generation(decision):
    parsed = _parsed(force_move={"enable_force_move": "True"})
    user = _user(force_move_enabled=decision)
    before = copy.deepcopy(parsed)
    output = _generate(parsed, user)
    assert f"enable_force_move: {decision}" in output
    assert parsed == before
    assert user["force_move_enabled"] is decision


@pytest.mark.parametrize("invalid", ["True", "False", 0, 1, None, [], {}])
def test_truthy_or_ambiguous_force_move_choice_is_rejected(invalid):
    with pytest.raises(GenerationError, match="force_move_enabled.*boolean"):
        _generate(_parsed(), _user(force_move_enabled=invalid))


def test_reconciler_adds_disabled_default_but_keeps_existing_explicit_values():
    text, changed = reconcile_printer_cfg_content("[printer]\nkinematics: none\n")
    assert changed and "enable_force_move: False" in text
    for value in ("True", "False"):
        original = f"[exclude_object]\n[force_move]\nenable_force_move: {value}\n"
        result, changed = reconcile_printer_cfg_content(original)
        assert result == original and not changed


@pytest.mark.parametrize("mode,auto", [("Beginner", "0"), ("Advanced", "1")])
def test_invisible_or_automatic_step_never_prompts_or_imports_true(monkeypatch, mode, auto):
    from core.wizard.steps import force_move
    monkeypatch.setattr(force_move, "get_mode", lambda: mode)
    monkeypatch.setenv("KACE_AUTO", auto)
    monkeypatch.setattr(force_move, "numbered_select", lambda *a, **k: pytest.fail("unexpected prompt"))
    data = {"board_parsed": {"force_move": {"enable_force_move": "True"}}}
    assert force_move._step_force_move(data) == "done"
    assert data["force_move_enabled"] is False
    data["force_move_enabled"] = True
    assert force_move._step_force_move(data) == "done"
    assert data["force_move_enabled"] is True


@pytest.mark.parametrize("choice,expected", [("disabled", False), ("enabled", True), ("back", None), ("quit", None)])
def test_advanced_choice_warns_and_back_quit_do_not_mutate(monkeypatch, capsys, choice, expected):
    from core.wizard.runner import _BACK, _QUIT
    from core.wizard.steps import force_move
    monkeypatch.setattr(force_move, "get_mode", lambda: "Advanced")
    monkeypatch.setenv("KACE_AUTO", "0")
    selected = {"back": _BACK, "quit": _QUIT}.get(choice, choice)
    monkeypatch.setattr(force_move, "numbered_select", lambda *a, **k: selected)
    data = {"board_parsed": {"force_move": {"enable_force_move": "True"}}}
    before = copy.deepcopy(data)
    if choice == "quit":
        with pytest.raises(WizardExit):
            force_move._step_force_move(data)
    else:
        result = force_move._step_force_move(data)
        assert result == (_BACK if choice == "back" else "done")
    if expected is None:
        assert data == before
    else:
        assert data["force_move_enabled"] is expected
    output = capsys.readouterr().out
    assert "FORCE_MOVE" in output and "SET_KINEMATIC_POSITION" in output


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
def test_force_move_messages_exist_in_all_languages(language):
    from core.translations import UI_STRINGS
    for key in ("force_move.prompt", "force_move.warning", "force_move.inherited", "force_move.disabled", "force_move.enabled",
                "wizard.step.force_move.header", "wizard.step.force_move.hint"):
        assert UI_STRINGS[key][language]


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
def test_effective_review_warns_when_diagnostic_motion_is_enabled(language):
    from core.configuration_review import build_configuration_review, render_configuration_review
    from core.managed_config import build_fresh_config_plan
    from core.translations import UI_STRINGS
    from tests.unit.test_configuration_review import _hardware
    plan = build_fresh_config_plan(_hardware() + b"[force_move]\nenable_force_move: True\n", None, {})
    review = build_configuration_review(plan)
    assert "force-move-enabled" in {item.code for item in review.validation.warnings}
    assert UI_STRINGS["force_move.warning"][language] in render_configuration_review(review, language=language, color=False)


@pytest.mark.parametrize("answers,expected_macros,expected_force", [(["2", "2"], False, True), (["1", "3", "2", "1"], False, False)])
def test_registered_advanced_step_follows_macros_and_back_returns_to_it(monkeypatch, answers, expected_macros, expected_force):
    from core import menu
    from core.translations import get_mode, set_mode
    from core.wizard.runner import WizardRunner
    from tests.unit.test_probe_review_navigation import actual_catalog
    previous = get_mode()
    try:
        set_mode("Advanced")
        monkeypatch.setenv("KACE_AUTO", "0")
        monkeypatch.setattr(menu, "_MOCK_PROMPTS_ACTIVE", False)
        responses = iter(answers)
        def answer(_):
            try:
                return next(responses)
            except StopIteration:
                pytest.fail("unexpected additional question")
        monkeypatch.setattr("builtins.input", answer)
        runner = WizardRunner(actual_catalog(), ["starter_macros", "force_move"], {})
        result = runner.run("starter_macros")
        assert result["macros_generated"] is expected_macros
        assert result["force_move_enabled"] is expected_force
        assert list(responses) == []
    finally:
        set_mode(previous)


@pytest.mark.parametrize("mode", ["Beginner", "Advanced"])
def test_printable_confirmation_and_force_move_are_independent_registered_decisions(monkeypatch, mode):
    from core import menu
    from core.firmware_workflow import persistable_wizard_data, restore_wizard_data
    from core.motion_model import printable_xy_confirmation_matches
    from core.translations import get_mode, set_mode
    from core.wizard.runner import WizardRunner
    from tests.unit.test_probe_review_navigation import actual_catalog
    previous = get_mode()
    try:
        set_mode(mode)
        monkeypatch.setenv("KACE_AUTO", "0")
        monkeypatch.setattr(menu, "_MOCK_PROMPTS_ACTIVE", False)
        responses = iter(["1", "2"] + (["2"] if mode == "Advanced" else []))
        def answer(_):
            try:
                return next(responses)
            except StopIteration:
                pytest.fail("unexpected question for invisible/finished step")
        monkeypatch.setattr("builtins.input", answer)
        state = {"x_size": "235", "y_size": "235", "z_size": "250",
                 "x_position_min": "-20", "x_position_max": "240",
                 "y_position_min": "-10", "y_position_max": "250"}
        runner = WizardRunner(actual_catalog(), ["printable_area", "starter_macros", "force_move"], state)
        result = runner.run("printable_area")
        assert printable_xy_confirmation_matches(result)
        assert result["force_move_enabled"] is (mode == "Advanced")
        assert result["x_position_min"] == "-20" and result["y_position_max"] == "250"
        assert result["macros_generated"] is False
        assert list(responses) == []
        restored = restore_wizard_data(persistable_wizard_data(result))
        assert restored["force_move_enabled"] is result["force_move_enabled"]
    finally:
        set_mode(previous)
