# core/translations/_t.py
# t() lookup function and translate_comment() translation layer.

import core.translations._state as _state
from core.translations._strings import UI_STRINGS


def t(key: str, **kwargs) -> str:
    """Look up a UI string by key in the current language.

    The selected session language is authoritative.  A missing translation is
    returned as its key instead of silently falling back to English: falling
    back would switch the interface language partway through a workflow and
    hides incomplete catalog entries during development.
    Applies str.format(**kwargs) for dynamic substitutions.
    """
    lang = _state._current_lang   # always read live value, not import-time snapshot
    entry = UI_STRINGS.get(key)
    if entry is None:
        return key.format(**kwargs) if kwargs else key
    text = entry.get(lang) or key
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
        },
        "--- optional ---": {
            "Español": "--- opcional ---",
            "Português": "--- opcional ---"
        },
        "Automatic gantry leveling when 2 or more independent Z motors are present.": {
            "Español": "Nivelación automática del gantry cuando hay 2 o más motores Z independientes.",
            "Português": "Nivelamento automático do gantry quando há 2 ou mais motores Z independentes."
        },
        "Klipper adjusts each Z motor individually to tilt the gantry parallel to the bed.": {
            "Español": "Klipper mueve cada motor Z por separado para inclinar el gantry hasta que quede paralelo a la cama.",
            "Português": "O Klipper move cada motor Z separadamente para inclinar o gantry até ficar paralelo à cama."
        },
        "Uncomment this section and run Z_TILT_ADJUST from the Klipper console to use it.": {
            "Español": "Descomenta esta sección y ejecuta Z_TILT_ADJUST desde la consola de Klipper para usarla.",
            "Português": "Descomente esta seção e execute Z_TILT_ADJUST no console do Klipper para usá-la."
        },
        "IMPORTANT — z_positions are NOT nozzle travel coordinates.": {
            "Español": "IMPORTANTE — z_positions NO son coordenadas de movimiento del nozzle.",
            "Português": "IMPORTANTE — z_positions NÃO são coordenadas de movimento do bico."
        },
        "They are the physical XY location of each Z screw or Z motor on the printer frame.": {
            "Español": "Son la ubicación física (XY) de cada tornillo Z o motor Z en el chasis de la impresora.",
            "Português": "São a localização física (XY) de cada parafuso Z ou motor Z no chassi da impressora."
        },
        "Measure with a ruler where the screws are relative to the axis origin.": {
            "Español": "Mide con una regla dónde están los tornillos en relación al origen del eje.",
            "Português": "Meça com uma régua onde estão os parafusos em relação à origem do eixo."
        },
        "Values may fall outside the print area (negative numbers or > max position).": {
            "Español": "Los valores pueden estar fuera del área de impresión (números negativos o > posición máxima).",
            "Português": "Os valores podem estar fora da área de impressão (números negativos ou > posição máxima)."
        },
        "Physical XY position of each Z motor/screw on the frame": {
            "Español": "Posición XY física de cada motor/tornillo Z en el frame",
            "Português": "Posição XY física de cada motor/parafuso Z no frame"
        },
        "Left Z motor (adjust for your printer)": {
            "Español": "Motor Z izquierdo (ajustar según tu impresora)",
            "Português": "Motor Z esquerdo (ajuste conforme sua impressora)"
        },
        "Right Z motor (adjust for your printer)": {
            "Español": "Motor Z derecho (ajustar según tu impresora)",
            "Português": "Motor Z direito (ajuste conforme sua impressora)"
        },
        "Front-left Z motor": {
            "Español": "Motor Z frontal izquierdo",
            "Português": "Motor Z frontal esquerdo"
        },
        "Front-right Z motor": {
            "Español": "Motor Z frontal derecho",
            "Português": "Motor Z frontal direito"
        },
        "Rear center Z motor": {
            "Español": "Motor Z trasero central",
            "Português": "Motor Z traseiro central"
        },
        "Rear-right Z motor": {
            "Español": "Motor Z trasero derecho",
            "Português": "Motor Z traseiro direito"
        },
        "Rear-left Z motor": {
            "Español": "Motor Z trasero izquierdo",
            "Português": "Motor Z traseiro esquerdo"
        },
        "Nozzle coordinates where the probe measures. Calculated by KACE from the reachable area.": {
            "Español": "Coordenadas de boquilla donde el probe mide. Calculadas por KACE a partir del área alcanzable.",
            "Português": "Coordenadas do bico onde o probe mede. Calculadas pelo KACE a partir da área alcançável."
        },
        "Travel speed between probe points (mm/s)": {
            "Español": "Velocidad de desplazamiento entre puntos de medición (mm/s)",
            "Português": "Velocidade de deslocamento entre pontos de medição (mm/s)"
        },
        "Safe Z height when moving between probe points (mm)": {
            "Español": "Altura Z de seguridad al moverse entre puntos (mm)",
            "Português": "Altura Z de segurança ao mover entre puntos (mm)"
        },
        "Maximum number of attempts to reach tolerance": {
            "Español": "Número máximo de intentos hasta alcanzar tolerancia",
            "Português": "Número máximo de tentativas para atingir a tolerância"
        },
        "Maximum acceptable difference between Z motors (mm). Typical values: 0.005–0.02": {
            "Español": "Diferencia máxima aceptable entre motores Z (mm). Valores típicos: 0.005–0.02",
            "Português": "Diferença máxima aceitável entre motores Z (mm). Valores típicos: 0.005–0.02"
        },
        "Gantry leveling for CoreXY printers with 4 independent Z motors (e.g. Voron).": {
            "Español": "Nivelación del gantry para impresoras CoreXY con 4 motores Z independientes (ej: Voron).",
            "Português": "Nivelamento do gantry para impressoras CoreXY com 4 motores Z independentes (ex: Voron)."
        },
        "Klipper adjusts all 4 corner motors to keep the gantry perfectly level.": {
            "Español": "Klipper adjusts all 4 corner motors to keep the gantry perfectly level.",
            "Português": "O Klipper ajusta os 4 motores de canto para manter o gantry perfeitamente nivelado."
        },
        "Uncomment this section and run QUAD_GANTRY_LEVEL from the Klipper console.": {
            "Español": "Descomenta esta sección y ejecuta QUAD_GANTRY_LEVEL desde la consola de Klipper.",
            "Português": "Descomente esta seção e execute QUAD_GANTRY_LEVEL no console do Klipper."
        },
        "gantry_corners are the physical corners of the gantry in nozzle coordinates.": {
            "Español": "gantry_corners son las esquinas físicas del gantry en coordenadas de boquilla.",
            "Português": "gantry_corners são os cantos físicos do gantry em coordenadas do bico."
        },
        "They usually extend beyond the print area. Consult your printer's design specs.": {
            "Español": "Generalmente van más allá del área de impresión. Consulta los planos de tu impresora.",
            "Português": "Geralmente vão além da área de impressão. Consulte os planos da sua impressora."
        },
        "Physical gantry corners (nozzle coords, NOT probe)": {
            "Español": "Esquinas físicas del gantry (coords boquilla, NO del probe)",
            "Português": "Cantos físicos do gantry (coords do bico, NÃO do probe)"
        },
        "Front-left corner": {
            "Español": "Esquina frontal izquierda",
            "Português": "Canto frontal esquerdo"
        },
        "Rear-right corner": {
            "Español": "Esquina trasera derecha",
            "Português": "Canto traseiro direito"
        },
        "Maximum acceptable difference between gantry corners (mm)": {
            "Español": "Diferencia máxima aceptable entre esquinas del gantry (mm)",
            "Português": "Diferença máxima aceitável entre os cantos do gantry (mm)"
        },
        "Maximum safety adjustment limit (mm). Stops if exceeded.": {
            "Español": "Límite de ajuste máximo por seguridad (mm). Detiene si se excede.",
            "Português": "Limite máximo de ajuste por segurança (mm). Para se excedido."
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
