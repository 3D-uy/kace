"""Semantic ANSI styles for the interactive KACE terminal UI.

Keep visual meaning independent of a caller's local colour preference.  The
wizard, menu and follow-up flows import these names rather than embedding ANSI
codes, so a role has one colour everywhere.
"""

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

# Interaction
QUESTION = "\033[1;96m"   # cyan: a question or selectable prompt
INPUT = "\033[92m"         # green: the active/default user selection

# Outcome and status
SUCCESS = "\033[92m"       # green: completed successfully
WARNING = "\033[93m"       # yellow: attention or potentially unsafe action
ERROR = "\033[91m"         # red: failure or blocking condition
INFO = "\033[96m"          # cyan: neutral explanatory information
PROGRESS = "\033[96m"      # cyan: work in progress
SECTION = "\033[96m"        # cyan: structural section heading
HINT = "\033[2;37m"        # dim gray: secondary guidance


def styled(role: str, text: object) -> str:
    """Return *text* wrapped in the named semantic role."""
    return f"{globals()[role]}{text}{RESET}"
