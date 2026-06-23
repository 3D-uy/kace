# core/translations.py

# ── i18n: UI String Layer ──────────────────────────────────────
# Language state — set once after the user's language choice, then
# read by all modules via get_lang() so callers never thread lang
# through every function signature.

_current_lang = "English"

_SUPPORTED_LANGS = ("English", "Español", "Português")


def set_lang(lang: str) -> None:
    """Set the active UI language for the current session."""
    global _current_lang
    if lang in _SUPPORTED_LANGS:
        _current_lang = lang


def get_lang() -> str:
    """Return the active UI language."""
    return _current_lang


_current_mode = "Beginner"


def set_mode(mode: str) -> None:
    """Set the configuration mode for the current session."""
    global _current_mode
    if mode in ("Beginner", "Advanced"):
        _current_mode = mode


def get_mode() -> str:
    """Return the active configuration mode."""
    return _current_mode


# All user-facing UI strings keyed by a short dot-separated ID.
# Each entry maps language name → display string.
# Strings may contain {placeholders} for str.format(**kwargs).
# Detection paths listed here use standard Klipper defaults and
# are kept in one place to make future configurability easy.
UI_STRINGS: dict = {
    # ── Wizard prompts ─────────────────────────────────────────
    "wizard.select_mode": {
        "English":   "Select Configuration Mode / Seleccione el Modo de Configuración / Selecione o Modo de Configuração:",
        "Español":   "Seleccione el Modo de Configuración:",
        "Português": "Selecione o Modo de Configuração:",
    },
    "wizard.mode.beginner": {
        "English":   "Beginner (guided with hints and recommendations)",
        "Español":   "Principiante (guiado con sugerencias y recomendaciones)",
        "Português": "Iniciante (guiado com dicas e recomendações)",
    },
    "wizard.mode.advanced": {
        "English":   "Advanced (collapsed UI, no hints or guidance)",
        "Español":   "Avanzado (UI simplificada, sin sugerencias ni guías)",
        "Português": "Avançado (UI simplificada, sem dicas ou guias)",
    },
    "wizard.select_language": {
        "English":   "Select language for comments / Seleccione el idioma / Selecione o idioma:",
        "Español":   "Seleccione el idioma para comentarios:",
        "Português": "Selecione o idioma para comentários:",
    },
    "wizard.select_printer_model": {
        "English":   "Select your Printer Model (type to search) [Ctrl+C to go back]:",
        "Español":   "Seleccione el modelo de impresora (escriba para buscar) [Ctrl+C para volver]:",
        "Português": "Selecione o modelo de impressora (digite para buscar) [Ctrl+C para voltar]:",
    },
    "wizard.select_printer_model_menu": {
        "English":   "Select your Printer Model:",
        "Español":   "Seleccione su modelo de impresora:",
        "Português": "Selecione o modelo de impressora:",
    },
    "wizard.select_board": {
        "English":   "Select your Board:",
        "Español":   "Seleccione su placa:",
        "Português": "Selecione sua placa:",
    },
    "wizard.select_board_suggested": {
        "English":   "Suggested boards based on your MCU:",
        "Español":   "Placas sugeridas según su MCU:",
        "Português": "Placas sugeridas com base no seu MCU:",
    },
    "wizard.select_board_manual": {
        "English":   "Select your board manually (type to search) [Ctrl+C to go back]:",
        "Español":   "Seleccione su placa manualmente (escriba para buscar) [Ctrl+C para volver]:",
        "Português": "Selecione sua placa manualmente (digite para buscar) [Ctrl+C para voltar]:",
    },
    "wizard.part_cooling_prompt": {
        "English":   "Select output pin for the Part Cooling Fan ([fan]):",
        "Español":   "Seleccione la salida para el Ventilador de Capa ([fan]):",
        "Português": "Selecione a saída para o Ventilador de Camada ([fan]):",
    },
    "wizard.hotend_fan_prompt": {
        "English":   "Select output pin for the Hotend Heatsink Fan ([heater_fan hotend_fan]) (Optional):",
        "Español":   "Seleccione la salida para el Ventilador del Fusor ([heater_fan hotend_fan]) (Opcional):",
        "Português": "Selecione a saída para o Ventilador do Fusor ([heater_fan hotend_fan]) (Opcional):",
    },
    "wizard.fan_board_default": {
        "English":   "Board Default (pin: {pin})",
        "Español":   "Predeterminado de la placa (pin: {pin})",
        "Português": "Padrão da placa (pin: {pin})",
    },
    "wizard.fan_custom": {
        "English":   "Custom pin...",
        "Español":   "Pin personalizado...",
        "Português": "Pin personalizado...",
    },
    "wizard.fan_none": {
        "English":   "None / Disable",
        "Español":   "Ninguno / Desactivar",
        "Português": "Nenhum / Desativar",
    },
    "wizard.fan_enter_custom": {
        "English":   "Enter custom pin name (e.g. PB6):",
        "Español":   "Ingrese el nombre del pin personalizado (ej. PB6):",
        "Português": "Digite o nome do pin personalizado (ex: PB6):",
    },
    "wizard.select_kinematics": {
        "English":   "Select Kinematics:",
        "Español":   "Seleccione la Cinemática:",
        "Português": "Selecione a Cinemática:",
    },
    "wizard.x_volume": {
        "English":   "Enter X build volume (mm) [Ctrl+C to go back]:",
        "Español":   "Ingrese el volumen de construcción X (mm) [Ctrl+C para volver]:",
        "Português": "Digite o volume de impressão X (mm) [Ctrl+C para voltar]:",
    },
    "wizard.y_volume": {
        "English":   "Enter Y build volume (mm) [Ctrl+C to go back]:",
        "Español":   "Ingrese el volumen de construcción Y (mm) [Ctrl+C para volver]:",
        "Português": "Digite o volume de impressão Y (mm) [Ctrl+C para voltar]:",
    },
    "wizard.z_volume": {
        "English":   "Enter Z build volume (mm) [Ctrl+C to go back]:",
        "Español":   "Ingrese el volumen de construcción Z (mm) [Ctrl+C para volver]:",
        "Português": "Digite o volume de impressão Z (mm) [Ctrl+C para voltar]:",
    },
    "wizard.select_probe": {
        "English":   "Select Probe Type:",
        "Español":   "Seleccione el Tipo de Sensor:",
        "Português": "Selecione o Tipo de Sensor:",
    },
    "wizard.bltouch_sensor_prompt": {
        "English":   "BLTouch sensor_pin (e.g. ^PB7 or ^PC5):",
        "Español":   "Pin de sensor de BLTouch (ej. ^PB7 o ^PC5):",
        "Português": "Pino do sensor do BLTouch (ex. ^PB7 ou ^PC5):",
    },
    "wizard.bltouch_control_prompt": {
        "English":   "BLTouch control_pin (e.g. PB6 or PE5):",
        "Español":   "Pin de control de BLTouch (ej. PB6 o PE5):",
        "Português": "Pino de controle do BLTouch (ex. PB6 ou PE5):",
    },
    "wizard.bltouch_unknown_pins_warn": {
        "English":   "\n[!] BLTouch/CR-Touch selected but pin mapping is unknown for:\n    {board}\n    Enter the pins manually below (check your board's wiring diagram).\n    Example — Octopus Pro: sensor_pin=^PB7  control_pin=PB6\n",
        "Español":   "\n[!] Se seleccionó BLTouch/CR-Touch pero se desconoce el mapa de pines para:\n    {board}\n    Ingrese los pines manualmente a continuación (consulte el diagrama de cableado de su placa).\n    Ejemplo — Octopus Pro: sensor_pin=^PB7  control_pin=PB6\n",
        "Português":   "\n[!] BLTouch/CR-Touch selecionado, mas o mapeamento de pinos é desconhecido para:\n    {board}\n    Insira os pinos manualmente abaixo (verifique o diagrama de fiação da sua placa).\n    Exemplo — Octopus Pro: sensor_pin=^PB7  control_pin=PB6\n",
    },
    "wizard.probe_x_offset": {
        "English":   "Probe X offset from nozzle (mm, e.g. -38 or 0):",
        "Español":   "Desplazamiento X del sensor desde la boquilla (mm, ej. -38 o 0):",
        "Português": "Deslocamento X do sensor em relação ao bico (mm, ex. -38 ou 0):",
    },
    "wizard.probe_y_offset": {
        "English":   "Probe Y offset from nozzle (mm, e.g. 0 or 25):",
        "Español":   "Desplazamiento Y del sensor desde la boquilla (mm, ej. 0 o 25):",
        "Português": "Deslocamento Y do sensor em relação ao bico (mm, ex. 0 ou 25):",
    },
    "wizard.probe_confirm_offsets": {
        "English":   "Are these probe offsets correct?",
        "Español":   "¿Son correctos estos desplazamientos del sensor?",
        "Português": "Estes deslocamentos do sensor estão corretos?",
    },
    "wizard.probe_confirm_yes": {
        "English":   "Yes, continue",
        "Español":   "Sí, continuar",
        "Português": "Sim, continuar",
    },
    "wizard.probe_confirm_retry": {
        "English":   "No, re-enter offsets",
        "Español":   "No, volver a ingresar desplazamientos",
        "Português": "Não, reinserir deslocamentos",
    },
    "wizard.select_hotend_therm": {
        "English":   "Select Hotend Thermistor:",
        "Español":   "Seleccione el Termistor del Hotend:",
        "Português": "Selecione o Termistor do Hotend:",
    },
    "wizard.custom_hotend_therm": {
        "English":   "Enter custom hotend thermistor name:",
        "Español":   "Ingrese el nombre personalizado del termistor del hotend:",
        "Português": "Digite o nome personalizado do termistor do hotend:",
    },
    "wizard.select_bed_therm": {
        "English":   "Select Bed Thermistor:",
        "Español":   "Seleccione el Termistor de la Cama:",
        "Português": "Selecione o Termistor da Mesa:",
    },
    "wizard.custom_bed_therm": {
        "English":   "Enter custom bed thermistor name:",
        "Español":   "Ingrese el nombre personalizado del termistor de la cama:",
        "Português": "Digite o nome personalizado do termistor da mesa:",
    },
    "wizard.select_driver": {
        "English":   "Select Stepper Driver Type:",
        "Español":   "Seleccione el Tipo de Driver de Motores:",
        "Português": "Selecione o Tipo de Driver de Motores:",
    },
    "wizard.select_driver_mode": {
        "English":   "Select {driver} Communication Mode:",
        "Español":   "Seleccione el Modo de Comunicación del {driver}:",
        "Português": "Selecione o Modo de Comunicação do {driver}:",
    },
    "wizard.z_motors": {
        "English":   "How many Z motor drivers are you using?",
        "Español":   "¿Cuántos drivers para motores Z está utilizando?",
        "Português": "Quantos drivers para motores Z você está usando?",
    },
    "wizard.select_web_ui": {
        "English":   "Select your Web Interface (for includes):",
        "Español":   "Seleccione su Interfaz Web (para includes):",
        "Português": "Selecione sua Interface Web (para includes):",
    },
    "wizard.select_driver_z": {
        "English":   "Select driver for {motor}:",
        "Español":   "Seleccione el driver para {motor}:",
        "Português": "Selecione o driver para {motor}:",
    },
    "wizard.mapping_pins": {
        "English":   ">>> Mapping pins for [ {motor} ] ...",
        "Español":   ">>> Asignando pines para [ {motor} ] ...",
        "Português": ">>> Mapeando pinos para [ {motor} ] ...",
    },
    "wizard.detected_mcu": {
        "English":   "Detected MCU",
        "Español":   "MCU Detectado",
        "Português": "MCU Detectado",
    },
    "wizard.stock_hardware_warning_title": {
        "English":   "[!] Incompatible stock hardware detected",
        "Español":   "[!] Hardware de fábrica incompatible detectado",
        "Português": "[!] Hardware de fábrica incompatível detectado",
    },
    "wizard.stock_hardware_profile": {
        "English":   "Printer profile:",
        "Español":   "Perfil de impresora:",
        "Português": "Perfil da impressora:",
    },
    "wizard.stock_hardware_expected": {
        "English":   "Expected stock MCU:",
        "Español":   "MCU de fábrica esperado:",
        "Português": "MCU de fábrica esperado:",
    },
    "wizard.stock_hardware_detected": {
        "English":   "Detected MCU:",
        "Español":   "MCU detectado:",
        "Português": "MCU detectado:",
    },
    "wizard.stock_hardware_mismatch": {
        "English":   "The connected controller does not match the expected stock hardware for this printer.",
        "Español":   "El controlador conectado no coincide con el hardware de fábrica esperado para esta impresora.",
        "Português": "O controlador conectado não corresponde ao hardware de fábrica esperado para esta impressora.",
    },
    "wizard.stock_hardware_reasons": {
        "English":   "This usually means:\n- the printer has a replacement mainboard\n- or the selected printer profile is incorrect\n\nPlease select a compatible manual board instead.",
        "Español":   "Esto generalmente significa:\n- la impresora tiene una placa base de reemplazo\n- o el perfil de impresora seleccionado es incorrecto\n\nPor favor, seleccione una placa manual compatible en su lugar.",
        "Português": "Isso geralmente significa:\n- a impressora tem uma placa-mãe de substituição\n- ou o perfil da impressora selecionado está incorreto\n\nPor favor, selecione uma placa manual compatível.",
    },
    "wizard.stock_hardware_ack": {
        "English":   "Press Enter to continue...",
        "Español":   "Presione Enter para continuar...",
        "Português": "Pressione Enter para continuar...",
    },
    "wizard.no_drivers_warning": {
        "English":   "Warning: Your board does not have enough available stepper drivers in its config for this Z motor.",
        "Español":   "Advertencia: Su placa no tiene suficientes drivers disponibles para este motor Z.",
        "Português": "Aviso: Sua placa não tem drivers disponíveis suficientes para este motor Z.",
    },
    "wizard.custom_step_pin": {
        "English":   "Enter step_pin (e.g. PC4):",
        "Español":   "Ingrese step_pin (ej. PC4):",
        "Português": "Digite step_pin (ex. PC4):",
    },
    "wizard.custom_dir_pin": {
        "English":   "Enter dir_pin (e.g. PA6):",
        "Español":   "Ingrese dir_pin (ej. PA6):",
        "Português": "Digite dir_pin (ex. PA6):",
    },
    "wizard.custom_en_pin": {
        "English":   "Enter enable_pin (e.g. !PC5):",
        "Español":   "Ingrese enable_pin (ej. !PC5):",
        "Português": "Digite enable_pin (ex. !PC5):",
    },
    "wizard.custom_uart_pin": {
        "English":   "Enter {mode}_pin for {motor}:",
        "Español":   "Ingrese {mode}_pin para {motor}:",
        "Português": "Digite {mode}_pin para {motor}:",
    },
    "wizard.assign_custom_pins_header": {
        "English":   "\nAssigning custom pins for {motor}:",
        "Español":   "\nAsignando pines personalizados para {motor}:",
        "Português": "\nAtribuindo pinos personalizados para {motor}:",
    },
    "wizard.confirm_standalone": {
        "English":   "No driver data detected. Are you sure you want to use Standalone / standard drivers (no UART/SPI)?",
        "Español":   "No se detectaron datos del driver. ¿Está seguro de que desea usar drivers Standalone / estándar (sin UART/SPI)?",
        "Português": "Nenhum dado de driver detectado. Tem certeza de que deseja usar drivers Standalone / padrão (sem UART/SPI)?",
    },
    # ── Common choice labels ────────────────────────────────────
    "choice.back": {
        "English":   "Back",
        "Español":   "Volver",
        "Português": "Voltar",
    },
    "choice.quit": {
        "English":   "Quit",
        "Español":   "Salir",
        "Português": "Sair",
    },
    "choice.search_manually": {
        "English":   "Search manually...",
        "Español":   "Buscar manualmente...",
        "Português": "Buscar manualmente...",
    },
    "choice.custom_scratch": {
        "English":   "Custom / Scratch Build",
        "Español":   "Construcción Personalizada / Desde Cero",
        "Português": "Construção Personalizada / Do Zero",
    },
    "choice.stock_board": {
        "English":   "Stock Board (from printer profile)",
        "Español":   "Placa de Fábrica (del perfil de la impresora)",
        "Português": "Placa de Fábrica (do perfil da impressora)",
    },
    "choice.other_manual": {
        "English":   "Other (Manual Entry)",
        "Español":   "Otro (Ingreso Manual)",
        "Português": "Outro (Entrada Manual)",
    },
    "choice.custom_pins": {
        "English":   "Custom pin assignment",
        "Español":   "Asignación de pines personalizada",
        "Português": "Atribuição de pinos personalizada",
    },
    "choice.quit_setup": {
        "English":   "Quit setup",
        "Español":   "Salir de la configuración",
        "Português": "Sair da configuração",
    },
    "choice.continue": {
        "English":   "✓  Continue",
        "Español":   "✓  Continuar",
        "Português": "✓  Continuar",
    },
    "choice.edit_profile": {
        "English":   "✎  Edit Profile",
        "Español":   "✎  Editar Perfil",
        "Português": "✎  Editar Perfil",
    },
    "choice.arrow_back": {
        "English":   "◀  Back",
        "Español":   "◀  Volver",
        "Português": "◀  Voltar",
    },
    "choice.back_discard": {
        "English":   "◀  Back (discard)",
        "Español":   "◀  Volver (descartar)",
        "Português": "◀  Voltar (descartar)",
    },
    "wizard.profile_review_prompt": {
        "English":   "What would you like to do?",
        "Español":   "¿Qué desea hacer?",
        "Português": "O que você gostaria de fazer?",
    },
    "wizard.profile_editor_prompt": {
        "English":   "Select a field to edit, or save:",
        "Español":   "Seleccione un campo para editar, o guarde:",
        "Português": "Selecione um campo para editar ou salvar:",
    },
    "choice.save_continue": {
        "English":   "✓  Save & Continue",
        "Español":   "✓  Guardar y Continuar",
        "Português": "✓  Salvar e Continuar",
    },
    "choice.editor_kinematics": {
        "English":   " 1. Kinematics",
        "Español":   " 1. Cinemática",
        "Português": " 1. Cinemática",
    },
    "choice.editor_volume": {
        "English":   " 2. Build Volume",
        "Español":   " 2. Volumen de Construcción",
        "Português": " 2. Volume de Impressão",
    },
    "choice.editor_x_min": {
        "English":   " 3. X position_min",
        "Español":   " 3. X position_min",
        "Português": " 3. X position_min",
    },
    "choice.editor_x_max": {
        "English":   " 4. X position_max",
        "Español":   " 4. X position_max",
        "Português": " 4. X position_max",
    },
    "choice.editor_x_endstop": {
        "English":   " 5. X position_endstop",
        "Español":   " 5. X position_endstop",
        "Português": " 5. X position_endstop",
    },
    "choice.editor_y_min": {
        "English":   " 6. Y position_min",
        "Español":   " 6. Y position_min",
        "Português": " 6. Y position_min",
    },
    "choice.editor_y_max": {
        "English":   " 7. Y position_max",
        "Español":   " 7. Y position_max",
        "Português": " 7. Y position_max",
    },
    "choice.editor_y_endstop": {
        "English":   " 8. Y position_endstop",
        "Español":   " 8. Y position_endstop",
        "Português": " 8. Y position_endstop",
    },
    "choice.editor_z_min": {
        "English":   " 9. Z position_min",
        "Español":   " 9. Z position_min",
        "Português": " 9. Z position_min",
    },
    "choice.editor_z_max": {
        "English":   "10. Z position_max",
        "Español":   "10. Z position_max",
        "Português": "10. Z position_max",
    },
    "choice.editor_z_endstop": {
        "English":   "11. Z position_endstop",
        "Español":   "11. Z position_endstop",
        "Português": "11. Z position_endstop",
    },
    "choice.editor_hotend_thermistor": {
        "English":   "12. Hotend Thermistor",
        "Español":   "12. Termistor del Hotend",
        "Português": "12. Termistor do Hotend",
    },
    "choice.editor_bed_thermistor": {
        "English":   "13. Bed Thermistor",
        "Español":   "13. Termistor de la Cama",
        "Português": "13. Termistor da Mesa",
    },
    # ── Dashboard strings ───────────────────────────────────────
    "dashboard.status_title": {
        "English":   "System Status",
        "Español":   "Estado del Sistema",
        "Português": "Status do Sistema",
    },
    "dashboard.installed": {
        "English":   "Installed",
        "Español":   "Instalado",
        "Português": "Instalado",
    },
    "dashboard.not_found": {
        "English":   "Not found",
        "Español":   "No encontrado",
        "Português": "Não encontrado",
    },
    "dashboard.found": {
        "English":   "Found",
        "Español":   "Encontrado",
        "Português": "Encontrado",
    },
    "dashboard.detected": {
        "English":   "detected",
        "Español":   "detectado",
        "Português": "detectado",
    },
    "dashboard.no_mcu": {
        "English":   "None detected",
        "Español":   "Ninguno detectado",
        "Português": "Nenhum detectado",
    },
    "dashboard.action_prompt": {
        "English":   "What would you like to do?",
        "Español":   "¿Qué desea hacer?",
        "Português": "O que você gostaria de fazer?",
    },
    "dashboard.action_generate": {
        "English":   "Generate new config",
        "Español":   "Generar nueva configuración",
        "Português": "Gerar nova configuração",
    },
    "dashboard.action_reconfig": {
        "English":   "Reconfigure existing printer",
        "Español":   "Reconfigurar impresora existente",
        "Português": "Reconfigurar impressora existente",
    },
    "dashboard.action_manage": {
        "English":   "View component status",
        "Español":   "Ver estado de componentes",
        "Português": "Ver status dos componentes",
    },
    "dashboard.action_quit": {
        "English":   "Quit",
        "Español":   "Salir",
        "Português": "Sair",
    },
    "dashboard.suggestions_header": {
        "English":   "Suggestions",
        "Español":   "Sugerencias",
        "Português": "Sugestões",
    },
    "dashboard.suggest_no_klipper": {
        "English":   "Klipper not found — install it via KACE or install.sh",
        "Español":   "Klipper no encontrado — instálelo con KACE o install.sh",
        "Português": "Klipper não encontrado — instale-o via KACE ou install.sh",
    },
    "dashboard.suggest_no_moonraker": {
        "English":   "Moonraker not found — install it to enable web control",
        "Español":   "Moonraker no encontrado — instálelo para habilitar el control web",
        "Português": "Moonraker não encontrado — instale-o para habilitar o controle web",
    },
    "dashboard.suggest_no_webui": {
        "English":   "No web UI detected — consider installing Mainsail or Fluidd",
        "Español":   "No se detectó interfaz web — considere instalar Mainsail o Fluidd",
        "Português": "Nenhuma interface web detectada — considere instalar Mainsail ou Fluidd",
    },
    "dashboard.suggest_no_cfg": {
        "English":   "No printer.cfg found — run 'Generate new config' to create one",
        "Español":   "No se encontró printer.cfg — ejecute 'Generar nueva configuración'",
        "Português": "Nenhum printer.cfg encontrado — execute 'Gerar nova configuração'",
    },
    "dashboard.manage_header": {
        "English":   "Component Status",
        "Español":   "Estado de Componentes",
        "Português": "Status dos Componentes",
    },
    "dashboard.press_enter": {
        "English":   "Press Enter to return to the menu...",
        "Español":   "Presione Enter para volver al menú...",
        "Português": "Pressione Enter para voltar ao menu...",
    },
    "dashboard.crowsnest": {
        "English":   "Crowsnest",
        "Español":   "Crowsnest",
        "Português": "Crowsnest",
    },
    # ── kace.py messages ────────────────────────────────────────
    "kace.cancelled": {
        "English":   "Setup cancelled by user.",
        "Español":   "Configuración cancelada por el usuario.",
        "Português": "Configuração cancelada pelo usuário.",
    },
    "kace.missing_dep": {
        "English":   "Missing dependency: {error}",
        "Español":   "Dependencia faltante: {error}",
        "Português": "Dependência ausente: {error}",
    },
    "kace.missing_dep_hint": {
        "English":   "Run: pip3 install -r requirements.txt --break-system-packages",
        "Español":   "Ejecute: pip3 install -r requirements.txt --break-system-packages",
        "Português": "Execute: pip3 install -r requirements.txt --break-system-packages",
    },
    "kace.skip_firmware": {
        "English":   "Skipping firmware compilation (no MCU designated).",
        "Español":   "Omitiendo compilación de firmware (sin MCU designado).",
        "Português": "Ignorando compilação de firmware (sem MCU designado).",
    },
    "kace.compile_prompt": {
        "English":   "Do you want to automatically compile Klipper firmware for your {mcu}?",
        "Español":   "¿Desea compilar automáticamente el firmware de Klipper para su {mcu}?",
        "Português": "Deseja compilar automaticamente o firmware do Klipper para seu {mcu}?",
    },
    "kace.compiling": {
        "English":   "Rebuilding Klipper firmware for your controller...",
        "Español":   "Recompilando firmware de Klipper para su controlador...",
        "Português": "Recompilando firmware do Klipper para seu controlador...",
    },
    "kace.firmware_success": {
        "English":   "Firmware built locally at {path}",
        "Español":   "Firmware compilado localmente en {path}",
        "Português": "Firmware compilado localmente em {path}",
    },
    "kace.firmware_error": {
        "English":   "Firmware build failed: {message}",
        "Español":   "Error al compilar firmware: {message}",
        "Português": "Falha na compilação do firmware: {message}",
    },
    "kace.deploy_firmware_prompt": {
        "English":   "Select Deployment Method for Firmware (klipper.bin/.uf2/.hex):",
        "Español":   "Seleccione el Método de Despliegue del Firmware (klipper.bin/.uf2/.hex):",
        "Português": "Selecione o Método de Deploy do Firmware (klipper.bin/.uf2/.hex):",
    },
    "kace.deploy_cfg_prompt": {
        "English":   "Select Deployment Method for Configuration (printer.cfg):",
        "Español":   "Seleccione el Método de Despliegue de la Configuración (printer.cfg):",
        "Português": "Selecione o Método de Deploy da Configuração (printer.cfg):",
    },
    "kace.generate_macros_prompt": {
        "English":   "Would you like to generate a starter macros configuration (macros.cfg)?",
        "Español":   "¿Desea generar una configuración de macros iniciales (macros.cfg)?",
        "Português": "Deseja gerar uma configuração de macros iniciais (macros.cfg)?",
    },
    "kace.deploy_none": {
        "English":   "None (Done)",
        "Español":   "Ninguno (Listo)",
        "Português": "Nenhum (Concluído)",
    },
    "kace.deploy_local": {
        "English":   "Local Folder (PC)",
        "Español":   "Carpeta Local (PC)",
        "Português": "Pasta Local (PC)",
    },
    "kace.deploy_usb": {
        "English":   "USB / SD Card",
        "Español":   "USB / Tarjeta SD",
        "Português": "USB / Cartão SD",
    },
    "kace.deploy_ssh": {
        "English":   "SSH (Push to host)",
        "Español":   "SSH (Enviar al host)",
        "Português": "SSH (Enviar ao host)",
    },
    "kace.deploy_avrdude": {
        "English":   "Flash via USB (avrdude)",
        "Español":   "Flashear por USB (avrdude)",
        "Português": "Gravar via USB (avrdude)",
    },
    "kace.deploy_moonraker": {
        "English":   "Moonraker API (push + restart)",
        "Español":   "API Moonraker (enviar + reiniciar)",
        "Português": "API Moonraker (enviar + reiniciar)",
    },
    "kace.ssh_host_prompt": {
        "English":   "Enter SSH Host (e.g. 192.168.1.100):",
        "Español":   "Ingrese el Host SSH (ej. 192.168.1.100):",
        "Português": "Digite o Host SSH (ex. 192.168.1.100):",
    },
    "kace.ssh_user_prompt": {
        "English":   "Enter SSH User (e.g. pi):",
        "Español":   "Ingrese el Usuario SSH (ej. pi):",
        "Português": "Digite o Usuário SSH (ex. pi):",
    },
    "kace.ssh_pass_prompt": {
        "English":   "Enter SSH Password:",
        "Español":   "Ingrese la Contraseña SSH:",
        "Português": "Digite a Senha SSH:",
    },
    "kace.ssh_dest_prompt": {
        "English":   "Enter Destination Path:",
        "Español":   "Ingrese la Ruta de Destino:",
        "Português": "Digite o Caminho de Destino:",
    },
    # ── Moonraker deploy strings ────────────────────────────────
    "moonraker.host_prompt": {
        "English":   "Enter Moonraker host (e.g. 192.168.1.100 or mainsailos.local):",
        "Español":   "Ingrese el host de Moonraker (ej. 192.168.1.100 o mainsailos.local):",
        "Português": "Digite o host do Moonraker (ex. 192.168.1.100 ou mainsailos.local):",
    },
    "moonraker.port_prompt": {
        "English":   "Enter Moonraker port (default: 7125):",
        "Español":   "Ingrese el puerto de Moonraker (por defecto: 7125):",
        "Português": "Digite a porta do Moonraker (padrão: 7125):",
    },
    "moonraker.api_key_prompt": {
        "English":   "Enter Moonraker API key (leave blank if not required):",
        "Español":   "Ingrese la clave API de Moonraker (deje en blanco si no es necesaria):",
        "Português": "Digite a chave de API do Moonraker (deixe em branco se não for necessária):",
    },
    "moonraker.http_warning": {
        "English":   "⚠️  WARNING: You entered an API key, but the connection is using unencrypted plain HTTP. Sending your API key over HTTP can expose it.\n  Are you sure you want to continue?",
        "Español":   "⚠️  ADVERTENCIA: Ingresó una clave API, pero la conexión utiliza HTTP no cifrado. Enviar su clave API por HTTP puede exponerla.\n  ¿Está seguro de que desea continuar?",
        "Português": "⚠️  AVISO: Você inseriu uma chave de API, mas a conexão está usando HTTP comum não criptografado. Enviar sua chave de API via HTTP pode expô-la.\n  Tem certeza de que deseja continuar?",
    },
    "moonraker.http_warning_cancelled": {
        "English":   "Moonraker deployment cancelled for security reasons.",
        "Español":   "Despliegue de Moonraker cancelado por razones de seguridad.",
        "Português": "Deploy do Moonraker cancelado por motivos de segurança.",
    },
    "moonraker.connecting": {
        "English":   "Connecting to Moonraker at {host}:{port}...",
        "Español":   "Conectando a Moonraker en {host}:{port}...",
        "Português": "Conectando ao Moonraker em {host}:{port}...",
    },
    "moonraker.connected": {
        "English":   "Connected — {version}",
        "Español":   "Conectado — {version}",
        "Português": "Conectado — {version}",
    },
    "moonraker.unreachable": {
        "English":   "Moonraker not reachable at {host}:{port} — {error}",
        "Español":   "Moonraker no accesible en {host}:{port} — {error}",
        "Português": "Moonraker inacessível em {host}:{port} — {error}",
    },
    "moonraker.uploading": {
        "English":   "Uploading printer.cfg to Moonraker...",
        "Español":   "Subiendo printer.cfg a Moonraker...",
        "Português": "Enviando printer.cfg para o Moonraker...",
    },
    "moonraker.upload_ok": {
        "English":   "printer.cfg uploaded successfully.",
        "Español":   "printer.cfg subido exitosamente.",
        "Português": "printer.cfg enviado com sucesso.",
    },
    "moonraker.upload_fail": {
        "English":   "Upload failed: {error}",
        "Español":   "Error al subir el archivo: {error}",
        "Português": "Falha no envio: {error}",
    },
    "moonraker.restart_prompt": {
        "English":   "Restart Klipper to apply the new configuration?",
        "Español":   "¿Reiniciar Klipper para aplicar la nueva configuración?",
        "Português": "Reiniciar o Klipper para aplicar a nova configuração?",
    },
    "moonraker.restart_firmware": {
        "English":   "FIRMWARE_RESTART (reload config, recommended)",
        "Español":   "FIRMWARE_RESTART (recargar config, recomendado)",
        "Português": "FIRMWARE_RESTART (recarregar config, recomendado)",
    },
    "moonraker.restart_service": {
        "English":   "SERVICE_RESTART (full Klipper service restart)",
        "Español":   "SERVICE_RESTART (reinicio completo del servicio Klipper)",
        "Português": "SERVICE_RESTART (reinício completo do serviço Klipper)",
    },
    "moonraker.restart_skip": {
        "English":   "Skip restart",
        "Español":   "Omitir reinicio",
        "Português": "Pular reinício",
    },
    "moonraker.restart_ok": {
        "English":   "Klipper restart issued successfully.",
        "Español":   "Reinicio de Klipper enviado exitosamente.",
        "Português": "Reinício do Klipper emitido com sucesso.",
    },
    "moonraker.restart_fail": {
        "English":   "Restart command failed: {error}",
        "Español":   "Error al enviar el comando de reinicio: {error}",
        "Português": "Falha no comando de reinício: {error}",
    },
    "moonraker.fallback_ssh": {
        "English":   "Would you like to fall back to SSH deployment instead?",
        "Español":   "¿Desea usar el despliegue por SSH en su lugar?",
        "Português": "Deseja usar o deploy por SSH como alternativa?",
    },
    "kace.fetching_cfg": {
        "English":   "Fetching configuration for {board}...",
        "Español":   "Obteniendo configuración para {board}...",
        "Português": "Obtendo configuração para {board}...",
    },
    "kace.fetching_cfg_done": {
        "English":   "Fetching configuration for {board}... Done!",
        "Español":   "Obteniendo configuración para {board}... ¡Listo!",
        "Português": "Obtendo configuração para {board}... Concluído!",
    },
    "kace.generating_cfg": {
        "English":   "Generating printer.cfg...",
        "Español":   "Generando printer.cfg...",
        "Português": "Gerando printer.cfg...",
    },
    "kace.generating_cfg_done": {
        "English":   "Generating printer.cfg... Done!",
        "Español":   "Generando printer.cfg... ¡Listo!",
        "Português": "Gerando printer.cfg... Concluído!",
    },
    "kace.cfg_success": {
        "English":   "printer.cfg generated successfully at {path}",
        "Español":   "printer.cfg generado exitosamente en {path}",
        "Português": "printer.cfg gerado com sucesso em {path}",
    },
    "kace.abort_missing_pins": {
        "English":   "Setup aborted. Missing pins for Z motors.",
        "Español":   "Configuración abortada. Pines faltantes para motores Z.",
        "Português": "Configuração abortada. Pinos ausentes para motores Z.",
    },
    "kace.abort_valid_pins": {
        "English":   "Error: Valid pins are required to proceed. Aborting.",
        "Español":   "Error: Se requieren pines válidos para continuar. Abortando.",
        "Português": "Erro: Pinos válidos são necessários para continuar. Abortando.",
    },
    "kace.abort_no_uart": {
        "English":   "Error: {mode} pin is critically required. Aborting.",
        "Español":   "Error: El pin {mode} es imprescindible. Abortando.",
        "Português": "Erro: O pino {mode} é obligatorio. Abortando.",
    },
    "kace.abort_no_tmc_map": {
        "English":   "Error: No {mode} pin mapping found on this board for {driver}.",
        "Español":   "Error: No se encontró mapeo de pin {mode} en esta placa para {driver}.",
        "Português": "Erro: Nenhum mapeamento de pino {mode} encontrado nesta placa para {driver}.",
    },
    "kace.abort_generation": {
        "English":   "Generation aborted to prevent missing parameters.",
        "Español":   "Generación abortada para evitar parámetros faltantes.",
        "Português": "Geração abortada para evitar parâmetros ausentes.",
    },
    # ── Summary strings ─────────────────────────────────────────
    "summary.title": {
        "English":   "Setup Complete",
        "Español":   "Configuración Completada",
        "Português": "Configuração Concluída",
    },
    "summary.firmware": {
        "English":   "Firmware:",
        "Español":   "Firmware:",
        "Português": "Firmware:",
    },
    "summary.config": {
        "English":   "Config:  ",
        "Español":   "Config:  ",
        "Português": "Config:  ",
    },
    "summary.generation_details": {
        "English":   "Generation Details",
        "Español":   "Detalles de Generación",
        "Português": "Detalhes de Geração",
    },
    "summary.printer_profile": {
        "English":   "Printer Profile:",
        "Español":   "Perfil de Impresora:",
        "Português": "Perfil de Impressora:",
    },
    "summary.board_config": {
        "English":   "Board Config:",
        "Español":   "Config. de Placa:",
        "Português": "Config. de Placa:",
    },
    "summary.kinematics": {
        "English":   "Kinematics:",
        "Español":   "Cinemática:",
        "Português": "Cinemática:",
    },
    "summary.hotend_thermistor": {
        "English":   "Hotend Thermistor:",
        "Español":   "Termistor del Hotend:",
        "Português": "Termistor do Hotend:",
    },
    "summary.bed_thermistor": {
        "English":   "Bed Thermistor:",
        "Español":   "Termistor de la Cama:",
        "Português": "Termistor da Mesa:",
    },
    "summary.next_steps": {
        "English":   "Next Steps:",
        "Español":   "Próximos pasos:",
        "Português": "Próximos passos:",
    },
    "summary.step1": {
        "English":   "Flash firmware to your board",
        "Español":   "Flashee el firmware en su placa",
        "Português": "Grave o firmware na sua placa",
    },
    "summary.step2": {
        "English":   "Upload printer.cfg to Klipper",
        "Español":   "Suba printer.cfg a Klipper",
        "Português": "Faça upload do printer.cfg para o Klipper",
    },
    "summary.step3": {
        "English":   "Restart Klipper",
        "Español":   "Reinicie Klipper",
        "Português": "Reinicie o Klipper",
    },
    "summary.board": {
        "English":   "Board:",
        "Español":   "Placa:",
        "Português": "Placa:",
    },
    "summary.mcu": {
        "English":   "MCU:",
        "Español":   "MCU:",
        "Português": "MCU:",
    },
    "summary.build_volume": {
        "English":   "Build Volume:",
        "Español":   "Volumen de construcción:",
        "Português": "Volume de impressão:",
    },
    "summary.probe": {
        "English":   "Probe:",
        "Español":   "Sensor (Probe):",
        "Português": "Sensor (Probe):",
    },
    "summary.probe_offsets": {
        "English":   "Probe Offsets:",
        "Español":   "Desplazamientos del Sensor:",
        "Português": "Deslocamentos do Sensor:",
    },
    "summary.driver_type": {
        "English":   "Driver Type:",
        "Español":   "Tipo de Driver:",
        "Português": "Tipo de Driver:",
    },
    "summary.driver_mode": {
        "English":   "Driver Mode:",
        "Español":   "Modo del Driver:",
        "Português": "Modo do Driver:",
    },
    "summary.display": {
        "English":   "Display:",
        "Español":   "Pantalla:",
        "Português": "Display:",
    },
    "summary.web_interface": {
        "English":   "Web Interface:",
        "Español":   "Interfaz Web:",
        "Português": "Interface Web:",
    },
    "summary.printable_bed": {
        "English":   "Printable Bed Area:",
        "Español":   "Área de cama imprimible:",
        "Português": "Área da mesa imprimível:",
    },
    "summary.nozzle_reachable": {
        "English":   "Nozzle Reachable:",
        "Español":   "Límite físico de boquilla:",
        "Português": "Alcance físico do bico:",
    },
    "summary.probeable_bed": {
        "English":   "Probeable Bed Area:",
        "Español":   "Área de cama medible:",
        "Português": "Área da mesa mensurável:",
    },
    "summary.homed_origin": {
        "English":   "Homed Origin:",
        "Español":   "Origen de Homing:",
        "Português": "Origem do Homing:",
    },
    "summary.generated_files": {
        "English":   "Generated Files:",
        "Español":   "Archivos Generados:",
        "Português": "Arquivos Gerados:",
    },
    "summary.happy_printing": {
        "English":   "Configuration completed successfully, HAPPY PRINTING!",
        "Español":   "Configuración completada exitosamente, ¡FELIZ IMPRESIÓN!",
        "Português": "Configuração concluída com sucesso, BOAS IMPRESSÕES!",
    },
    # ── builder.py strings ──────────────────────────────────────
    "builder.summary_title": {
        "English":   "🛠  Klipper Firmware Target Summary",
        "Español":   "🛠  Resumen de Destino del Firmware de Klipper",
        "Português": "🛠  Resumo do Alvo do Firmware do Klipper",
    },
    "builder.architecture": {
        "English":   "Architecture",
        "Español":   "Arquitectura",
        "Português": "Arquitetura",
    },
    "builder.processor": {
        "English":   "Processor Model",
        "Español":   "Modelo de Procesador",
        "Português": "Modelo do Processador",
    },
    "builder.bootloader": {
        "English":   "Bootloader Offset",
        "Español":   "Offset del Bootloader",
        "Português": "Offset do Bootloader",
    },
    "builder.comm_interface": {
        "English":   "Communication Interface",
        "Español":   "Interfaz de Comunicación",
        "Português": "Interface de Comunicação",
    },
    "builder.clock": {
        "English":   "Clock Frequency",
        "Español":   "Frecuencia de Reloj",
        "Português": "Frequência de Clock",
    },
    "builder.usb_path": {
        "English":   "USB IDs / Serial Path",
        "Español":   "IDs USB / Ruta Serial",
        "Português": "IDs USB / Caminho Serial",
    },
    "builder.not_detected": {
        "English":   "Not Detected",
        "Español":   "No Detectado",
        "Português": "Não Detectado",
    },
    "builder.config_correct": {
        "English":   "Is this configuration correct? (Use arrow keys)",
        "Español":   "¿Es correcta esta configuración? (Use las flechas)",
        "Português": "Esta configuração está correta? (Use as setas)",
    },
    "builder.compile_now": {
        "English":   "🚀  Compile Firmware Now",
        "Español":   "🚀  Compilar Firmware Ahora",
        "Português": "🚀  Compilar Firmware Agora",
    },
    "builder.edit_arch": {
        "English":   "🔧  Edit Architecture",
        "Español":   "🔧  Editar Arquitectura",
        "Português": "🔧  Editar Arquitetura",
    },
    "builder.edit_proc": {
        "English":   "🔧  Edit Processor Model",
        "Español":   "🔧  Editar Modelo de Procesador",
        "Português": "🔧  Editar Modelo do Processador",
    },
    "builder.edit_boot": {
        "English":   "🔧  Edit Bootloader Offset",
        "Español":   "🔧  Editar Offset del Bootloader",
        "Português": "🔧  Editar Offset do Bootloader",
    },
    "builder.edit_comm": {
        "English":   "🔧  Edit Communication Interface",
        "Español":   "🔧  Editar Interfaz de Comunicación",
        "Português": "🔧  Editar Interface de Comunicação",
    },
    "builder.edit_clock": {
        "English":   "🔧  Edit Clock Frequency",
        "Español":   "🔧  Editar Frecuencia de Reloj",
        "Português": "🔧  Editar Frequência de Clock",
    },
    "builder.abort": {
        "English":   "❌  Abort",
        "Español":   "❌  Abortar",
        "Português": "❌  Abortar",
    },
    "builder.boot_no": {
        "English":   "No bootloader",
        "Español":   "Sin bootloader",
        "Português": "Sem bootloader",
    },
    "builder.boot_8k": {
        "English":   "8KiB bootloader",
        "Español":   "Bootloader de 8KiB",
        "Português": "Bootloader de 8KiB",
    },
    "builder.boot_16k": {
        "English":   "16KiB bootloader",
        "Español":   "Bootloader de 16KiB",
        "Português": "Bootloader de 16KiB",
    },
    "builder.boot_28k": {
        "English":   "28KiB bootloader",
        "Español":   "Bootloader de 28KiB",
        "Português": "Bootloader de 28KiB",
    },
    "builder.boot_32k": {
        "English":   "32KiB bootloader",
        "Español":   "Bootloader de 32KiB",
        "Português": "Bootloader de 32KiB",
    },
    "builder.boot_64k": {
        "English":   "64KiB bootloader",
        "Español":   "Bootloader de 64KiB",
        "Português": "Bootloader de 64KiB",
    },
    "builder.boot_128k": {
        "English":   "128KiB bootloader",
        "Español":   "Bootloader de 128KiB",
        "Português": "Bootloader de 128KiB",
    },
    "builder.enter_arch": {
        "English":   "Enter Kconfig Architecture (e.g. stm32, lpc176x):",
        "Español":   "Ingrese la Arquitectura de Kconfig (ej. stm32, lpc176x):",
        "Português": "Digite a Arquitetura do Kconfig (ex. stm32, lpc176x):",
    },
    "builder.enter_proc": {
        "English":   "Enter Processor Model (e.g. stm32f446):",
        "Español":   "Ingrese el Modelo del Procesador (ej. stm32f446):",
        "Português": "Digite o Modelo do Processador (ex. stm32f446):",
    },
    "builder.select_boot": {
        "English":   "Select Bootloader Offset:",
        "Español":   "Seleccione el Offset del Bootloader:",
        "Português": "Selecione o Offset do Bootloader:",
    },
    "builder.enter_manual": {
        "English":   "Enter manually",
        "Español":   "Ingresar manualmente",
        "Português": "Inserir manualmente",
    },
    "builder.enter_hex": {
        "English":   "Enter HEX offset (e.g. 0x8000):",
        "Español":   "Ingrese el offset HEX (ej. 0x8000):",
        "Português": "Digite o offset HEX (ex. 0x8000):",
    },
    "builder.select_interface": {
        "English":   "Select Interface:",
        "Español":   "Seleccione la Interfaz:",
        "Português": "Selecione a Interface:",
    },
    "builder.enter_clock": {
        "English":   "Enter Clock Frequency in Hz (e.g. 120000000):",
        "Español":   "Ingrese la Frecuencia de Reloj en Hz (ej. 120000000):",
        "Português": "Digite a Frequência de Clock em Hz (ex. 120000000):",
    },
    "builder.derivation_failed": {
        "English":   "Configuration derivation failed: {error}",
        "Español":   "La derivación de la configuración falló: {error}",
        "Português": "A derivação da configuração falhou: {error}",
    },
    "builder.compilation_aborted": {
        "English":   "Compilation aborted by user.",
        "Español":   "Compilación abortada por el usuario.",
        "Português": "Compilação abortada pelo usuário.",
    },
    "builder.no_binary": {
        "English":   "Firmware compiled, but no recognized output file (klipper.bin/.uf2/.elf.hex) found.",
        "Español":   "Firmware compilado, pero no se encontró ningún archivo de salida reconocido (klipper.bin/.uf2/.elf.hex).",
        "Português": "Firmware compilado, mas nenhum arquivo de saída reconhecido (klipper.bin/.uf2/.elf.hex) foi encontrado.",
    },
    "builder.make_error": {
        "English":   "Failed to compile firmware (Make error {code}):\n{error}",
        "Español":   "Error al compilar el firmware (Error de Make {code}):\n{error}",
        "Português": "Falha ao compilar o firmware (Erro do Make {code}):\n{error}",
    },
    "builder.make_not_found": {
        "English":   "Failed to compile firmware: 'make' command not found. build-essential package required.",
        "Español":   "Error al compilar el firmware: comando 'make' no encontrado. Se requiere el paquete build-essential.",
        "Português": "Falha ao compilar o firmware: comando 'make' não encontrado. Pacote build-essential necessário.",
    },
    "builder.unexpected_error": {
        "English":   "An unexpected error occurred during build: {error}",
        "Español":   "Ocurrió un error inesperado durante la compilación: {error}",
        "Português": "Ocorreu um erro inesperado durante a compilação: {error}",
    },
    # ── Macros strings ──────────────────────────────────────────
    "macro.pid_hotend.desc": {
        "English":   "PID Calibration for the hotend",
        "Español":   "Calibración PID para el hotend",
        "Português": "Calibração PID para o hotend",
    },
    "macro.pid_bed.desc": {
        "English":   "PID Calibration for the bed",
        "Español":   "Calibración PID para la cama",
        "Português": "Calibração PID para a mesa",
    },
    "macro.test_movement.desc": {
        "English":   "Test X and Y movement",
        "Español":   "Probar el movimiento en X e Y",
        "Português": "Testar o movimento em X e Y",
    },
    "macro.test_extruder.desc": {
        "English":   "Test extruder movement (hotend must be hot)",
        "Español":   "Probar el movimiento del extrusor (el hotend debe estar caliente)",
        "Português": "Testar o movimento da extrusora (o hotend deve estar quente)",
    },
    "macro.preheat_pla.desc": {
        "English":   "Preheat for PLA",
        "Español":   "Precalentar para PLA",
        "Português": "Preaquecer para PLA",
    },
    "macro.preheat_petg.desc": {
        "English":   "Preheat for PETG",
        "Español":   "Precalentar para PETG",
        "Português": "Preaquecer para PETG",
    },
    "macro.home_and_center.desc": {
        "English":   "Home all axes and center the toolhead",
        "Español":   "Hacer home en todos los ejes y centrar el cabezal",
        "Português": "Fazer home em todos os eixos e centralizar o cabeçote",
    },
    "macro.park_head.desc": {
        "English":   "Park the toolhead",
        "Español":   "Estacionar el cabezal",
        "Português": "Estacionar o cabeçote",
    },
    "macro.load_filament.desc": {
        "English":   "Load filament",
        "Español":   "Cargar filamento",
        "Português": "Carregar filamento",
    },
    "macro.unload_filament.desc": {
        "English":   "Unload filament",
        "Español":   "Descargar filamento",
        "Português": "Descarregar filamento",
    },
    "macro.print_start.desc": {
        "English":   "Start print procedure",
        "Español":   "Iniciar procedimiento de impresión",
        "Português": "Iniciar procedimento de impressão",
    },
    "macro.print_end.desc": {
        "English":   "End print procedure",
        "Español":   "Finalizar procedimiento de impresión",
        "Português": "Finalizar procedimento de impressão",
    },
    # ── Profile summary strings ──────────────────────────────────
    "profile.detected_header": {
        "English":   "Detected profile:",
        "Español":   "Perfil detectado:",
        "Português": "Perfil detectado:",
    },
    "profile.build_volume": {
        "English":   "Build volume",
        "Español":   "Volumen de impresión",
        "Português": "Volume de impressão",
    },
    "profile.kinematics": {
        "English":   "Kinematics",
        "Español":   "Cinemática",
        "Português": "Cinemática",
    },
    "profile.hotend_thermistor": {
        "English":   "Hotend thermistor",
        "Español":   "Termistor del hotend",
        "Português": "Termistor do hotend",
    },
    "profile.bed_thermistor": {
        "English":   "Bed thermistor",
        "Español":   "Termistor de la cama",
        "Português": "Termistor da mesa",
    },
    "profile.comment_x_limits": {
        "English":   "X axis travel limits and homing position",
        "Español":   "límites de recorrido y posición de homing en X",
        "Português": "limites de curso e posição de homing em X",
    },
    "profile.comment_y_limits": {
        "English":   "Y axis travel limits and homing position",
        "Español":   "límites de recorrido y posición de homing en Y",
        "Português": "limites de curso e posição de homing em Y",
    },
    "profile.comment_z_limits": {
        "English":   "Z axis travel limits and homing position",
        "Español":   "límites de recorrido y posición de homing en Z",
        "Português": "limites de curso e posição de homing em Z",
    },
    "profile.comment_probe_offsets": {
        "English":   "probe distance from nozzle in X, Y, Z",
        "Español":   "distancia del sensor a la boquilla en X, Y, Z",
        "Português": "distância do sensor ao bico em X, Y, Z",
    },
    "profile.comment_kinematics": {
        "English":   "printer kinematics model",
        "Español":   "modelo cinemático de la impresora",
        "Português": "modelo cinemático da impressora",
    },
    "profile.comment_position_min_x": {
        "English":   "minimum position travel in X",
        "Español":   "recorrido mínimo de posición en X",
        "Português": "curso mínimo de posição em X",
    },
    "profile.comment_position_max_x": {
        "English":   "maximum position travel in X",
        "Español":   "recorrido máximo de posición en X",
        "Português": "curso máximo de posição em X",
    },
    "profile.comment_position_endstop_x": {
        "English":   "X homing trigger position",
        "Español":   "posición de activación de homing en X",
        "Português": "posição de ativação do homing em X",
    },
    "profile.comment_position_min_y": {
        "English":   "minimum position travel in Y",
        "Español":   "recorrido mínimo de posición en Y",
        "Português": "curso mínimo de posição em Y",
    },
    "profile.comment_position_max_y": {
        "English":   "maximum position travel in Y",
        "Español":   "recorrido máximo de posición en Y",
        "Português": "curso máximo de posición em Y",
    },
    "profile.comment_position_endstop_y": {
        "English":   "Y homing trigger position",
        "Español":   "posición de activación de homing en Y",
        "Português": "posição de ativação do homing em Y",
    },
    "profile.comment_position_min_z": {
        "English":   "minimum position travel in Z",
        "Español":   "recorrido mínimo de posición en Z",
        "Português": "curso mínimo de posição em Z",
    },
    "profile.comment_position_max_z": {
        "English":   "maximum position travel in Z",
        "Español":   "recorrido máximo de posición en Z",
        "Português": "curso máximo de posición en Z",
    },
    "profile.comment_position_endstop_z": {
        "English":   "Z homing trigger position",
        "Español":   "posición de activación de homing en Z",
        "Português": "posição de ativação do homing em Z",
    },
    "profile.comment_build_volume": {
        "English":   "printable bed travel envelope",
        "Español":   "volumen de recorrido de la cama imprimible",
        "Português": "volume de curso da mesa de impressão",
    },
    "profile.comment_probe_type": {
        "English":   "probe sensor hardware type",
        "Español":   "tipo de hardware del sensor de nivelación",
        "Português": "tipo de hardware do sensor de nivelamento",
    },
    "profile.comment_probe_offset_x": {
        "English":   "probe distance from nozzle in X",
        "Español":   "distancia del sensor a la boquilla en X",
        "Português": "distância do sensor ao bico em X",
    },
    "profile.comment_probe_offset_y": {
        "English":   "probe distance from nozzle in Y",
        "Español":   "distancia del sensor a la boquilla en Y",
        "Português": "distância do sensor ao bico em Y",
    },
    "profile.comment_probe_offset_z": {
        "English":   "probe distance from nozzle in Z",
        "Español":   "distancia del sensor a la boquilla en Z",
        "Português": "distância do sensor ao bico em Z",
    },
    "profile.comment_driver_type": {
        "English":   "integrated stepper driver type",
        "Español":   "tipo de controlador de motor integrado",
        "Português": "tipo de driver de motor integrado",
    },
    "profile.comment_driver_mode": {
        "English":   "stepper driver communication mode",
        "Español":   "modo de comunicación del controlador de motor",
        "Português": "modo de comunicação do driver de motor",
    },
    "profile.comment_hotend_therm": {
        "English":   "hotend temperature sensor type",
        "Español":   "tipo de sensor de temperatura del hotend",
        "Português": "tipo de sensor de temperatura do hotend",
    },
    "profile.comment_bed_therm": {
        "English":   "heated bed temperature sensor type",
        "Español":   "tipo de sensor de temperatura de la cama caliente",
        "Português": "tipo de sensor de temperatura da mesa aquecida",
    },
    "profile.comment_display": {
        "English":   "LCD display interface type",
        "Español":   "tipo de interfaz de pantalla LCD",
        "Português": "tipo de interface da tela LCD",
    },
    # ── Display Compatibility Layer strings ─────────────────────
    "display.class_fully_compatible": {
        "English":   "Fully Compatible",
        "Español":   "Totalmente compatible",
        "Português": "Totalmente compatível",
    },
    "display.class_compatible_with_adapter": {
        "English":   "Compatible with Adapter",
        "Español":   "Compatible con adaptador",
        "Português": "Compatível com adaptador",
    },
    "display.class_compatible_with_adapter_mod": {
        "English":   "Compatible with Adapter/Modification",
        "Español":   "Compatible con adaptador/modificación",
        "Português": "Compatível com adaptador/modificação",
    },
    "display.class_experimental": {
        "English":   "Experimental",
        "Español":   "Experimental",
        "Português": "Experimental",
    },
    "display.class_unsafe": {
        "English":   "UNSAFE / HIGH RISK",
        "Español":   "INSEGURO / ALTO RIESGO",
        "Português": "INSEGURO / ALTO RISCO",
    },
    "display.warning_header": {
        "English":   "⚠️  Display Compatibility Warning",
        "Español":   "⚠️  Advertencia de Compatibilidad de Pantalla",
        "Português": "⚠️  Aviso de Compatibilidade de Display",
    },
    "display.status_supported": {
        "English":   "🟢 SUPPORTED",
        "Español":   "🟢 COMPATIBLE",
        "Português": "🟢 SUPORTADO",
    },
    "display.status_partial": {
        "English":   "🟡 PARTIAL SUPPORT",
        "Español":   "🟡 SOPORTE PARCIAL",
        "Português": "🟡 SUPORTE PARCIAL",
    },
    "display.status_unsupported": {
        "English":   "🔴 UNSUPPORTED",
        "Español":   "🔴 NO COMPATIBLE",
        "Português": "🔴 NÃO SUPORTADO",
    },
    "display.status_untested": {
        "English":   "⬜ UNTESTED",
        "Español":   "⬜ SIN PRUEBAS",
        "Português": "⬜ NÃO TESTADO",
    },
    "display.recommendation_disconnect": {
        "English":   "Recommendation: Physically disconnect the display from the mainboard",
        "Español":   "Recomendación: Desconecte físicamente la pantalla de la placa principal",
        "Português": "Recomendação: Desconecte fisicamente o display da placa principal",
    },
    "display.recommendation_optional": {
        "English":   "Recommendation: Display may have limited functionality — consider using the web UI instead",
        "Español":   "Recomendación: La pantalla puede tener funcionalidad limitada — considere usar la interfaz web",
        "Português": "Recomendação: O display pode ter funcionalidade limitada — considere usar a interface web",
    },
    "display.oem_explanation": {
        "English":   "OEM printer touchscreens are often designed specifically for Marlin firmware and may not function correctly under Klipper without additional community modifications.",
        "Español":   "Las pantallas táctiles de impresoras OEM generalmente están diseñadas específicamente para el firmware Marlin y pueden no funcionar correctamente en Klipper sin modificaciones adicionales de la comunidad.",
        "Português": "As telas touchscreen de impressoras OEM são frequentemente projetadas especificamente para o firmware Marlin e podem não funcionar corretamente com o Klipper sem modificações adicionais da comunidade.",
    },
    "display.web_ui_hint": {
        "English":   "💡 Mainsail and Fluidd provide full printer control from any phone, tablet, or PC — no physical screen required.",
        "Español":   "💡 Mainsail y Fluidd ofrecen control total de la impresora desde cualquier teléfono, tablet o PC — sin necesidad de pantalla física.",
        "Português": "💡 Mainsail e Fluidd oferecem controle total da impressora em qualquer telefone, tablet ou PC — sem necessidade de tela física.",
    },
    "display.docs_hint": {
        "English":   "📖 For full details, see: docs/en/DISPLAYS.md",
        "Español":   "📖 Para más detalles, consulte: docs/es/DISPLAYS.md",
        "Português": "📖 Para mais detalhes, consulte: docs/pt/DISPLAYS.md",
    },
    "display.continue_prompt": {
        "English":   "This printer may have display compatibility issues. Continue with configuration generation?",
        "Español":   "Esta impresora puede tener problemas de compatibilidad de pantalla. ¿Continuar con la generación de la configuración?",
        "Português": "Esta impressora pode ter problemas de compatibilidade de display. Continuar com a geração da configuração?",
    },
    "display.section_label": {
        "English":   "Detected section",
        "Español":   "Sección detectada",
        "Português": "Seção detectada",
    },
    # ── Display Setup Wizard strings ────────────────────────────
    "wizard.display_use_prompt": {
        "English":   "Do you want to use a display?",
        "Español":   "¿Desea usar una pantalla?",
        "Português": "Deseja usar um display?",
    },
    "wizard.display_category_prompt": {
        "English":   "Select a display from the recommended list:",
        "Español":   "Seleccione un display de la lista recomendada:",
        "Português": "Selecione um display da lista recomendada:",
    },
    "wizard.display_recommended_header": {
        "English":   "Recommended displays for your board:",
        "Español":   "Pantallas recomendadas para su placa:",
        "Português": "Displays recomendados para sua placa:",
    },
    "wizard.display_manual_prompt": {
        "English":   "Search display by name or section key (type to filter):",
        "Español":   "Buscar pantalla por nombre o clave de sección (escriba para filtrar):",
        "Português": "Buscar display por nome ou chave de seção (digite para filtrar):",
    },
    "wizard.display_no_display": {
        "English":   "No display (use web interface only)",
        "Español":   "Sin pantalla (usar solo interfaz web)",
        "Português": "Sem display (usar apenas interface web)",
    },
    "wizard.display_manual_mode": {
        "English":   "Manual Search / Advanced Selection",
        "Español":   "Búsqueda manual / Selección avanzada",
        "Português": "Busca manual / Seleção avançada",
    },
    "wizard.display_risk_header": {
        "English":   "Hardware Risk Analysis",
        "Español":   "Análisis de Riesgos de Hardware",
        "Português": "Análise de Riscos de Hardware",
    },
    "wizard.display_confirm_experimental": {
        "English":   "This display requires modifications or has uncertain compatibility. Continue anyway?",
        "Español":   "Esta pantalla requiere modificaciones o tiene compatibilidad incierta. ¿Continuar de todos modos?",
        "Português": "Este display requer modificações ou tem compatibilidade incerta. Continuar mesmo assim?",
    },
    "wizard.display_confirm_unsafe": {
        "English":   "⚠️  Type \"I accept the risk\" to proceed with this unsafe combination, or press Enter to go back:",
        "Español":   "⚠️  Escriba \"I accept the risk\" para continuar con esta combinación insegura, o presione Enter para volver:",
        "Português": "⚠️  Digite \"I accept the risk\" para prosseguir com esta combinação insegura, ou pressione Enter para voltar:",
    },
    "wizard.display_voltage_ok": {
        "English":   "Voltage: Compatible ✅",
        "Español":   "Voltaje: Compatible ✅",
        "Português": "Tensão: Compatível ✅",
    },
    "wizard.display_voltage_warn": {
        "English":   "Voltage: Requires level shifter 🟡",
        "Español":   "Voltaje: Requiere convertidor de nivel 🟡",
        "Português": "Tensão: Requer conversor de nível 🟡",
    },
    "wizard.display_voltage_danger": {
        "English":   "Voltage: INCOMPATIBLE — damage risk 🔴",
        "Español":   "Voltaje: INCOMPATIBLE — riesgo de daño 🔴",
        "Português": "Tensão: INCOMPATÍVEL — risco de dano 🔴",
    },
    "wizard.display_interface_ok": {
        "English":   "Interface: Available on board ✅",
        "Español":   "Interfaz: Disponible en la placa ✅",
        "Português": "Interface: Disponível na placa ✅",
    },
    "wizard.display_interface_adapter": {
        "English":   "Interface: Requires adapter 🟡",
        "Español":   "Interfaz: Requiere adaptador 🟡",
        "Português": "Interface: Requer adaptador 🟡",
    },
    "wizard.display_confidence": {
        "English":   "Confidence: {level}",
        "Español":   "Confianza: {level}",
        "Português": "Confiança: {level}",
    },
    "wizard.phase_label": {
        "English":   "Phase",
        "Español":   "Fase",
        "Português": "Fase",
    },
    "wizard.step_label": {
        "English":   "Step",
        "Español":   "Paso",
        "Português": "Passo",
    },
    "wizard.of_label": {
        "English":   "of",
        "Español":   "de",
        "Português": "de",
    },
    # ── Phase names ───────────────────────────────────────────
    "wizard.phase.hardware": {
        "English":   "Hardware",
        "Español":   "Hardware",
        "Português": "Hardware",
    },
    "wizard.phase.motion": {
        "English":   "Motion",
        "Español":   "Movimiento",
        "Português": "Movimento",
    },
    "wizard.phase.sensors": {
        "English":   "Sensors",
        "Español":   "Sensores",
        "Português": "Sensores",
    },
    "wizard.phase.software": {
        "English":   "Software",
        "Español":   "Software",
        "Português": "Software",
    },
    "wizard.phase.complete": {
        "English":   "✔ Phase complete: {phase}",
        "Español":   "✔ Fase completada: {phase}",
        "Português": "✔ Fase concluída: {phase}",
    },
    # ── Wizard step headers and context hints ──────────────────
    "wizard.step.board.header": {
        "English":   "Motherboard Selection",
        "Español":   "Selección de Placa Base",
        "Português": "Seleção da Placa-Mãe",
    },
    "wizard.step.board.hint": {
        "English":   "The motherboard defines the microcontroller unit (MCU) and available socket/pin configurations.",
        "Español":   "La placa base define la unidad de microcontrolador (MCU) y las configuraciones de pines/sockets disponibles.",
        "Português": "A placa-mãe define a unidade de microcontrolador (MCU) e as configurações de pinos/soquetes disponíveis.",
    },
    "wizard.step.fan_assignment.header": {
        "English":   "Cooling Fan Pins Assignment",
        "Español":   "Asignación de Pines de Ventiladores",
        "Português": "Atribuição de Pinos de Ventiladores",
    },
    "wizard.step.fan_assignment.hint": {
        "English":   "Define cooling fan output pins to prevent extruder heat creep and ensure proper part cooling.",
        "Español":   "Defina los pines de salida de los ventiladores para evitar el calor en el extrusor y garantizar el enfriamiento de la pieza.",
        "Português": "Defina os pinos de saída dos ventiladores para evitar refluxo de calor no extrusor e garantir o resfriamento da peça.",
    },
    "wizard.step.z_motors.header": {
        "English":   "Z Axis Motors Count",
        "Español":   "Cantidad de Motores del Eje Z",
        "Português": "Quantidade de Motores do Eixo Z",
    },
    "wizard.step.z_motors.hint": {
        "English":   "Selecting the correct number of Z-axis motors allows independent control and auto-leveling adjustment.",
        "Español":   "Seleccionar la cantidad correcta de motores del eje Z permite el control independiente y el ajuste de autonivelación.",
        "Português": "Selecionar a quantidade correta de motores do eixo Z permite controle independente e ajuste de nivelamento automático.",
    },
    "wizard.step.z_socket_assignment.header": {
        "English":   "Z Driver Socket Assignment",
        "Español":   "Asignación de Sockets de Driver Z",
        "Português": "Atribuição de Soquetes de Driver Z",
    },
    "wizard.step.z_socket_assignment.hint": {
        "English":   "Assign physical driver sockets on the motherboard for multi-motor Z-axis layouts.",
        "Español":   "Asigne sockets físicos de driver en la placa base para diseños de múltiples motores del eje Z.",
        "Português": "Atribua soquetes físicos de driver na placa-mãe para layouts de múltiplos motores do eixo Z.",
    },
    "wizard.step.driver_type.header": {
        "English":   "Stepper Driver Type",
        "Español":   "Tipo de Driver de Motores",
        "Português": "Tipo de Driver de Motores",
    },
    "wizard.step.driver_type.hint": {
        "English":   "Specifying the correct stepper driver type guarantees accurate motor current and step generation.",
        "Español":   "Especificar el tipo correcto de driver garantiza una corriente de motor y generación de pasos precisas.",
        "Português": "Especificar o tipo correto de driver garante corrente de motor e geração de passos precisas.",
    },
    "wizard.step.driver_mode.header": {
        "English":   "Stepper Communication Mode",
        "Español":   "Modo de Comunicación del Driver",
        "Português": "Modo de Comunicação do Driver",
    },
    "wizard.step.driver_mode.hint": {
        "English":   "Choose between Standalone, UART, or SPI to configure active driver current control and diagnostics.",
        "Español":   "Elija entre Standalone, UART o SPI para configurar el control de corriente activo y los diagnósticos del driver.",
        "Português": "Escolha entre Standalone, UART ou SPI para configurar o controle de corrente ativo e os diagnósticos do driver.",
    },
    "wizard.step.printer_profile.header": {
        "English":   "Printer Profile Selection",
        "Español":   "Selección de Perfil de Impresora",
        "Português": "Seleção de Perfil da Impressora",
    },
    "wizard.step.printer_profile.hint": {
        "English":   "Choose a pre-defined printer profile to load recommended kinematic limits and dimensions.",
        "Español":   "Elija un perfil de impresora predefinido para cargar las dimensiones y límites cinemáticos recomendados.",
        "Português": "Escolha um perfil de impressora predefinido para carregar os limites e dimensões cinemáticas recomendados.",
    },
    "wizard.step.profile_review.header": {
        "English":   "Profile Configuration Review",
        "Español":   "Revisión de la Configuración del Perfil",
        "Português": "Revisão da Configuração do Perfil",
    },
    "wizard.step.profile_review.hint": {
        "English":   "Review and customize the loaded printer parameters before continuing with the wizard.",
        "Español":   "Revise y personalice los parámetros de la impresora cargados antes de continuar con el asistente.",
        "Português": "Revise e personalize os parâmetros da impressora carregados antes de continuar com o assistente.",
    },
    "wizard.step.kinematics.header": {
        "English":   "Kinematics Type",
        "Español":   "Tipo de Cinemática",
        "Português": "Tipo de Cinemática",
    },
    "wizard.step.kinematics.hint": {
        "English":   "Kinematics define how motor rotation translates into mechanical printhead positioning.",
        "Español":   "La cinemática define cómo la rotación del motor se traduce en el posicionamiento mecánico del cabezal de impresión.",
        "Português": "A cinemática define como a rotação do motor se traduz no posicionamento mecânico do cabeçote de impressão.",
    },
    "wizard.step.x_volume.header": {
        "English":   "X Axis Build Volume",
        "Español":   "Volumen de Construcción del Eje X",
        "Português": "Volume de Impressão do Eixo X",
    },
    "wizard.step.x_volume.hint": {
        "English":   "The maximum physical travel of the printhead along the horizontal X axis.",
        "Español":   "El recorrido físico máximo del cabezal de impresión a lo largo del eje horizontal X.",
        "Português": "O curso físico máximo do cabeçote de impressão ao longo do eixo horizontal X.",
    },
    "wizard.step.y_volume.header": {
        "English":   "Y Axis Build Volume",
        "Español":   "Volumen de Construcción del Eje Y",
        "Português": "Volume de Impressão do Eixo Y",
    },
    "wizard.step.y_volume.hint": {
        "English":   "The maximum physical travel of the print bed or printhead along the Y axis.",
        "Español":   "El recorrido físico máximo de la cama o cabezal de impresión a lo largo del eje Y.",
        "Português": "O curso físico máximo da mesa ou cabeçote de impressão ao longo do eixo Y.",
    },
    "wizard.step.z_volume.header": {
        "English":   "Z Axis Build Volume",
        "Español":   "Volumen de Construcción del Eje Z",
        "Português": "Volume de Impressão do Eixo Z",
    },
    "wizard.step.z_volume.hint": {
        "English":   "The maximum height the printer can print along the vertical Z axis.",
        "Español":   "La altura máxima que la impresora puede imprimir a lo largo del eje vertical Z.",
        "Português": "A altura máxima que a impressora pode imprimir ao longo do eixo vertical Z.",
    },
    "wizard.step.probe.header": {
        "English":   "Z Probe Type",
        "Español":   "Tipo de Sensor de Nivelación Z",
        "Português": "Tipo de Sensor de Nivelamento Z",
    },
    "wizard.step.probe.hint": {
        "English":   "Choose the sensor type used to automatically measure and align the print bed height.",
        "Español":   "Elija el tipo de sensor utilizado para medir y alinear automáticamente la altura de la cama.",
        "Português": "Escolha o tipo de sensor usado para medir e alinhar automaticamente a altura da mesa.",
    },
    "wizard.step.bltouch_pins.header": {
        "English":   "BLTouch/CR-Touch Pin Assignment",
        "Español":   "Asignación de Pines de BLTouch/CR-Touch",
        "Português": "Atribuição de Pinos do BLTouch/CR-Touch",
    },
    "wizard.step.bltouch_pins.hint": {
        "English":   "Enter the physical control and sensor pins connected to the BLTouch or CR-Touch device.",
        "Español":   "Ingrese los pines físicos de control y sensor conectados al dispositivo BLTouch o CR-Touch.",
        "Português": "Insira os pinos físicos de controle e sensor conectados ao dispositivo BLTouch ou CR-Touch.",
    },
    "wizard.step.probe_offsets.header": {
        "English":   "Probe Offsets",
        "Español":   "Desplazamientos del Sensor (Offsets)",
        "Português": "Deslocamentos do Sensor (Offsets)",
    },
    "wizard.step.probe_offsets.hint": {
        "English":   "Probe offsets define the physical distance in millimeters between the probe sensor and the nozzle tip.",
        "Español":   "Los desplazamientos definen la distancia física en milímetros entre el sensor y la punta de la boquilla.",
        "Português": "Os deslocamentos definem a distância física em milímetros entre o sensor e a ponta do bico.",
    },
    "wizard.step.x_limits.header": {
        "English":   "X Axis Travel Limits",
        "Español":   "Límites de Recorrido del Eje X",
        "Português": "Limites de Curso do Eixo X",
    },
    "wizard.step.x_limits.hint": {
        "English":   "Specify X axis physical travel boundaries (position_min, position_max) and the home endstop trigger coordinate.",
        "Español":   "Especifique los límites físicos de recorrido del eje X (position_min, position_max) y la coordenada de activación del final de carrera.",
        "Português": "Especifique os limites físicos de curso do eixo X (position_min, position_max) e a coordenada do sensor de fim de curso.",
    },
    "wizard.step.y_limits.header": {
        "English":   "Y Axis Travel Limits",
        "Español":   "Límites de Recorrido del Eje Y",
        "Português": "Limites de Curso do Eixo Y",
    },
    "wizard.step.y_limits.hint": {
        "English":   "Specify Y axis physical travel boundaries (position_min, position_max) and the home endstop trigger coordinate.",
        "Español":   "Especifique los límites físicos de recorrido del eje Y (position_min, position_max) y la coordenada de activación del final de carrera.",
        "Português": "Especifique os limites físicos de curso do eixo Y (position_min, position_max) e a coordenada do sensor de fim de curso.",
    },
    "wizard.step.z_limits.header": {
        "English":   "Z Axis Travel Limits",
        "Español":   "Límites de Recorrido del Eje Z",
        "Português": "Limites de Curso do Eixo Z",
    },
    "wizard.step.z_limits.hint": {
        "English":   "Specify Z axis physical travel boundaries (position_min, position_max) and the home endstop trigger coordinate.",
        "Español":   "Especifique los límites físicos de recorrido del eje Z (position_min, position_max) y la coordenada de activación del final de carrera.",
        "Português": "Especifique os limites físicos de curso do eixo Z (position_min, position_max) e a coordenada do sensor de fim de curso.",
    },
    "wizard.x_position_min": {
        "English":   "Enter X position_min (mm) [type '<' to go back]:",
        "Español":   "Ingrese X position_min (mm) [escriba '<' para volver]:",
        "Português": "Digite X position_min (mm) [digite '<' para voltar]:",
    },
    "wizard.x_position_max": {
        "English":   "Enter X position_max (mm) [type '<' to go back]:",
        "Español":   "Ingrese X position_max (mm) [escriba '<' para volver]:",
        "Português": "Digite X position_max (mm) [digite '<' para voltar]:",
    },
    "wizard.x_position_endstop": {
        "English":   "Enter X position_endstop (mm) [type '<' to go back]:",
        "Español":   "Ingrese X position_endstop (mm) [escriba '<' para volver]:",
        "Português": "Digite X position_endstop (mm) [digite '<' para voltar]:",
    },
    "wizard.y_position_min": {
        "English":   "Enter Y position_min (mm) [type '<' to go back]:",
        "Español":   "Ingrese Y position_min (mm) [escriba '<' para volver]:",
        "Português": "Digite Y position_min (mm) [digite '<' para voltar]:",
    },
    "wizard.y_position_max": {
        "English":   "Enter Y position_max (mm) [type '<' to go back]:",
        "Español":   "Ingrese Y position_max (mm) [escriba '<' para volver]:",
        "Português": "Digite Y position_max (mm) [digite '<' para voltar]:",
    },
    "wizard.y_position_endstop": {
        "English":   "Enter Y position_endstop (mm) [type '<' to go back]:",
        "Español":   "Ingrese Y position_endstop (mm) [escriba '<' para volver]:",
        "Português": "Digite Y position_endstop (mm) [digite '<' para voltar]:",
    },
    "wizard.z_position_min": {
        "English":   "Enter Z position_min (mm) [type '<' to go back]:",
        "Español":   "Ingrese Z position_min (mm) [escriba '<' para volver]:",
        "Português": "Digite Z position_min (mm) [digite '<' para voltar]:",
    },
    "wizard.z_position_max": {
        "English":   "Enter Z position_max (mm) [type '<' to go back]:",
        "Español":   "Ingrese Z position_max (mm) [escriba '<' para volver]:",
        "Português": "Digite Z position_max (mm) [digite '<' para voltar]:",
    },
    "wizard.z_position_endstop": {
        "English":   "Enter Z position_endstop (mm) [type '<' to go back]:",
        "Español":   "Ingrese Z position_endstop (mm) [escriba '<' para volver]:",
        "Português": "Digite Z position_endstop (mm) [digite '<' para voltar]:",
    },
    "profile.custom_header": {
        "English":   "Custom printer profile:",
        "Español":   "Perfil de impresora personalizado:",
        "Português": "Perfil da impressora personalizado:",
    },
    "wizard.step.hotend_therm.header": {
        "English":   "Hotend Thermistor Model",
        "Español":   "Modelo de Termistor del Hotend",
        "Português": "Modelo de Termistor do Hotend",
    },
    "wizard.step.hotend_therm.hint": {
        "English":   "Select the hotend sensor model to ensure safe and accurate extrusion temperature readings.",
        "Español":   "Seleccione el modelo de sensor del hotend para garantizar lecturas de temperatura de extrusión seguras y precisas.",
        "Português": "Selecione o modelo do sensor do hotend para garantir leituras de temperatura de extrusão seguras e precisas.",
    },
    "wizard.step.bed_therm.header": {
        "English":   "Bed Thermistor Model",
        "Español":   "Modelo de Termistor de la Cama",
        "Português": "Modelo de Termistor da Mesa",
    },
    "wizard.step.bed_therm.hint": {
        "English":   "Select the heated bed sensor model to ensure safe and accurate bed temperature readings.",
        "Español":   "Seleccione el modelo de sensor de la cama caliente para garantizar lecturas de temperatura seguras y precisas.",
        "Português": "Selecione o modelo do sensor da mesa aquecida para garantir leituras de temperatura seguras e precisas.",
    },
    "wizard.step.display.header": {
        "English":   "Display Controller Setup",
        "Español":   "Configuración del Controlador de Pantalla",
        "Português": "Configuração do Controlador de Tela",
    },
    "wizard.step.display.hint": {
        "English":   "Configure a physical screen attached to the printer for offline status monitoring.",
        "Español":   "Configure una pantalla física conectada a la impresora para el monitoreo de estado fuera de línea.",
        "Português": "Configure uma tela física conectada à impressora para monitoramento de status offline.",
    },
    "wizard.step.web_ui.header": {
        "English":   "Web Interface Selection",
        "Español":   "Selección de Interfaz Web",
        "Português": "Seleção de Interface Web",
    },
    "wizard.step.web_ui.hint": {
        "English":   "Select Mainsail or Fluidd to set up the default macros and configuration includes for web control.",
        "Español":   "Seleccione Mainsail o Fluidd para configurar las macros predeterminadas e includes de configuración para control web.",
        "Português": "Selecione Mainsail ou Fluidd para configurar as macros padrão e includes de configuração para controle web.",
    },
}


