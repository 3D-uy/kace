"""Small SSH terminals retain offset signs, guidance, warnings and actions."""

import copy
import os
from unittest.mock import patch

import pytest
from wcwidth import wcswidth

from core import menu, probe_offset_visualizer as preview
from core.translations import get_lang, set_lang, t
from core.wizard.steps import motion


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
@pytest.mark.parametrize("columns,lines", [(60, 20), (80, 24)])
def test_small_preview_complete_input_flow_fits_and_retains_signs(language, columns, lines, capsys):
    original_language = get_lang()
    state = {"probe": "BLTouch", "x_size": "300", "y_size": "300"}
    before = copy.deepcopy(state)
    answers = iter(["-38", "12", "yes"])
    screens = []
    try:
        set_lang(language)
        def answer(prompt):
            screens.append((capsys.readouterr().out, prompt))
            return next(answers)
        with patch.object(menu, "_check_questionary_mock", return_value=menu._MOCK_DEFAULT), \
                patch("shutil.get_terminal_size", return_value=os.terminal_size((columns, lines))), \
                patch("builtins.input", side_effect=answer):
            result = preview.run_probe_offset_step(state)
        assert result == {"probe_x_offset": "-38.0", "probe_y_offset": "12.0"}
        assert state == before
        assert len(screens) == 3
        for output, prompt in screens:
            text = menu._plain_label(output)
            # Short terminals scroll, but never replace the educational grid.
            assert t("probe.back") in text and t("probe.front") in text
            assert "|" in text and "[-]" in text and "[+]" in text
            assert t("probe.legend") in " ".join(text.split())
            assert max(wcswidth(line) for line in text.splitlines()) <= columns
            assert wcswidth(menu._plain_label(prompt)) <= columns
        first = " ".join(menu._plain_label(screens[0][0]).split())
        assert t("probe.overlap_warning") in first
        last = menu._plain_label(screens[-1][0])
        assert "X: -38.0 mm | Y: +12.0 mm" in last
        assert t("wizard.probe_confirm_yes") in last
        assert t("choice.back") in last and t("choice.quit") in last
        expected_warning = preview._check_reachability(-38, 12, state)
        assert " ".join(expected_warning.split()) in " ".join(last.split())
    finally:
        set_lang(original_language)


def test_tall_terminal_keeps_full_bed_grid(capsys):
    with patch("shutil.get_terminal_size", return_value=os.terminal_size((100, 40))), \
            patch.object(preview, "_render_bed", wraps=preview._render_bed) as bed:
        preview._print_frame(-38, 12, 300, 300, "BLTouch")
    bed.assert_called_once_with(-38, 12, 300, 300)
    output = capsys.readouterr().out
    assert t("probe.legend") in output
    assert "X: -38.0 mm" in output and "Y: +12.0 mm" in output


@pytest.mark.parametrize("columns", [40, 60, 80])
def test_profile_editor_separators_fit_terminal(columns, capsys):
    def select(prompt, choices):
        separators = [choice for choice in choices if isinstance(choice, menu.Separator)]
        assert separators
        assert all(wcswidth("    " + str(choice)) <= columns for choice in separators)
        return "back"
    with patch("shutil.get_terminal_size", return_value=os.terminal_size((columns, 20))), \
            patch.object(motion, "numbered_select", side_effect=select):
        assert motion._step_profile_editor_inner({}, {}, {}) == "back"
    lines = capsys.readouterr().out.splitlines()
    separators = [line for line in lines if "─" in line]
    assert separators
    assert all(wcswidth(line) <= columns for line in separators)
