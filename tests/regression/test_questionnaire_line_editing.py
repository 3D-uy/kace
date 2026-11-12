"""Real Linux SSH-style PTY regression; no printer or network access."""
import errno
import json
import os
from pathlib import Path
import select
import signal
import sys
import time

import pytest


pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux PTY/readline contract")


class QuestionnairePTY:
    def __init__(self, source):
        import fcntl
        import pty
        import struct
        import termios
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            root = Path(__file__).resolve().parents[2]
            os.chdir(root)
            env = dict(os.environ, TERM="xterm", KACE_AUTO="0", INPUTRC="/dev/null")
            os.execve(sys.executable, [sys.executable, "-u", "-c", source], env)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        self.output = bytearray()
        self.position = 0

    def until(self, token):
        deadline = time.monotonic() + 10
        while token not in self.output[self.position:]:
            remaining = deadline - time.monotonic()
            assert remaining > 0, bytes(self.output)
            if not select.select([self.fd], [], [], remaining)[0]:
                continue
            try:
                data = os.read(self.fd, 65536)
            except OSError as error:
                if error.errno != errno.EIO:
                    raise
                data = b""
            assert data, bytes(self.output)
            self.output.extend(data)
        self.position = self.output.index(token, self.position) + len(token)

    def send(self, value):
        os.write(self.fd, value)

    def result(self):
        self.until(b"RESULT:")
        self.until(b"\r\n")
        return json.loads(bytes(self.output).split(b"RESULT:", 1)[1].splitlines()[0])

    def close(self):
        try:
            os.kill(self.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        os.waitpid(self.pid, 0)
        os.close(self.fd)


def test_up_recalls_last_text_across_menus_and_arrows_edit_without_escape_literals():
    terminal = QuestionnairePTY('''
import json
from core.menu import simple_input, numbered_select
first = simple_input("FIRST")
choice = numbered_select("MENU", ["one", "two"])
second = simple_input("SECOND")
third = simple_input("THIRD")
print("RESULT:" + json.dumps([first, choice, second, third]))
''')
    try:
        terminal.until(b"FIRST: ")
        terminal.send(b"P2.17\n")
        terminal.until(b"[1-2]:")
        terminal.send(b"2\n")
        terminal.until(b"SECOND: ")
        terminal.send(b"\x1b[A\x1b[D\x1b[D\x1b[C\x7f2\n")
        terminal.until(b"THIRD: ")
        terminal.send(b"\x1b[A\n")
        assert terminal.result() == ["P2.17", "two", "P2.27", "P2.27"]
        assert b"^[[" not in terminal.output
    finally:
        terminal.close()


def test_password_api_key_private_input_and_ambient_history_cannot_be_recalled():
    terminal = QuestionnairePTY('''
import json, readline
from core.menu import simple_input, password_input
readline.add_history("external-value")
public = simple_input("PUBLIC")
secret = password_input("APIKEY")
private = simple_input("PRIVATE", history=False)
last = simple_input("LAST")
ambient = [readline.get_history_item(i) for i in range(1, readline.get_current_history_length()+1)]
print("RESULT:" + json.dumps([last, secret == "synthetic-secret", ambient]))
''')
    try:
        terminal.until(b"PUBLIC: ")
        terminal.send(b"P0.10\n")
        terminal.until(b"APIKEY: ")
        terminal.send(b"synthetic-secret\n")
        terminal.until(b"PRIVATE: ")
        terminal.send(b"private-value\n")
        terminal.until(b"LAST: ")
        terminal.send(b"\x1b[A\n")
        assert terminal.result() == ["P0.10", True, ["external-value"]]
        assert b"synthetic-secret" not in terminal.output
    finally:
        terminal.close()


def test_rejected_text_can_be_recalled_and_corrected_in_wrapped_colored_prompt():
    terminal = QuestionnairePTY('''
import json
from core.menu import simple_input
prompt = "\\x1b[36m" + "Known pin and connector " * 6 + "\\x1b[0mRETRY"
value = simple_input(prompt, validate=lambda text: text == "P2.27")
print("RESULT:" + json.dumps(value))
''')
    try:
        terminal.until(b"RETRY: ")
        terminal.send(b"P2.17\n")
        terminal.until(b"RETRY: ")
        terminal.send(b"\x1b[A\x1b[D\x7f2\n")
        assert terminal.result() == "P2.27"
        assert b"\x1b[36m" in terminal.output
        assert b"^[[" not in terminal.output
        assert b"\x01" not in terminal.output and b"\x02" not in terminal.output
    finally:
        terminal.close()


@pytest.mark.parametrize("control", [b"\x03", b"\x04"])
def test_control_c_and_eof_preserve_questionnaire_cancellation(control):
    terminal = QuestionnairePTY('''
import json
from core.menu import simple_input
from core.exceptions import WizardExit
try:
    simple_input("CANCEL")
except WizardExit:
    print("RESULT:" + json.dumps("cancelled"))
''')
    try:
        terminal.until(b"CANCEL: ")
        terminal.send(control)
        assert terminal.result() == "cancelled"
    finally:
        terminal.close()
