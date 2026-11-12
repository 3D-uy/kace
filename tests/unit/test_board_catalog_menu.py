"""Unified board selection and navigation through searchable catalogs."""

from unittest.mock import patch

import pytest

from core import menu, terminal
from core.exceptions import WizardExit
from core.translations import t, get_lang, set_lang
from core.wizard.runner import _BACK, _QUIT
from core.wizard.steps import hardware, motion


def test_board_catalog_initially_shows_exact_candidates_and_explicit_search():
    state = {}
    with patch.object(hardware, "autocomplete_select", return_value=_BACK) as select:
        assert hardware._step_board(state, ["generic-suggested.cfg"],
                                    ["generic-other.cfg", "generic-suggested.cfg"]) == _BACK
    choices = select.call_args.kwargs["choices"]
    assert [choice["value"] for choice in choices] == [
        "generic-suggested.cfg", "__search_boards__", _BACK, _QUIT,
    ]
    assert choices[0]["name"] == "generic-suggested.cfg"
    assert select.call_args.kwargs["require_explicit"] is True
    assert choices[1]["name"] == t("catalog.search_other_boards")
    assert state == {}


@pytest.mark.parametrize("prefix", [[], ["generic-"]])
@pytest.mark.parametrize("answer,expected", [("<", _BACK), (_BACK, _BACK), (_QUIT, _QUIT),
                                            ("generic-0.cfg", "generic-0.cfg")])
def test_long_catalog_navigation_and_values_work_in_filtered_results(prefix, answer, expected):
    choices = [(f"generic-{i}.cfg {terminal.WARNING}(recommended){terminal.RESET}",
                f"generic-{i}.cfg") for i in range(20)]
    choices.extend([(t("choice.back"), _BACK), (t("choice.quit"), _QUIT)])
    with patch("builtins.input", side_effect=[*prefix, answer]):
        assert menu.autocomplete_select("Board", choices) == expected


def test_long_catalog_matches_visible_label_and_yellow_result_numbers(capsys):
    choices = [(f"Board {i} {terminal.WARNING}(recommended){terminal.RESET}", i)
               for i in range(20)]
    with patch("builtins.input", side_effect=["Board", "2"]):
        assert menu.autocomplete_select("Board", choices) == 1
    assert f"{terminal.WARNING}1){terminal.RESET} Board 0" in capsys.readouterr().out
    with patch("builtins.input", return_value="Board 3 (recommended)"):
        assert menu.autocomplete_select("Board", choices) == 3


def test_long_catalog_displays_available_navigation(capsys):
    choices = [f"Board {i}" for i in range(20)]
    choices.extend([(t("choice.back"), _BACK), (t("choice.quit"), _QUIT)])
    with patch("builtins.input", return_value=_BACK):
        assert menu.autocomplete_select("Board", choices) == _BACK
    output = capsys.readouterr().out
    assert "< " + t("choice.back") in output
    assert "q " + t("choice.quit") in output


@pytest.mark.parametrize("answer", [_BACK, _QUIT])
def test_profile_search_navigation_never_fetches_a_control_value(answer):
    with patch.object(motion, "numbered_select", return_value="search"), patch.object(
        motion, "autocomplete_select", return_value=answer
    ) as select, patch.object(motion, "fetch_raw_config") as fetch:
        if answer == _QUIT:
            with pytest.raises(WizardExit):
                motion._step_printer_profile({}, ["printer-example.cfg"])
        else:
            assert motion._step_printer_profile({}, ["printer-example.cfg"]) == "__retry__"
    assert [choice["value"] for choice in select.call_args.kwargs["choices"][-2:]] == [_BACK, _QUIT]
    assert select.call_args.kwargs["require_explicit"] is True
    fetch.assert_not_called()


def test_interaction_revision_tracks_prompts_without_counting_auto_mode(monkeypatch):
    monkeypatch.delenv("KACE_AUTO", raising=False)
    before = menu.interaction_revision()
    with patch("builtins.input", return_value="1"):
        assert menu.numbered_select("Choose", ["one"]) == "one"
    assert menu.interaction_revision() > before
    monkeypatch.setenv("KACE_AUTO", "1")
    before = menu.interaction_revision()
    assert menu.numbered_select("Choose", ["one"]) == "one"
    assert menu.interaction_revision() == before


