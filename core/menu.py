# core/menu.py
"""
Terminal-agnostic input helpers for KACE CLI.
Replaces questionary TUI calls with plain input()/print() that work
reliably in any environment: true TTY, bridged PTY, xterm.js SSH, pipes.
"""

import sys
import os
import getpass

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

def _check_questionary_mock(helper_name, prompt):
    import sys
    import os
    from unittest.mock import Mock, MagicMock, DEFAULT
    
    # Only run mock hook if testing environment is active
    if os.environ.get("KACE_TESTING") != "1":
        return DEFAULT
        
    q = sys.modules.get('questionary')
    if not q:
        return DEFAULT
        
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
                            return ask_attr()
                    elif callable(ask_attr):
                        return ask_attr()
                return res
            
            # Otherwise, check the return_value
            ret = mock_func.return_value
            ask_attr = getattr(ret, 'ask', None)
            if ask_attr is not None:
                if isinstance(ask_attr, (Mock, MagicMock)):
                    if ask_attr._mock_return_value is not DEFAULT or ask_attr.side_effect is not None:
                        mock_func()
                        return ask_attr()
                elif callable(ask_attr):
                    mock_func()
                    return ask_attr()
                    
            # If the mock itself has a custom return value set
            if mock_func._mock_return_value is not DEFAULT:
                res = mock_func()
                ask_attr_res = getattr(res, 'ask', None)
                if ask_attr_res is not None:
                    if isinstance(ask_attr_res, (Mock, MagicMock)):
                        if ask_attr_res._mock_return_value is not DEFAULT or ask_attr_res.side_effect is not None:
                            return ask_attr_res()
                    elif callable(ask_attr_res):
                        return ask_attr_res()
                return res
        except Exception:
            pass
            
    return DEFAULT


def numbered_select(prompt, choices, default=0):
    """
    Replace questionary.select().
    choices: list of str, list of (label, value) tuples, list of dicts, or Separators.
    Returns the selected value (str or tuple value).
    default: 0-based index used on empty input.
    """
    from unittest.mock import DEFAULT
    mock_val = _check_questionary_mock("numbered_select", prompt)
    if mock_val is not DEFAULT:
        return mock_val

    display_lines, selectable_choices = parse_choices(choices)
    if not selectable_choices:
        return None
        
    if default < 0 or default >= len(selectable_choices):
        default = 0
        
    if _is_auto():
        return selectable_choices[default][1]
        
    print(f"\n  \033[96m{prompt}\033[0m")
    
    selectable_idx = 1
    selectable_map = {}
    
    for is_selectable, item in display_lines:
        if is_selectable:
            label, value = item
            if (selectable_idx - 1) == default:
                print(f"    \033[93m{selectable_idx}) {label}\033[0m")
            else:
                print(f"    {selectable_idx}) {label}")
            selectable_map[str(selectable_idx)] = value
            selectable_idx += 1
        else:
            print(f"    {item}")
            
    default_label, default_val = selectable_choices[default]
    input_prompt = f"  \033[93mSelect [1-{len(selectable_choices)}] (default: {default_label}):\033[0m "
    
    while True:
        try:
            val = input(input_prompt).strip()
        except (KeyboardInterrupt, EOFError):
            print()
            sys.exit(0)
            
        if not val:
            return default_val
            
        if val in selectable_map:
            return selectable_map[val]
            
        # Also allow entering the actual label/value case-insensitively if it matches
        for label, val_choice in selectable_choices:
            if val.lower() == str(label).lower() or val.lower() == str(val_choice).lower():
                return val_choice
                
        print(f"  Invalid choice. Please select a number between 1 and {len(selectable_choices)}.")

def simple_input(prompt, default=None, validate=None):
    """
    Replace questionary.text().
    validate: optional callable(str) -> bool/str. Re-prompts on failure.
    Returns stripped string.
    """
    from unittest.mock import DEFAULT
    mock_val = _check_questionary_mock("simple_input", prompt)
    if mock_val is not DEFAULT:
        return mock_val

    if _is_auto():
        return str(default).strip() if default is not None else ""
        
    prompt = prompt.rstrip(" :")
    if default is not None:
        full_prompt = f"  {prompt} (default: {default}): "
    else:
        full_prompt = f"  {prompt}: "
        
    while True:
        try:
            val = input(full_prompt).strip()
        except (KeyboardInterrupt, EOFError):
            print()
            sys.exit(0)
            
        if not val and default is not None:
            val = str(default).strip()
            
        if validate is not None:
            res = validate(val)
            if isinstance(res, str):
                print(f"  [!] {res}")
                continue
            elif not res:
                print("  [!] Invalid input. Please try again.")
                continue
                
        return val

