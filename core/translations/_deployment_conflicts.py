"""Destination ownership decisions remain explicit in every wizard mode."""
DEPLOYMENT_CONFLICT_STRINGS = {
    "deploy.local_help": {
        "English": "KACE is running on this host. To install and verify Klipper configuration here, choose Moonraker below. Local folder only exports files; it does not activate the installation.",
        "Español": "KACE se ejecuta en este equipo. Para instalar y verificar aquí la configuración de Klipper, elegí Moonraker abajo. Carpeta local solo exporta archivos; no activa la instalación.",
        "Português": "O KACE está sendo executado neste computador. Para instalar e verificar aqui a configuração do Klipper, escolha Moonraker abaixo. Pasta local apenas exporta arquivos; não ativa a instalação.",
    },
    "deploy.ssh_unavailable": {
        "English": "SSH is unavailable: its optional Paramiko dependency is not installed in KACE's environment. Choose another method; no credentials are needed. To enable SSH later, install requirements-ssh.txt with --require-hashes using KACE's virtual environment.",
        "Español": "SSH no está disponible: falta la dependencia opcional Paramiko en el entorno de KACE. Elegí otro método; no hace falta ingresar credenciales. Para habilitar SSH después, instalá requirements-ssh.txt con --require-hashes desde el entorno virtual de KACE.",
        "Português": "SSH indisponível: a dependência opcional Paramiko não está instalada no ambiente do KACE. Escolha outro método; não é necessário informar credenciais. Para habilitar SSH depois, instale requirements-ssh.txt com --require-hashes no ambiente virtual do KACE.",
    },
    "deploy.changes.details_prompt": {
        "English": "View technical details of these changes?",
        "Español": "¿Ver los detalles técnicos de estos cambios?",
        "Português": "Ver os detalhes técnicos destas alterações?",
    },
    "deploy.homing_conflict.cancel": {
        "English": "Cancel and review the questionnaire", "Español": "Cancelar y revisar el cuestionario", "Português": "Cancelar e revisar o questionário",
    },
    "deploy.homing_conflict.title": {
        "English": "Review the values that changed",
        "Español": "Revisá los valores que cambiaron",
        "Português": "Revise os valores que mudaram",
    },
    "deploy.homing_conflict.help": {
        "English": "The installed configuration contains values that differ from your questionnaire answers. Choose which set to use below.",
        "Español": "La configuración instalada tiene valores distintos de los que ingresaste en el cuestionario. Abajo podés elegir cuáles usar.",
        "Português": "A configuração instalada tem valores diferentes dos informados no questionário. Abaixo você pode escolher quais usar.",
    },
    "deploy.homing_conflict.endstop_help": {
        "English": "Endstop position: the axis coordinate where its switch triggers during homing. It is not the bed size or the maximum travel.",
        "Español": "Posición del final de carrera: coordenada del eje donde se activa el interruptor durante el homing. No es el tamaño de la cama ni el recorrido máximo.",
        "Português": "Posição do fim de curso: coordenada do eixo onde o interruptor é acionado durante o homing. Não é o tamanho da mesa nem o curso máximo.",
    },
    "deploy.homing_conflict.probe_help": {
        "English": "Probe Z offset: nozzle-to-bed distance when the probe triggers. It is separate from the mechanical Z minimum. Changing it does not calibrate the printer.",
        "Español": "Offset Z de sonda: distancia de la boquilla a la cama cuando se activa la sonda. Es distinto del mínimo mecánico Z. Cambiarlo no calibra la impresora.",
        "Português": "Offset Z da sonda: distância do bico à mesa quando a sonda é acionada. É diferente do mínimo mecânico Z. Alterá-lo não calibra a impressora.",
    },
    "deploy.homing_conflict.endstop": {
        "English": "Endstop {axis}", "Español": "Final de carrera {axis}", "Português": "Fim de curso {axis}",
    },
    "deploy.homing_conflict.probe": {
        "English": "Probe Z offset", "Español": "Offset Z de sonda", "Português": "Offset Z da sonda",
    },
    "deploy.homing_conflict.old": {
        "English": "Saved", "Español": "Guardado", "Português": "Salvo",
    },
    "deploy.homing_conflict.new": {
        "English": "Questionnaire", "Español": "Cuestionario", "Português": "Questionário",
    },
    "deploy.homing_conflict.review": {
        "English": "This choice does not apply changes yet. KACE validates the resulting configuration and asks for final review before writing. Choosing values does not calibrate the printer.",
        "Español": "Esta elección todavía no aplica cambios. KACE valida la configuración resultante y pide una revisión final antes de escribir. Elegir valores no calibra la impresora.",
        "Português": "Esta escolha ainda não aplica alterações. O KACE valida a configuração resultante e pede uma revisão final antes de gravar. Escolher valores não calibra a impressora.",
    },
    "deploy.homing_conflict.calibration": {
        "English": "A value has a saved SAVE_CONFIG calibration. Option 2 cannot replace it; review that calibration separately.",
        "Español": "Un valor tiene una calibración guardada en SAVE_CONFIG. La opción 2 no puede reemplazarla; revisá esa calibración por separado.",
        "Português": "Um valor tem uma calibração salva no SAVE_CONFIG. A opção 2 não pode substituí-la; revise essa calibração separadamente.",
    },
    "deploy.homing_conflict.prompt": {
        "English": "How should these differences be resolved?", "Español": "¿Cómo querés resolver estas diferencias?", "Português": "Como deseja resolver estas diferenças?",
    },
    "deploy.homing_conflict.keep": {
        "English": "Keep saved values and validate compatibility", "Español": "Conservar valores guardados y validar compatibilidad", "Português": "Manter valores salvos e validar compatibilidade",
    },
    "deploy.homing_conflict.replace": {
        "English": "Use the questionnaire values shown above", "Español": "Usar los valores del cuestionario indicados arriba", "Português": "Usar os valores do questionário indicados acima",
    },
    "deploy.homing_conflict.saved": {
        "English": "A value belongs to SAVE_CONFIG. It was preserved. Review that saved calibration and the wizard limits before retrying; no files were written.",
        "Español": "Un valor pertenece a SAVE_CONFIG. Se conservó. Revisá esa calibración guardada y los límites del asistente antes de reintentar; no se escribió ningún archivo.",
        "Português": "Um valor pertence ao SAVE_CONFIG. Foi preservado. Revise essa calibração salva e os limites do assistente antes de tentar novamente; nenhum arquivo foi gravado.",
    },
}