def t(key: str, **kwargs) -> str:
    """Look up a UI string by key in the current language.

    Falls back to English if the current language is missing a key,
    then falls back to the key string itself if no entry exists at all.
    Applies str.format(**kwargs) for dynamic substitutions.
    """
    lang = _current_lang
    entry = UI_STRINGS.get(key)
    if entry is None:
        return key.format(**kwargs) if kwargs else key
    text = entry.get(lang) or entry.get("English") or key
    return text.format(**kwargs) if kwargs else text


# ── Comment translation layer (unchanged) ─────────────────────

def translate_comment(comment, lang):
    if lang == "English":
        return comment

    translations = {
        "Serial connection to the printer controller board. Auto-detected by KACE. Verify in /dev/serial/by-id/ if connection fails.": {
            "Español": "Conexión serial a la placa controladora. Auto-detectado por KACE. Verifica en /dev/serial/by-id/ si falla.",
            "Português": "Conexão serial com a placa controladora. Auto-detectado pelo KACE. Verifique em /dev/serial/by-id/ se falhar."
        },
        "Printer kinematics type (cartesian, corexy, delta)": {
            "Español": "Tipo de cinemática de la impresora (cartesiana, corexy, delta)",
            "Português": "Tipo de cinemática da impressora (cartesiana, corexy, delta)"
        },
        "Maximum velocity (in mm/s) of the toolhead": {
            "Español": "Velocidad máxima (en mm/s) del cabezal",
            "Português": "Velocidade máxima (em mm/s) do cabeçote"
        },
        "Maximum acceleration (in mm/s^2) of the toolhead": {
            "Español": "Aceleración máxima (en mm/s^2) del cabezal",
            "Português": "Aceleração máxima (em mm/s^2) do cabeçote"
        },
        "Maximum velocity (in mm/s) of movement along the z axis": {
            "Español": "Velocidad máxima (en mm/s) del movimiento en el eje Z",
            "Português": "Velocidade máxima (em mm/s) de movimento no eixo Z"
        },
        "Maximum acceleration (in mm/s^2) of movement along the z axis": {
            "Español": "Aceleración máxima (en mm/s^2) en el eje Z",
            "Português": "Aceleração máxima (em mm/s^2) no eixo Z"
        },
        "Step pin for the X stepper driver": {
            "Español": "Pin de paso (step) para el motor X",
            "Português": "Pino de passo (step) para o motor X"
        },
        "Direction pin. Add or remove \"!\" to invert motor direction": {
            "Español": "Pin de dirección (dir). Agrega o quita \"!\" para invertir la dirección",
            "Português": "Pino de direção (dir). Adicione ou remova \"!\" para inverter a direção"
        },
        "Enable pin for the stepper driver": {
            "Español": "Pin de habilitación (enable) del motor",
            "Português": "Pino de habilitação (enable) do motor"
        },
        "Number of microsteps per full step": {
            "Español": "Número de micropasos por paso completo",
            "Português": "Número de micropassos por passo completo"
        },
        "Distance in mm the axis travels per full rotation of the motor": {
            "Español": "Distancia en mm que viaja el eje por cada rotación completa del motor",
            "Português": "Distância em mm que o eixo viaja por cada rotação completa do motor"
        },
        "Endstop pin. Add or remove \"!\" to invert logic": {
            "Español": "Pin de fin de carrera. Agrega o quita \"!\" para invertir la lógica",
            "Português": "Pino de fim de curso. Adicione ou remova \"!\" para inverter a lógica"
        },
        "Location of the endstop (usually 0)": {
            "Español": "Ubicación del fin de carrera (generalmente 0)",
            "Português": "Localização do fim de curso (geralmente 0)"
        },
        "Maximum valid X position": {
            "Español": "Posición máxima válida en X",
            "Português": "Posição máxima válida em X"
        },
        "Maximum velocity (in mm/s) of the stepper when homing": {
            "Español": "Velocidad máxima (en mm/s) del motor al hacer homing",
            "Português": "Velocidade máxima (em mm/s) do motor ao fazer homing"
        },
        "Step pin for the Y stepper driver": {
            "Español": "Pin de paso (step) para el motor Y",
            "Português": "Pino de passo (step) para o motor Y"
        },
        "Maximum valid Y position": {
            "Español": "Posición máxima válida en Y",
            "Português": "Posição máxima válida em Y"
        },
        "Step pin for the Z stepper driver": {
            "Español": "Pin de paso (step) para el motor Z",
            "Português": "Pino de passo (step) para o motor Z"
        },
        "Maximum valid Z position": {
            "Español": "Posición máxima válida en Z",
            "Português": "Posição máxima válida em Z"
        },
        "Step pin for the Z1 stepper driver": {
            "Español": "Pin de paso (step) para el motor Z1",
            "Português": "Pino de passo (step) para o motor Z1"
        },
        "Step pin for the extruder driver": {
            "Español": "Pin de paso (step) para el extrusor",
            "Português": "Pino de passo (step) para a extrusora"
        },
        "Pin connected to the hotend heater cartridge": {
            "Español": "Pin conectado al cartucho calentador del hotend",
            "Português": "Pino conectado ao cartucho de aquecimento do hotend"
        },
        "Pin connected to the hotend thermistor": {
            "Español": "Pin conectado al termistor del hotend",
            "Português": "Pino conectado ao termistor do hotend"
        },
        "Distance in mm the filament travels per full rotation of the motor": {
            "Español": "Distancia en mm que el filamento viaja por rotación del motor",
            "Português": "Distância em mm que o filamento viaja por rotação do motor"
        },
        "Diameter of the installed nozzle in mm": {
            "Español": "Diámetro de la boquilla instalada en mm",
            "Português": "Diâmetro do bico instalado em mm"
        },
        "Diameter of the filament being used": {
            "Español": "Diámetro del filamento que se está utilizando",
            "Português": "Diâmetro do filamento sendo utilizado"
        },
        "Type of thermistor used for the hotend": {
            "Español": "Tipo de termistor utilizado para el hotend",
            "Português": "Tipo de termistor utilizado para o hotend"
        },
        "Temperature control algorithm": {
            "Español": "Algoritmo de control de temperatura",
            "Português": "Algoritmo de controle de temperatura"
        },
        "PID proportional gain": {
            "Español": "Ganancia proporcional (PID)",
            "Português": "Ganho proporcional (PID)"
        },
        "PID integral gain": {
            "Español": "Ganancia integral (PID)",
            "Português": "Ganho integral (PID)"
        },
        "PID derivative gain": {
            "Español": "Ganancia derivativa (PID)",
            "Português": "Ganho derivativo (PID)"
        },
        "Minimum safe temperature": {
            "Español": "Temperatura mínima segura",
            "Português": "Temperatura mínima segura"
        },
        "Maximum safe temperature": {
            "Español": "Temperatura máxima segura",
            "Português": "Temperatura máxima segura"
        },
        "Pin connected to the probe sensor": {
            "Español": "Pin conectado al sensor del probe",
            "Português": "Pino conectado ao sensor do probe"
        },
        "Pin connected to the probe control": {
            "Español": "Pin conectado al control del probe",
            "Português": "Pino conectado ao controle do probe"
        },
        "Offset relative to the nozzle. Must be measured for your specific printer": {
            "Español": "Offset relativo a la boquilla. Debe medirse para tu impresora específica",
            "Português": "Offset relativo ao bico. Deve ser medido para sua impressora específica"
        },
        "Z offset should be calibrated using PROBE_CALIBRATE": {
            "Español": "El offset de Z debe calibrarse usando PROBE_CALIBRATE",
            "Português": "O offset de Z deve ser calibrado usando PROBE_CALIBRATE"
        },
        "XY position to move to before homing Z": {
            "Español": "Posición XY a la que moverse antes de hacer homing de Z",
            "Português": "Posição XY para a qual se mover antes de fazer homing de Z"
        },
        "Speed at which the toolhead is moved to the safe Z home coordinate": {
            "Español": "Velocidad a la que el cabezal se mueve hacia la coordenada de Z segura",
            "Português": "Velocidade em que o cabeçote é movido para a coordenada de Z segura"
        },
        "Distance (in mm) to lift the Z axis prior to homing": {
            "Español": "Distancia (mm) para levantar el eje Z antes de hacer homing",
            "Português": "Distância (mm) para levantar o eixo Z antes do homing"
        },
        "Speed (in mm/s) at which the Z axis is lifted prior to homing": {
            "Español": "Velocidad (en mm/s) a la que se levanta el eje Z antes del homing",
            "Português": "Velocidade (em mm/s) em que o eixo Z é levantado antes do homing"
        },
        "Pin connected to the heated bed solid state relay or MOSFET": {
            "Español": "Pin conectado al relé de estado sólido o MOSFET de la cama caliente",
            "Português": "Pino conectado ao relé de estado sólido ou MOSFET da mesa aquecida"
        },
        "Pin connected to the heated bed thermistor": {
            "Español": "Pin conectado al termistor de la cama caliente",
            "Português": "Pino conectado ao termistor da mesa aquecida"
        },
        "Type of thermistor used for the heated bed": {
            "Español": "Tipo de termistor utilizado para la cama caliente",
            "Português": "Tipo de termistor utilizado para a mesa aquecida"
        },
        "UART communication pin": {
            "Español": "Pin de comunicación UART",
            "Português": "Pino de comunicação UART"
        },
        "UART TX pin": {
            "Español": "Pin de TX UART",
            "Português": "Pino de TX UART"
        },
        "SPI chip select pin": {
            "Español": "Pin de selección de chip (CS) de SPI",
            "Português": "Pino de seleção de chip (CS) de SPI"
        },
        "SPI clock pin": {
            "Español": "Pin de reloj (SCK) de SPI",
            "Português": "Pino de relógio (SCK) de SPI"
        },
        "SPI MOSI pin": {
            "Español": "Pin MOSI de SPI",
            "Português": "Pino MOSI de SPI"
        },
        "SPI MISO pin": {
            "Español": "Pin MISO de SPI",
            "Português": "Pino MISO de SPI"
        },
        "SPI bus name": {
            "Español": "Nombre del bus SPI",
            "Português": "Nome do barramento SPI"
        },
        "Motor run current in amps": {
            "Español": "Corriente de funcionamiento del motor (Amperios)",
            "Português": "Corrente de funcionamento do motor (Amperes)"
        },
        "Motor hold current in amps": {
            "Español": "Corriente de retención del motor (Amperios)",
            "Português": "Corrente de retenção do motor (Amperes)"
        },
        "Set to 0 to use spreadCycle mode": {
            "Español": "Establecer en 0 para usar modo spreadCycle",
            "Português": "Defina como 0 para usar modo spreadCycle"
        },
        "Define aliases for board pins (e.g., EXP1 and EXP2 headers)": {
            "Español": "Define los alias para los pines de la placa (ej., conectores EXP1 y EXP2)",
            "Português": "Define os aliases para os pinos da placa (ex., conectores EXP1 e EXP2)"
        },
        "filament per motor revolution (mm) --- manual configuration --- (calibrate by extruding 100mm)": {
            "Español": "filamento por revolución del motor (mm) --- configuración manual --- (calibrar extruyendo 100mm)",
            "Português": "filamento por revolução do motor (mm) --- configuração manual --- (calibrar extrusando 100mm)"
        },
        "PID proportional --- manual configuration --- (run PID_CALIBRATE HEATER=extruder TARGET=200)": {
            "Español": "PID proporcional --- configuración manual --- (ejecutar PID_CALIBRATE HEATER=extruder TARGET=200)",
            "Português": "PID proporcional --- configuração manual --- (executar PID_CALIBRATE HEATER=extruder TARGET=200)"
        },
        "PID integral --- manual configuration --- (run PID_CALIBRATE)": {
            "Español": "PID integral --- configuración manual --- (ejecutar PID_CALIBRATE)",
            "Português": "PID integral --- configuração manual --- (executar PID_CALIBRATE)"
        },
        "PID derivative --- manual configuration --- (run PID_CALIBRATE)": {
            "Español": "PID derivativo --- configuración manual --- (ejecutar PID_CALIBRATE)",
            "Português": "PID derivativo --- configuração manual --- (executar PID_CALIBRATE)"
        },
        "distance from nozzle to probe in X (mm) --- manual configuration --- (measure physically from nozzle to probe tip)": {
            "Español": "distancia de la boquilla al sensor en X (mm) --- configuración manual --- (medir físicamente desde la boquilla hasta la punta del sensor)",
            "Português": "distância do bico ao sensor em X (mm) --- configuração manual --- (medir fisicamente do bico até a ponta do sensor)"
        },
        "distance from nozzle to probe in Y (mm) --- manual configuration --- (measure physically from nozzle to probe tip)": {
            "Español": "distancia de la boquilla al sensor en Y (mm) --- configuración manual --- (medir físicamente desde la boquilla hasta la punta del sensor)",
            "Português": "distância do bico ao sensor em Y (mm) --- configuração manual --- (medir fisicamente do bico até a ponta do sensor)"
        },
        "nozzle to bed distance (mm) --- manual configuration --- (set using PROBE_CALIBRATE)": {
            "Español": "distancia de la boquilla a la cama (mm) --- configuración manual --- (configurar usando PROBE_CALIBRATE)",
            "Português": "distância do bico à mesa (mm) --- configuração manual --- (configurar usando PROBE_CALIBRATE)"
        },
        "Probe speed in mm/s": {
            "Español": "Velocidad de prueba en mm/s",
            "Português": "Velocidade de teste em mm/s"
        },
        "Z height before moving to next probe point": {
            "Español": "Altura de Z antes de moverse al siguiente punto",
            "Português": "Altura de Z antes de mover para o próximo ponto"
        },
        "probing area start (mm) --- manual configuration --- (must be inside bed limits)": {
            "Español": "inicio del área de prueba (mm) --- configuración manual --- (debe estar dentro de los límites de la cama)",
            "Português": "início da área de teste (mm) --- configuração manual --- (deve estar dentro dos limites da mesa)"
        },
        "probing area end (mm) --- manual configuration --- (must be inside bed limits)": {
            "Español": "fin del área de prueba (mm) --- configuración manual --- (debe estar dentro de los límites de la cama)",
            "Português": "fim da área de teste (mm) --- configuração manual --- (deve estar dentro dos limites da mesa)"
        },
        "Probe grid size": {
            "Español": "Tamaño de la cuadrícula de prueba",
            "Português": "Tamanho da grade de teste"
        },
        "--- optional --- (automatic Z leveling for multiple motors)": {
            "Español": "--- opcional --- (nivelación automática de Z para múltiples motores)",
            "Português": "--- opcional --- (nivelamento automático de Z para múltiplos motores)"
        },
        "Locations of the bed pivot points": {
            "Español": "Ubicaciones de los puntos de pivote de la cama",
            "Português": "Localizações dos pontos de pivô da mesa"
        },
        "Probing points for Z leveling": {
            "Español": "Puntos de prueba para la nivelación de Z",
            "Português": "Pontos de teste para o nivelamento de Z"
        },
        "Speed of non-probing moves during leveling": {
            "Español": "Velocidad de movimientos sin prueba durante la nivelación",
            "Português": "Velocidade de movimentos sem teste durante o nivelamento"
        },
        "Z height to clear the bed when moving": {
            "Español": "Altura Z para despejar la cama al moverse",
            "Português": "Altura Z para limpar a mesa ao se mover"
        },
        "--- optional --- (for CoreXY gantry leveling)": {
            "Español": "--- opcional --- (para nivelación de pórtico CoreXY)",
            "Português": "--- opcional --- (para nivelamento de pórtico CoreXY)"
        },
        "Locations of the gantry pivot points": {
            "Español": "Ubicaciones de los puntos de pivote del pórtico",
            "Português": "Localizações dos pontos de pivô do pórtico"
        },
        "Probing points for gantry leveling": {
            "Español": "Puntos de prueba para la nivelación del pórtico",
            "Português": "Pontos de teste para o nivelamento do pórtico"
        },
        "bed PID proportional --- manual configuration --- (run PID_CALIBRATE HEATER=heater_bed TARGET=60)": {
            "Español": "PID proporcional de la cama --- configuración manual --- (ejecutar PID_CALIBRATE HEATER=heater_bed TARGET=60)",
            "Português": "PID proporcional da mesa --- configuração manual --- (executar PID_CALIBRATE HEATER=heater_bed TARGET=60)"
        },
        "bed PID integral --- manual configuration --- (run PID_CALIBRATE)": {
            "Español": "PID integral de la cama --- configuración manual --- (ejecutar PID_CALIBRATE)",
            "Português": "PID integral da mesa --- configuração manual --- (executar PID_CALIBRATE)"
        },
        "bed PID derivative --- manual configuration --- (run PID_CALIBRATE)": {
            "Español": "PID derivativo de la cama --- configuración manual --- (ejecutar PID_CALIBRATE)",
            "Português": "PID derivativo da mesa --- configuração manual --- (executar PID_CALIBRATE)"
        },
        "motor current (A) --- manual configuration --- (check motor specs)": {
            "Español": "corriente del motor (A) --- configuración manual --- (verificar especificaciones)",
            "Português": "corrente do motor (A) --- configuração manual --- (verificar especificações)"
        },
        "Includes": {
            "Español": "Componentes Incluidos",
            "Português": "Componentes Incluídos"
        },
        "MCU": {
            "Español": "MCU (Microcontrolador)",
            "Português": "MCU (Microcontrolador)"
        },
        "Printer": {
            "Español": "Impresora",
            "Português": "Impressora"
        },
        "Steppers": {
            "Español": "Motores de Paso (Steppers)",
            "Português": "Motores de Passo (Steppers)"
        },
        "Probe & Bed Leveling": {
            "Español": "Sensor y Nivelación de Cama (Probe & Bed Leveling)",
            "Português": "Sensor e Nivelamento de Mesa (Probe & Bed Leveling)"
        },
        "Part Cooling Fan": {
            "Español": "Ventilador de Capa",
            "Português": "Ventilador de Camada"
        },
        "Hotend Heatsink Fan": {
            "Español": "Ventilador del Disipador del Hotend",
            "Português": "Ventilador do Dissipador do Hotend"
        },
        "Heated Bed": {
            "Español": "Cama Caliente",
            "Português": "Mesa Aquecida"
        },
        "TMC Drivers": {
            "Español": "Controladores (Drivers) TMC",
            "Português": "Controladores (Drivers) TMC"
        },
        "EXP1 / EXP2 Pinout": {
            "Español": "Distribución de pines EXP1 / EXP2",
            "Português": "Distribuição de pinos EXP1 / EXP2"
        },
        "REQUIRED CALIBRATION STEPS": {
            "Español": "PASOS DE CALIBRACIÓN REQUERIDOS",
            "Português": "PASSOS DE CALIBRAÇÃO REQUERIDOS"
        },
        "1. Calibrate extruder (rotation_distance)": {
            "Español": "1. Calibrar extrusor (rotation_distance)",
            "Português": "1. Calibrar extrusora (rotation_distance)"
        },
        "2. Run PID_CALIBRATE for hotend and bed": {
            "Español": "2. Ejecutar PID_CALIBRATE para hotend y cama",
            "Português": "2. Executar PID_CALIBRATE para hotend e mesa"
        },
        "3. Calibrate Z offset (PROBE_CALIBRATE)": {
            "Español": "3. Calibrar el offset de Z (PROBE_CALIBRATE)",
            "Português": "3. Calibrar o offset de Z (PROBE_CALIBRATE)"
        },
        "4. Verify endstops and axis directions": {
            "Español": "4. Verificar finales de carrera y direcciones de los ejes",
            "Português": "4. Verificar chaves de fim de curso e direções dos eixos"
        },
        "ADVANCED HARDWARE SECTIONS": {
            "Español": "SECCIONES DE HARDWARE AVANZADO",
            "Português": "SEÇÕES DE HARDWARE AVANÇADO"
        },
        "The sections below were detected in your board's source config.": {
            "Español": "Las siguientes secciones fueron detectadas en la configuración original de su placa.",
            "Português": "As seções abaixo foram detectadas na configuração de origem da sua placa."
        },
        "They are preserved here as commented-out blocks so you retain": {
            "Español": "Se conservan aquí como bloques comentados para que conserve",
            "Português": "Elas são preservadas aqui como blocos comentados para que você mantenha"
        },
        "the original pin data. Review each section carefully, then": {
            "Español": "los datos de pines originales. Revise cada sección cuidadosamente, luego",
            "Português": "os dados de pinos originais. Revise cada seção cuidadosamente, então"
        },
        "uncomment and adjust as needed. Do NOT uncomment without reading": {
            "Español": "descomente y ajuste según sea necesario. NO descomente sin leer",
            "Português": "descomente e ajuste conforme necessário. NÃO descomente sem ler"
        },
        "the note above each block — some require physical calibration.": {
            "Español": "la nota sobre cada bloque — algunos requieren calibración física.",
            "Português": "a nota acima de cada bloco — alguns requerem calibração física."
        },
        "Gear ratio of the axis": {
            "Español": "Relación de transmisión del eje",
            "Português": "Relação de transmissão del eixo"
        },
        "Gear ratio of the extruder": {
            "Español": "Relación de transmisión del extrusor",
            "Português": "Relação de transmissão da extrusora"
        },
        "distance from nozzle to probe in X (mm) --- set in KACE wizard --- (re-measure physically if probe is moved)": {
            "Español": "distancia de la boquilla al sensor en X (mm) --- configurado en el asistente de KACE --- (volver a medir físicamente si se mueve el sensor)",
            "Português": "distância do bico ao sensor em X (mm) --- configurado no assistente do KACE --- (medir fisicamente novamente se o sensor for movido)"
        },
        "distance from nozzle to probe in Y (mm) --- set in KACE wizard --- (re-measure physically if probe is moved)": {
            "Español": "distancia de la boquilla al sensor en Y (mm) --- configurado en el asistente de KACE --- (volver a medir físicamente si se mueve el sensor)",
            "Português": "distância do bico ao sensor em Y (mm) --- configurado no assistente do KACE --- (medir fisicamente novamente se o sensor for movido)"
        },
        "Tension of the bicubic curve": {
            "Español": "Tensión de la curva bicúbica",
            "Português": "Tensão da curva bicúbica"
        },
        "Number of points to interpolate per segment": {
            "Español": "Número de puntos a interpolar por segmento",
            "Português": "Número de pontos a interpolar por segmento"
        },
        "Adaptive margin for mesh": {
            "Español": "Margen adaptativo para la malla",
            "Português": "Margem adaptativa para a malha"
        },
        "Z height at which to start fading mesh leveling": {
            "Español": "Altura de Z en la que comenzar a desvanecer la nivelación de malla",
            "Português": "Altura de Z na qual iniciar o desvanecimento do nivelamento da malha"
        },
        "Z height at which mesh leveling is completely disabled": {
            "Español": "Altura de Z en la que la nivelación de malla está completamente desactivada",
            "Português": "Altura de Z na qual o nivelamento da malha é completamente desativado"
        },
        "Target Z offset to fade towards": {
            "Español": "Desplazamiento Z objetivo hacia el cual desvanecer",
            "Português": "Offset Z alvo para o qual desvanecer"
        },
        "Interpolation algorithm": {
            "Español": "Algoritmo de interpolación",
            "Português": "Algoritmo de interpolação"
        },
        "Probing area minimum (derived from physical limits)": {
            "Español": "Mínimo del área de prueba (derivado de los límites físicos)",
            "Português": "Mínimo da área de teste (derivado dos limites físicos)"
        },
        "Probing area maximum (derived from physical limits)": {
            "Español": "Máximo del área de prueba (derivado de los límites físicos)",
            "Português": "Máximo da área de teste (derivado dos limites físicos)"
        },
        "Note: Klipper requires nozzle coordinates (not probe coordinates) for both z_positions and points.": {
            "Español": "Nota: Klipper requiere coordenadas de la boquilla (no del sensor) tanto para z_positions como para points.",
            "Português": "Nota: O Klipper requer coordenadas do bico (não do sensor) tanto para z_positions quanto para points."
        },
        "Note: Klipper requires nozzle coordinates (not probe coordinates) for both gantry_corners and points.": {
            "Español": "Nota: Klipper requiere coordenadas de la boquilla (no del sensor) tanto para gantry_corners como para points.",
            "Português": "Nota: O Klipper requer coordenadas do bico (não do sensor) tanto para gantry_corners quanto para points."
        },
        "Locations of the gantry pivot points (nozzle coordinates)": {
            "Español": "Ubicaciones de los puntos de pivote del pórtico (coordenadas de la boquilla)",
            "Português": "Localizações dos pontos de pivô do pórtico (coordenadas do bico)"
        },
        "Pin connected to the part cooling fan": {
            "Español": "Pin conectado al ventilador de capa",
            "Português": "Pino conectado ao ventilador de camada"
        },
        "Pin connected to the part cooling fan (uncomment and set if available)": {
            "Español": "Pin conectado al ventilador de capa (descomentar y configurar si está disponible)",
            "Português": "Pino conectado ao ventilador de camada (descomentar e configurar se disponível)"
        },
        "Pin connected to the hotend heatsink fan": {
            "Español": "Pin conectado al ventilador del disipador del hotend",
            "Português": "Pino conectado ao ventilador do dissipador do hotend"
        },
        "Heater associated with this fan": {
            "Español": "Calentador asociado con este ventilador",
            "Português": "Aquecedor associado a este ventilador"
        },
        "Temperature above which the fan is enabled": {
            "Español": "Temperatura por encima de la cual se activa el ventilador",
            "Português": "Temperatura acima da qual o ventilador é ativado"
        },
        "EXP1 header": {
            "Español": "conector EXP1",
            "Português": "conector EXP1"
        },
        "EXP2 header": {
            "Español": "conector EXP2",
            "Português": "conector EXP2"
        }
    }

    # Handle dynamic generated headers prefix-wise
    if comment.startswith("This file was generated by KACE"):
        if lang == "Español":
            return "Este archivo fue generado por KACE (Klipper Automated Configuration Ecosystem)"
        if lang == "Português":
            return "Este arquivo foi gerado pelo KACE (Klipper Automated Configuration Ecosystem)"
            
    if comment.startswith("Board:"):
        board_val = comment[6:].strip()
        if lang == "Español":
            return f"Placa: {board_val}"
        if lang == "Português":
            return f"Placa: {board_val}"
            
    if comment.startswith("Kinematics:"):
        kin_val = comment[11:].strip()
        if lang == "Español":
            return f"Cinemática: {kin_val}"
        if lang == "Português":
            return f"Cinemática: {kin_val}"
            
    if comment.startswith("Stepper Drivers:"):
        drv_val = comment[16:].strip()
        if lang == "Español":
            return f"Drivers de motores: {drv_val}"
        if lang == "Português":
            return f"Drivers de motores: {drv_val}"
            
    if comment.startswith("Probe:"):
        probe_val = comment[6:].strip()
        if lang == "Español":
            return f"Sensor (Probe): {probe_val}"
        if lang == "Português":
            return f"Sensor (Probe): {probe_val}"
            
    if comment.startswith("Z Motors:"):
        z_val = comment[9:].strip()
        if lang == "Español":
            return f"Motores Z: {z_val}"
        if lang == "Português":
            return f"Motores Z: {z_val}"

    # If exact match exists
    if comment in translations and lang in translations[comment]:
        return translations[comment][lang]
        
    return comment
