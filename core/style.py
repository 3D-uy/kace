from prompt_toolkit.styles import Style

custom_style = Style([
    # --- Base ---
    ('', 'bg:default'),

    # --- Pregunta / respuesta ---
    ('qmark', 'fg:#673ab7 bold'),
    ('question', 'bold'),
    ('answer', 'fg:#4caf50 bold'),

    # --- Navegación ---
    ('pointer', 'fg:#f5a623 bold bg:default'),

    # --- Estados ---
    ('highlighted', 'fg:#f5a623 bold bg:default'),
    ('selected', 'fg:#4caf50 bg:default'),
    ('selected.highlighted', 'fg:#4caf50 bold bg:default'),

    # 🔥 FIX REAL (prompt_toolkit internals)
    ('cursor-line', 'bg:default'),
    ('cursor-line.selected', 'bg:default'),

    # --- Estructura ---
    ('separator', 'fg:#00bcd4'),
    ('instruction', 'fg:#888888'),
    ('text', ''),
    ('disabled', 'fg:#858585 italic'),

    # --- Checkbox específicos ---
    ('checkbox', ''),
    ('checkbox-selected', 'fg:#4caf50 bg:default'),

    # --- Autocomplete ---
    ('completion-menu', 'bg:#1a1a2e fg:#e0e0e0'),
    ('completion-menu.completion', 'bg:#1a1a2e fg:#e0e0e0'),
    ('completion-menu.completion.current', 'fg:#f5a623 bold bg:default'),
    ('completion-menu.meta.completion', 'bg:#1a1a2e fg:#888888'),
    ('completion-menu.meta.completion.current', 'fg:#f5a623'),
])