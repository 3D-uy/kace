"""Exact-MCU candidates and explicit catalog search."""

CATALOG_REVIEW_STRINGS = {
    "catalog.auto_board_required": {
        "English": "Automatic mode requires an explicitly selected board present in the catalog. Run the questionnaire interactively to select it; MCU detection alone cannot select a board.",
        "Español": "El modo automático requiere una placa seleccionada explícitamente y presente en el catálogo. Ejecutá el cuestionario interactivo para elegirla; detectar el MCU no permite seleccionar una placa.",
        "Português": "O modo automático exige uma placa selecionada explicitamente e presente no catálogo. Execute o questionário interativo para escolhê-la; detectar o MCU não permite selecionar uma placa.",
    },
    "catalog.detected_processor": {
        "English": "Detected MCU: {mcu}",
        "Español": "MCU detectado: {mcu}",
        "Português": "MCU detectado: {mcu}",
    },
    "catalog.board_unconfirmed": {
        "English": "Board model not confirmed. Select your physical board from the MCU-compatible candidates. MCU detection alone does not identify its wiring or firmware support.",
        "Español": "Modelo de placa sin confirmar. Elegí tu placa física entre las candidatas compatibles con el MCU. Detectar el MCU no identifica su cableado ni el soporte de firmware.",
        "Português": "Modelo da placa não confirmado. Escolha sua placa física entre as candidatas compatíveis com o MCU. Detectar o MCU não identifica sua fiação nem o suporte de firmware.",
    },
    "catalog.confirmed_board": {
        "English": "Board selected by user",
        "Español": "Placa seleccionada por el usuario",
        "Português": "Placa selecionada pelo usuário",
    },
    "catalog.mcu_conflict": {
        "English": "Detected MCU {mcu} conflicts with {board} ({expected}). Select the matching board; no profile was loaded.",
        "Español": "El MCU detectado {mcu} no coincide con {board} ({expected}). Elegí la placa correspondiente; no se cargó ningún perfil.",
        "Português": "O MCU detectado {mcu} não corresponde a {board} ({expected}). Escolha a placa correspondente; nenhum perfil foi carregado.",
    },
    "catalog.search_other_boards": {
        "English": "Search other boards…",
        "Español": "Buscar otras placas…",
        "Português": "Buscar outras placas…",
    },
    "catalog.no_exact_board": {
        "English": "No exact MCU match is available. Search by board model and review its variant.",
        "Español": "No hay coincidencias exactas de MCU disponibles. Buscá el modelo de placa y revisá su variante.",
        "Português": "Não há correspondências exatas de MCU disponíveis. Busque o modelo da placa e revise sua variante.",
    },
    "catalog.search_board_prompt": {
        "English": "Search boards by manufacturer or model:",
        "Español": "Buscá placas por fabricante o modelo:",
        "Português": "Busque placas por fabricante ou modelo:",
    },
    "catalog.search_prompt": {
        "English": "Type a manufacturer or model:",
        "Español": "Escribí una marca o modelo:",
        "Português": "Digite uma marca ou modelo:",
    },
    "catalog.search_help": {
        "English": "Type text to search the full catalog. Choose a visible number. / starts a new search.",
        "Español": "Escribí para buscar en todo el catálogo. Elegí un número visible. / inicia otra búsqueda.",
        "Português": "Digite para buscar em todo o catálogo. Escolha um número visível. / inicia outra busca.",
    },
}
