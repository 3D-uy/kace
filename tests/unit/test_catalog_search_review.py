"""Explicit search and exact-MCU candidate presentation preserve navigation."""
from copy import deepcopy
import os
from unittest.mock import patch

import pytest

from core import menu
from core.board_identity import suggested_board_configs
from core.translations import t, get_lang, set_lang
from core.wizard.runner import _BACK, _QUIT
from core.wizard.steps import hardware, motion


@pytest.fixture(autouse=True)
def interactive(monkeypatch):
    monkeypatch.setenv("KACE_AUTO", "0")
    monkeypatch.setattr(menu, "_MOCK_PROMPTS_ACTIVE", False)
    monkeypatch.setattr(menu.shutil, "get_terminal_size", lambda **kw: os.terminal_size((80, 24)))


@pytest.mark.parametrize("count", [3, 110])
def test_search_starts_empty_then_numbers_visible_matches_and_navigation(count, capsys):
    choices = ["printer-other.cfg", "printer-anet-a8.cfg", "printer-anet-a4.cfg"]
    choices += [f"printer-unrelated-{i}.cfg" for i in range(count - 3)]
    choices += [(t("choice.back"), _BACK), (t("choice.quit"), _QUIT)]
    screens = []
    def answer(prompt):
        screens.append(menu._plain_label(capsys.readouterr().out))
        return "anet" if len(screens) == 1 else "2"
    with patch("builtins.input", side_effect=answer):
        assert menu.autocomplete_select("Printer", choices, require_explicit=True,
                                        search_first=True, renumber_results=True) == "printer-anet-a4.cfg"
    assert "printer-" not in screens[0]
    assert "1) printer-anet-a8.cfg" in screens[1]
    assert "2) printer-anet-a4.cfg" in screens[1]
    assert "3) " + t("choice.back") in screens[1]
    assert "4) " + t("choice.quit") in screens[1]
    assert "printer-other" not in screens[1]


@pytest.mark.parametrize("answer,expected", [("3", _BACK), ("4", _QUIT), ("<", _BACK), ("q", _QUIT)])
def test_filtered_navigation_indices_and_shortcuts(answer, expected):
    choices = ["printer-other.cfg", "printer-anet-a8.cfg", "printer-anet-a4.cfg",
               (t("choice.back"), _BACK), (t("choice.quit"), _QUIT)]
    with patch("builtins.input", side_effect=["anet", answer]):
        assert menu.autocomplete_select("Printer", choices, search_first=True,
                                        renumber_results=True) == expected


def test_new_search_and_no_matches_clear_previous_choices(capsys):
    choices = ["printer-anet-a8.cfg", "printer-anet-a4.cfg", "printer-creality.cfg",
               (t("choice.back"), _BACK)]
    screens = []
    answers = iter(["anet", "missing-model", "/", "", "creal", "1"])
    def answer(prompt):
        screens.append(menu._plain_label(capsys.readouterr().out))
        return next(answers)
    with patch("builtins.input", side_effect=answer):
        assert menu.autocomplete_select("Printer", choices, search_first=True,
                                        renumber_results=True) == "printer-creality.cfg"
    assert "printer-anet" not in screens[2]
    assert "printer-" not in screens[3] and "printer-" not in screens[4]
    assert t("menu.selection_required") in screens[4]
    assert "1) printer-creality.cfg" in screens[5]


def test_hidden_catalog_number_cannot_select_but_exact_model_can(capsys):
    choices = [f"printer-model-{i}.cfg" for i in range(50)]
    with patch("builtins.input", side_effect=["model-", "50", "printer-model-49.cfg"]):
        assert menu.autocomplete_select("Printer", choices, search_first=True,
                                        renumber_results=True) == "printer-model-49.cfg"
    assert t("menu.list_visible_number") in capsys.readouterr().out


@pytest.mark.parametrize("detected,expected", [
    ("lpc1769", ["generic-bigtreetech-skr-v1.4.cfg"]),
    ("lpc1768", ["generic-bigtreetech-skr-v1.4.cfg", "generic-bigtreetech-skr-v1.3.cfg"]),
    ("STM32F407XX", ["generic-bigtreetech-skr-2.cfg"]),
    ("stm32f4", []),
])
def test_initial_board_candidates_use_existing_exact_identity(detected, expected):
    boards = ["generic-bigtreetech-skr-v1.4.cfg", "generic-bigtreetech-skr-v1.3.cfg",
              "generic-bigtreetech-skr-2.cfg"]
    suggestions = suggested_board_configs(boards, detected)
    assert suggestions == expected
    state = {"mcu_type": detected}
    before = deepcopy(state)
    with patch.object(hardware, "autocomplete_select", return_value=_BACK) as select:
        assert hardware._step_board(state, suggestions, boards) == _BACK
    values = [choice["value"] for choice in select.call_args.kwargs["choices"]]
    assert values == [*expected, "__search_boards__", _BACK, _QUIT]
    assert state == before


def test_search_other_boards_back_returns_to_candidates_without_mutation():
    boards = ["generic-bigtreetech-skr-v1.4.cfg", "generic-bigtreetech-skr-v1.3.cfg"]
    state = {"mcu_type": "lpc1769", "board": "previous.cfg"}
    before = deepcopy(state)
    with patch.object(hardware, "autocomplete_select", side_effect=["__search_boards__", _BACK, _BACK]) as select, \
         patch.object(hardware, "fetch_raw_config") as fetch:
        assert hardware._step_board(state, boards[:1], boards) == _BACK
    assert select.call_count == 3
    search = select.call_args_list[1].kwargs
    assert search["search_first"] and search["renumber_results"] and search["require_explicit"]
    assert [choice["value"] for choice in search["choices"]] == [*boards, _BACK, _QUIT]
    assert select.call_args_list[0] == select.call_args_list[2]
    fetch.assert_not_called()
    assert state == before


def test_printer_profile_opts_into_empty_search_and_local_numbering():
    with patch.object(motion, "numbered_select", return_value="search"), \
         patch.object(motion, "autocomplete_select", return_value=_BACK) as select:
        assert motion._step_printer_profile({}, ["printer-example.cfg"]) == "__retry__"
    assert select.call_args.kwargs["search_first"]
    assert select.call_args.kwargs["renumber_results"]
    assert select.call_args.kwargs["require_explicit"]


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
def test_five_anet_matches_and_numbered_navigation_fit_80x24(language, capsys):
    previous = get_lang()
    set_lang(language)
    choices = [f"printer-anet-{name}.cfg" for name in ("a4-2018", "a8-2017", "a8-2019", "e10-2018", "e16-2019")]
    choices += [f"printer-unrelated-{i}.cfg" for i in range(100)]
    choices += [(t("choice.back"), _BACK), (t("choice.quit"), _QUIT)]
    frames = []
    def answer(prompt):
        frames.append(menu._plain_label(capsys.readouterr().out))
        return "anet" if len(frames) == 1 else "6"
    try:
        with patch("builtins.input", side_effect=answer):
            assert menu.autocomplete_select(t("wizard.select_printer_model"), choices,
                                            search_first=True, renumber_results=True,
                                            require_explicit=True) == _BACK
        assert all(f"{i + 1}) {name}" in frames[1] for i, name in enumerate(choices[:5]))
        assert "6) " + t("choice.back") in frames[1]
        assert "7) " + t("choice.quit") in frames[1]
        assert len(frames[1].splitlines()) < 24
        assert all(len(line) <= 80 for line in frames[1].splitlines())
    finally:
        set_lang(previous)
