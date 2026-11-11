"""Motor rotation choices are separate from axis homing and geometry."""
MOTOR_DIRECTION_STRINGS = {
    "motor.review": {
        "English": "Motor rotation directions", "Español": "Sentidos de giro de los motores", "Português": "Sentidos de rotação dos motores",
    },
    "motor.label": {
        "English": "Motor {motor}", "Español": "Motor {motor}", "Português": "Motor {motor}",
    },
    "motor.extruder": {
        "English": "Extruder motor", "Español": "Motor del extrusor", "Português": "Motor do extrusor",
    },
    "motor.keep": {
        "English": "Keep board direction", "Español": "Conservar sentido de la placa", "Português": "Manter sentido da placa",
    },
    "motor.invert": {
        "English": "Invert board direction", "Español": "Invertir sentido de la placa", "Português": "Inverter sentido da placa",
    },
    "motor.value": {
        "English": "{mode} — dir_pin: {pin}", "Español": "{mode} — dir_pin: {pin}", "Português": "{mode} — dir_pin: {pin}",
    },
    "motor.source": {
        "English": "Original board/socket dir_pin: {pin}",
        "Español": "dir_pin original de la placa/socket: {pin}",
        "Português": "dir_pin original da placa/socket: {pin}",
    },
    "motor.choose": {
        "English": "Choose this motor's rotation direction:",
        "Español": "Elegí el sentido de giro de este motor:",
        "Português": "Escolha o sentido de rotação deste motor:",
    },
    "motor.comment": {
        "English": "dir_pin polarity; independent of homing direction",
        "Español": "polaridad de dir_pin; independiente del sentido de homing",
        "Português": "polaridade de dir_pin; independente do sentido de homing",
    },
    "motor.compact_keep": {
        "English": "Keep", "Español": "Conservar", "Português": "Manter",
    },
    "motor.compact_invert": {
        "English": "Invert", "Español": "Invertir", "Português": "Inverter",
    },
    "motor.compact_value": {
        "English": "{mode} ({pin})", "Español": "{mode} ({pin})", "Português": "{mode} ({pin})",
    },
    "motor.review_source": {
        "English": "Source changed — select Keep or Invert again",
        "Español": "Cambió el origen — elegí Conservar o Invertir nuevamente",
        "Português": "A origem mudou — escolha Manter ou Inverter novamente",
    },
    "motor.guide": {
        "English": "Keep uses the original dir_pin from the selected board/socket. Invert adds or removes its leading !: PA2 becomes !PA2, and !PA2 becomes PA2. Repeating Invert keeps that choice; it does not toggle it again.\n\nThis does not change homing direction, axis limits or wiring. CoreXY motors A/B work together to move X/Y. Z motors sharing one driver share its direction; independent drivers have separate choices. Physical direction still needs checking during commissioning; no movement is performed here.",
        "Español": "Conservar usa el dir_pin original de la placa/socket seleccionado. Invertir agrega o quita su ! inicial: PA2 pasa a !PA2 y !PA2 pasa a PA2. Elegir Invertir otra vez mantiene esa elección; no vuelve a alternar el sentido.\n\nEsto no cambia el sentido de homing, los límites ni el cableado. En CoreXY los motores A/B trabajan juntos para mover X/Y. Los motores Z que comparten un driver comparten su sentido; los drivers independientes tienen opciones separadas. El sentido físico se comprueba durante la puesta en marcha; aquí no se mueve ningún motor.",
        "Português": "Manter usa o dir_pin original da placa/socket selecionado. Inverter adiciona ou remove seu ! inicial: PA2 passa a !PA2 e !PA2 passa a PA2. Escolher Inverter novamente mantém essa escolha; não alterna o sentido outra vez.\n\nIsto não altera o sentido de homing, os limites nem a ligação. No CoreXY os motores A/B trabalham juntos para mover X/Y. Motores Z no mesmo driver compartilham seu sentido; drivers independentes têm escolhas separadas. O sentido físico é verificado durante a colocação em serviço; nenhum motor é movimentado aqui.",
    },
    "wizard.step.motor_directions.header": {
        "English": "Motor rotation directions", "Español": "Sentidos de giro de los motores", "Português": "Sentidos de rotação dos motores",
    },
    "wizard.step.motor_directions.hint": {
        "English": "Keep each board direction or invert it explicitly. This changes only dir_pin polarity, not homing or geometry.",
        "Español": "Conservá el sentido de cada motor de la placa o invertilo explícitamente. Solo cambia la polaridad de dir_pin, no el homing ni la geometría.",
        "Português": "Mantenha o sentido de cada motor da placa ou inverta-o explicitamente. Só altera a polaridade de dir_pin, não o homing nem a geometria.",
    },
}
