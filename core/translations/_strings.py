# core/translations/_strings.py
# All user-facing UI strings keyed by a short dot-separated ID.
# Each entry maps language name -> display string.

from core.translations._state import _SUPPORTED_LANGS  # noqa: F401 (re-exported)

UI_STRINGS: dict = {
    # ── Wizard prompts ─────────────────────────────────────────
    "wizard.select_mode": {
        "English":   "Select Configuration Mode:",
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
    "wizard.probe_custom": {
        "English":   "Custom Probe",
        "Español":   "Sonda personalizada",
        "Português": "Sonda personalizada",
    },
    "wizard.custom_probe_pin": {
        "English":   "Select the probe input pin. KACE lists currently unused pins for this board:",
        "Español":   "Seleccione el pin de entrada de la sonda. KACE muestra los pines sin usar de esta placa:",
        "Português": "Selecione o pino de entrada da sonda. KACE lista os pinos não usados desta placa:",
    },
    "wizard.custom_probe_dedicated_pin": {
        "English":   "Recommended: board PROBE connector",
        "Español":   "Recomendado: conector PROBE de la placa",
        "Português": "Recomendado: conector PROBE da placa",
    },
    "wizard.custom_probe_pullup": {
        "English":   "Enable the internal pull-up (^)? Recommended when the probe output is an open switch to ground.",
        "Español":   "¿Activar la resistencia pull-up interna (^)? Se recomienda si la sonda es un interruptor a tierra.",
        "Português": "Ativar o pull-up interno (^)? Recomendado quando a saída da sonda é um interruptor para terra.",
    },
    "wizard.custom_probe_inverted": {
        "English":   "Invert the probe signal (!)? Enable only if Klipper reports triggered when the probe is open.",
        "Español":   "¿Invertir la señal de la sonda (!)? Actívelo sólo si Klipper informa activada cuando está abierta.",
        "Português": "Inverter o sinal da sonda (!)? Ative apenas se o Klipper informar acionada quando ela estiver aberta.",
    },
    "wizard.custom_probe_pin_manual": {
        "English":   "Enter a pin manually (validated against the board)",
        "Español":   "Ingresar un pin manualmente (validado contra la placa)",
        "Português": "Inserir um pino manualmente (validado para a placa)",
    },
    "wizard.custom_probe_pin_manual_prompt": {
        "English":   "Probe input pin (for example ^PB7). This pin senses contact:",
        "Español":   "Pin de entrada de la sonda (por ejemplo ^PB7). Este pin detecta el contacto:",
        "Português": "Pino de entrada da sonda (por exemplo ^PB7). Este pino detecta o contato:",
    },
    "wizard.custom_probe_z_offset": {
        "English":   "Probe Z offset from nozzle in mm (optional; leave blank to calibrate later):",
        "Español":   "Desplazamiento Z de la sonda desde la boquilla en mm (opcional; deje vacío para calibrar después):",
        "Português": "Deslocamento Z da sonda em relação ao bico em mm (opcional; deixe em branco para calibrar depois):",
    },
    "wizard.custom_probe_samples": {
        "English":   "Number of readings per probe point. More readings improve repeatability:",
        "Español":   "Cantidad de lecturas por punto. Más lecturas mejoran la repetibilidad:",
        "Português": "Número de leituras por ponto. Mais leituras melhoram a repetibilidade:",
    },
    "wizard.custom_probe_samples_tolerance": {
        "English":   "Maximum allowed difference between readings in mm before retrying:",
        "Español":   "Diferencia máxima permitida entre lecturas en mm antes de reintentar:",
        "Português": "Diferença máxima permitida entre leituras em mm antes de tentar novamente:",
    },
    "wizard.custom_probe_samples_tolerance_retries": {
        "English":   "How many times to retry readings outside the tolerance:",
        "Español":   "Cuántas veces reintentar lecturas fuera de la tolerancia:",
        "Português": "Quantas vezes repetir leituras fora da tolerância:",
    },
    "wizard.custom_probe_speed": {
        "English":   "Probe speed in mm/s. Start conservatively for reliable triggering:",
        "Español":   "Velocidad de sondeo en mm/s. Comience de forma conservadora para un disparo fiable:",
        "Português": "Velocidade de sondagem em mm/s. Comece de forma conservadora para acionamento confiável:",
    },
    "wizard.custom_probe_samples_result": {
        "English":   "How Klipper combines repeated readings:",
        "Español":   "Cómo combina Klipper las lecturas repetidas:",
        "Português": "Como o Klipper combina leituras repetidas:",
    },
    "wizard.custom_probe_samples_result_median": {
        "English":   "Median (recommended; rejects isolated outliers)",
        "Español":   "Mediana (recomendado; descarta valores atípicos aislados)",
        "Português": "Mediana (recomendado; descarta valores discrepantes isolados)",
    },
    "wizard.custom_probe_samples_result_average": {
        "English":   "Average",
        "Español":   "Promedio",
        "Português": "Média",
    },
    "wizard.custom_probe_sample_retract_dist": {
        "English":   "Distance to lift between readings in mm. Prevents repeated contact at the same height:",
        "Español":   "Distancia de elevación entre lecturas en mm. Evita contactos repetidos a la misma altura:",
        "Português": "Distância para elevar entre leituras em mm. Evita contato repetido na mesma altura:",
    },
    "wizard.custom_probe_missing_fields": {
        "English":   "Custom probe setup is incomplete. Return to fill in the probe pin and X/Y offsets.",
        "Español":   "La configuración de la sonda personalizada está incompleta. Vuelva para indicar el pin y los desplazamientos X/Y.",
        "Português": "A configuração da sonda personalizada está incompleta. Volte para informar o pino e os deslocamentos X/Y.",
    },
    "wizard.custom_probe_review": {
        "English":   "Generated custom [probe] configuration (review before continuing):",
        "Español":   "Configuración [probe] personalizada generada (revísela antes de continuar):",
        "Português": "Configuração [probe] personalizada gerada (revise antes de continuar):",
    },
    "wizard.custom_probe_intro": {
        "English":   "Enter the complete custom Klipper probe block.",
        "Español":   "Ingrese el bloque completo de configuración Klipper de la sonda.",
        "Português": "Insira o bloco completo de configuração Klipper da sonda.",
    },
    "wizard.custom_probe_requirements": {
        "English":   "It must start with [probe] or [dockable_probe]. Related gcode macros are allowed.",
        "Español":   "Debe comenzar con [probe] o [dockable_probe]. Se permiten macros gcode relacionadas.",
        "Português": "Deve começar com [probe] ou [dockable_probe]. Macros gcode relacionadas são permitidas.",
    },
    "wizard.custom_probe_finish": {
        "English":   "Finish input with END on a line by itself. Press Ctrl+C to go back.",
        "Español":   "Finalice escribiendo END en una línea propia. Presione Ctrl+C para volver.",
        "Português": "Finalize digitando END em uma linha própria. Pressione Ctrl+C para voltar.",
    },
    "wizard.custom_probe_invalid": {
        "English":   "Invalid custom probe configuration",
        "Español":   "Configuración de sonda personalizada inválida",
        "Português": "Configuração de sonda personalizada inválida",
    },
    "wizard.custom_probe_x_offset": {
        "English":   "Probe X offset from nozzle in mm. Negative means the probe is left of the nozzle:",
        "Español":   "Desplazamiento X de la sonda desde la boquilla en mm. Negativo significa que está a la izquierda:",
        "Português": "Deslocamento X da sonda em relação ao bico em mm. Negativo significa que está à esquerda:",
    },
    "wizard.custom_probe_y_offset": {
        "English":   "Probe Y offset from nozzle in mm. Negative means the probe is in front of the nozzle:",
        "Español":   "Desplazamiento Y de la sonda desde la boquilla en mm. Negativo significa que está delante:",
        "Português": "Deslocamento Y da sonda em relação ao bico em mm. Negativo significa que está à frente:",
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
        "English":   "Kinematics",
        "Español":   "Cinemática",
        "Português": "Cinemática",
    },
    "choice.editor_volume": {
        "English":   "Build Volume",
        "Español":   "Volumen de Construcción",
        "Português": "Volume de Impressão",
    },
    "choice.editor_x_min": {
        "English":   "X position_min",
        "Español":   "X position_min",
        "Português": "X position_min",
    },
    "choice.editor_x_max": {
        "English":   "X position_max",
        "Español":   "X position_max",
        "Português": "X position_max",
    },
    "choice.editor_x_endstop": {
        "English":   "X position_endstop",
        "Español":   "X position_endstop",
        "Português": "X position_endstop",
    },
    "choice.editor_y_min": {
        "English":   "Y position_min",
        "Español":   "Y position_min",
        "Português": "Y position_min",
    },
    "choice.editor_y_max": {
        "English":   "Y position_max",
        "Español":   "Y position_max",
        "Português": "Y position_max",
    },
    "choice.editor_y_endstop": {
        "English":   "Y position_endstop",
        "Español":   "Y position_endstop",
        "Português": "Y position_endstop",
    },
    "choice.editor_z_min": {
        "English":   "Z position_min",
        "Español":   "Z position_min",
        "Português": "Z position_min",
    },
    "choice.editor_z_max": {
        "English":   "Z position_max",
        "Español":   "Z position_max",
        "Português": "Z position_max",
    },
    "choice.editor_z_endstop": {
        "English":   "Z position_endstop",
        "Español":   "Z position_endstop",
        "Português": "Z position_endstop",
    },
    "choice.editor_hotend_thermistor": {
        "English":   "Hotend Thermistor",
        "Español":   "Termistor del Hotend",
        "Português": "Termistor do Hotend",
    },
    "choice.editor_bed_thermistor": {
        "English":   "Bed Thermistor",
        "Español":   "Termistor de la Cama",
        "Português": "Termistor da Mesa",
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
    "kace.deploy_sd_verify": {
        "English":   "SD Card (copy + automatic flash verification)",
        "Español":   "Tarjeta SD (copiar + verificar flasheo automáticamente)",
        "Português": "Cartão SD (copiar + verificar gravação automaticamente)",
    },
    "kace.sd_flash_instructions": {
        "English":   "Safely eject the SD card, insert it into the printer controller, then turn only the printer off and on. Keep the Raspberry Pi powered on; KACE will detect the temporary MCU disconnect and verify the new firmware.",
        "Español":   "Expulse la tarjeta SD de forma segura, insértela en la controladora de la impresora y apague y encienda solamente la impresora. Mantenga encendida la Raspberry Pi; KACE detectará la desconexión temporal del MCU y verificará el firmware nuevo.",
        "Português": "Ejete o cartão SD com segurança, insira-o na controladora da impressora e desligue e ligue somente a impressora. Mantenha o Raspberry Pi ligado; o KACE detectará a desconexão temporária do MCU e verificará o novo firmware.",
    },
    "kace.sd_flash_ready_prompt": {
        "English":   "Press Enter after the printer is powered off and on to begin automatic verification...",
        "Español":   "Presione Enter después de apagar y encender la impresora para iniciar la verificación automática...",
        "Português": "Pressione Enter depois de desligar e ligar a impressora para iniciar a verificação automática...",
    },
    "kace.sd_verify_success": {
        "English":   "Firmware verified. The controller reconnected with the newly compiled version.",
        "Español":   "Firmware verificado. La controladora se reconectó con la versión recién compilada.",
        "Português": "Firmware verificado. A controladora reconectou com a versão recém-compilada.",
    },
    "kace.sd_verify_unavailable": {
        "English":   "The firmware was copied, but automatic verification is unavailable because this build has no version fingerprint. Power-cycle the printer and continue with configuration deployment.",
        "Español":   "El firmware fue copiado, pero la verificación automática no está disponible porque esta compilación no tiene una huella de versión. Apague y encienda la impresora y continúe con el despliegue de configuración.",
        "Português": "O firmware foi copiado, mas a verificação automática não está disponível porque esta compilação não tem uma impressão digital de versão. Desligue e ligue a impressora e continue com o deploy da configuração.",
    },
    "kace.sd_verify_timeout": {
        "English":   "Automatic verification timed out: {detail}. Confirm the SD card was inserted in the controller, power-cycle only the printer, and check that Moonraker/Klipper is running on this Raspberry Pi before retrying.",
        "Español":   "La verificación automática agotó el tiempo: {detail}. Confirme que la tarjeta SD fue insertada en la controladora, apague y encienda solamente la impresora y compruebe que Moonraker/Klipper esté ejecutándose en esta Raspberry Pi antes de reintentar.",
        "Português": "A verificação automática expirou: {detail}. Confirme que o cartão SD foi inserido na controladora, desligue e ligue somente a impressora e verifique se Moonraker/Klipper está em execução neste Raspberry Pi antes de tentar novamente.",
    },
    "kace.sd_verify_wrong_version": {
        "English":   "The controller reconnected, but it is not running the firmware just copied: {detail}. Check the board's required SD-card filename/format and retry the flash.",
        "Español":   "La controladora se reconectó, pero no está ejecutando el firmware recién copiado: {detail}. Compruebe el nombre/formato de archivo requerido por la tarjeta SD de la placa y reintente el flasheo.",
        "Português": "A controladora reconectou, mas não está executando o firmware recém-copiado: {detail}. Verifique o nome/formato de arquivo exigido pelo cartão SD da placa e tente a gravação novamente.",
    },
    "kace.sd_verify_config_error": {
        "English":   "Klipper reported a configuration error while the controller returned: {detail}. Review the existing printer configuration, correct it, and retry verification.",
        "Español":   "Klipper informó un error de configuración mientras la controladora regresaba: {detail}. Revise la configuración existente de la impresora, corríjala y reintente la verificación.",
        "Português": "O Klipper informou um erro de configuração enquanto a controladora retornava: {detail}. Revise a configuração existente da impressora, corrija-a e tente a verificação novamente.",
    },
    "kace.sd_verify_failed": {
        "English":   "Automatic firmware verification did not complete: {detail}. Check the printer connection and retry the SD-card flash.",
        "Español":   "La verificación automática del firmware no se completó: {detail}. Compruebe la conexión de la impresora y reintente el flasheo por tarjeta SD.",
        "Português": "A verificação automática do firmware não foi concluída: {detail}. Verifique a conexão da impressora e tente novamente a gravação pelo cartão SD.",
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
        "English":   "Enter SSH User (e.g. kace):",
        "Español":   "Ingrese el Usuario SSH (ej. kace):",
        "Português": "Digite o Usuário SSH (ex. kace):",
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
        "English":   "Enter Moonraker host (e.g. 192.168.1.100):",
        "Español":   "Ingrese el host de Moonraker (ej. 192.168.1.100):",
        "Português": "Digite o host do Moonraker (ex. 192.168.1.100):",
    },
    "moonraker.port_prompt": {
        "English":   "Enter Moonraker port",
        "Español":   "Ingrese el puerto de Moonraker",
        "Português": "Digite a porta do Moonraker",
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
        "English":   "RESTART (reload config, recommended)",
        "Español":   "RESTART (recargar config, recomendado)",
        "Português": "RESTART (recarregar config, recomendado)",
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
    "menu.select_range": {
        "English": "Select [1-{count}]:",
        "Español": "Seleccione [1-{count}]:",
        "Português": "Selecione [1-{count}]:",
    },
    "wizard.hardware_discovery_start": {
        "English": "Starting Hardware Discovery...",
        "Español": "Iniciando detección de hardware...",
        "Português": "Iniciando detecção de hardware...",
    },
    "wizard.board_database_fetch": {
        "English": "Fetching board database...",
        "Español": "Obteniendo base de datos de placas...",
        "Português": "Obtendo banco de dados de placas...",
    },
    "mcu.none_detected": {
        "English": "[!] No MCU serial devices detected.",
        "Español": "[!] No se detectaron dispositivos seriales de MCU.",
        "Português": "[!] Nenhum dispositivo serial de MCU foi detectado.",
    },
    "mcu.diagnostics_header": {
        "English": "Please verify the following hardware diagnostics:",
        "Español": "Verifique los siguientes diagnósticos de hardware:",
        "Português": "Verifique os seguintes diagnósticos de hardware:",
    },
    "mcu.diagnostic_usb": {
        "English": "USB Connection: Ensure the USB cable is securely connected to both the Pi and the board. Try another cable/port.",
        "Español": "Conexión USB: asegúrese de que el cable USB esté bien conectado tanto a la Pi como a la placa. Pruebe otro cable o puerto.",
        "Português": "Conexão USB: certifique-se de que o cabo USB esteja firmemente conectado à Pi e à placa. Tente outro cabo ou porta.",
    },
    "mcu.diagnostic_firmware": {
        "English": "Firmware: Verify Klipper firmware has been flashed to the controller. If in bootloader mode, it won't appear.",
        "Español": "Firmware: verifique que el firmware de Klipper se haya grabado en el controlador. No aparecerá si está en modo bootloader.",
        "Português": "Firmware: verifique se o firmware do Klipper foi gravado no controlador. Ele não aparecerá no modo bootloader.",
    },
    "mcu.diagnostic_power": {
        "English": "Board Power: Verify the board is powered on (check status LEDs or power supply switches).",
        "Español": "Alimentación de la placa: verifique que la placa esté encendida (revise los LED de estado o los interruptores de la fuente).",
        "Português": "Alimentação da placa: verifique se a placa está ligada (verifique LEDs de status ou interruptores da fonte).",
    },
    "mcu.diagnostic_permissions": {
        "English": "Permissions: Verify that the current user has access to serial devices (e.g. member of 'dialout').",
        "Español": "Permisos: verifique que el usuario actual tenga acceso a dispositivos seriales (por ejemplo, que pertenezca a 'dialout').",
        "Português": "Permissões: verifique se o usuário atual tem acesso a dispositivos seriais (por exemplo, se pertence a 'dialout').",
    },
    "mcu.proceed_prompt": {
        "English": "How would you like to proceed?",
        "Español": "¿Cómo desea continuar?",
        "Português": "Como você gostaria de continuar?",
    },
    "mcu.retry": {
        "English": "Retry hardware discovery",
        "Español": "Reintentar detección de hardware",
        "Português": "Tentar novamente a detecção de hardware",
    },
    "mcu.manual": {
        "English": "Skip / Enter serial path manually",
        "Español": "Omitir / Ingresar ruta serial manualmente",
        "Português": "Pular / Informar caminho serial manualmente",
    },
    "mcu.manual_path_prompt": {
        "English": "Enter serial path manually (e.g. /dev/ttyUSB0, COM3, or leave blank to skip MCU detection):",
        "Español": "Ingrese la ruta serial manualmente (por ejemplo, /dev/ttyUSB0, COM3, o deje vacío para omitir la detección de MCU):",
        "Português": "Informe o caminho serial manualmente (por exemplo, /dev/ttyUSB0, COM3, ou deixe em branco para pular a detecção de MCU):",
    },
    "mcu.exit": {
        "English": "Exiting KACE.",
        "Español": "Saliendo de KACE.",
        "Português": "Saindo do KACE.",
    },
    "probe.preview_title": {"English": "Probe Offset Preview", "Español": "Vista previa de desplazamientos del sensor", "Português": "Prévia dos deslocamentos do sensor"},
    "probe.legend": {"English": "N = Nozzle · P = Probe (X = Overlap)", "Español": "N = Boquilla · P = Sensor (X = Superposición)", "Português": "N = Bico · P = Sensor (X = Sobreposição)"},
    "probe.back": {"English": "BACK", "Español": "ATRÁS", "Português": "TRÁS"},
    "probe.front": {"English": "FRONT", "Español": "FRENTE", "Português": "FRENTE"},
    "probe.example_1": {"English": "Example \"1\" (right+, back+)", "Español": "Ejemplo \"1\" (derecha+, atrás+)", "Português": "Exemplo \"1\" (direita+, trás+)"},
    "probe.example_2": {"English": "Example \"2\" (left-, back+)", "Español": "Ejemplo \"2\" (izquierda-, atrás+)", "Português": "Exemplo \"2\" (esquerda-, trás+)"},
    "probe.example_3": {"English": "Example \"3\" (right+, front-)", "Español": "Ejemplo \"3\" (derecha+, frente-)", "Português": "Exemplo \"3\" (direita+, frente-)"},
    "probe.example_4": {"English": "Example \"4\" (left-, front-)", "Español": "Ejemplo \"4\" (izquierda-, frente-)", "Português": "Exemplo \"4\" (esquerda-, frente-)"},
    "probe.nozzle_label": {"English": "Nozzle", "Español": "Boquilla", "Português": "Bico"},
    "probe.overlap_warning": {"English": "Nozzle and probe overlap — confirm offsets are correct", "Español": "La boquilla y el sensor se superponen; confirme que los desplazamientos sean correctos", "Português": "O bico e o sensor se sobrepõem; confirme se os deslocamentos estão corretos"},
    "probe.instructions": {"English": "Enter the distance from the nozzle to the probe tip.", "Español": "Ingrese la distancia desde la boquilla hasta la punta del sensor.", "Português": "Informe a distância do bico até a ponta do sensor."},
    "probe.negative_x": {"English": "Negative X = probe is LEFT of nozzle", "Español": "X negativo = el sensor está a la IZQUIERDA de la boquilla", "Português": "X negativo = o sensor está à ESQUERDA do bico"},
    "probe.positive_x": {"English": "Positive X = probe is RIGHT of nozzle", "Español": "X positivo = el sensor está a la DERECHA de la boquilla", "Português": "X positivo = o sensor está à DIREITA do bico"},
    "probe.negative_y": {"English": "Negative Y = probe is in FRONT of nozzle", "Español": "Y negativo = el sensor está al FRENTE de la boquilla", "Português": "Y negativo = o sensor está à FRENTE do bico"},
    "probe.positive_y": {"English": "Positive Y = probe is BEHIND nozzle", "Español": "Y positivo = el sensor está DETRÁS de la boquilla", "Português": "Y positivo = o sensor está ATRÁS do bico"},
    "probe.misses_left": {"English": "Probe cannot reach left edge of bed (misses first {distance:.1f} mm)", "Español": "El sensor no alcanza el borde izquierdo de la cama (faltan los primeros {distance:.1f} mm)", "Português": "O sensor não alcança a borda esquerda da mesa (faltam os primeiros {distance:.1f} mm)"},
    "probe.misses_right": {"English": "Probe cannot reach right edge of bed (misses last {distance:.1f} mm)", "Español": "El sensor no alcanza el borde derecho de la cama (faltan los últimos {distance:.1f} mm)", "Português": "O sensor não alcança a borda direita da mesa (faltam os últimos {distance:.1f} mm)"},
    "probe.misses_front": {"English": "Probe cannot reach front edge of bed (misses first {distance:.1f} mm)", "Español": "El sensor no alcanza el borde frontal de la cama (faltan los primeros {distance:.1f} mm)", "Português": "O sensor não alcança a borda frontal da mesa (faltam os primeiros {distance:.1f} mm)"},
    "probe.misses_back": {"English": "Probe cannot reach back edge of bed (misses last {distance:.1f} mm)", "Español": "El sensor no alcanza el borde trasero de la cama (faltan los últimos {distance:.1f} mm)", "Português": "O sensor não alcança a borda traseira da mesa (faltam os últimos {distance:.1f} mm)"},
    "probe.x_offset_large": {"English": "X offset ({offset:+.1f} mm) is extremely large relative to bed size", "Español": "El desplazamiento X ({offset:+.1f} mm) es extremadamente grande respecto al tamaño de la cama", "Português": "O deslocamento X ({offset:+.1f} mm) é extremamente grande em relação ao tamanho da mesa"},
    "probe.y_offset_large": {"English": "Y offset ({offset:+.1f} mm) is extremely large relative to bed size", "Español": "El desplazamiento Y ({offset:+.1f} mm) es extremadamente grande respecto al tamaño de la cama", "Português": "O deslocamento Y ({offset:+.1f} mm) é extremamente grande em relação ao tamanho da mesa"},
    "probe.confirmed": {"English": "Probe offset confirmed: X={x:+.1f} mm, Y={y:+.1f} mm", "Español": "Desplazamientos del sensor confirmados: X={x:+.1f} mm, Y={y:+.1f} mm", "Português": "Deslocamentos do sensor confirmados: X={x:+.1f} mm, Y={y:+.1f} mm"},
    "probe.z_calibration_hint": {"English": "Z offset will be calibrated later with PROBE_CALIBRATE.", "Español": "El desplazamiento Z se calibrará más adelante con PROBE_CALIBRATE.", "Português": "O deslocamento Z será calibrado mais tarde com PROBE_CALIBRATE."},
}
