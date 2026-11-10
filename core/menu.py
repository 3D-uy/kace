# core/menu.py
"""
Terminal-agnostic input helpers for KACE CLI.
Replaces questionary TUI calls with input()/print() and optional native TTY
editing: true TTY, bridged PTY, xterm.js SSH, or plain-input pipes.
"""

import sys
import os
import getpass
import warnings
import shutil
import textwrap
import re
from wcwidth import wcwidth, wcswidth
from core.exceptions import WizardExit
from core.line_input import read_line
from core.terminal import ERROR, QUESTION, RESET, WARNING
from core.translations import t

class Choice:
    """Class representing a choice for compatibility with questionary.Choice."""
    def __init__(self, title, value=None):
        self.title = title
        self.value = value if value is not None else title

class Separator:
    """Decorative menu separator that cannot be selected."""
    def __init__(self, text=""):
        self.text = text
    def __str__(self):
        return self.text

def _is_auto():
    return os.environ.get("KACE_AUTO") == "1"

_INTERACTION_REVISION = 0


def interaction_revision():
    """Identify whether a wizard step offered an interactive prompt."""
    return _INTERACTION_REVISION


def _record_interaction():
    global _INTERACTION_REVISION
    if not _is_auto():
        _INTERACTION_REVISION += 1


def _plain_label(label):
    return re.sub(r"\x1b\[[0-9;]*m", "", str(label))


def _exact_choices(query, choices):
    """Match visible labels and values, including navigation in filtered lists."""
    query = query.casefold()
    if query in ("<", "back", "volver", "voltar"):
        back = [item for item in choices if item[1] in ("__back__", "back")]
        if back:
            return back
    if query == "q":
        quit_choices = [item for item in choices if item[1] in ("__quit__", "quit")]
        if quit_choices:
            return quit_choices
    return [item for item in choices
            if query in (_plain_label(item[0]).casefold(), str(item[1]).casefold())]


def parse_choices(choices):
    """
    Parses various choice formats into:
      - display_lines: list of (is_selectable, item)
      - selectable_choices: list of (label, value)
    """
    display_lines = []
    selectable_choices = []
    
    for choice in choices:
        # Check if the choice is a Separator
        if isinstance(choice, Separator) or (hasattr(choice, 'text') and type(choice).__name__ == 'Separator'):
            display_lines.append((False, str(choice)))
        elif hasattr(choice, 'title') and hasattr(choice, 'value'):
            display_lines.append((True, (choice.title, choice.value)))
            selectable_choices.append((choice.title, choice.value))
        elif isinstance(choice, dict):
            name = choice.get("name")
            value = choice.get("value", name)
            if isinstance(name, list):
                if name and isinstance(name[0], (tuple, list)):
                    name = "".join(item[1] for item in name)
                else:
                    name = str(name)
            if name is None:
                name = str(value)
            display_lines.append((True, (name, value)))
            selectable_choices.append((name, value))
        elif isinstance(choice, tuple) and len(choice) == 2:
            display_lines.append((True, choice))
            selectable_choices.append(choice)
        elif isinstance(choice, list) and len(choice) == 2:
            display_lines.append((True, (choice[0], choice[1])))
            selectable_choices.append((choice[0], choice[1]))
        else:
            display_lines.append((True, (str(choice), choice)))
            selectable_choices.append((str(choice), choice))
            
    return display_lines, selectable_choices

_MOCK_DEFAULT = object()
_MOCK_PROMPTS_ACTIVE = False

def set_mock_prompts_active(active: bool) -> None:
    """Enable or disable prompt mocking for testing environment."""
    global _MOCK_PROMPTS_ACTIVE
    _MOCK_PROMPTS_ACTIVE = active

