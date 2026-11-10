"""Probe parameter explanations and explicit Z review actions."""

PROBE_REVIEW_ACTION_STRINGS = {
    "wizard.probe_z.confirm_deferred_minimum": {
        "English": "Provisional offset 0 requires changing minimum Z from {old} to {new} mm. Have you checked that the nozzle can physically reach Z={new} without collision, and do you accept this limit change?",
        "Español": "El offset provisional 0 requiere cambiar el mínimo Z de {old} a {new} mm. ¿Comprobaste que la boquilla puede llegar físicamente a Z={new} sin chocar y aceptás este cambio de límite?",
        "Português": "O offset provisório 0 exige alterar o mínimo Z de {old} para {new} mm. Você verificou que o bico pode chegar fisicamente a Z={new} sem colisão e aceita esta alteração de limite?",
    },
    "wizard.probe_z.deferred_title": {
        "English": "Calibrate later — confirm permitted Z travel",
        "Español": "Calibrar después — confirmar el recorrido Z permitido",
        "Português": "Calibrar depois — confirmar o curso Z permitido",
    },
    "wizard.probe_z.range_unresolved": {
        "English": "Z travel could not be reviewed. Return to the printer profile or motion limits to resolve it; the offset choice and travel have not changed.",
        "Español": "No se pudo revisar el recorrido Z. Volvé al perfil de impresora o a los límites de movimiento para resolverlo; la elección del offset y el recorrido se conservaron.",
        "Português": "Não foi possível revisar o curso Z. Volte ao perfil da impressora ou aos limites de movimento para resolvê-lo; a escolha do offset e o curso foram mantidos.",
    },
    "wizard.probe_z.back_offset": {
        "English": "Back to Z offset choice",
        "Español": "Volver a la elección del offset Z",
        "Português": "Voltar à escolha do offset Z",
    },
    "wizard.probe_z.deferred_context": {
        "English": "Calibrate later: Z offset stays provisional at 0 mm. After setup, use PROBE_CALIBRATE and SAVE_CONFIG.",
        "Español": "Calibrar después: el offset Z queda provisional en 0 mm. Después de instalar, usá PROBE_CALIBRATE y SAVE_CONFIG.",
        "Português": "Calibrar depois: o offset Z fica provisório em 0 mm. Após instalar, use PROBE_CALIBRATE e SAVE_CONFIG.",
    },
    "wizard.probe_z.deferred_minimum": {
        "English": "Minimum Z {minimum} mm excludes provisional offset 0. Review minimum 0 mm only if the nozzle can reach Z=0 without collision. Nothing changes until you confirm.",
        "Español": "El mínimo Z de {minimum} mm deja afuera el offset provisional 0. Revisá un mínimo de 0 mm solo si la boquilla puede llegar a Z=0 sin chocar. Nada cambia hasta que confirmes.",
        "Português": "O mínimo Z de {minimum} mm exclui o offset provisório 0. Revise um mínimo de 0 mm somente se o bico puder chegar a Z=0 sem colisão. Nada muda até sua confirmação.",
    },
    "wizard.probe_z.deferred_range": {
        "English": "The current Z travel ({minimum} to {maximum} mm) is incompatible with provisional offset 0 mm. Review the mechanical limits; calibration remains pending.",
        "Español": "El recorrido Z actual ({minimum} a {maximum} mm) es incompatible con el offset provisional de 0 mm. Revisá los límites mecánicos; la calibración sigue pendiente.",
        "Português": "O curso Z atual ({minimum} a {maximum} mm) é incompatível com o offset provisório de 0 mm. Revise os limites mecânicos; a calibração continua pendente.",
    },
    "wizard.probe_z.review_minimum": {
        "English": "Review minimum Z: 0 mm (confirm next)",
        "Español": "Revisar mínimo Z: 0 mm (confirmar después)",
        "Português": "Revisar mínimo Z: 0 mm (confirmar a seguir)",
    },
    "wizard.probe_z.edit_minimum": {
        "English": "Edit mechanical Z minimum",
        "Español": "Editar mínimo mecánico Z",
        "Português": "Editar mínimo mecânico Z",
    },
    "wizard.probe_z.minimum_prompt": {
        "English": "How would you like to review the Z minimum?",
        "Español": "¿Cómo querés revisar el mínimo Z?",
        "Português": "Como deseja revisar o mínimo Z?",
    },
    "wizard.probe_z.definition": {
        "English": "Z offset is the nozzle-to-bed distance when the probe triggers: nozzle 2 mm above the bed means offset 2 mm. It is not the sensor-tip gap or the minimum Z travel.",
        "Español": "El offset Z es la distancia de la boquilla a la cama cuando se activa la sonda: boquilla a 2 mm de la cama significa offset de 2 mm. No es la separación de la punta del sensor ni el mínimo de recorrido Z.",
        "Português": "O offset Z é a distância do bico à mesa quando a sonda ativa: bico a 2 mm da mesa significa offset de 2 mm. Não é a distância da ponta do sensor nem o mínimo do curso Z."
    },
    "wizard.probe_z.decision": {
        "English": "Do you know the probe Z offset?",
        "Español": "¿Conocés el offset Z de la sonda?",
        "Português": "Você conhece o offset Z da sonda?"
    },
    "wizard.probe_z.known": {
        "English": "I know the Z offset — enter millimeters",
        "Español": "Conozco el offset Z — ingresar milímetros",
        "Português": "Conheço o offset Z — informar milímetros"
    },
    "wizard.probe_z.later": {
        "English": "I do not know it — calibrate later",
        "Español": "No lo conozco — calibrar después",
        "Português": "Não conheço — calibrar depois"
    },
    "wizard.probe_z.calibration_later": {
        "English": "Provisional Z offset: 0 mm. After setup, follow Klipper's PROBE_CALIBRATE procedure and SAVE_CONFIG. Preparing this value does not calibrate the probe or establish readiness to print.",
        "Español": "Offset Z provisional: 0 mm. Después de la configuración, seguí el procedimiento PROBE_CALIBRATE de Klipper y SAVE_CONFIG. Preparar este valor no calibra la sonda ni acredita que se pueda imprimir.",
        "Português": "Offset Z provisório: 0 mm. Após a configuração, siga o procedimento PROBE_CALIBRATE do Klipper e SAVE_CONFIG. Preparar esse valor não calibra a sonda nem comprova prontidão para imprimir."
    },
    "wizard.probe_z.prepare_later": {
        "English": "Calibrate later — review compatible Z minimum 0 mm",
        "Español": "Calibrar después — revisar mínimo Z compatible de 0 mm",
        "Português": "Calibrar depois — revisar mínimo Z compatível de 0 mm"
    },
    "wizard.probe_z.mechanical_minimum": {
        "English": "Other action: edit mechanical Z travel minimum",
        "Español": "Otra acción: editar mínimo de recorrido mecánico Z",
        "Português": "Outra ação: editar mínimo do curso mecânico Z"
    },
    "wizard.probe_review.group_connection": {
        "English": "Connection", "Español": "Conexión", "Português": "Conexão"
    },
    "wizard.probe_review.group_offsets": {
        "English": "Offsets", "Español": "Offsets", "Português": "Offsets"
    },
    "wizard.probe_review.group_measurements": {
        "English": "Measurements", "Español": "Mediciones", "Português": "Medições"
    },
    "summary.probe_homed_z": {
        "English": "Z [{offset}] (configured probe trigger)",
        "Español": "Z [{offset}] (activación configurada de sonda)",
        "Português": "Z [{offset}] (ativação configurada da sonda)"
    },
    "probe.finite_offset": {
        "English": "Enter a finite number (for example: -38, 0, 23.5).",
        "Español": "Ingresá un número finito (por ejemplo: -38, 0, 23.5).",
        "Português": "Informe um número finito (por exemplo: -38, 0, 23.5)."
    },
    "probe.empty_reach": {
        "English": "No measurable bed area remains. Review XY offsets and travel limits before continuing.",
        "Español": "No queda área de cama medible. Revisá los offsets XY y los límites de recorrido antes de continuar.",
        "Português": "Não resta área da mesa para medir. Revise os offsets XY e os limites de curso antes de continuar."
    },
    "wizard.review_z.summary": {
        "English": "Z minimum: {minimum} mm | Maximum: {maximum} mm | Probe z_offset: {offset} mm",
        "Español": "Mínimo Z: {minimum} mm | Máximo: {maximum} mm | z_offset de sonda: {offset} mm",
        "Português": "Mínimo Z: {minimum} mm | Máximo: {maximum} mm | z_offset da sonda: {offset} mm"
    },
    "wizard.review_z.zero_conflict": {
        "English": "Offset 0 is below minimum {minimum}. Review Z minimum or enter an already measured offset; an unknown offset remains provisional.",
        "Español": "El offset 0 queda debajo del mínimo {minimum}. Revisá el mínimo Z o ingresá un offset ya medido; un offset desconocido sigue provisional.",
        "Português": "O offset 0 está abaixo do mínimo {minimum}. Revise o mínimo Z ou informe um offset já medido; um offset desconhecido continua provisório."
    },
    "wizard.review_z.range": {
        "English": "Required: {minimum} <= z_offset {offset} <= {maximum}, with minimum < maximum. Review Z travel or the known probe offset.",
        "Español": "Se requiere: {minimum} <= z_offset {offset} <= {maximum}, con mínimo < máximo. Revisá el recorrido Z o el offset conocido de la sonda.",
        "Português": "Exigido: {minimum} <= z_offset {offset} <= {maximum}, com mínimo < máximo. Revise o curso Z ou o offset conhecido da sonda."
    },
    "wizard.review_z.clearance": {
        "English": "Z minimum limits nozzle travel; z_offset describes the probe trigger height. Confirm physical clearance before changing travel. This does not calibrate the probe.",
        "Español": "El mínimo Z limita el recorrido de la boquilla; z_offset describe la altura de activación de la sonda. Confirmá el espacio físico antes de cambiar el recorrido. Esto no calibra la sonda.",
        "Português": "O mínimo Z limita o curso do bico; z_offset descreve a altura de ativação da sonda. Confirme o espaço físico antes de alterar o curso. Isto não calibra a sonda."
    },
    "wizard.probe_z.edit_known": {
        "English": "Enter a known probe Z offset",
        "Español": "Ingresar offset Z conocido de la sonda",
        "Português": "Informar offset Z conhecido da sonda"
    },
    "wizard.probe_z.back_review": {
        "English": "Back to probe review",
        "Español": "Volver a revisar la sonda",
        "Português": "Voltar à revisão da sonda"
    },
    "wizard.probe_z.known_input": {
        "English": "Known z_offset (mm; use your measured value, < to go back)",
        "Español": "z_offset conocido (mm; usá tu valor medido, < para volver)",
        "Português": "z_offset conhecido (mm; use seu valor medido, < para voltar)"
    },
    "wizard.probe_z.confirm_offset": {
        "English": "Use the supplied z_offset {new} mm instead of {old} mm and continue? Z travel stays unchanged.",
        "Español": "¿Usar el z_offset ingresado de {new} mm en lugar de {old} mm y continuar? El recorrido Z se conserva.",
        "Português": "Usar o z_offset informado de {new} mm em vez de {old} mm e continuar? O curso Z permanece igual."
    },
    "wizard.probe_z.offset_rejected": {
        "English": "Offset {value} is outside Z travel {minimum} to {maximum} mm or is not finite; nothing changed.",
        "Español": "El offset {value} queda fuera del recorrido Z {minimum} a {maximum} mm o no es finito; nada cambió.",
        "Português": "O offset {value} está fora do curso Z {minimum} a {maximum} mm ou não é finito; nada mudou."
    },
    "wizard.probe_parameter.pin": {
        "English": "input; ^ pull-up, ! inverted",
        "Español": "entrada; ^ pull-up, ! invertida",
        "Português": "entrada; ^ pull-up, ! invertida"
    },
    "wizard.probe_parameter.x_offset": {
        "English": "from nozzle: - left, + right",
        "Español": "desde boquilla: - izquierda, + derecha",
        "Português": "desde o bico: - esquerda, + direita"
    },
    "wizard.probe_parameter.y_offset": {
        "English": "from nozzle: - front, + back",
        "Español": "desde boquilla: - delante, + atrás",
        "Português": "desde o bico: - frente, + atrás"
    },
    "wizard.probe_parameter.z_offset": {
        "English": "nozzle height at probe trigger",
        "Español": "altura de boquilla al activarse la sonda",
        "Português": "altura do bico ao ativar a sonda"
    },
    "wizard.probe_parameter.samples": {
        "English": "measurements at each point",
        "Español": "mediciones en cada punto",
        "Português": "medições em cada ponto"
    },
    "wizard.probe_parameter.samples_result": {
        "English": "how measurements are combined",
        "Español": "cómo se combinan las mediciones",
        "Português": "como as medições são combinadas"
    },
    "wizard.probe_parameter.samples_tolerance": {
        "English": "maximum spread between samples",
        "Español": "diferencia máxima entre muestras",
        "Português": "diferença máxima entre amostras"
    },
    "wizard.probe_parameter.samples_tolerance_retries": {
        "English": "retries if tolerance is exceeded",
        "Español": "reintentos si se supera la tolerancia",
        "Português": "tentativas se exceder a tolerância"
    },
    "wizard.probe_parameter.speed": {
        "English": "vertical probing speed",
        "Español": "velocidad vertical de sondeo",
        "Português": "velocidade vertical da sondagem"
    },
    "wizard.probe_parameter.sample_retract_dist": {
        "English": "lift between samples",
        "Español": "elevación entre muestras",
        "Português": "elevação entre amostras"
    }
}
