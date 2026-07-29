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


if __name__ == "__main__":
    unittest.main()
