"""Line editing preserves plain-input fallbacks and isolates in-memory history."""
import io
from unittest.mock import Mock, patch

import pytest

from core import line_input, menu
from core.exceptions import WizardExit


@pytest.fixture(autouse=True)
def interactive(monkeypatch):
    monkeypatch.setenv("KACE_AUTO", "0")
    monkeypatch.setattr(menu, "_MOCK_PROMPTS_ACTIVE", False)
    line_input._TEXT_HISTORY.clear()
    yield
    line_input._TEXT_HISTORY.clear()


def test_mocked_input_and_redirected_streams_keep_plain_prompt():
    with patch("builtins.input", return_value="P2.27") as read, \
            patch.object(line_input, "import_module") as load:
        assert menu.simple_input("Pin") == "P2.27"
    read.assert_called_once_with("  Pin: ")
    load.assert_not_called()
    assert not line_input._TEXT_HISTORY
    with patch("sys.stdin", io.StringIO("pipe\n")), \
            patch.object(line_input, "import_module") as load:
        assert line_input.read_line("Pipe: ", remember=True) == "pipe"
    load.assert_not_called()


def test_unavailable_readline_falls_back_without_changing_input():
    with patch.object(line_input, "_tty_input", return_value=True), \
            patch.object(line_input, "import_module", side_effect=ImportError), \
            patch("builtins.input", return_value="plain") as read:
        assert line_input.read_line("Prompt: ", remember=True) == "plain"
    read.assert_called_once_with("Prompt: ")


@pytest.mark.parametrize("failure", [KeyboardInterrupt, EOFError])
def test_readline_restores_ambient_history_even_on_cancel(failure):
    history = ["outside-application"]
    readline = Mock()
    readline.get_current_history_length.side_effect = lambda: len(history)
    readline.get_history_item.side_effect = lambda index: history[index - 1]
    readline.clear_history.side_effect = history.clear
    readline.add_history.side_effect = history.append
    line_input._TEXT_HISTORY.append("questionnaire-only")
    def cancelled(prompt):
        assert history == ["questionnaire-only"]
        history.append("partial-input")
        raise failure
    with patch.object(line_input, "_tty_input", return_value=True), \
            patch.object(line_input, "import_module", return_value=readline), \
            patch("builtins.input", side_effect=cancelled):
        with pytest.raises(WizardExit):
            menu.simple_input("Text")
    assert history == ["outside-application"]
    assert list(line_input._TEXT_HISTORY) == ["questionnaire-only"]


def test_auto_and_password_do_not_use_text_editor():
    with patch.object(menu, "read_line") as read:
        with patch.object(menu, "_is_auto", return_value=True):
            assert menu.simple_input("Text", default="default") == "default"
        with patch.object(menu.getpass, "getpass", return_value="synthetic-secret"):
            assert menu.password_input("API key") == "synthetic-secret"
    read.assert_not_called()
    assert not line_input._TEXT_HISTORY


def test_private_text_can_explicitly_disable_recording():
    with patch.object(menu, "read_line", return_value="private") as read:
        assert menu.simple_input("Private text", history=False) == "private"
    assert read.call_args.kwargs == {"remember": False}
