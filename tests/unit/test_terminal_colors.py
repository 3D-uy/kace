import os
import re
import unittest
from unittest.mock import patch

from core import terminal
from core.menu import numbered_select, simple_input, yes_no


class TestTerminalColorSemantics(unittest.TestCase):
    def test_semantic_roles_are_distinct_and_reset(self):
        roles = (
            terminal.QUESTION, terminal.INPUT, terminal.SUCCESS,
            terminal.WARNING, terminal.ERROR, terminal.INFO,
            terminal.PROGRESS, terminal.SECTION, terminal.HINT,
        )
        self.assertTrue(all(role.startswith("\033[") for role in roles))
        self.assertEqual(terminal.styled("SUCCESS", "done"), f"{terminal.SUCCESS}done{terminal.RESET}")
        self.assertNotEqual(terminal.ERROR, terminal.WARNING)
        self.assertNotEqual(terminal.SECTION, terminal.QUESTION)

    @patch("builtins.input", side_effect=["invalid", "1"])
    @patch("sys.stdout", new_callable=lambda: __import__("io").StringIO())
    def test_menu_uses_question_input_and_error_roles(self, stdout, _input):
        self.assertEqual(numbered_select("Choose", ["one"]), "one")
        output = stdout.getvalue()
        self.assertIn(f"{terminal.QUESTION}Choose{terminal.RESET}", output)
        self.assertIn(f"{terminal.INPUT}1) one{terminal.RESET}", output)
        self.assertIn(terminal.ERROR, output)

    @patch("builtins.input", side_effect=["maybe", "y"])
    @patch("sys.stdout", new_callable=lambda: __import__("io").StringIO())
    def test_yes_no_invalid_answer_is_an_error(self, stdout, _input):
        self.assertTrue(yes_no("Continue?"))
        self.assertIn(terminal.ERROR, stdout.getvalue())

    @patch("core.menu.shutil.get_terminal_size", return_value=os.terminal_size((42, 24)))
    @patch("builtins.input", return_value="1")
    @patch("sys.stdout", new_callable=lambda: __import__("io").StringIO())
    def test_long_menu_prompt_wraps_to_terminal_width(self, stdout, _input, _size):
        prompt = (
            "Seleccione la salida para el Ventilador del Fusor "
            "([heater_fan hotend_fan]) (Opcional):"
        )

        self.assertEqual(
            numbered_select(prompt, ["Sin ventilador"], require_explicit=True),
            "Sin ventilador",
        )

        ansi = re.compile(r"\x1b\[[0-9;]*m")
        visible_lines = [
            ansi.sub("", line)
            for line in stdout.getvalue().splitlines()
            if line.strip()
        ]
        self.assertTrue(all(len(line) <= 42 for line in visible_lines))
        prompt_lines = []
        for line in visible_lines:
            if re.match(r"\s*\d+\)", line):
                break
            prompt_lines.append(line.strip())
        rendered_prompt = " ".join(prompt_lines)
        self.assertIn(prompt, rendered_prompt)


if __name__ == "__main__":
    unittest.main()