def _check_questionary_mock(helper_name, prompt):
    # Only run mock hook if testing environment is active
    if not _MOCK_PROMPTS_ACTIVE:
        return _MOCK_DEFAULT
        
    import sys
    from unittest.mock import Mock, MagicMock, DEFAULT
    
    q = sys.modules.get('questionary')
    if not q:
        return _MOCK_DEFAULT
        
    mock_names = {
        "simple_input": ["text"],
        "autocomplete_select": ["autocomplete", "text"],
        "numbered_select": ["select"],
        "yes_no": ["confirm"],
        "password_input": ["password"]
    }.get(helper_name, [])
    
    for name in mock_names:
        mock_func = getattr(q, name, None)
        if mock_func is None or not isinstance(mock_func, (Mock, MagicMock)):
            continue
        # Skip unconfigured MagicMock attributes (auto-created children of the
        # questionary MagicMock() stub in CI).  Without this guard, accessing
        # mock_func.return_value below mutates _mock_return_value from DEFAULT,
        # causing later branches to return garbage MagicMock objects.
        if mock_func.side_effect is None and mock_func._mock_return_value is DEFAULT:
            continue
        try:
            # If side_effect is set, we must call mock_func() to get the item for this call
            if mock_func.side_effect is not None:
                res = mock_func()
                # Resolve ask on the returned item
                ask_attr = getattr(res, 'ask', None)
                if ask_attr is not None:
                    if isinstance(ask_attr, (Mock, MagicMock)):
                        if ask_attr._mock_return_value is not DEFAULT or ask_attr.side_effect is not None:
                            val = ask_attr()
                            return _MOCK_DEFAULT if val is DEFAULT else val
                    elif callable(ask_attr):
                        val = ask_attr()
                        return _MOCK_DEFAULT if val is DEFAULT else val
                return _MOCK_DEFAULT if res is DEFAULT else res
            
            # Otherwise, check the return_value
            ret = mock_func.return_value
            ask_attr = getattr(ret, 'ask', None)
            if ask_attr is not None:
                if isinstance(ask_attr, (Mock, MagicMock)):
                    if ask_attr._mock_return_value is not DEFAULT or ask_attr.side_effect is not None:
                        mock_func()
                        val = ask_attr()
                        return _MOCK_DEFAULT if val is DEFAULT else val
                elif callable(ask_attr):
                    mock_func()
                    val = ask_attr()
                    return _MOCK_DEFAULT if val is DEFAULT else val
                    
            # If the mock itself has a custom return value set
            if mock_func._mock_return_value is not DEFAULT:
                res = mock_func()
                ask_attr_res = getattr(res, 'ask', None)
                if ask_attr_res is not None:
                    if isinstance(ask_attr_res, (Mock, MagicMock)):
                        if ask_attr_res._mock_return_value is not DEFAULT or ask_attr_res.side_effect is not None:
                            val = ask_attr_res()
                            return _MOCK_DEFAULT if val is DEFAULT else val
                    elif callable(ask_attr_res):
                        val = ask_attr_res()
                        return _MOCK_DEFAULT if val is DEFAULT else val
                return _MOCK_DEFAULT if res is DEFAULT else res
        except Exception:
            pass
            
    return _MOCK_DEFAULT


def _wrapped_prompt_lines(prompt, indent="  "):
    """Wrap a menu question to the visible terminal width.

    Wrapping happens before ANSI styling is applied so colour escape sequences
    do not count toward the visible width.  Long Klipper identifiers are kept
    intact whenever the terminal is wide enough to display them.
    """
    columns = shutil.get_terminal_size(fallback=(80, 24)).columns
    width = max(20, columns - len(indent))
    lines = []
    for source_line in str(prompt).splitlines() or [""]:
        lines.extend(textwrap.wrap(
            source_line,
            width=width,
            break_long_words=False,
            break_on_hyphens=False,
        ) or [""])
    return lines


def _choice_lines(index, label, columns):
    """Wrap visible label cells while retaining ANSI tokens and hanging indent."""
    prefix = f"    {WARNING}{index}){RESET} "
    indent = " " * (len(str(index)) + 6)
    width = max(1, columns - len(indent))
    tokens = re.findall(r"\x1b\[[0-9;]*m|[^\x1b]", str(label))
    chunks, current, cells = [], [], 0
    for token in tokens:
        token_width = 0 if token.startswith("\x1b[") else max(0, wcwidth(token))
        if token == "\n":
            chunks.append("".join(current))
            current, cells = [], 0
            continue
        if cells + token_width > width:
            split = next((i for i in range(len(current) - 1, -1, -1)
                          if current[i].isspace()), -1)
            if split > 0:
                chunks.append("".join(current[:split]))
                current = current[split + 1:]
                cells = sum(0 if part.startswith("\x1b[") else max(0, wcwidth(part))
                            for part in current)
            else:
                chunks.append("".join(current))
                current, cells = [], 0
        current.append(token)
        cells += token_width
    chunks.append("".join(current))
    return [prefix + chunks[0], *(indent + chunk for chunk in chunks[1:])]