@pytest.mark.parametrize("columns,rows", [(60, 20), (80, 24), (100, 30), (120, 40)])
@pytest.mark.parametrize("language", ["English", "Español", "Português"])
def test_catalog_preview_reserves_controls_without_flooding_terminal(columns, rows, language, capsys):
    import os
    old_language = get_lang()
    set_lang(language)
    choices = [f"generic-board-with-a-long-name-{i}.cfg" for i in range(86)]
    choices.extend([(t("choice.back"), _BACK), (t("choice.quit"), _QUIT)])
    def inspect_page(_prompt):
        output = capsys.readouterr().out
        assert "generic-board-with-a-long-name-0.cfg" in output
        assert "generic-board-with-a-long-name-85.cfg" not in output
        assert "< " + t("choice.back") in output
        assert "q " + t("choice.quit") in output
        assert all(len(menu._plain_label(line)) <= columns for line in output.splitlines())
        assert len(output.splitlines()) < rows
        assert "86" in output
        assert t("menu.catalog_controls") not in output
        return _BACK
    try:
        with patch.object(menu.shutil, "get_terminal_size", return_value=os.terminal_size((columns, rows))), patch(
            "builtins.input", side_effect=inspect_page
        ):
            assert menu.autocomplete_select(t("wizard.select_board"), choices) == _BACK
    finally:
        set_lang(old_language)


def test_filter_searches_hidden_results_and_preserves_original_numbers(capsys):
    import re
    choices = [f"Board {i}" for i in range(40)]
    screens = []
    def select(_prompt):
        output = menu._plain_label(capsys.readouterr().out)
        screens.append(output)
        return ["oard 2", "oard 29", "30"][len(screens) - 1]
    with patch("builtins.input", side_effect=select):
        assert menu.autocomplete_select("Board", choices) == "Board 29"
    assert len(screens) == 3
    assert re.findall(r"^\s+(\d+)\) Board (\d+)$", screens[2], re.MULTILINE) == [("30", "29")]
    assert "Board 39" not in screens[0]
    assert "Board 29" not in screens[0] and "Board 29" not in screens[1]


def test_number_for_hidden_initial_result_requires_filter_or_exact_label(capsys):
    choices = [f"Board {i}" for i in range(86)]
    with patch("builtins.input", side_effect=["86", "Board 85"]):
        assert menu.autocomplete_select("Board", choices) == "Board 85"
    assert t("menu.list_visible_number") in capsys.readouterr().out


@pytest.mark.parametrize("count", [3, 110])
def test_explicit_catalog_rejects_empty_input_and_preserves_selection(count, capsys):
    with patch("builtins.input", side_effect=["", "2"]) as read:
        assert menu.autocomplete_select("Printer", [f"printer-{i}.cfg" for i in range(count)],
                                        require_explicit=True) == "printer-1.cfg"
    assert read.call_count == 2
    assert t("menu.selection_required") in capsys.readouterr().out
    assert all("printer-0.cfg" not in call.args[0] for call in read.call_args_list)


def test_filtered_catalog_can_clear_or_back_without_selecting_default(capsys):
    choices = [(f"Board {i}", i) for i in range(40)] + [(t("choice.back"), _BACK)]
    with patch("builtins.input", side_effect=["oard 2", "/", "", "<"]):
        assert menu.autocomplete_select("Board", choices, require_explicit=True) == _BACK
    assert t("menu.selection_required") in capsys.readouterr().out


def test_number_outside_filter_does_not_select_hidden_board(capsys):
    with patch("builtins.input", side_effect=["oard 2", "85", "3"]):
        assert menu.autocomplete_select("Board", [f"Board {i}" for i in range(86)]) == "Board 2"
    assert t("menu.list_visible_number") in capsys.readouterr().out


def test_printer_search_empty_answer_cannot_load_first_model():
    with patch("builtins.input", side_effect=["search", "", "<"]), patch.object(
        motion, "fetch_raw_config"
    ) as fetch:
        assert motion._step_printer_profile({}, [f"printer-{i}.cfg" for i in range(110)]) == "__retry__"
    fetch.assert_not_called()


