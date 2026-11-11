"""Software selection and compact firmware/configuration review."""

SOFTWARE_PRESENTATION_STRINGS = {
    "wizard.step.starter_macros.header": {
        "English": "KACE starter macros",
        "Español": "Macros iniciales de KACE",
        "Português": "Macros iniciais do KACE",
    },
    "wizard.step.starter_macros.hint": {
        "English": "Choose whether to prepare the optional macros.cfg bundle. This is separate from the Mainsail/Fluidd include. Existing user macros remain protected during deployment review.",
        "Español": "Elegí si querés preparar el archivo opcional macros.cfg. Es independiente del include de Mainsail/Fluidd. Las macros existentes del usuario se protegen en la revisión de aplicación.",
        "Português": "Escolha se deseja preparar o arquivo opcional macros.cfg. É independente do include do Mainsail/Fluidd. As macros existentes do usuário são protegidas na revisão da aplicação.",
    },
    "software.starter_macros_yes": {
        "English": "Generate KACE starter macros (macros.cfg)",
        "Español": "Generar macros iniciales de KACE (macros.cfg)",
        "Português": "Gerar macros iniciais do KACE (macros.cfg)",
    },
    "software.starter_macros_no": {
        "English": "Continue without KACE starter macros",
        "Español": "Continuar sin las macros iniciales de KACE",
        "Português": "Continuar sem as macros iniciais do KACE",
    },
    "software.select_macros": {
        "English": "Choose the web interface macro include:",
        "Español": "Elegí el include de macros de la interfaz web:",
        "Português": "Escolha o include de macros da interface web:",
    },
    "software.macros_help": {
        "English": "This selects configuration macros. It does not install, remove or disable a web interface.",
        "Español": "Esto selecciona macros de configuración. No instala, elimina ni desactiva una interfaz web.",
        "Português": "Isto seleciona macros de configuração. Não instala, remove nem desativa uma interface web.",
    },
    "software.both_detected": {
        "English": "Mainsail and Fluidd were detected. This choice disables neither; they do not require two macro includes.",
        "Español": "Se detectaron Mainsail y Fluidd. Esta elección no desactiva ninguna; no necesitan dos includes de macros.",
        "Português": "Mainsail e Fluidd foram detectados. Esta escolha não desativa nenhuma; não precisam de dois includes de macros.",
    },
    "software.includes_existing": {
        "English": "Existing includes in the configuration: {includes}. They will be preserved.",
        "Español": "Includes existentes en la configuración: {includes}. Se conservarán.",
        "Português": "Includes existentes na configuração: {includes}. Serão preservados.",
    },
    "software.includes_unverified": {
        "English": "The existing include graph could not be fully reviewed. Keep it unchanged or go back; no web interface include will be added. Review unreadable, missing or unsupported includes before changing macros.",
        "Español": "No se pudieron revisar todos los includes existentes. Conservá la configuración o volvé; no se agregará un include de interfaz web. Revisá los includes ilegibles, faltantes o no admitidos antes de cambiar las macros.",
        "Português": "Não foi possível revisar todos os includes existentes. Mantenha a configuração ou volte; nenhum include de interface web será adicionado. Revise os includes ilegíveis, ausentes ou não aceitos antes de alterar as macros.",
    },
    "software.preserved_unverified": {
        "English": "Existing includes preserved; review pending",
        "Español": "Includes existentes conservados; revisión pendiente",
        "Português": "Includes existentes mantidos; revisão pendente",
    },
    "software.keep_includes": {
        "English": "Keep existing includes; add none",
        "Español": "Conservar includes existentes; no agregar otro",
        "Português": "Manter includes existentes; não adicionar outro",
    },
    "software.no_include": {
        "English": "Do not add a web interface include",
        "Español": "No agregar un include de interfaz web",
        "Português": "Não adicionar um include de interface web",
    },
    "software.include_conflict": {
        "English": "Adding {selected} alongside {existing} may duplicate macros. Keep the existing includes, or choose again. Changing them requires reviewing the current configuration; KACE will not remove them here.",
        "Español": "Agregar {selected} junto a {existing} puede duplicar macros. Conservá los includes existentes o elegí otra vez. Cambiarlos requiere revisar la configuración actual; KACE no los eliminará aquí.",
        "Português": "Adicionar {selected} junto a {existing} pode duplicar macros. Mantenha os includes existentes ou escolha novamente. Alterá-los exige revisar a configuração atual; o KACE não os removerá aqui.",
    },
    "software.resolve_include": {
        "English": "How would you like to continue?",
        "Español": "¿Cómo querés continuar?",
        "Português": "Como deseja continuar?",
    },
    "software.choose_again": {
        "English": "Choose again", "Español": "Elegir otra vez", "Português": "Escolher novamente",
    },
    "software.preserved": {
        "English": "{includes} (existing includes preserved)",
        "Español": "{includes} (includes existentes conservados)",
        "Português": "{includes} (includes existentes mantidos)",
    },
    "firmware.review.details": {
        "English": "View technical details", "Español": "Ver detalles técnicos", "Português": "Ver detalhes técnicos",
    },
    "firmware.review.skip": {
        "English": "Skip compilation for now", "Español": "Omitir compilación por ahora", "Português": "Pular compilação por enquanto",
    },
    "firmware.review.next": {
        "English": "Next: compile this target, then follow its installation instructions. Compilation does not install firmware.",
        "Español": "Siguiente: compilar este destino y seguir sus instrucciones de instalación. Compilar no instala el firmware.",
        "Português": "Próximo: compilar este destino e seguir suas instruções de instalação. Compilar não instala o firmware.",
    },
    "firmware.review.exact_mcu": {
        "English": "Confirm the exact MCU before compiling: LPC1768 and LPC1769/Turbo firmware are incompatible.",
        "Español": "Confirmá el MCU exacto antes de compilar: los firmwares LPC1768 y LPC1769/Turbo son incompatibles.",
        "Português": "Confirme o MCU exato antes de compilar: os firmwares LPC1768 e LPC1769/Turbo são incompatíveis.",
    },
    "firmware.review.filename": {
        "English": "For SD installation, keep the exact filename firmware.bin, including lowercase letters.",
        "Español": "Para instalar por SD, conservá el nombre exacto firmware.bin, en minúsculas.",
        "Português": "Para instalar por SD, mantenha o nome exato firmware.bin, em letras minúsculas.",
    },
    "firmware.review.diff": {
        "English": "Changes from the initial compiler configuration:",
        "Español": "Cambios respecto a la configuración inicial del compilador:",
        "Português": "Alterações em relação à configuração inicial do compilador:",
    },
    "firmware.review.no_changes": {
        "English": "No changes", "Español": "Sin cambios", "Português": "Sem alterações",
    },
    "firmware.manual.checksum_label": {
        "English": "SHA-256 (verified):", "Español": "SHA-256 (verificado):", "Português": "SHA-256 (verificado):",
    },
    "firmware.manual.instructions_label": {
        "English": "Installation steps:", "Español": "Pasos de instalación:", "Português": "Etapas de instalação:",
    },
    "summary.hardware_group": {
        "English": "Hardware and software", "Español": "Hardware y software", "Português": "Hardware e software",
    },
    "summary.probe_group": {
        "English": "Probe", "Español": "Sonda", "Português": "Sonda",
    },
    "summary.firmware_pending_step": {
        "English": "Complete the pending firmware installation and verification before applying the configuration.",
        "Español": "Completá la instalación y verificación pendientes del firmware antes de aplicar la configuración.",
        "Português": "Conclua a instalação e verificação pendentes do firmware antes de aplicar a configuração.",
    },
}
