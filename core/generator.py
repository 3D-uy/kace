import os
from jinja2 import Environment, FileSystemLoader
from core.translations import translate_comment, get_lang
from core.macro_generator import generate_starter_macros

# Resolve templates directory relative to this file's location, not the CWD
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEMPLATES_DIR = os.path.join(_BASE_DIR, 'templates')

def has_todo_pins(parsed_data: dict) -> list:
    """Return a list of (section, key) tuples for any unresolved TODO pins.

    Scans parsed config values for literal 'TODO' strings.  Called early
    in kace.py — before the firmware compilation prompt — so the user is
    not sent through compilation for a config that is already known to be
    incomplete.  An empty list means the config is clean.
    """
    todos = []
    current_section = "unknown"
    for section, values in parsed_data.items():
        if isinstance(values, dict):
            for key, val in values.items():
                if isinstance(val, str) and "TODO" in val:
                    todos.append((section, key))
    return todos


def generate_config(parsed_data, user_data, output_path=None, include_macros=False):

    """Generate printer.cfg from parsed config and user data using Jinja2."""
    # Setup Jinja2 environment
    env = Environment(loader=FileSystemLoader(_TEMPLATES_DIR, encoding='utf-8'))
    template = env.get_template('printer.cfg.j2')
    
    # Render the template with parsed pins and user input
    output = template.render(
        pins=parsed_data,
        user=user_data
    )
    
    # Align inline comments for a professional look
    aligned_lines = []
    comment_col = 48
    # get_lang() is always authoritative: set by the dashboard language picker
    # before the wizard runs. user_data['language'] is a synced copy of it.
    language = get_lang()
    for line in output.splitlines():
        # Check if line is a commented setting that contains an inline comment
        is_commented_setting = line.lstrip().startswith('#') and line.count('#') > 1 and (':' in line or ('[' in line and ']' in line))
        if ('#' in line and not line.lstrip().startswith('#')) or is_commented_setting:
            if not is_commented_setting:
                content, comment = line.split('#', 1)
            else:
                first_hash = line.find('#')
                second_hash = line.find('#', first_hash + 1)
                content, comment = line[:second_hash], line[second_hash+1:]

            content = content.rstrip()
            comment = comment.strip()
            
            # Translate if necessary
            comment = translate_comment(comment, language)
            
            # Ensure at least one space before the comment
            padding = max(1, comment_col - len(content))
            aligned_lines.append(f"{content}{' ' * padding}# {comment}")
        else:
            # Regular line or normal full-line comment
            if line.lstrip().startswith('#'):
                comment = line.lstrip()[1:].strip()
                translated = translate_comment(comment, language)
                if comment != translated:
                    # Update translated full line comment
                    line = line.replace(f"# {comment}", f"# {translated}")
            aligned_lines.append(line)
    
    final_output = chr(10).join(aligned_lines)
    
    if include_macros:
        final_output = "[include macros.cfg]\n\n" + final_output
    # Validation: Do not proceed if generic TODO pins are left active, preventing Klipper startup errors
    has_active_todo = False
    for line in final_output.splitlines():
        if "TODO" in line and not line.lstrip().startswith("#"):
            has_active_todo = True
            break
            
    if has_active_todo:
        import sys
        print("\n\033[91mCRITICAL ERROR: Configuration generated with unresolved 'TODO' values!\033[0m")
        print("\033[93mThis usually happens if your board does not map all required pins natively.\033[0m")
        
        current_section = "unknown"
        for line in final_output.splitlines():
            stripped = line.strip()
            if stripped.startswith("[") and "]" in stripped:
                current_section = stripped
            elif "TODO" in line and not line.lstrip().startswith("#"):
                key = line.split(":")[0].strip().lstrip("#").strip()
                print(f"TODO_FOUND: {current_section} -> {key}")
                
        print("\033[91mGeneration aborted to guarantee it starts without errors in Klipper.\033[0m")
        sys.exit(1)
        
    # Write to printer.cfg
    if not output_path:
        base_path = os.path.expanduser('~/kace')
        os.makedirs(base_path, exist_ok=True)
        cfg_file = os.path.join(base_path, 'printer.cfg')
    else:
        parent = os.path.dirname(os.path.abspath(output_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        cfg_file = output_path
        
    with open(cfg_file, 'w', encoding='utf-8') as f:
        f.write(final_output)

    if include_macros:
        output_dir = os.path.dirname(cfg_file)
        generate_starter_macros(output_dir)