def numbered_select(prompt, choices, default=0, require_explicit=False):
    """
    Replace questionary.select().
    choices: list of str, list of (label, value) tuples, list of dicts, or Separators.
    Returns the selected value (str or tuple value).
    default: 0-based index used on empty input.
    require_explicit: when true, an empty input re-prompts instead of silently
        accepting the default.  Automatic/non-interactive mode still uses the
        default because it cannot request input.
    """
    _record_interaction()
    mock_val = _check_questionary_mock("numbered_select", prompt)
    if mock_val is not _MOCK_DEFAULT:
        return mock_val

    display_lines, selectable_choices = parse_choices(choices)
    if not selectable_choices:
        return None
        
    if default < 0 or default >= len(selectable_choices):
        default = 0
        
    if _is_auto():
        return selectable_choices[default][1]

    size = shutil.get_terminal_size(fallback=(80, 24))

    print()
    for prompt_line in _wrapped_prompt_lines(prompt):
        print(f"  {QUESTION}{prompt_line}{RESET}")
    
    selectable_idx = 1
    selectable_map = {}
    
    for is_selectable, item in display_lines:
        if is_selectable:
            label, value = item
            for line in _choice_lines(selectable_idx, label, size.columns):
                print(line)
            selectable_map[str(selectable_idx)] = value
            selectable_idx += 1
        else:
            print(f"    {item}")
            
    default_label, default_val = selectable_choices[default]
    input_prompt = f"  {QUESTION}{t('menu.select_range', count=len(selectable_choices))}{RESET} "
    
    while True:
        try:
            val = read_line(input_prompt).strip()
        except (KeyboardInterrupt, EOFError):
            print()
            # R-06: Raise WizardExit instead of sys.exit(0) so the top-level
            # handler in kace.py gets a chance to clean up and log before exit.
            raise WizardExit
            
        if not val and require_explicit:
            print(f"  {WARNING}{t('menu.selection_required')}{RESET}")
            continue

        if not val:
            return default_val
            
        if val in selectable_map:
            return selectable_map[val]
            
        # Also allow entering the actual label/value case-insensitively if it matches
        exact_matches = _exact_choices(val, selectable_choices)
        if len(exact_matches) == 1:
            return exact_matches[0][1]
                
        print(f"  {ERROR}{t('menu.invalid_choice', count=len(selectable_choices))}{RESET}")

def _read_input(full_prompt, *, remember=False):
    """Keep input help readable on narrow SSH terminals without splitting words."""
    columns = shutil.get_terminal_size(fallback=(80, 24)).columns
    if wcswidth(_plain_label(full_prompt)) <= columns:
        return read_line(full_prompt, remember=remember)
    # Reserve the two-space indent and the trailing input separator.
    lines = _wrapped_prompt_lines(full_prompt.strip(), indent="   ")
    for line in lines[:-1]:
        print("  " + line)
    return read_line("  " + lines[-1] + " ", remember=remember)


