"""Focused probe review and compatible Z preparation guidance."""

WIZARD_REVIEW_STRINGS = {
    "geometry.physical_unknown": {
        "English": "Physical bed size and origin are not established here. Klipper travel limits cannot determine them; the diagram represents only the printable area.",
        "Español": "El tamaño y origen de la cama física no están establecidos aquí. Los límites de Klipper no permiten deducirlos; el dibujo representa sólo el área imprimible.",
        "Português": "O tamanho e a origem da mesa física não estão estabelecidos aqui. Os limites do Klipper não permitem deduzi-los; o desenho representa apenas a área imprimível.",
    },
    "geometry.proposal": {
        "English": "Printable bounds: proposal or previously supplied values; explicit confirmation is pending.",
        "Español": "Límites imprimibles: propuesta o valores aportados anteriormente; falta confirmación explícita.",
        "Português": "Limites imprimíveis: proposta ou valores fornecidos anteriormente; falta confirmação explícita.",
    },
    "geometry.confirmed": {
        "English": "Printable bounds: confirmed by the operator for these configured travel limits; not a physical measurement by KACE.",
        "Español": "Límites imprimibles: confirmados por el operador para estos límites de movimiento; no son una medición física de KACE.",
        "Português": "Limites imprimíveis: confirmados pelo operador para estes limites de movimento; não são uma medição física do KACE.",
    },
    "geometry.explanation": {
        "English": "Review the printable rectangle separately from mechanical travel. A profile's position_max is only a proposal. Use the manufacturer's information or measurements to enter and confirm the usable area, including its coordinate origin. Editing this area does not change the movement limits.",
        "Español": "Revisá el rectángulo imprimible por separado del recorrido mecánico. El position_max de un perfil es sólo una propuesta. Usá información del fabricante o mediciones para ingresar y confirmar el área utilizable, incluido su origen de coordenadas. Editarla no cambia los límites de movimiento.",
        "Português": "Revise o retângulo imprimível separadamente do curso mecânico. O position_max de um perfil é apenas uma proposta. Use informações do fabricante ou medições para informar e confirmar a área utilizável, incluindo sua origem de coordenadas. Editá-la não altera os limites de movimento.",
    },
    "geometry.confirm_action": {
        "English": "Confirm this printable area using information I checked",
        "Español": "Confirmar esta área imprimible con información que verifiqué",
        "Português": "Confirmar esta área imprimível com informações que verifiquei",
    },
    "geometry.fixed_artifact": {
        "English": "Confirm the printable rectangle of this generated configuration using the manufacturer's information or measurements. This operation keeps these files unchanged. To correct the coordinates, cancel and use the configuration wizard; resuming does not regenerate them. Physical bed size and origin remain unknown.",
        "Español": "Confirmá el rectángulo imprimible de esta configuración generada con información del fabricante o mediciones. Esta operación conserva estos archivos. Para corregir las coordenadas, cancelá y usá el asistente de configuración; reanudar no las regenera. El tamaño y origen físicos de cama siguen siendo desconocidos.",
        "Português": "Confirme o retângulo imprimível desta configuração gerada com informações do fabricante ou medições. Esta operação mantém estes arquivos. Para corrigir as coordenadas, cancele e use o assistente de configuração; retomar não as regenera. O tamanho e a origem físicos da mesa continuam desconhecidos.",
    },
    "geometry.fixed_choose": {
        "English": "Confirm these printable coordinates or cancel",
        "Español": "Confirmá estas coordenadas imprimibles o cancelá",
        "Português": "Confirme estas coordenadas imprimíveis ou cancele",
    },
    "geometry.fixed_bounds": {
        "English": "Exact printable {axis} bounds in the generated configuration: [{low}, {high}] mm.",
        "Español": "Límites imprimibles exactos {axis} de la configuración generada: [{low}, {high}] mm.",
        "Português": "Limites imprimíveis exatos {axis} da configuração gerada: [{low}, {high}] mm.",
    },
    "geometry.edit_action": {
        "English": "Enter or edit printable XY bounds", "Español": "Ingresar o editar límites imprimibles XY", "Português": "Informar ou editar limites imprimíveis XY",
    },
    "geometry.choose": {
        "English": "Confirm or correct the printable rectangle", "Español": "Confirmá o corregí el rectángulo imprimible", "Português": "Confirme ou corrija o retângulo imprimível",
    },
    "geometry.invalid": {
        "English": "Printable geometry is unresolved: enter finite, ordered XY bounds within the configured travel; go Back if the travel itself is unknown or incorrect.",
        "Español": "Geometría imprimible sin resolver: ingresá límites XY finitos y ordenados dentro del recorrido configurado; volvé atrás si ese recorrido es desconocido o incorrecto.",
        "Português": "Geometria imprimível não resolvida: informe limites XY finitos e ordenados dentro do curso configurado; volte se esse curso for desconhecido ou incorreto.",
    },
    "wizard.step.printable_area.header": {
        "English": "Printable area", "Español": "Área imprimible", "Português": "Área imprimível",
    },
    "wizard.step.printable_area.hint": {
        "English": "Confirm usable coordinates; do not infer physical bed dimensions from travel.",
        "Español": "Confirmá las coordenadas utilizables; no deduzcas la cama física del recorrido.",
        "Português": "Confirme as coordenadas utilizáveis; não deduza a mesa física pelo curso.",
    },
    "nozzle_bed.title": {
        "English": "Nozzle relative to the printable area", "Español": "Boquilla respecto al área imprimible", "Português": "Bico em relação à área imprimível",
    },
    "nozzle_bed.missing": {
        "English": "Define printable XY bounds and travel limits to display distances.",
        "Español": "Definí los límites imprimibles XY y de movimiento para mostrar las distancias.",
        "Português": "Defina os limites imprimíveis XY e de movimento para mostrar as distâncias.",
    },
    "nozzle_bed.invalid": {
        "English": "Distances unavailable: review printable and travel limits.",
        "Español": "Distancias no disponibles: revisá los límites imprimibles y de movimiento.",
        "Português": "Distâncias indisponíveis: revise os limites imprimíveis e de movimento.",
    },
    "nozzle_bed.orientation": {
        "English": "Top view: -X left / +X right; -Y front / +Y back.",
        "Español": "Vista superior: -X izquierda / +X derecha; -Y frente / +Y atrás.",
        "Português": "Vista superior: -X esquerda / +X direita; -Y frente / +Y trás.",
    },
    "nozzle_bed.schematic": {
        "English": "Box = printable area. Edge coordinates in mm; drawing not to scale.",
        "Español": "Recuadro = área imprimible. Coordenadas de sus bordes en mm; dibujo sin escala.",
        "Português": "Retângulo = área imprimível. Coordenadas das bordas em mm; desenho sem escala.",
    },
    "nozzle_bed.size": {
        "English": "Printable area (X width x Y depth): {x} x {y} mm.",
        "Español": "Área imprimible (ancho X x fondo Y): {x} x {y} mm.",
        "Português": "Área imprimível (largura X x profundidade Y): {x} x {y} mm.",
    },
    "nozzle_bed.bed_label": {
        "English": "PRINTABLE AREA", "Español": "ÁREA IMPRIMIBLE", "Português": "ÁREA IMPRIMÍVEL",
    },
    "nozzle_bed.bed_bounds": {
        "English": "Printable area {axis}: {low} to {high} mm.",
        "Español": "Área imprimible {axis}: {low} a {high} mm.",
        "Português": "Área imprimível {axis}: {low} a {high} mm.",
    },
    "nozzle_bed.homing": {
        "English": "1. XY homing reference (endstops)", "Español": "1. Referencia de homing XY (endstops)", "Português": "1. Referência de homing XY (endstops)",
    },
    "nozzle_bed.position": {
        "English": "Nozzle: X = {x} mm; Y = {y} mm.", "Español": "Boquilla: X = {x} mm; Y = {y} mm.", "Português": "Bico: X = {x} mm; Y = {y} mm.",
    },
    "nozzle_bed.outside": {
        "English": "{axis}: {distance} mm outside the printable area — {side}.",
        "Español": "{axis}: {distance} mm fuera del área imprimible — {side}.",
        "Português": "{axis}: {distance} mm fora da área imprimível — {side}.",
    },
    "nozzle_bed.inside": {
        "English": "{axis}: 0 mm outside (within the printable area or its edge).",
        "Español": "{axis}: 0 mm fuera (dentro del área imprimible o su borde).",
        "Português": "{axis}: 0 mm fora (dentro da área imprimível ou sua borda).",
    },
    "nozzle_bed.unknown_home": {
        "English": "{axis}: homing reference undefined or outside travel; distance unavailable.",
        "Español": "{axis}: referencia de homing sin definir o fuera del recorrido; distancia no disponible.",
        "Português": "{axis}: referência de homing indefinida ou fora do curso; distância indisponível.",
    },
    "nozzle_bed.homing_note": {
        "English": "Configured endstop coordinates, not live position. Z homing or macros may move the nozzle afterwards.",
        "Español": "Coordenadas configuradas de los endstops, no posición en vivo. El homing Z o las macros pueden mover después la boquilla.",
        "Português": "Coordenadas configuradas dos endstops, não posição ao vivo. O homing Z ou macros podem mover o bico depois.",
    },
    "nozzle_bed.travel": {
        "English": "2. Declared travel beyond the printable area", "Español": "2. Recorrido declarado fuera del área imprimible", "Português": "2. Curso declarado fora da área imprimível",
    },
    "nozzle_bed.travel_bounds": {
        "English": "Nozzle travel {axis}: {low} to {high} mm.",
        "Español": "Recorrido de boquilla {axis}: {low} a {high} mm.",
        "Português": "Curso do bico {axis}: {low} a {high} mm.",
    },
    "nozzle_bed.travel_axis": {
        "English": "{axis}: {low_side} = {low} mm; {high_side} = {high} mm.",
        "Español": "{axis}: {low_side} = {low} mm; {high_side} = {high} mm.",
        "Português": "{axis}: {low_side} = {low} mm; {high_side} = {high} mm.",
    },
    "nozzle_bed.travel_note": {
        "English": "0 mm: no travel beyond that edge. Declared limits; no movement test performed.",
        "Español": "0 mm: sin recorrido fuera de ese borde. Límites declarados; sin prueba de movimiento.",
        "Português": "0 mm: sem curso além dessa borda. Limites declarados; sem teste de movimento.",
    },
    "nozzle_bed.left": {"English": "left (-X)", "Español": "izquierda (-X)", "Português": "esquerda (-X)"},
    "nozzle_bed.right": {"English": "right (+X)", "Español": "derecha (+X)", "Português": "direita (+X)"},
    "nozzle_bed.front": {"English": "front (-Y)", "Español": "frente (-Y)", "Português": "frente (-Y)"},
    "nozzle_bed.back": {"English": "back (+Y)", "Español": "atrás (+Y)", "Português": "trás (+Y)"},
    "profile.editor.kinematics": {
        "English": "motion model", "Español": "modelo de movimiento", "Português": "modelo de movimento",
    },
    "profile.editor.build_volume": {
        "English": "printable volume", "Español": "volumen imprimible", "Português": "volume imprimível",
    },
    "profile.editor.position_min": {
        "English": "minimum travel", "Español": "recorrido mínimo", "Português": "curso mínimo",
    },
    "profile.editor.position_max": {
        "English": "maximum travel", "Español": "recorrido máximo", "Português": "curso máximo",
    },
    "profile.editor.position_endstop": {
        "English": "endstop trigger", "Español": "activación endstop", "Português": "acionamento endstop",
    },
    "profile.editor.hotend_therm": {
        "English": "hotend sensor", "Español": "sensor del hotend", "Português": "sensor do hotend",
    },
    "profile.editor.bed_therm": {
        "English": "bed sensor", "Español": "sensor de cama", "Português": "sensor da mesa",
    },
    "profile.editor.homing": {
        "English": "homing direction", "Español": "sentido de homing", "Português": "sentido de homing",
    },
    "profile.editor.motor": {
        "English": "motor rotation", "Español": "giro del motor", "Português": "rotação do motor",
    },
    "profile.editor.homing_auto": {
        "English": "Auto: {direction}", "Español": "Auto: {direction}", "Português": "Auto: {direction}",
    },
    "profile.editor.homing_min": {
        "English": "min (-{axis})", "Español": "mín (-{axis})", "Português": "mín (-{axis})",
    },
    "profile.editor.homing_max": {
        "English": "max (+{axis})", "Español": "máx (+{axis})", "Português": "máx (+{axis})",
    },
    "profile.editor.homing_unresolved": {
        "English": "Auto: choose min/max", "Español": "Auto: elegir mín/máx", "Português": "Auto: escolher mín/máx",
    },
    "probe.compact_x": {
        "English": "From nozzle: -X LEFT | +X RIGHT",
        "Español": "Desde la boquilla: -X IZQUIERDA | +X DERECHA",
        "Português": "A partir do bico: -X ESQUERDA | +X DIREITA",
    },
    "probe.compact_y": {
        "English": "From nozzle: -Y FRONT | +Y BACK",
        "Español": "Desde la boquilla: -Y FRENTE | +Y ATRÁS",
        "Português": "A partir do bico: -Y FRENTE | +Y TRÁS",
    },
    "wizard.review_profile.motion": {
        "English": "Motion System", "Español": "Sistema de movimiento", "Português": "Sistema de movimento",
    },
    "wizard.review_profile.volume": {
        "English": "Build Volume", "Español": "Volumen de impresión", "Português": "Volume de impressão",
    },
    "wizard.review_profile.thermistors": {
        "English": "Thermistors", "Español": "Termistores", "Português": "Termistores",
    },
    "wizard.review_profile.z_provisional": {
        "English": "Automatic Z homing: provisional until probe selection.",
        "Español": "Homing Z automático: provisional hasta elegir la sonda.",
        "Português": "Homing Z automático: provisório até escolher a sonda.",
    },
    "wizard.review_profile.details": {
        "English": "View details and explanations",
        "Español": "Ver detalles y explicaciones",
        "Português": "Ver detalhes e explicações",
    },
    "wizard.review_profile.return": {
        "English": "Profile details",
        "Español": "Detalles del perfil",
        "Português": "Detalhes do perfil",
    },
    "wizard.review_profile.back_summary": {
        "English": "Back to summary",
        "Español": "Volver al resumen",
        "Português": "Voltar ao resumo",
    },
    "wizard.step.z_mechanics.header": {
        "English": "Additional Z motor mechanics",
        "Español": "Mecánica de los motores Z adicionales",
        "Português": "Mecânica dos motores Z adicionais",
    },
    "wizard.step.z_mechanics.hint": {
        "English": "Review each Z motor's travel per rotation, microsteps and gearing.",
        "Español": "Revisá el recorrido por vuelta, los microsteps y la reducción de cada motor Z.",
        "Português": "Revise o curso por volta, os microsteps e a redução de cada motor Z.",
    },
    "wizard.review_z.summary": {
        "English": "Z travel: {minimum} to {maximum} mm | Probe offset: {offset} mm",
        "Español": "Recorrido Z: {minimum} a {maximum} mm | Offset de sonda: {offset} mm",
        "Português": "Curso Z: {minimum} a {maximum} mm | Offset da sonda: {offset} mm",
    },
    "wizard.review_z.zero_conflict": {
        "English": "The offset 0 is below the Z minimum {minimum}. Raising the minimum will not help. You can prepare a compatible minimum of 0 after checking clearance, or go back to enter an already calibrated offset. An unknown offset stays provisional.",
        "Español": "El offset 0 queda debajo del mínimo Z {minimum}. Aumentar el mínimo no lo resuelve. Podés preparar un mínimo compatible de 0 tras revisar el recorrido físico, o volver para ingresar un offset ya calibrado. Un offset desconocido sigue siendo provisional.",
        "Português": "O offset 0 está abaixo do mínimo Z {minimum}. Aumentar o mínimo não resolve. Você pode preparar um mínimo compatível de 0 após conferir o curso físico, ou voltar para inserir um offset já calibrado. Um offset desconhecido continua provisório.",
    },
    "wizard.review_z.range": {
        "English": "Required: {minimum} <= offset {offset} <= {maximum}, with minimum < maximum and finite values. Review the mechanical limits or return to the probe settings; do not invent a calibrated offset.",
        "Español": "Se requiere: {minimum} <= offset {offset} <= {maximum}, con mínimo < máximo y valores finitos. Revisá los límites mecánicos o volvé a la sonda; no inventes un offset calibrado.",
        "Português": "Exigido: {minimum} <= offset {offset} <= {maximum}, com mínimo < máximo e valores finitos. Revise os limites mecânicos ou volte à sonda; não invente um offset calibrado.",
    },
    "wizard.review_z.rejected": {
        "English": "Minimum {value} is incompatible; nothing was changed.",
        "Español": "El mínimo {value} es incompatible; no se cambió nada.",
        "Português": "O mínimo {value} é incompatível; nada foi alterado.",
    },
    "wizard.review_z.prepare_zero": {
        "English": "Prepare Z minimum: 0 mm (confirm)",
        "Español": "Preparar mínimo Z: 0 mm (confirmar)",
        "Português": "Preparar mínimo Z: 0 mm (confirmar)",
    },
    "wizard.review_z.clearance": {
        "English": "This changes the permitted Z travel, not the probe offset. Confirm that the nozzle can reach the new minimum without a collision. It does not calibrate the probe. Later calibration may need a reviewed negative limit: klipper3d.org/Bed_Level.html",
        "Español": "Esto cambia el recorrido Z permitido, no el offset de sonda. Confirmá que la boquilla pueda alcanzar el nuevo mínimo sin chocar. No calibra la sonda. La calibración posterior puede necesitar un límite negativo revisado: klipper3d.org/Bed_Level.html",
        "Português": "Isto altera o curso Z permitido, não o offset da sonda. Confirme que o bico possa alcançar o novo mínimo sem colisão. Não calibra a sonda. A calibração posterior pode exigir um limite negativo revisado: klipper3d.org/Bed_Level.html",
    },
    "wizard.review_z.confirm": {
        "English": "I reviewed clearance: change Z minimum from {old} to {new} mm and continue?",
        "Español": "Revisé el recorrido físico: ¿cambiar el mínimo Z de {old} a {new} mm y continuar?",
        "Português": "Revisei o curso físico: alterar o mínimo Z de {old} para {new} mm e continuar?",
    },
    "wizard.review_probe.title": {
        "English": "Probe review [{section}]", "Español": "Revisión de sonda [{section}]", "Português": "Revisão da sonda [{section}]",
    },
    "wizard.review_probe.pin": {
        "English": "Signal pin: {pin}", "Español": "Pin de señal: {pin}", "Português": "Pino de sinal: {pin}",
    },
    "wizard.review_probe.offsets": {
        "English": "Offsets (mm): X {x} | Y {y} | Z {z}", "Español": "Offsets (mm): X {x} | Y {y} | Z {z}", "Português": "Offsets (mm): X {x} | Y {y} | Z {z}",
    },
    "wizard.review_probe.samples": {
        "English": "Samples: {samples} ({result}) | Tolerance: {tolerance} mm | Retries: {retries}",
        "Español": "Muestras: {samples} ({result}) | Tolerancia: {tolerance} mm | Reintentos: {retries}",
        "Português": "Amostras: {samples} ({result}) | Tolerância: {tolerance} mm | Tentativas: {retries}",
    },
    "wizard.review_probe.motion": {
        "English": "Probing speed: {speed} mm/s | Retraction: {retract} mm",
        "Español": "Velocidad de sondeo: {speed} mm/s | Retracción: {retract} mm",
        "Português": "Velocidade de sondagem: {speed} mm/s | Retração: {retract} mm",
    },
    "wizard.review_probe.provisional": {
        "English": "Z offset: PROVISIONAL 0; calibrate later with PROBE_CALIBRATE.",
        "Español": "Offset Z: PROVISIONAL 0; calibrar después con PROBE_CALIBRATE.",
        "Português": "Offset Z: PROVISÓRIO 0; calibrar depois com PROBE_CALIBRATE.",
    },
    "wizard.review_probe.supplied": {
        "English": "Z offset: supplied value; KACE has not measured its calibration.",
        "Español": "Offset Z: valor ingresado; KACE no midió su calibración.",
        "Português": "Offset Z: valor informado; o KACE não mediu sua calibração.",
    },
    "wizard.review_probe.imported": {
        "English": "Imported block preserved. Review its full configuration in Details; calibration is not verified.",
        "Español": "Bloque importado conservado. Revisá su configuración completa en Detalle; calibración sin verificar.",
        "Português": "Bloco importado preservado. Revise a configuração completa em Detalhes; calibração não verificada.",
    },
    "wizard.review_probe.signal_pending": {
        "English": "Signal unverified: check QUERY_PROBE before homing/probing.",
        "Español": "Señal sin verificar: comprobar QUERY_PROBE antes de homing/sondeo.",
        "Português": "Sinal não verificado: confira QUERY_PROBE antes de homing/sondagem.",
    },
    "wizard.review_probe.details": {
        "English": "View full configuration and comments", "Español": "Ver configuración completa y comentarios", "Português": "Ver configuração completa e comentários",
    },
    "wizard.review_probe.detail_return": {
        "English": "Configuration detail", "Español": "Detalle de configuración", "Português": "Detalhes da configuração",
    },
    "wizard.review_probe.back_summary": {
        "English": "Back to summary", "Español": "Volver al resumen", "Português": "Voltar ao resumo",
    },
}
