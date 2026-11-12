"""Exercise the real line-input path with newlines buffered before startup."""

import io
from unittest.mock import patch

import pytest

from core.dashboard import run_dashboard
from core.translations import get_lang, get_mode, set_lang, set_mode


@pytest.mark.parametrize("choice,language", [("2", "Español"), ("3", "Português")])
def test_buffered_newlines_do_not_skip_language_or_mode(choice, language):
    previous = get_lang(), get_mode()
    # Two Enters buffered while the installer is busy, then an explicit locale;
    # a blank mode answer must likewise wait for the explicit Advanced choice.
    incoming = io.StringIO("\n\n" + choice + "\n\n2\n1\nremaining\n")
    state = {"klipper": True, "moonraker": True, "mainsail": True,
             "fluidd": False, "printer_cfg": True, "mcu": None,
             "mcu_path": None, "crowsnest_status": "not_found"}
    try:
        with patch("sys.stdin", incoming), patch("sys.stdout", new_callable=io.StringIO):
            result = run_dashboard(state)
        assert result == "generate"
        assert get_lang() == language
        assert get_mode() == "Advanced"
        assert incoming.readline() == "remaining\n"
    finally:
        set_lang(previous[0])
        set_mode(previous[1])
