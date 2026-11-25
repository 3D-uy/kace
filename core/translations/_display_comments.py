"""Localized prose for display warnings and hardware notes written to printer.cfg.

The hardware catalog and classifier own the English wording and decisions.
Only their explanation is translated here. Config fields are rendered separately.
"""

from core.translations import cfg_text, get_lang


_DISPLAY_COMMENTS = {
    "DISPLAY: {section}": {
        "Español": "PANTALLA: {section}",
        "Português": "TELA: {section}",
    },
    "Compatibility: {status}": {
        "Español": "Compatibilidad: {status}",
        "Português": "Compatibilidade: {status}",
    },
    "FULLY_COMPATIBLE": {
        "Español": "COMPATIBLE",
        "Português": "COMPATIVEL",
    },
    "COMPATIBLE_WITH_ADAPTER": {
        "Español": "COMPATIBLE CON ADAPTADOR",
        "Português": "COMPATIVEL COM ADAPTADOR",
    },
    "UNSAFE": {
        "Español": "INSEGURA",
        "Português": "INSEGURA",
    },
    "EXPERIMENTAL": {
        "Español": "EXPERIMENTAL",
        "Português": "EXPERIMENTAL",
    },
    "Selected by user during KACE display setup wizard": {
        "Español": "Seleccionada por el usuario en el asistente de pantallas de KACE",
        "Português": "Selecionada pelo usuario no assistente de telas do KACE",
    },
    "DANGER: THIS COMBINATION IS UNSAFE / HIGH RISK!": {
        "Español": "PELIGRO: COMBINACION INSEGURA DE ALTO RIESGO",
        "Português": "PERIGO: COMBINACAO INSEGURA DE ALTO RISCO",
    },
    "WARNING: ADAPTER OR WIRING MODIFICATION REQUIRED.": {
        "Español": "ADVERTENCIA: SE REQUIERE UN ADAPTADOR O UN CAMBIO DE CABLEADO.",
        "Português": "AVISO: E NECESSARIO UM ADAPTADOR OU UMA ALTERACAO NA FIACAO.",
    },
    "EXPERIMENTAL: Community reports only - outcome uncertain.": {
        "Español": "EXPERIMENTAL: Solo hay informes de la comunidad. El resultado es incierto.",
        "Português": "EXPERIMENTAL: Ha apenas relatos da comunidade. O resultado e incerto.",
    },
    "RISK: {detail}": {
        "Español": "RIESGO: {detail}",
        "Português": "RISCO: {detail}",
    },
    "REQUIRED MODIFICATION: {detail}": {
        "Español": "MODIFICACION NECESARIA: {detail}",
        "Português": "MODIFICACAO NECESSARIA: {detail}",
    },
    "REQUIRED: {detail}": {
        "Español": "NECESARIO: {detail}",
        "Português": "NECESSARIO: {detail}",
    },
    "Note: {detail}": {
        "Español": "Nota: {detail}",
        "Português": "Nota: {detail}",
    },
    "WAS: {value}": {
        "Español": "ANTERIOR: {value}",
        "Português": "ANTERIOR: {value}",
    },
    "TODO: Configure [{section}] section manually": {
        "Español": "PENDIENTE: Configura manualmente la seccion [{section}]",
        "Português": "PENDENTE: Configure manualmente a secao [{section}]",
    },
    "TODO: Add pin configuration for [{section}]": {
        "Español": "PENDIENTE: Configura los pines de [{section}]",
        "Português": "PENDENTE: Configure os pinos de [{section}]",
    },
    "Refer to Klipper docs: Config_Reference.md#[display]": {
        "Español": "Consulta la documentacion de Klipper: Config_Reference.md#[display]",
        "Português": "Consulte a documentacao do Klipper: Config_Reference.md#[display]",
    },
    "5V logic levels from MCU will exceed UC1701 driver's absolute maximum logic rating, destroying the display controller IC.": {
        "Español": "La logica de 5V de la MCU superara el limite absoluto del UC1701 y destruira el circuito integrado que controla la pantalla.",
        "Português": "A logica de 5V da MCU excedera o limite absoluto do UC1701 e destruira o circuito integrado que controla a tela.",
    },
    "Use a 5V-to-3.3V logic level shifter on all data, chip select, and clock lines.": {
        "Español": "Usa un conversor de nivel de 5V a 3.3V en todas las lineas de datos, seleccion de chip y reloj.",
        "Português": "Use um conversor de nivel de 5V para 3.3V em todas as linhas de dados, selecao de chip e clock.",
    },
    "5V logic signals fed back from the display will permanently destroy the 3.3V-only RP2040 GPIO pins.": {
        "Español": "Las senales de 5V que regresen desde la pantalla destruiran permanentemente los GPIO del RP2040, que solo admiten 3.3V.",
        "Português": "Os sinais de 5V que retornarem da tela destruirao permanentemente os GPIOs do RP2040, que so aceitam 3.3V.",
    },
    "Do not connect 5V feedback to 3.3V-only GPIOs. Voltage translation must be reviewed for each signal direction and device.": {
        "Español": "No conectes senales de retorno de 5V a GPIO que solo admitan 3.3V. Revisa la conversion de nivel para cada dispositivo y sentido de senal.",
        "Português": "Nao conecte sinais de retorno de 5V a GPIOs que so aceitem 3.3V. Confira a conversao de nivel para cada dispositivo e sentido de sinal.",
    },
    "Declared 5V input tolerance does not establish that 3.3V outputs meet the display's input thresholds.": {
        "Español": "La tolerancia de entrada declarada de 5V no garantiza que las salidas de 3.3V alcancen los umbrales de entrada de la pantalla.",
        "Português": "A tolerancia de entrada declarada de 5V nao garante que as saidas de 3.3V atinjam os limiares de entrada da tela.",
    },
    "Verify the selected GPIOs, display input thresholds and signal directions before connecting.": {
        "Español": "Antes de conectar, revisa los GPIO elegidos, los umbrales de entrada de la pantalla y el sentido de las senales.",
        "Português": "Antes de conectar, confira os GPIOs selecionados, os limiares de entrada da tela e o sentido dos sinais.",
    },
    "Standard 12864 graphic and character LCDs are natively supported by Klipper": {
        "Español": "Klipper admite de forma nativa las pantallas LCD graficas 12864 y las de caracteres",
        "Português": "O Klipper oferece suporte nativo a telas LCD graficas 12864 e de caracteres",
    },
    "Officially registered in Klipper's LCD_chips driver registry (display.py)": {
        "Español": "Registrado en LCD_chips, el registro de controladores de Klipper (display.py)",
        "Português": "Registrado em LCD_chips, o registro de drivers do Klipper (display.py)",
    },
    "Covers: RepRapDiscount Smart LCD (st7920), mini12864 (uc1701), HD44780 (2004)": {
        "Español": "Incluye RepRapDiscount Smart LCD (st7920), mini12864 (uc1701) y HD44780 (2004)",
        "Português": "Inclui RepRapDiscount Smart LCD (st7920), mini12864 (uc1701) e HD44780 (2004)",
    },
    "Connects via standard EXP1/EXP2 10-pin ribbon headers": {
        "Español": "Usa conectores estandar EXP1/EXP2 de 10 pines para cable plano",
        "Português": "Usa conectores padrao EXP1/EXP2 de 10 pinos para cabo de fita",
    },
    "The generic controller selection does not establish the module's supply or signal voltage limits": {
        "Español": "Elegir el controlador generico no determina los limites de tension de alimentacion ni de senal del modulo",
        "Português": "A escolha do controlador generico nao determina os limites de tensao de alimentacao nem de sinal do modulo",
    },
    "Verify ribbon connector orientation — reversed EXP cables destroy GPIO": {
        "Español": "Verifica la orientacion del conector del cable plano. Invertir los cables EXP destruye los GPIO",
        "Português": "Confira a orientacao do conector do cabo de fita. Inverter os cabos EXP destroi os GPIOs",
    },
    "lcd_menu is a native Klipper software feature — no hardware interface": {
        "Español": "lcd_menu es una funcion de Klipper que no requiere interfaz de hardware",
        "Português": "lcd_menu e um recurso de software do Klipper que dispensa uma interface de hardware",
    },
    "Used alongside [display] sections for menu navigation logic": {
        "Español": "Se usa junto a las secciones [display] para la navegacion por los menus",
        "Português": "Usado com as secoes [display] para navegacao pelos menus",
    },
    "display_status is a standard Klipper virtual object — no compatibility concerns": {
        "Español": "display_status es un objeto virtual estandar de Klipper sin problemas de compatibilidad",
        "Português": "display_status e um objeto virtual padrao do Klipper sem problemas de compatibilidade",
    },
    "display_template is a native Klipper templating feature — fully supported": {
        "Español": "Klipper admite de forma nativa las plantillas display_template",
        "Português": "O Klipper oferece suporte nativo a modelos display_template",
    },
    "display_data is a native Klipper data binding feature — fully supported": {
        "Español": "Klipper admite de forma nativa la vinculacion de datos mediante display_data",
        "Português": "O Klipper oferece suporte nativo a vinculacao de dados com display_data",
    },
    "HD44780 character displays natively supported (registered in LCD_chips)": {
        "Español": "Las pantallas de caracteres HD44780 tienen soporte nativo y figuran en LCD_chips",
        "Português": "As telas de caracteres HD44780 tem suporte nativo e constam em LCD_chips",
    },
    "RepRapDiscount 2004 Smart Controller uses this driver": {
        "Español": "RepRapDiscount 2004 Smart Controller usa este controlador",
        "Português": "O RepRapDiscount 2004 Smart Controller usa este driver",
    },
    "Operates via 4-bit parallel interface over EXP1": {
        "Español": "Usa una interfaz paralela de 4 bits por EXP1",
        "Português": "Usa uma interface paralela de 4 bits via EXP1",
    },
    "Verify the module's supply, signal directions and input thresholds; 5V tolerance alone does not prove 3.3V operation": {
        "Español": "Verifica la alimentacion del modulo, el sentido de las senales y los umbrales de entrada. Tolerar 5V no garantiza el funcionamiento a 3.3V",
        "Português": "Confira a alimentacao do modulo, o sentido dos sinais e os limiares de entrada. Tolerar 5V nao garante o funcionamento a 3.3V",
    },
    "HD44780 via SPI bridge — natively supported in Klipper (LCD_chips)": {
        "Español": "Klipper admite de forma nativa el HD44780 con puente SPI (LCD_chips)",
        "Português": "O Klipper oferece suporte nativo ao HD44780 com ponte SPI (LCD_chips)",
    },
    "Requires SPI bus — verify board exposes hardware or software SPI": {
        "Español": "Requiere un bus SPI. Verifica que la placa ofrezca SPI por hardware o software",
        "Português": "Requer um barramento SPI. Confira se a placa oferece SPI por hardware ou software",
    },
    "Avoids EXP1/EXP2 wiring complexity": {
        "Español": "Simplifica el cableado al prescindir de EXP1/EXP2",
        "Português": "Simplifica a ligacao ao dispensar EXP1/EXP2",
    },
    "ST7920 natively supported (registered in LCD_chips as 'st7920')": {
        "Español": "El ST7920 tiene soporte nativo y figura como 'st7920' en LCD_chips",
        "Português": "O ST7920 tem suporte nativo e consta como 'st7920' em LCD_chips",
    },
    "RepRapDiscount Full Graphic Smart Controller uses this chip": {
        "Español": "RepRapDiscount Full Graphic Smart Controller usa este chip",
        "Português": "O RepRapDiscount Full Graphic Smart Controller usa este chip",
    },
    "Ender 3 stock display uses ST7920 with Creality EXP pinout": {
        "Español": "La pantalla original de la Ender 3 usa ST7920 con la asignacion de pines EXP de Creality",
        "Português": "A tela original da Ender 3 usa ST7920 com a pinagem EXP da Creality",
    },
    "The ST7920 driver does not establish a specific panel's input tolerance or logic thresholds": {
        "Español": "El controlador ST7920 no determina la tolerancia de entrada ni los umbrales logicos del panel concreto",
        "Português": "O driver ST7920 nao determina a tolerancia de entrada nem os limiares logicos do painel especifico",
    },
    "EXP1/EXP2 ribbon connectors — check orientation before plugging in": {
        "Español": "Verifica la orientacion de los conectores de los cables planos EXP1/EXP2 antes de conectarlos",
        "Português": "Confira a orientacao dos conectores dos cabos de fita EXP1/EXP2 antes de conecta-los",
    },
    "Software-emulated ST7920 SPI mode — supported in Klipper": {
        "Español": "Klipper admite el modo SPI de ST7920 emulado por software",
        "Português": "O Klipper oferece suporte ao modo SPI do ST7920 emulado por software",
    },
    "Useful when hardware SPI conflicts with other peripherals": {
        "Español": "Util cuando el SPI por hardware entra en conflicto con otros perifericos",
        "Português": "Util quando o SPI por hardware entra em conflito com outros perifericos",
    },
    "UC1701 natively supported in Klipper (LCD_chips registry)": {
        "Español": "Klipper admite de forma nativa el UC1701 (registro LCD_chips)",
        "Português": "O Klipper oferece suporte nativo ao UC1701 (registro LCD_chips)",
    },
    "Used in mini12864 displays (Fysetc, BigTreeTech, etc.)": {
        "Español": "Se usa en pantallas mini12864 de Fysetc, BigTreeTech y otros fabricantes",
        "Português": "Usado em telas mini12864 da Fysetc, BigTreeTech e outros fabricantes",
    },
    "SPI interface — does NOT use EXP1/EXP2 directly (uses EXP1 as SPI source)": {
        "Español": "Usa SPI, con EXP1 como origen de las senales SPI. No usa EXP1/EXP2 directamente",
        "Português": "Usa SPI, com EXP1 como origem dos sinais SPI. Nao usa EXP1/EXP2 diretamente",
    },
    "Catalog logic declaration is 3.3V; verify the exact module and board's electrical specifications": {
        "Español": "El catalogo indica logica de 3.3V. Verifica las especificaciones electricas de la placa y del modulo concretos",
        "Português": "O catalogo indica logica de 3.3V. Confira as especificacoes eletricas da placa e do modulo exatos",
    },
    "Requires RGB LED section separately if display has RGB backlight": {
        "Español": "Si la pantalla tiene retroiluminacion RGB, requiere una seccion separada para sus LED RGB",
        "Português": "Se a tela tiver iluminacao de fundo RGB, precisa de uma secao separada para os LEDs RGB",
    },
    "SSD1306 OLED natively supported in Klipper (LCD_chips as 'ssd1306')": {
        "Español": "Klipper admite de forma nativa las pantallas OLED SSD1306 ('ssd1306' en LCD_chips)",
        "Português": "O Klipper oferece suporte nativo a telas OLED SSD1306 ('ssd1306' em LCD_chips)",
    },
    "I2C interface (address: 0x3C or 0x3D)": {
        "Español": "Interfaz I2C (direccion 0x3C o 0x3D)",
        "Português": "Interface I2C (endereco 0x3C ou 0x3D)",
    },
    "Module supply range and signal limits require separate verification for the exact module": {
        "Español": "Verifica por separado el rango de alimentacion y los limites de senal del modulo concreto",
        "Português": "Confira separadamente a faixa de alimentacao e os limites de sinal do modulo especifico",
    },
    "A regulator or 5V supply input does not establish 5V logic tolerance; verify pull-ups and signal levels": {
        "Español": "Un regulador o una entrada de alimentacion de 5V no garantiza tolerancia logica de 5V. Verifica las resistencias pull-up y los niveles de senal",
        "Português": "Um regulador ou uma entrada de alimentacao de 5V nao garante tolerancia logica de 5V. Confira os resistores de pull-up e os niveis de sinal",
    },
    "SH1106 OLED natively supported in Klipper (LCD_chips as 'sh1106')": {
        "Español": "Klipper admite de forma nativa las pantallas OLED SH1106 ('sh1106' en LCD_chips)",
        "Português": "O Klipper oferece suporte nativo a telas OLED SH1106 ('sh1106' em LCD_chips)",
    },
    "Pin-compatible with SSD1306 in most cases": {
        "Español": "En la mayoria de los casos la asignacion de pines coincide con la del SSD1306",
        "Português": "Na maioria dos casos a pinagem coincide com a do SSD1306",
    },
    "I2C or SPI interface (check your module)": {
        "Español": "Interfaz I2C o SPI. Verifica tu modulo",
        "Português": "Interface I2C ou SPI. Confira o seu modulo",
    },
    "AIP31068 SPI character LCD supported natively in Klipper": {
        "Español": "Klipper admite de forma nativa la pantalla LCD de caracteres AIP31068 con SPI",
        "Português": "O Klipper oferece suporte nativo a tela LCD de caracteres AIP31068 com SPI",
    },
    "Alternative to HD44780 using SPI instead of parallel interface": {
        "Español": "Alternativa al HD44780 que usa SPI en lugar de una interfaz paralela",
        "Português": "Alternativa ao HD44780 que usa SPI em vez de interface paralela",
    },
    "Requires hardware or software SPI bus": {
        "Español": "Requiere un bus SPI por hardware o software",
        "Português": "Requer um barramento SPI por hardware ou software",
    },
    "UART serial conflicts may corrupt communication with other serial devices": {
        "Español": "Los conflictos de UART pueden corromper la comunicacion con otros dispositivos serie",
        "Português": "Conflitos na UART podem corromper a comunicacao com outros dispositivos seriais",
    },
    "BTT TFT in 'emulated' mode only — touch functionality is non-operational": {
        "Español": "La BTT TFT solo funciona en modo emulado. La funcion tactil queda inactiva",
        "Português": "A BTT TFT funciona apenas no modo emulado. A funcao de toque fica inativa",
    },
    "Set BTT TFT firmware to 'Marlin emulation' mode (not touch mode)": {
        "Español": "Selecciona 'Marlin emulation' en el firmware de la BTT TFT. No uses el modo tactil",
        "Português": "Selecione 'Marlin emulation' no firmware da BTT TFT. Nao use o modo de toque",
    },
    "Connect via UART TX/RX pins — not USB": {
        "Español": "Conecta los pines TX/RX de UART. No uses USB",
        "Português": "Conecte os pinos TX/RX da UART. Nao use USB",
    },
    "Configure [display] with lcd_type: hd44780 or st7920 for emulation": {
        "Español": "Configura [display] con lcd_type: hd44780 o st7920 para la emulacion",
        "Português": "Configure [display] com lcd_type: hd44780 ou st7920 para a emulacao",
    },
    "Web UI (Mainsail/Fluidd) provides complete functionality without display": {
        "Español": "La interfaz web Mainsail/Fluidd ofrece todas las funciones sin pantalla",
        "Português": "A interface web Mainsail/Fluidd oferece todas as funcoes sem tela",
    },
    "Serial TFT displays (BTT TFT35, MKS TFT, Robin TFT) use Marlin bridge protocol": {
        "Español": "Las pantallas TFT serie BTT TFT35, MKS TFT y Robin TFT usan el protocolo puente de Marlin",
        "Português": "As telas TFT seriais BTT TFT35, MKS TFT e Robin TFT usam o protocolo de ponte do Marlin",
    },
    "Touch functionality is non-operational under Klipper": {
        "Español": "La funcion tactil no funciona con Klipper",
        "Português": "A funcao de toque nao funciona com o Klipper",
    },
    "BTT TFT35 can emulate a standard 12864 display in 'Marlin mode'": {
        "Español": "La BTT TFT35 puede emular una pantalla 12864 estandar en modo Marlin",
        "Português": "A BTT TFT35 pode emular uma tela 12864 padrao no modo Marlin",
    },
    "UART baud rate must match firmware configuration (typically 250000)": {
        "Español": "La velocidad de UART debe coincidir con la configurada en el firmware (normalmente 250000 baudios)",
        "Português": "A taxa da UART deve coincidir com a configurada no firmware (normalmente 250000 bauds)",
    },
    "Web UI provides complete feature parity from phone/tablet/PC": {
        "Español": "La interfaz web ofrece todas las funciones desde un telefono, una tableta o un PC",
        "Português": "A interface web oferece todas as funcoes pelo celular, tablet ou PC",
    },
    "Recommend: use web UI instead of attempting serial TFT integration": {
        "Español": "Se recomienda la interfaz web en lugar de integrar una TFT serie",
        "Português": "Recomenda-se a interface web em vez da integracao de uma TFT serial",
    },
    "Firmware version mismatch can cause non-recoverable display brick": {
        "Español": "Una version incompatible del firmware puede inutilizar la pantalla de forma irreversible",
        "Português": "Uma versao incompativel do firmware pode inutilizar a tela de forma irreversivel",
    },
    "UART conflicts if display shares serial bus with other devices": {
        "Español": "Puede haber conflictos si la pantalla comparte el bus UART con otros dispositivos",
        "Português": "Pode haver conflitos se a tela compartilhar o barramento UART com outros dispositivos",
    },
    "Install community 'klipper-dgus' plugin (NOT installed by KACE)": {
        "Español": "Instala el complemento comunitario 'klipper-dgus'. KACE no lo instala",
        "Português": "Instale o plugin comunitario 'klipper-dgus'. O KACE nao o instala",
    },
    "Flash matching DGUS firmware to the display (version must match exactly)": {
        "Español": "Graba en la pantalla el firmware DGUS correspondiente. La version debe coincidir exactamente",
        "Português": "Grave na tela o firmware DGUS correspondente. A versao deve coincidir exatamente",
    },
    "Configure UART connection with correct baud rate and pin mapping": {
        "Español": "Configura la velocidad y la asignacion de pines correctas para UART",
        "Português": "Configure a taxa de transmissao e a pinagem corretas para a UART",
    },
    "Alternatively: disconnect display and use web UI": {
        "Español": "Como alternativa, desconecta la pantalla y usa la interfaz web",
        "Português": "Como alternativa, desconecte a tela e use a interface web",
    },
    "DWIN displays require firmware that exactly matches the display version": {
        "Español": "Las pantallas DWIN requieren un firmware que coincida exactamente con la version de la pantalla",
        "Português": "As telas DWIN exigem firmware que corresponda exatamente a versao da tela",
    },
    "Community Klipper DWIN/DGUS plugins exist but are not installed by KACE": {
        "Español": "Existen complementos comunitarios DWIN/DGUS para Klipper. KACE no los instala",
        "Português": "Existem plugins comunitarios DWIN/DGUS para o Klipper. O KACE nao os instala",
    },
    "Flashing wrong firmware version can brick the display permanently": {
        "Español": "Grabar una version incorrecta del firmware puede inutilizar la pantalla de forma permanente",
        "Português": "Gravar uma versao incorreta do firmware pode inutilizar a tela permanentemente",
    },
    "Mismatch symptoms: frozen UI, missing menus, blank screen": {
        "Español": "Sintomas de incompatibilidad: interfaz bloqueada, menus ausentes o pantalla en blanco",
        "Português": "Sintomas de incompatibilidade: interface travada, menus ausentes ou tela em branco",
    },
    "Incorrect cable orientation can damage the display driver IC": {
        "Español": "Una orientacion incorrecta del cable puede danar el circuito integrado que controla la pantalla",
        "Português": "A orientacao incorreta do cabo pode danificar o circuito integrado que controla a tela",
    },
    "12864 ribbon cables are NOT keyed — reversed connection destroys GPIO": {
        "Español": "Los cables planos 12864 no impiden fisicamente la conexion al reves. Invertirla destruye los GPIO",
        "Português": "Os cabos de fita 12864 nao impedem fisicamente a conexao invertida. Inverte-la destroi os GPIOs",
    },
    "Flash BTT TFT35 firmware to 'Marlin emulation' mode": {
        "Español": "Graba el firmware de BTT TFT35 para el modo 'Marlin emulation'",
        "Português": "Grave o firmware da BTT TFT35 para o modo 'Marlin emulation'",
    },
    "Verify cable orientation (pin 1 alignment) before powering on": {
        "Español": "Antes de encender, comprueba la orientacion del cable y la alineacion del pin 1",
        "Português": "Antes de ligar, confira a orientacao do cabo e o alinhamento do pino 1",
    },
    "Set display firmware to 12864 emulation mode via firmware menu": {
        "Español": "Selecciona el modo de emulacion 12864 en el menu del firmware de la pantalla",
        "Português": "Selecione o modo de emulacao 12864 no menu do firmware da tela",
    },
    "Configure [display] section with appropriate lcd_type in printer.cfg": {
        "Español": "Configura la seccion [display] de printer.cfg con el lcd_type correspondiente",
        "Português": "Configure a secao [display] de printer.cfg com o lcd_type correspondente",
    },
    "BTT TFT35 has dual-mode firmware: touch mode (Marlin/Klipper-incompatible) and emulation mode": {
        "Español": "El firmware BTT TFT35 tiene modo tactil (Marlin, incompatible con Klipper) y modo de emulacion",
        "Português": "O firmware da BTT TFT35 tem modo de toque (Marlin, incompativel com o Klipper) e modo de emulacao",
    },
    "Only '12864 emulation' mode works partially under Klipper": {
        "Español": "Con Klipper solo funciona parcialmente el modo '12864 emulation'",
        "Português": "Com o Klipper, apenas o modo '12864 emulation' funciona parcialmente",
    },
    "Community reports are mixed — menu responsiveness is slower than native LCD": {
        "Español": "Los informes de la comunidad difieren. El menu responde mas lentamente que el de una LCD nativa",
        "Português": "Os relatos da comunidade variam. O menu responde mais devagar que o de uma LCD nativa",
    },
    "BTT TFT cable orientation varies by revision — check pinout carefully": {
        "Español": "La orientacion del cable BTT TFT cambia segun la revision. Comprueba bien la asignacion de pines",
        "Português": "A orientacao do cabo BTT TFT varia conforme a revisao. Confira a pinagem com cuidado",
    },
    "MKS mini12864 V3 uses FSMC interface on MKS boards — not SPI": {
        "Español": "En placas MKS, la MKS mini12864 V3 usa FSMC en lugar de SPI",
        "Português": "Em placas MKS, a MKS mini12864 V3 usa FSMC em vez de SPI",
    },
    "Connecting V3 to BTT/SKR SPI boards without firmware change causes no-display or visual corruption": {
        "Español": "Conectar la V3 a una placa SPI BTT/SKR sin cambiar el firmware puede dejar la pantalla sin imagen o con la imagen danada",
        "Português": "Conectar a V3 a uma placa SPI BTT/SKR sem trocar o firmware pode deixar a tela sem imagem ou com a imagem corrompida",
    },
    "Verify MKS mini12864 hardware revision (V1/V2 vs V3)": {
        "Español": "Verifica la revision de hardware de la MKS mini12864 (V1/V2 o V3)",
        "Português": "Confira a revisao de hardware da MKS mini12864 (V1/V2 ou V3)",
    },
    "V1/V2: standard SPI, compatible with most boards": {
        "Español": "V1/V2 usan SPI estandar y son compatibles con la mayoria de las placas",
        "Português": "V1/V2 usam SPI padrao e sao compativeis com a maioria das placas",
    },
    "V3: requires FSMC mode flag in firmware — incompatible with standard SPI boards": {
        "Español": "V3 requiere habilitar el modo FSMC en el firmware y es incompatible con placas SPI estandar",
        "Português": "A V3 exige habilitar o modo FSMC no firmware. Nao funciona com placas SPI padrao",
    },
    "Alternatively use Fysetc mini12864 which uses standard SPI universally": {
        "Español": "Como alternativa, la Fysetc mini12864 usa SPI estandar en todas sus versiones",
        "Português": "Como alternativa, a Fysetc mini12864 usa SPI padrao em todas as versoes",
    },
    "MKS mini12864 V3 introduced FSMC (Flexible Static Memory Controller) interface": {
        "Español": "MKS mini12864 V3 introdujo la interfaz FSMC (Flexible Static Memory Controller)",
        "Português": "A MKS mini12864 V3 introduziu a interface FSMC (Flexible Static Memory Controller)",
    },
    "FSMC is specific to STM32F4 hardware — not available on SKR, Octopus etc.": {
        "Español": "FSMC es especifico de STM32F4 y no esta disponible en SKR, Octopus y otras placas",
        "Português": "O FSMC e especifico do STM32F4 e nao esta disponivel em SKR, Octopus e outras placas",
    },
    "MKS V1/V2 use standard SPI and are broadly compatible": {
        "Español": "MKS V1/V2 usan SPI estandar y son compatibles con muchas placas",
        "Português": "MKS V1/V2 usam SPI padrao e sao compativeis com muitas placas",
    },
    "Check PCB revision markings before purchasing/installing": {
        "Español": "Comprueba las marcas de revision de la PCB antes de comprarla o instalarla",
        "Português": "Confira as marcas de revisao da PCB antes da compra ou instalacao",
    },
    "Sending Klipper UART traffic to t5uid1 controller can corrupt display EEPROM": {
        "Español": "Enviar trafico UART de Klipper al controlador t5uid1 puede corromper la EEPROM de la pantalla",
        "Português": "Enviar trafego UART do Klipper ao controlador t5uid1 pode corromper a EEPROM da tela",
    },
    "Boot loop caused by incompatible protocol can stress MCU power delivery": {
        "Español": "Un protocolo incompatible puede provocar reinicios continuos que sobrecarguen la alimentacion de la MCU",
        "Português": "Um protocolo incompativel pode causar reinicializacoes continuas que sobrecarreguem a alimentacao da MCU",
    },
    "No path to make this functional without replacing display firmware entirely": {
        "Español": "Para que funcione es necesario reemplazar por completo el firmware de la pantalla",
        "Português": "Para funcionar, e necessario substituir todo o firmware da tela",
    },
    "DISCONNECT the display before running Klipper for the first time": {
        "Español": "DESCONECTA la pantalla antes de ejecutar Klipper por primera vez",
        "Português": "DESCONECTE a tela antes de executar o Klipper pela primeira vez",
    },
    "Use Mainsail or Fluidd web interface for all printer control": {
        "Español": "Usa la interfaz web de Mainsail o Fluidd para controlar toda la impresora",
        "Português": "Use a interface web do Mainsail ou Fluidd para controlar toda a impressora",
    },
    "Optional: flash community 'klipper-dgus' compatible firmware to display": {
        "Español": "Opcional: graba en la pantalla firmware comunitario compatible con 'klipper-dgus'",
        "Português": "Opcional: grave na tela firmware comunitario compativel com 'klipper-dgus'",
    },
    "Community resource: search 'Klipper DGUS display firmware' for your model": {
        "Español": "Recurso comunitario: busca 'Klipper DGUS display firmware' para tu modelo",
        "Português": "Recurso da comunidade: pesquise 'Klipper DGUS display firmware' para o seu modelo",
    },
    "t5uid1 is Creality's proprietary DGUS touchscreen protocol": {
        "Español": "t5uid1 es el protocolo DGUS propietario de Creality para pantallas tactiles",
        "Português": "t5uid1 e o protocolo DGUS proprietario da Creality para telas de toque",
    },
    "Designed exclusively for Creality's Marlin-based firmware — incompatible with Klipper": {
        "Español": "Fue disenado exclusivamente para el firmware de Creality basado en Marlin y es incompatible con Klipper",
        "Português": "Foi desenvolvido apenas para o firmware da Creality baseado no Marlin. Nao funciona com o Klipper",
    },
    "Expected outcome with Klipper: black screen, boot loop, or display freeze": {
        "Español": "Con Klipper se espera una pantalla negra, reinicios continuos o una pantalla bloqueada",
        "Português": "Com o Klipper, espera-se tela preta, reinicializacoes continuas ou tela travada",
    },
    "No native Klipper driver — community plugins require display firmware replacement": {
        "Español": "Klipper carece de un controlador nativo. Los complementos comunitarios requieren reemplazar el firmware de la pantalla",
        "Português": "O Klipper nao inclui um driver nativo. Os plugins comunitarios exigem substituir o firmware da tela",
    },
    "CR-6 SE, Ender 6, and some CR-10 Smart units ship with t5uid1 displays": {
        "Español": "CR-6 SE, Ender 6 y algunas unidades CR-10 Smart incluyen pantallas t5uid1",
        "Português": "CR-6 SE, Ender 6 e algumas unidades CR-10 Smart incluem telas t5uid1",
    },
    "WS2812/WS2812B data lines expect 5V logic — connecting 3.3V MCU directly can cause unreliable operation": {
        "Español": "Las lineas de datos WS2812/WS2812B esperan logica de 5V. Conectar directamente una MCU de 3.3V puede causar fallos intermitentes",
        "Português": "As linhas de dados WS2812/WS2812B esperam logica de 5V. Conectar uma MCU de 3.3V diretamente pode causar falhas intermitentes",
    },
    "Some RP2040 boards use level shifters — verify your specific board": {
        "Español": "Algunas placas RP2040 usan conversores de nivel. Verifica tu placa concreta",
        "Português": "Algumas placas RP2040 usam conversores de nivel. Confira a sua placa especifica",
    },
    "For 3.3V MCUs (STM32, RP2040): use a 74AHCT125 or similar 3.3V→5V level shifter on the data line": {
        "Español": "Para MCU de 3.3V (STM32, RP2040), usa un 74AHCT125 o un conversor similar de 3.3V a 5V en la linea de datos",
        "Português": "Para MCUs de 3.3V (STM32, RP2040), use um 74AHCT125 ou conversor semelhante de 3.3V para 5V na linha de dados",
    },
    "For 5V MCUs (ATmega): direct connection is fine": {
        "Español": "Para MCU de 5V (ATmega), se admite la conexion directa",
        "Português": "Para MCUs de 5V (ATmega), a conexao direta e adequada",
    },
    "Neopixel/WS2812 LED sections are natively supported by Klipper": {
        "Español": "Klipper admite de forma nativa las secciones de LED Neopixel/WS2812",
        "Português": "O Klipper oferece suporte nativo a secoes de LEDs Neopixel/WS2812",
    },
    "KACE handles neopixel as passthrough — generates commented config block": {
        "Español": "KACE conserva neopixel como un bloque de configuracion comentado",
        "Português": "O KACE preserva neopixel como um bloco de configuracao comentado",
    },
    "Data line voltage requirement: WS2812B expects ≥0.7*VCC ≈ 3.5V minimum for 5V VCC": {
        "Español": "Tension de la linea de datos: WS2812B requiere >=0.7*VCC, aproximadamente 3.5V como minimo con VCC de 5V",
        "Português": "Tensao da linha de dados: WS2812B exige >=0.7*VCC, aproximadamente 3.5V no minimo com VCC de 5V",
    },
    "Many 3.3V MCU boards work reliably in practice due to high noise margins": {
        "Español": "Muchas placas con MCU de 3.3V funcionan de forma fiable en la practica gracias a margenes de ruido amplios",
        "Português": "Muitas placas com MCU de 3.3V funcionam de forma confiavel na pratica devido a margens de ruido amplas",
    },
    "Dotstar/APA102 LEDs use SPI interface — natively supported by Klipper": {
        "Español": "Los LED Dotstar/APA102 usan SPI y tienen soporte nativo en Klipper",
        "Português": "Os LEDs Dotstar/APA102 usam SPI e tem suporte nativo no Klipper",
    },
    "KACE handles dotstar as passthrough — generates commented config block": {
        "Español": "KACE conserva dotstar como un bloque de configuracion comentado",
        "Português": "O KACE preserva dotstar como um bloco de configuracao comentado",
    },
    "APA102 data lines tolerate 3.3V input from most boards": {
        "Español": "Las lineas de datos APA102 toleran entradas de 3.3V de la mayoria de las placas",
        "Português": "As linhas de dados APA102 toleram entradas de 3.3V da maioria das placas",
    },
    "Ensure I2C address is correctly configured (0x3E default)": {
        "Español": "Verifica la direccion I2C configurada (0x3E de forma predeterminada)",
        "Português": "Confira o endereco I2C configurado (0x3E por padrao)",
    },
    "KACE generates commented passthrough block — manual pin mapping required": {
        "Español": "KACE genera un bloque de referencia comentado. Es necesario asignar los pines manualmente",
        "Português": "O KACE gera um bloco de referencia comentado. E necessario mapear os pinos manualmente",
    },
    "SX1509 I2C GPIO expander is natively supported by Klipper": {
        "Español": "Klipper admite de forma nativa el expansor de GPIO I2C SX1509",
        "Português": "O Klipper oferece suporte nativo ao expansor de GPIO I2C SX1509",
    },
    "KACE handles sx1509 as passthrough — generates commented config block": {
        "Español": "KACE conserva sx1509 como un bloque de configuracion comentado",
        "Português": "O KACE preserva sx1509 como um bloco de configuracao comentado",
    },
    "Used on some BigTreeTech boards to expand available GPIO pins": {
        "Español": "Algunas placas BigTreeTech lo usan para ampliar la cantidad de pines GPIO disponibles",
        "Português": "Algumas placas BigTreeTech o usam para ampliar a quantidade de pinos GPIO disponiveis",
    },
    "[pca9685] is not a native standalone Klipper section; do not activate it": {
        "Español": "[pca9685] no es una seccion independiente nativa de Klipper. No la actives",
        "Português": "[pca9685] nao e uma secao independente nativa do Klipper. Nao a ative",
    },
    "PCA9685 is implemented internally by Replicape, not an alias for [replicape]": {
        "Español": "Replicape implementa PCA9685 internamente. PCA9685 no es un alias de [replicape]",
        "Português": "O Replicape implementa PCA9685 internamente. PCA9685 nao e um alias para [replicape]",
    },
    "KACE preserves an inactive reference and classifies it as unsupported": {
        "Español": "KACE conserva una referencia inactiva y la clasifica como no admitida",
        "Português": "O KACE preserva uma referencia inativa e a classifica como nao suportada",
    },
    "SKR Pico (RP2040) operates at 3.3V — most RepRap LCDs are 3.3V-tolerant on data lines": {
        "Español": "SKR Pico (RP2040) funciona a 3.3V. La mayoria de las LCD RepRap toleran 3.3V en las lineas de datos",
        "Português": "A SKR Pico (RP2040) opera a 3.3V. A maioria das telas LCD RepRap tolera 3.3V nas linhas de dados",
    },
    "ST7920 and HD44780 data inputs are typically 5V-tolerant (VIH ≥ 0.7*VCC)": {
        "Español": "Las entradas de datos ST7920 y HD44780 suelen tolerar 5V (VIH >= 0.7*VCC)",
        "Português": "As entradas de dados ST7920 e HD44780 costumam tolerar 5V (VIH >= 0.7*VCC)",
    },
    "Verify VCC is connected to 5V (not 3.3V) to meet LCD contrast requirements": {
        "Español": "Verifica que VCC este conectado a 5V y no a 3.3V para cumplir los requisitos de contraste de la pantalla",
        "Português": "Confira se VCC esta ligado a 5V e nao a 3.3V para atender aos requisitos de contraste da tela",
    },
    "LCD backlight may require 5V — use board's 5V rail if available": {
        "Español": "La retroiluminacion de la LCD puede requerir 5V. Usa la linea de 5V de la placa si esta disponible",
        "Português": "A iluminacao de fundo da LCD pode exigir 5V. Use a linha de 5V da placa se estiver disponivel",
    },
    "RP2040 GPIO pins are 3.3V output — do NOT connect to any 5V-only input": {
        "Español": "Las salidas GPIO del RP2040 son de 3.3V. No las conectes a entradas que requieran 5V",
        "Português": "As saidas GPIO do RP2040 sao de 3.3V. Nao as conecte a entradas que exijam 5V",
    },
    "mini12864 (UC1701) operates at 3.3V — fully compatible with RP2040 3.3V GPIO": {
        "Español": "La mini12864 (UC1701) funciona a 3.3V y es compatible con los GPIO de 3.3V del RP2040",
        "Português": "A mini12864 (UC1701) opera a 3.3V e funciona com os GPIOs de 3.3V do RP2040",
    },
    "No voltage level issues — safe plug-and-play": {
        "Español": "Sin problemas de niveles de tension: admite conexion directa",
        "Português": "Sem problemas de niveis de tensao: permite conexao direta",
    },
    "Step 1: Purchase or build a Duet2-to-EXP adapter board": {
        "Español": "Paso 1: Consigue o fabrica una placa adaptadora de Duet2 a EXP",
        "Português": "Passo 1: Adquira ou monte uma placa adaptadora de Duet2 para EXP",
    },
    "Step 2: Map Duet2 SPI/GPIO pins to display data lines manually": {
        "Español": "Paso 2: Asigna manualmente los pines SPI/GPIO de Duet2 a las lineas de datos de la pantalla",
        "Português": "Passo 2: Mapeie manualmente os pinos SPI/GPIO da Duet2 para as linhas de dados da tela",
    },
    "Step 3: Configure [display] section with explicit pin names (not EXP aliases)": {
        "Español": "Paso 3: Configura [display] con nombres de pines explicitos, sin alias EXP",
        "Português": "Passo 3: Configure [display] com nomes de pinos explicitos, sem aliases EXP",
    },
    "Duet2 (SAM4E 3.3V) can drive most RepRap LCDs at 3.3V data levels": {
        "Español": "Duet2 (SAM4E de 3.3V) puede controlar la mayoria de las LCD RepRap con senales de datos de 3.3V",
        "Português": "A Duet2 (SAM4E de 3.3V) pode controlar a maioria das telas LCD RepRap com sinais de dados de 3.3V",
    },
    "ST7920 and HD44780 are typically 5V-tolerant — verify your specific display": {
        "Español": "ST7920 y HD44780 suelen tolerar 5V. Verifica tu pantalla concreta",
        "Português": "ST7920 e HD44780 costumam tolerar 5V. Confira a sua tela especifica",
    },
    "Duet2 does not use standard EXP1/EXP2 connectors — custom wiring required": {
        "Español": "Duet2 carece de conectores EXP1/EXP2 estandar y requiere cableado especifico",
        "Português": "A Duet2 nao possui conectores EXP1/EXP2 padrao e requer fiacao especifica",
    },
    "No standard RepRap EXP header on Duet2 — adapter board needed": {
        "Español": "Duet2 carece de conector EXP RepRap estandar. Se necesita una placa adaptadora",
        "Português": "A Duet2 nao possui conector EXP RepRap padrao. E necessaria uma placa adaptadora",
    },
    "RAMPS/ATmega2560 board operates at 5V — perfect match for 5V RepRap LCDs": {
        "Español": "RAMPS/ATmega2560 funciona a 5V y es compatible con pantallas LCD RepRap de 5V",
        "Português": "A RAMPS/ATmega2560 opera a 5V e funciona com telas LCD RepRap de 5V",
    },
    "Standard EXP1/EXP2 connectors — direct plug-and-play": {
        "Español": "Conectores EXP1/EXP2 estandar de conexion directa",
        "Português": "Conectores EXP1/EXP2 padrao de conexao direta",
    },
    "RepRapDiscount Full Graphic (ST7920) and 2004 (HD44780) are natively compatible": {
        "Español": "RepRapDiscount Full Graphic (ST7920) y 2004 (HD44780) tienen compatibilidad nativa",
        "Português": "RepRapDiscount Full Graphic (ST7920) e 2004 (HD44780) tem compatibilidade nativa",
    },
    "5V GPIO signals may exceed UC1701 absolute maximum VIH (typically 3.6V)": {
        "Español": "Las senales GPIO de 5V pueden superar el maximo absoluto de VIH del UC1701 (normalmente 3.6V)",
        "Português": "Os sinais GPIO de 5V podem exceder o limite absoluto de VIH do UC1701 (normalmente 3.6V)",
    },
    "Repeated overvoltage degrades and eventually destroys the UC1701 display driver": {
        "Español": "La sobretension repetida degrada el controlador de pantalla UC1701 y acaba por destruirlo",
        "Português": "Sobretensoes repetidas degradam o controlador de tela UC1701 e acabam por destrui-lo",
    },
    "Step 1: Review voltage translation for each signal using the exact board and display specifications; no universal adapter is specified": {
        "Español": "Paso 1: Revisa la conversion de nivel de cada senal con las especificaciones de la placa y la pantalla exactas. No se especifica un adaptador universal",
        "Português": "Passo 1: Confira a conversao de nivel de cada sinal com as especificacoes exatas da placa e da tela. Nao se especifica um adaptador universal",
    },
    "Step 2: Power mini12864 from 3.3V rail": {
        "Español": "Paso 2: Alimenta la mini12864 desde la linea de 3.3V",
        "Português": "Passo 2: Alimente a mini12864 pela linha de 3.3V",
    },
    "Step 3: Configure [display] with software SPI to allow remapped level-shifted pins": {
        "Español": "Paso 3: Configura [display] con SPI por software para reasignar los pines que pasan por el conversor de nivel",
        "Português": "Passo 3: Configure [display] com SPI por software para remapear os pinos que passam pelo conversor de nivel",
    },
    "mini12864 (UC1701) operates at 3.3V — ATmega 5V GPIO may exceed absolute max ratings": {
        "Español": "La mini12864 (UC1701) funciona a 3.3V. Los GPIO de 5V del ATmega pueden superar sus limites maximos absolutos",
        "Português": "A mini12864 (UC1701) opera a 3.3V. Os GPIOs de 5V do ATmega podem exceder seus limites maximos absolutos",
    },
    "UC1701 VIH max is typically 3.6V — 5V GPIO output risks display driver damage": {
        "Español": "El maximo de VIH del UC1701 suele ser de 3.6V. Una salida GPIO de 5V puede danar el controlador de pantalla",
        "Português": "O limite de VIH do UC1701 costuma ser 3.6V. Uma saida GPIO de 5V pode danificar o controlador da tela",
    },
    "Level shifter on DATA, CLK, CS lines strongly recommended": {
        "Español": "Se recomienda encarecidamente usar un conversor de nivel en las lineas DATA, CLK y CS",
        "Português": "E altamente recomendavel usar um conversor de nivel nas linhas DATA, CLK e CS",
    },
}


def display_comment(source: str, **values: str) -> str:
    translated = _DISPLAY_COMMENTS.get(source, {}).get(get_lang(), source)
    text = cfg_text(translated)
    return text.format(**values) if values else text
