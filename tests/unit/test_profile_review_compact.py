"""The profile retains explanations and original actions with readable wrapping."""

import copy
import os
from unittest.mock import patch

import pytest
from wcwidth import wcswidth

from core import menu
from core.exceptions import WizardExit
from core.translations import get_lang, set_lang, t
from core.wizard.steps import motion


@pytest.fixture
def profile():
    defaults = {
        "printer_profile": "Custom / Scratch Build", "kinematics": "cartesian",
        "x_size": "300", "y_size": "300", "z_size": "350",
        "hotend_thermistor": "Generic 3950", "bed_thermistor": "Generic 3950",
    }
    for axis, minimum, maximum, endstop in (
        ("x", 0, 320, 320), ("y", -8, 300, -8), ("z", 0.5, 350, 0.5),
    ):
        defaults.update({f"{axis}_position_min": minimum,
                         f"{axis}_position_max": maximum,
                         f"{axis}_position_endstop": endstop})
    state = copy.deepcopy(defaults)
    state.update(printable_x_min=20, printable_x_max=320,
                 printable_y_min=0, printable_y_max=300)
    state["_value_provenance"] = {"x_position_min": "user"}
    return defaults, {}, state


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
@pytest.mark.parametrize("columns,lines", [(60, 20), (80, 24), (100, 30)])
def test_profile_review_keeps_explained_values_and_original_actions(profile, language, columns, lines, capsys):
    import re
    original_language = get_lang()
    before = copy.deepcopy(profile)
    prompts = []
    try:
        set_lang(language)
        def answer(prompt):
            prompts.append((capsys.readouterr().out, prompt))
            return "3"
        with patch.object(menu, "_check_questionary_mock", return_value=menu._MOCK_DEFAULT), \
                patch("shutil.get_terminal_size", return_value=os.terminal_size((columns, lines))), \
                patch("builtins.input", side_effect=answer):
            assert motion._step_profile_review_inner(*profile) == "back"
        assert len(prompts) == 1
        output, prompt = prompts[0]
        text = menu._plain_label(output)
        normalized = " ".join(text.split())
        for axis, values in (("X", (0, 320, 320)), ("Y", (-8, 300, -8)), ("Z", (0.5, 350, 0.5))):
            for field, value in zip(("min", "max", "endstop"), values):
                assert re.search(rf"{axis} position_{field}:\s+{re.escape(str(value))}\b", text)
        for value in ("+X", "-Y", "-Z", "300 x 300 x 350", "Generic 3950"):
            assert value in normalized
        assert "X 20..320 mm / Y 0..300 mm" in normalized
        assert t("profile.printable_bounds") in normalized
        assert " ".join(t("profile.comment_kinematics").split()) in normalized
        assert " ".join(t("wizard.homing.z_probe_hint").split()) in normalized
        for key in ("choice.continue", "choice.edit_profile", "choice.arrow_back"):
            assert t(key) in text
        assert t("wizard.review_profile.details") not in text
        assert max(wcswidth(line) for line in text.splitlines()) <= columns
        assert wcswidth(menu._plain_label(prompt)) <= columns
        assert profile == before
    finally:
        set_lang(original_language)


def test_profile_retains_explicit_homing_and_omits_unknown_fields(capsys):
    parsed = {"printer": {"kinematics": "corexy"},
              "stepper_x": {"position_min": 0, "position_max": 300,
                            "homing_positive_dir": "True"}}
    before = copy.deepcopy(parsed)
    motion.print_detected_profile_summary({}, parsed, {})
    output = capsys.readouterr().out
    assert "X position_min:" in output and "X position_max:" in output
    assert "+X" in output
    assert "X position_endstop:" not in output
    assert "Y position_min:" not in output and "Z position_min:" not in output
    assert t("wizard.homing.z_probe_hint") not in output
    assert f"X {t('profile.bounds_undefined')} / Y {t('profile.bounds_undefined')}" in " ".join(output.split())
    assert parsed == before


@pytest.mark.parametrize("language,headings", [
    ("English", ("Motion System", "Build Volume", "Thermistors")),
    ("Español", ("Sistema de movimiento", "Volumen de impresión", "Termistores")),
    ("Português", ("Sistema de movimento", "Volume de impressão", "Termistores")),
])
def test_profile_section_titles_are_localized(profile, language, headings, capsys):
    original_language = get_lang()
    try:
        set_lang(language)
        motion.print_detected_profile_summary(*profile)
        output = menu._plain_label(capsys.readouterr().out)
        for heading in headings:
            assert heading in output
        if language != "English":
            assert "Motion System" not in output
            assert "Build Volume" not in output
            assert "Thermistors" not in output
    finally:
        set_lang(original_language)


def test_cancel_profile_review_preserves_state(profile):
    before = copy.deepcopy(profile)
    with patch.object(motion, "numbered_select", return_value=None):
        with pytest.raises(WizardExit):
            motion._step_profile_review_inner(*profile)
    assert profile == before