def simple_input(prompt, default=None, validate=None, *, back_value=None, history=True):
    """
    Replace questionary.text().
    validate: optional callable(str) -> bool/str. Re-prompts on failure.
    Returns stripped string, or back_value for explicit navigation when enabled.
    Navigation is resolved before domain validation and default substitution.
    history: retain ordinary text in process memory for Up-arrow recall on TTYs.
        Secrets must use password_input(); history=False omits other private text.
    """
    _record_interaction()
    mock_val = _check_questionary_mock("simple_input", prompt)
    if mock_val is not _MOCK_DEFAULT:
        return mock_val

    if _is_auto():
        return str(default).strip() if default is not None else ""
        
    prompt = prompt.rstrip(" :")
    if back_value is not None:
        prompt += f" [{t('choice.back')}: <]"
    if default is not None and str(default).strip() != "":
        full_prompt = f"  {prompt} ({t('menu.default', value=default)}): "
    else:
        full_prompt = f"  {prompt}: "
        
    while True:
        try:
            val = _read_input(full_prompt, remember=history).strip()
        except (KeyboardInterrupt, EOFError):
            print()
            # S2-01: Raise WizardExit instead of sys.exit(0) so the top-level
            # handler in kace.py gets a chance to clean up (e.g. close open SSH
            # connections) before the process exits.
            raise WizardExit
            
        if back_value is not None and val.lower() in ("<", "back", "volver", "voltar", "__back__"):
            return back_value

        if not val and default is not None:
            val = str(default).strip()
            
        if validate is not None:
            res = validate(val)
            if isinstance(res, str):
                print(f"  {ERROR}[!] {res}{RESET}")
                continue
            elif not res:
                print(f"  {ERROR}[!] {t('menu.invalid_input')}{RESET}")
                continue
                
        return val

def yes_no(prompt, default=False):
    """
    Replace questionary.confirm().
    Returns bool. Lowercase choices show the Enter default explicitly.
    """
    _record_interaction()
    mock_val = _check_questionary_mock("yes_no", prompt)
    if mock_val is not _MOCK_DEFAULT:
        return mock_val

    if _is_auto():
        return default
        
    prompt = prompt.rstrip(" :")
    indicator = t("menu.yes_no_default_yes" if default else "menu.yes_no_default_no")
    full_prompt = f"  {prompt} {indicator}: "
    while True:
        try:
            val = _read_input(full_prompt).strip().lower()
        except (KeyboardInterrupt, EOFError):
            print()
            # S2-01: Raise WizardExit instead of sys.exit(0).
            raise WizardExit
            
        if not val:
            return default
            
        if val in ('y', 'yes', 's', 'si', 'sí', 'sim'):
            return True
        if val in ('n', 'no', 'não', 'nao'):
            return False
            
        print(f"  {ERROR}{t('menu.yes_no_expected')}{RESET}")

def autocomplete_select(prompt, choices, default=0, require_explicit=False, *,
                        search_first=False, renumber_results=False, allow_auto_default=True):
    """Select from a visible catalog with optional substring search.

    Lists below 20 choices retain the standard numbered menu. Longer lists show
    a bounded preview and keep navigation available after filtering.
    allow_auto_default=False requires an explicit choice instead of selecting the
    first item in automatic mode (used for unconfirmed board identity).
    """
    _record_interaction()
    mock_val = _check_questionary_mock("autocomplete_select", prompt)
    if mock_val is not _MOCK_DEFAULT:
        return mock_val

    _, selectable_choices = parse_choices(choices)
    if not selectable_choices:
        return None
    if default < 0 or default >= len(selectable_choices):
        default = 0
    if _is_auto():
        if not allow_auto_default:
            print(f"  {ERROR}{t('catalog.auto_board_required')}{RESET}")
            raise WizardExit
        return selectable_choices[default][1]
    if len(selectable_choices) < 20 and not search_first:
        return numbered_select(prompt, choices, default=default,
                               require_explicit=require_explicit)

    return _catalog_select(prompt, selectable_choices, default, require_explicit,
                           search_first=search_first, renumber_results=renumber_results)


