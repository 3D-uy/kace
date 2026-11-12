"""Startup choices must not consume a buffered blank as a default selection."""

import io
from unittest.mock import patch

import pytest

from core.dashboard import _select_language, _select_mode
from core.exceptions import WizardExit
from core.translations import get_lang, get_mode, set_lang, set_mode, t


@pytest.fixture(autouse=True)
def restore_locale_and_mode():
    language, mode = get_lang(), get_mode()
    yield
    set_lang(language)
    set_mode(mode)


@pytest.mark.parametrize("answer,language", [
    ("1", "English"), ("2", "Español"), ("3", "Português"),
])
def test_language_reprompts_empty_and_invalid_input_before_selecting(answer, language):
    with patch("builtins.input", side_effect=["", "  ", "invalid", "4", answer]) as read, \
            patch("sys.stdout", new_callable=io.StringIO):
        _select_language()
    assert read.call_count == 5
    assert get_lang() == language


@pytest.mark.parametrize("language", ["English", "Español", "Português"])
@pytest.mark.parametrize("answer,mode", [("1", "Beginner"), ("2", "Advanced")])
def test_mode_reprompts_and_reports_invalid_input_in_selected_language(language, answer, mode):
    set_lang(language)
    with patch("builtins.input", side_effect=["", "bad", "3", answer]) as read, \
            patch("sys.stdout", new_callable=io.StringIO) as output:
        _select_mode()
    assert read.call_count == 4
    assert get_mode() == mode
    assert t("menu.invalid_choice", count=2) in output.getvalue()


@pytest.mark.parametrize("selector", [_select_language, _select_mode])
@pytest.mark.parametrize("interruption", [EOFError, KeyboardInterrupt])
def test_retry_preserves_cancellation_without_changing_selection(selector, interruption):
    set_lang("Português")
    set_mode("Advanced")
    with patch("builtins.input", side_effect=["", interruption]), \
            patch("sys.stdout", new_callable=io.StringIO), pytest.raises(WizardExit):
        selector()
    assert get_lang() == "Português"
    assert get_mode() == "Advanced"
