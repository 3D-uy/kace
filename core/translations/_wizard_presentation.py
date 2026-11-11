"""Continuous wizard menus and generated-configuration presentation."""

WIZARD_PRESENTATION_STRINGS = {
    "installation.complete.title": {
        "English": "KACE installation completed",
        "Español": "Instalación de KACE completada",
        "Português": "Instalação do KACE concluída",
    },
    "installation.complete.firmware": {
        "English": "MCU firmware verified",
        "Español": "Firmware de la MCU verificado",
        "Português": "Firmware da MCU verificado",
    },
    "installation.complete.configuration": {
        "English": "Printer configuration installed and verified",
        "Español": "Configuración de la impresora instalada y verificada",
        "Português": "Configuração da impressora instalada e verificada",
    },
    "installation.complete.klipper": {
        "English": "Klipper connected and ready",
        "Español": "Klipper conectado y listo",
        "Português": "Klipper conectado e pronto",
    },
    "installation.complete.next": {
        "English": "Next: hardware commissioning",
        "Español": "Siguiente paso: comprobación del hardware (commissioning)",
        "Português": "Próximo passo: comissionamento do hardware",
    },
    "installation.complete.commissioning": {
        "English": "Before printing, verify endstops, motor direction, heaters and sensors.",
        "Español": "Antes de imprimir, verificá finales de carrera, sentido de los motores, calentadores y sensores.",
        "Português": "Antes de imprimir, verifique fins de curso, sentido dos motores, aquecedores e sensores.",
    },
    "installation.complete.calibration": {
        "English": "Complete the pending calibrations. Installation does not calibrate the printer.",
        "Español": "Completá las calibraciones pendientes. La instalación no calibra la impresora.",
        "Português": "Conclua as calibrações pendentes. A instalação não calibra a impressora.",
    },
    "firmware.manual.copy_step": {
        "English": "Copy/flash the prepared file using the board-specific method.",
        "Español": "Copiá/flasheá el archivo preparado con el método específico de la placa.",
        "Português": "Copie/grave o arquivo preparado pelo método específico da placa.",
    },
    "firmware.manual.power_step": {
        "English": "Power-cycle the board as directed by its installation instructions.",
        "Español": "Apagá y encendé la placa según sus instrucciones de instalación.",
        "Português": "Desligue e ligue novamente a placa conforme suas instruções de instalação.",
    },
    "firmware.manual.keep_open": {
        "English": "Keep KACE open to continue this workflow with MCU verification.",
        "Español": "Mantené KACE abierto para continuar este flujo con la verificación del MCU.",
        "Português": "Mantenha o KACE aberto para continuar este fluxo com a verificação do MCU.",
    },
    "firmware.manual.prepared_title": {
        "English": "Prepared firmware",
        "Español": "Firmware preparado",
        "Português": "Firmware preparado",
    },
    "firmware.manual.artifact_label": {
        "English": "Prepared file:",
        "Español": "Archivo preparado:",
        "Português": "Arquivo preparado:",
    },
    "firmware.manual.filename_label": {
        "English": "Final filename:",
        "Español": "Nombre final del archivo:",
        "Português": "Nome final do arquivo:",
    },
    "menu.list_filter_help": {
        "English": "Select a visible number or type text to filter. / clears the filter.",
        "Español": "Elegí un número visible o escribí para filtrar. / quita el filtro.",
        "Português": "Escolha um número visível ou digite para filtrar. / limpa o filtro.",
    },
    "menu.list_preview_count": {
        "English": "Showing {shown} of {total} matches.",
        "Español": "Mostrando {shown} de {total} coincidencias.",
        "Português": "Mostrando {shown} de {total} resultados.",
    },
    "menu.list_filter_prompt": {
        "English": "Number, search text or navigation:",
        "Español": "Número, búsqueda o navegación:",
        "Português": "Número, busca ou navegação:",
    },
    "menu.list_visible_number": {
        "English": "Choose a displayed number, or clear the filter with /.",
        "Español": "Elegí un número mostrado o quitá el filtro con /.",
        "Português": "Escolha um número exibido ou remova o filtro com /.",
    },
    "summary.generated_title": {
        "English": "Generated configuration summary",
        "Español": "Resumen de la configuración generada",
        "Português": "Resumo da configuração gerada",
    },
    "summary.application_pending": {
        "English": "Configuration generated. Application and installation verification are still pending.",
        "Español": "Configuración generada. Su aplicación y la verificación de la instalación siguen pendientes.",
        "Português": "Configuração gerada. A aplicação e a verificação da instalação continuam pendentes.",
    },
    "summary.motion_model": {
        "English": "Motion model", "Español": "Modelo de movimiento", "Português": "Modelo de movimento",
    },
    "summary.generated_mesh": {
        "English": "Generated bed mesh", "Español": "Malla de cama generada", "Português": "Malha da mesa gerada",
    },
    "summary.mesh_min": {
        "English": "Mesh minimum:", "Español": "Mínimo de malla:", "Português": "Mínimo da malha:",
    },
    "summary.mesh_max": {
        "English": "Mesh maximum:", "Español": "Máximo de malla:", "Português": "Máximo da malha:",
    },
    "summary.probe_count": {
        "English": "Probe count:", "Español": "Puntos de sondeo:", "Português": "Pontos de sondagem:",
    },
    "summary.mesh_algorithm": {
        "English": "Algorithm:", "Español": "Algoritmo:", "Português": "Algoritmo:",
    },
    "summary.review_generated": {
        "English": "Review the generated configuration and its destination.",
        "Español": "Revisá la configuración generada y su destino.",
        "Português": "Revise a configuração gerada e seu destino.",
    },
    "summary.choose_application": {
        "English": "Choose how to apply or export it in the next menu.",
        "Español": "Elegí cómo aplicarla o exportarla en el siguiente menú.",
        "Português": "Escolha como aplicar ou exportar no próximo menu.",
    },
    "summary.follow_verification": {
        "English": "Follow the workflow until it reports the verified installation result.",
        "Español": "Seguí el flujo hasta que informe el resultado verificado de la instalación.",
        "Português": "Siga o fluxo até que informe o resultado verificado da instalação.",
    },
}