def test_quit_is_available_from_filtered_list():
    choices = [f"printer-{i}.cfg" for i in range(110)] + [(t("choice.quit"), _QUIT)]
    with patch("builtins.input", side_effect=["printer-1", "q"]):
        assert menu.autocomplete_select("Printer", choices, require_explicit=True) == _QUIT


def test_ansi_label_wrapping_preserves_content_color_and_cell_width():
    from wcwidth import wcswidth
    label = ("X position_min " + terminal.INFO + "0.5" + terminal.RESET + " " +
             terminal.HINT + "# límite mecánico explicado sin cortar la información" + terminal.RESET)
    lines = menu._choice_lines(1, label, 42)
    assert len(lines) > 1
    assert all(wcswidth(menu._plain_label(line)) <= 42 for line in lines)
    assert terminal.INFO + "0.5" + terminal.RESET in "\n".join(lines)
    assert terminal.HINT in "\n".join(lines)
    assert " ".join(menu._plain_label("\n".join(lines)).split()) == (
        "1) " + " ".join(menu._plain_label(label).split())
    )
    assert all(line.startswith("       ") for line in lines[1:])


def test_short_profile_menu_shows_all_wrapped_rows_and_actions_without_pages(capsys):
    import os
    import re
    from wcwidth import wcswidth
    choices = [(f"X field {i} {terminal.INFO}0.5{terminal.RESET} "
                f"{terminal.HINT}# comentario suficientemente largo para dos líneas en terminal{terminal.RESET}",
                f"field-{i}") for i in range(16)]
    choices += [("Guardar y continuar", "save"), ("Volver", _BACK)]
    def choose(_prompt):
        visible = menu._plain_label(capsys.readouterr().out)
        assert all(wcswidth(line) <= 80 for line in visible.splitlines())
        assert "17) Guardar y continuar" in visible and "18) Volver" in visible
        assert [int(number) for number in re.findall(r"^\s+(\d+)\)", visible, re.MULTILINE)] == list(range(1, 19))
        assert t("menu.catalog_controls") not in visible
        return "17"
    with patch.object(menu.shutil, "get_terminal_size", return_value=os.terminal_size((80, 24))), patch(
        "builtins.input", side_effect=choose
    ) as read:
        assert menu.numbered_select("Seleccione un campo o guarde", choices) == "save"
    assert read.call_count == 1


def test_tall_numbered_menu_keeps_back_available():
    import os
    choices = [("Long option " * 7, i) for i in range(17)] + [("Volver", _BACK)]
    with patch.object(menu.shutil, "get_terminal_size", return_value=os.terminal_size((60, 20))), patch(
        "builtins.input", return_value="<"
    ):
        assert menu.numbered_select("Choose", choices) == _BACK


@pytest.mark.parametrize("answer,expected", [("18", "save"), ("19", "back"), ("<", "back")])
def test_actual_profile_editor_actions_keep_original_indices(answer, expected, capsys):
    import os
    def choose(_prompt):
        output = capsys.readouterr().out
        visible = menu._plain_label(output)
        # Printable XY bounds adds one field; the tall menu must retain the
        # resulting action numbers, labels and colors without renumbering.
        assert "18)" in visible and "19)" in visible
        assert terminal.WARNING + "18)" + terminal.RESET in output
        assert terminal.WARNING + "19)" + terminal.RESET in output
        assert "18) " + t("choice.save_continue") in visible
        assert "19) " + t("choice.back_discard") in visible
        return answer
    with patch.object(menu.shutil, "get_terminal_size", return_value=os.terminal_size((80, 24))), patch(
        "builtins.input", side_effect=choose
    ):
        assert motion._step_profile_editor_inner({}, {}, {}) == expected


def test_tall_numbered_quit_action_keeps_value_and_index(capsys):
    import os
    choices = [("Long option " * 6, i) for i in range(17)] + [("Exit", "quit")]
    with patch.object(menu.shutil, "get_terminal_size", return_value=os.terminal_size((80, 24))), patch(
        "builtins.input", return_value="q"
    ):
        assert menu.numbered_select("Choose", choices) == "quit"
    output = menu._plain_label(capsys.readouterr().out)
    assert "18) Exit" in output