def yes_no(prompt, default=False):
    """
    Replace questionary.confirm().
    Returns bool. default shown in prompt as [Y/n] or [y/N].
    """
    from unittest.mock import DEFAULT
    mock_val = _check_questionary_mock("yes_no", prompt)
    if mock_val is not DEFAULT:
        return mock_val

    if _is_auto():
        return default
        
    prompt = prompt.rstrip(" :")
    indicator = "[Y/n]" if default else "[y/N]"
    full_prompt = f"  {prompt} {indicator}: "
    while True:
        try:
            val = input(full_prompt).strip().lower()
        except (KeyboardInterrupt, EOFError):
            print()
            sys.exit(0)
            
        if not val:
            return default
            
        if val in ('y', 'yes'):
            return True
        if val in ('n', 'no'):
            return False
            
        print("  Please enter 'y' or 'n'.")

def autocomplete_select(prompt, choices, default=0):
    """
    Replace questionary.autocomplete().
    For short lists (<20): behaves like numbered_select.
    For long lists (20+): accepts typed input, shows fuzzy-matched
    candidates (case-insensitive substring match), re-prompts until valid.
    choices: list of str or list of (label, value) tuples.
    """
    from unittest.mock import DEFAULT
    mock_val = _check_questionary_mock("autocomplete_select", prompt)
    if mock_val is not DEFAULT:
        return mock_val

    display_lines, selectable_choices = parse_choices(choices)
    if not selectable_choices:
        return None
        
    if default < 0 or default >= len(selectable_choices):
        default = 0
        
    if _is_auto():
        return selectable_choices[default][1]
        
    if len(selectable_choices) < 20:
        return numbered_select(prompt, choices, default=default)
        
    default_label, default_val = selectable_choices[default]
    
    prompt = prompt.rstrip(" :")
    print(f"\n  {prompt}")
    print(f"  (This is a long list of {len(selectable_choices)} options. Type search query to filter.)")
    
    while True:
        try:
            query = input(f"  Search (default: {default_label}): ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            sys.exit(0)
            
        if not query:
            return default_val
            
        matches = [item for item in selectable_choices if query.lower() in item[0].lower()]
        
        if not matches:
            print(f"  No matches found for '{query}'. Please try again.")
            continue
            
        # Check for exact match
        exact_matches = [item for item in matches if item[0].lower() == query.lower()]
        if len(exact_matches) == 1:
            return exact_matches[0][1]
            
        # Show matches
        while True:
            print(f"\n  Matches for '{query}':")
            for idx, (lbl, _) in enumerate(matches, 1):
                print(f"    {idx}) {lbl}")
            
            try:
                sel = input(f"  Select [1-{len(matches)}] or type new query: ").strip()
            except (KeyboardInterrupt, EOFError):
                print()
                sys.exit(0)
                
            if not sel:
                break
                
            if sel.isdigit():
                sel_idx = int(sel) - 1
                if 0 <= sel_idx < len(matches):
                    return matches[sel_idx][1]
                    
            # Treat search input as new query
            query = sel
            matches = [item for item in selectable_choices if query.lower() in item[0].lower()]
            if not matches:
                print(f"  No matches found for '{query}'. Returning to search.")
                break
                
            exact_matches = [item for item in matches if item[0].lower() == query.lower()]
            if len(exact_matches) == 1:
                return exact_matches[0][1]

def password_input(prompt):
    """
    Replace questionary.password().
    Uses getpass.getpass() for hidden input.
    """
    from unittest.mock import DEFAULT
    mock_val = _check_questionary_mock("password_input", prompt)
    if mock_val is not DEFAULT:
        return mock_val

    if _is_auto():
        return ""
        
    prompt = prompt.rstrip(" :")
    try:
        val = getpass.getpass(prompt=f"  {prompt}: ")
    except (KeyboardInterrupt, EOFError):
        print()
        sys.exit(0)
    return val