def _catalog_select(prompt, selectable_choices, default, require_explicit, *,
                    search_first=False, renumber_results=False):
    """Keep one numbered list and its navigation while allowing optional filtering."""
    default_label, default_val = selectable_choices[default]
    indexed = list(enumerate(selectable_choices, 1))
    navigation = [(index, item) for index, item in indexed
                  if item[1] in ("__back__", "back", "__quit__", "quit")]
    catalog = [(index, item) for index, item in indexed if (index, item) not in navigation]
    matches, query = ([] if search_first else catalog), ""
    notice = ""
    while True:
        columns, rows = shutil.get_terminal_size(fallback=(80, 24))
        prompt_lines = _wrapped_prompt_lines(prompt)
        query_lines = _wrapped_prompt_lines(t("menu.search_matches", query=query)) if query else []
        help_lines = _wrapped_prompt_lines(t("catalog.search_help" if search_first else "menu.list_filter_help"))
        navigation_lines = [line for index, (label, _) in navigation
                            for line in _choice_lines(index, label, columns)]
        controls = [("< " if value in ("__back__", "back") else "q ") + _plain_label(label)
                    for _, (label, value) in navigation]
        control_lines = _wrapped_prompt_lines(" | ".join(controls)) if controls else []
        notice_lines = _wrapped_prompt_lines(notice) if notice else []
        input_text = (t("catalog.search_prompt") if search_first and not query else
                      t("menu.list_filter_prompt") if require_explicit or query else
                      t("menu.search_prompt", value=default_label))
        count_lines = _wrapped_prompt_lines(t("menu.list_preview_count", shown=len(matches), total=len(matches)))
        # Leave room for the existing wizard header, help, controls and input.
        # Filtering searches the complete catalog, so no paging is necessary.
        header_reserve = 0 if search_first and query else 10
        available = max(1, rows - header_reserve - 1 - sum(map(len, (
            prompt_lines, query_lines, help_lines, navigation_lines, control_lines,
            notice_lines, count_lines, _wrapped_prompt_lines(input_text),
        ))))
        visible, result_lines = [], []
        for index, item in matches:
            display_index = len(visible) + 1 if renumber_results else index
            lines = _choice_lines(display_index, item[0], columns)
            if visible and len(result_lines) + len(lines) > available:
                break
            visible.append((display_index, item))
            result_lines.extend(lines)
        visible_navigation = ([(len(visible) + index, item) for index, (_, item) in enumerate(navigation, 1)]
                              if renumber_results else navigation)
        navigation_lines = [line for index, (label, _) in visible_navigation
                            for line in _choice_lines(index, label, columns)]
        print()
        for line in prompt_lines:
            print(f"  {QUESTION}{line}{RESET}")
        for line in query_lines:
            print("  " + line)
        for line in result_lines + navigation_lines:
            print(line)
        if query or not search_first:
            for line in _wrapped_prompt_lines(t("menu.list_preview_count", shown=len(visible), total=len(matches))):
                print("  " + line)
        for line in help_lines + control_lines:
            print("  " + line)
        for line in notice_lines:
            print(f"  {WARNING}{line}{RESET}")
        try:
            answer = _read_input(f"  {QUESTION}{input_text}{RESET} ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            raise WizardExit
        notice = ""
        if not answer:
            if query:
                matches, query = ([] if search_first else catalog), ""
            elif require_explicit or search_first:
                notice = t("menu.selection_required")
            else:
                return default_val
            continue
        if answer == "/":
            matches, query = ([] if search_first else catalog), ""
            continue
        if answer.isdigit():
            selected = next((item for index, item in visible + visible_navigation if index == int(answer)), None)
            if selected is not None:
                return selected[1]
            notice = t("menu.list_visible_number")
            continue
        exact_matches = _exact_choices(answer, selectable_choices)
        if len(exact_matches) == 1:
            return exact_matches[0][1]
        filtered = [(index, item) for index, item in catalog
                    if answer.casefold() in _plain_label(item[0]).casefold()]
        if not filtered:
            if search_first:
                matches, query = [], answer
            notice = t("menu.search_no_matches", query=answer)
            continue
        matches, query = filtered, answer


def password_input(prompt):
    """
    Replace questionary.password().
    Uses getpass.getpass() for hidden input; refuses echoing fallbacks.
    """
    _record_interaction()
    mock_val = _check_questionary_mock("password_input", prompt)
    if mock_val is not _MOCK_DEFAULT:
        return mock_val

    if _is_auto():
        return ""
        
    prompt = prompt.rstrip(" :")
    try:
        # getpass otherwise warns and reads with echo when terminal control is
        # unavailable. Turn that warning into an error before it reads a secret.
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            val = getpass.getpass(prompt=f"  {prompt}: ")
    except (getpass.GetPassWarning, OSError):
        print(f"  {t('menu.secret_input_unavailable')}")
        raise WizardExit from None
    except (KeyboardInterrupt, EOFError):
        print()
        # S2-01: Raise WizardExit instead of sys.exit(0).
        raise WizardExit
    return val
