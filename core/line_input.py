"""Optional standard-library line editing for questionnaire text on a real TTY.

Only questionnaire text is retained, in memory for this process.  Readline's
ambient history is isolated/restored around each prompt; no history file is read
or written. Password/API-key prompts continue to use getpass, never this helper.
"""

from collections import deque
from importlib import import_module
import inspect
import re
import sys


_TEXT_HISTORY = deque(maxlen=50)
_ANSI_STYLE = re.compile(r"\x1b\[[0-9;]*m")


def _tty_input():
    # CPython uses readline only with the actual terminal descriptors. Keep
    # patched input(), pipes, redirected output and unsupported hosts unchanged.
    try:
        return (inspect.isbuiltin(input) and sys.stdin.isatty() and sys.stdout.isatty()
                and sys.stdin.fileno() == 0 and sys.stdout.fileno() == 1)
    except (AttributeError, OSError, ValueError):
        return False


def read_line(prompt, *, remember=False):
    """Read with native editing when available, otherwise ordinary input()."""
    if not _tty_input():
        return input(prompt)
    try:
        readline = import_module("readline")
    except ImportError:
        return input(prompt)

    previous = [readline.get_history_item(index)
                for index in range(1, readline.get_current_history_length() + 1)]
    try:
        readline.clear_history()
        for value in _TEXT_HISTORY:
            readline.add_history(value)
        # GNU readline must not count styling bytes when wrapping/redrawing.
        styled_prompt = _ANSI_STYLE.sub(lambda match: "\001" + match[0] + "\002", prompt)
        value = input(styled_prompt)
        if remember and value.strip() and value not in ("<", "__back__"):
            if not _TEXT_HISTORY or _TEXT_HISTORY[-1] != value:
                _TEXT_HISTORY.append(value)
        return value
    finally:
        # input() automatically appends submitted text to readline's history.
        # Remove that entry even on cancellation; never leak it to another CLI.
        readline.clear_history()
        for value in previous:
            readline.add_history(value)
