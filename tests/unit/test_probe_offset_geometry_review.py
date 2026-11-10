"""The offset preview reuses motion geometry and preserves accepted input."""
import copy
import os

import pytest

from core import menu, probe_offset_visualizer as preview
from core.motion_model import ProbeGeometryError
from core.translations import get_lang, set_lang, t


@pytest.fixture(autouse=True)
def interactive(monkeypatch):
    language = get_lang()
    set_lang("English")
    monkeypatch.setenv("KACE_AUTO", "0")
    monkeypatch.setattr(menu, "_check_questionary_mock", lambda *a: menu._MOCK_DEFAULT)
    yield
    set_lang(language)


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
def test_negative_nine_warning_uses_mechanical_travel_not_offset_sign(language):
    set_lang(language)
    user = dict(x_size=300, y_size=300, x_position_max=300, y_position_min=-8)
    assert preview._check_reachability(-9, 1, user) == t("probe.misses_right", distance=9)
    user["x_position_max"] = 320
    assert preview._check_reachability(-9, 1, user) == ""


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
def test_missing_left_and_front_distances_subtract_printable_origin(language):
    set_lang(language)
    user = dict(x_position_min=10, x_position_max=310, printable_x_min=10, printable_x_max=300,
                y_position_min=20, y_position_max=320, printable_y_min=20, printable_y_max=300)
    assert preview._check_reachability(5, 7, user) == (
        t("probe.misses_left", distance=5) + "  " + t("probe.misses_front", distance=7))


@pytest.mark.parametrize("value", ["nan", "NaN", "inf", "-inf", "1e999"])
def test_nonfinite_values_are_rejected_before_any_render(value):
    assert preview._validate_offset(value) is not True


def test_real_input_rejects_nan_and_keeps_previous_precision(monkeypatch):
    user = dict(probe="BLTouch", x_size=300, y_size=300, probe_x_offset="-9.25", probe_y_offset="1.75")
    before = copy.deepcopy(user)
    answers = iter(["nan", "", "inf", "", "1"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    result = preview.run_probe_offset_step(user)
    assert result == {"probe_x_offset": "-9.25", "probe_y_offset": "1.75"}
    assert user == before


def test_enter_preserves_offsets_beyond_six_significant_digits(monkeypatch):
    user = dict(probe="BLTouch", x_size=300, y_size=300,
                probe_x_offset="-12.3456789", probe_y_offset="1.23456789")
    before = copy.deepcopy(user)
    answers = iter(["", "", "1"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    result = preview.run_probe_offset_step(user)
    assert result == {"probe_x_offset": "-12.3456789", "probe_y_offset": "1.23456789"}
    assert user == before


@pytest.mark.parametrize("answers", [["<"], ["10", "<"], ["10", "12", "3"]])
def test_back_from_any_offset_stage_preserves_input(monkeypatch, answers):
    user = dict(probe="BLTouch", x_size=300, y_size=300, probe_x_offset="-9", probe_y_offset="1")
    before = copy.deepcopy(user)
    replies = iter(answers)
    monkeypatch.setattr("builtins.input", lambda *a: next(replies))
    result = preview.run_probe_offset_step(user)
    assert "__back__" in result.values()
    assert user == before


def test_empty_reach_cannot_be_confirmed_and_can_be_corrected(monkeypatch):
    user = dict(probe="BLTouch", x_size=300, y_size=300)
    before = copy.deepcopy(user)
    with pytest.raises(ProbeGeometryError):
        preview._check_reachability(301, 0, user)
    values = iter(["301", "0", "-9", "1"])
    monkeypatch.setattr(preview, "simple_input", lambda *a, **kw: next(values))
    menus = []
    def choose(prompt, choices):
        actions = [item["value"] for item in choices]
        menus.append(actions)
        return "retry" if "yes" not in actions else "yes"
    monkeypatch.setattr(preview, "numbered_select", choose)
    result = preview.run_probe_offset_step(user)
    assert menus == [["retry", "back", "quit"], ["yes", "retry", "back", "quit"]]
    assert result == {"probe_x_offset": "-9.0", "probe_y_offset": "1.0"}
    assert user == before


def test_empty_reach_real_menu_back_does_not_commit(monkeypatch):
    user = dict(probe="BLTouch", x_size=300, y_size=300, probe_x_offset="-9", probe_y_offset="1")
    before = copy.deepcopy(user)
    answers = iter(["301", "0", "2"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    result = preview.run_probe_offset_step(user)
    assert result["probe_x_offset"] == "__back__"
    assert user == before


def test_partial_coverage_is_yellow_and_empty_geometry_is_red(capsys):
    warning = preview._check_reachability(-9, 0, dict(x_size=300, y_size=300))
    preview._print_frame(-9, 0, 300, 300, "Probe", warning)
    text = capsys.readouterr().out
    assert preview._YL + warning in text and preview._RD not in text
    preview._print_frame(301, 0, 300, 300, "Probe", t("probe.empty_reach"), geometry_error=True)
    assert preview._RD in capsys.readouterr().out


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
@pytest.mark.parametrize("columns,rows", [(40, 20), (60, 20), (80, 24), (120, 40)])
def test_grid_and_wrapped_legend_always_visible(monkeypatch, capsys, language, columns, rows):
    set_lang(language)
    monkeypatch.setattr("shutil.get_terminal_size", lambda **kw: os.terminal_size((columns, rows)))
    preview._print_frame(-9, 1, 300, 300, "BLTouch")
    text = menu._plain_label(capsys.readouterr().out)
    assert "|" in text and "[-]" in text and "[+]" in text
    normalized = " ".join(text.split())
    assert t("probe.legend") in normalized
    for key in ("probe.example_1", "probe.example_2", "probe.example_3", "probe.example_4"):
        assert t(key) in normalized
    assert max(map(len, text.splitlines())) <= columns
