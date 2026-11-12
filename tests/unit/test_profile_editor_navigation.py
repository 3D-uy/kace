"""Nested editor cancellation preserves accepted edits until explicit discard."""

import copy

import pytest

from core import menu
from core.profile_values import safe_defaults
from core.translations import get_lang, set_lang
from core.wizard.steps import motion


@pytest.fixture
def editor(monkeypatch):
    previous_language = get_lang()
    set_lang("English")
    monkeypatch.setenv("KACE_AUTO", "0")
    monkeypatch.setattr(menu, "_MOCK_PROMPTS_ACTIVE", False)
    monkeypatch.setattr(motion, "_INTERACTIVE_MODE", False)
    data = safe_defaults()
    data.update({f"{axis}_{field}": value for axis in ("x", "y", "z")
                 for field, value in (("position_min", "0"),
                                      ("position_max", "320"),
                                      ("position_endstop", "0"))})
    motion.normalize_and_validate_configuration(data)
    defaults = copy.deepcopy(data)
    parsed = {}

    def run(answers):
        inputs = iter(answers)
        monkeypatch.setattr("builtins.input", lambda prompt: next(inputs))
        result = motion._step_profile_editor_inner(defaults, parsed, data)
        assert next(inputs, None) is None
        return result

    yield data, defaults, parsed, run
    set_lang(previous_language)


@pytest.mark.parametrize("field,answers", [
    ("kinematics", ["<"]),
    ("hotend_thermistor", ["<"]),
    ("bed_thermistor", ["<"]),
    ("hotend_thermistor", ["Other (Manual Entry)", "<"]),
    ("bed_thermistor", ["Other (Manual Entry)", "<"]),
    ("z_position_min", ["<"]),
])
def test_nested_back_preserves_prior_edits_and_keeps_cancelled_field(editor, field, answers):
    data, defaults, parsed, run = editor
    before = data[field]
    assert run(["x_position_max", "400", field, *answers, "save"]) == "save"
    assert data["x_position_max"] == "400"
    assert defaults["x_position_max"] == "400"
    assert parsed["stepper_x"]["position_max"] == "400"
    assert data[field] == before


@pytest.mark.parametrize("cancel_at", [0, 1, 2])
def test_build_volume_cancel_is_atomic_and_keeps_other_staged_edits(editor, cancel_at):
    data, defaults, parsed, run = editor
    keys = ("x_size", "y_size", "z_size", "printable_x_min", "printable_x_max",
            "printable_y_min", "printable_y_max", "printable_z_max")
    before = {key: data.get(key) for key in keys}
    assert run(["x_position_max", "400", "volume", *["100"] * cancel_at,
                "<", "save"]) == "save"
    assert data["x_position_max"] == "400"
    assert {key: data.get(key) for key in keys} == before


def test_explicit_editor_discard_still_preserves_original_sources(editor):
    data, defaults, parsed, run = editor
    before = copy.deepcopy((data, defaults, parsed))
    assert run(["x_position_max", "400", "back"]) == "back"
    assert (data, defaults, parsed) == before
